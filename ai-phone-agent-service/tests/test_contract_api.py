from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _plan_payload(idempotency_key: str = "idem-plan-1") -> dict:
    return {
        "org_id": "org-1",
        "intake_id": "intake-1",
        "intake_version": 1,
        "intake_hash": "sha256:intake",
        "app_package": "com.example.app",
        "goal": "Open the app and verify it does not crash",
        "capability_snapshot": {"target_type": "emulator"},
        "idempotency_key": idempotency_key,
        "correlation_id": "corr-plan-1",
    }


def _session_payload(idempotency_key: str = "idem-session-1") -> dict:
    return {
        "org_id": "org-1",
        "execution_id": "exec-1",
        "approved_scenario_hash": "sha256:scenario",
        "policy_version": "policy-v1",
        "lease_id": "lease-1",
        "fencing_token": "fence-1",
        "app_package": "com.example.app",
        "allowed_operations": ["launch", "tap", "wait", "finish"],
        "budget": {
            "max_steps": 5,
            "deadline_epoch_ms": 4_102_444_800_000,
            "max_model_calls": 5,
            "max_cost_usd": 1.0,
        },
        "idempotency_key": idempotency_key,
        "correlation_id": "corr-session-1",
    }


def test_health_ready_reports_contract_planner() -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "ai-phone-agent.v1"
    assert body["planner"] == "deterministic-contract-planner"


def test_plan_generation_is_idempotent_and_schema_bounded() -> None:
    first = client.post("/v1/plans", json=_plan_payload())
    second = client.post("/v1/plans", json=_plan_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    assert second.json()["job_id"] == first_body["job_id"]
    assert first_body["status"] == "succeeded"
    assert first_body["draft"]["app_package"] == "com.example.app"
    assert [step["type"] for step in first_body["draft"]["steps"]] == ["launch", "wait", "assert"]
    assert "prompt_policy_version" in first_body


def test_reactive_session_returns_one_allowed_action_per_observation() -> None:
    session = client.post("/v1/sessions", json=_session_payload())
    assert session.status_code == 200
    session_id = session.json()["session_id"]

    observed = client.post(
        f"/v1/sessions/{session_id}/observations",
        json={
            "correlation_id": "corr-observe-1",
            "observation_id": "obs-1",
            "ui_tree": {"nodes": [{"resource_id": "continue", "text": "Continue", "clickable": True}]},
            "screenshot_ref": "artifact://screen-1",
            "evidence_ref": "artifact://evidence-1",
            "app_package": "com.example.app",
        },
    )

    assert observed.status_code == 200
    body = observed.json()
    assert body["schema_version"] == "ai-phone-agent.v1"
    assert body["session_id"] == session_id
    assert body["action"]["operation"] in {"launch", "tap", "wait", "finish"}
    assert body["action"]["operation"] == "launch"
    assert body["action"]["expires_at"]


def test_policy_rejects_unknown_operations_and_package_mismatch() -> None:
    bad_session = _session_payload("idem-session-bad")
    bad_session["allowed_operations"] = ["launch", "raw_adb_shell"]
    response = client.post("/v1/sessions", json=bad_session)

    assert response.status_code == 422

    session = client.post("/v1/sessions", json=_session_payload("idem-session-package")).json()
    mismatch = client.post(
        f"/v1/sessions/{session['session_id']}/observations",
        json={
            "correlation_id": "corr-observe-mismatch",
            "observation_id": "obs-mismatch",
            "ui_tree": {},
            "app_package": "com.other.app",
        },
    )

    assert mismatch.status_code == 409


def test_cancel_blocks_later_observations() -> None:
    session = client.post("/v1/sessions", json=_session_payload("idem-session-cancel")).json()
    canceled = client.post(f"/v1/sessions/{session['session_id']}/cancel?correlation_id=corr-cancel")

    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"

    observed = client.post(
        f"/v1/sessions/{session['session_id']}/observations",
        json={
            "correlation_id": "corr-after-cancel",
            "observation_id": "obs-after-cancel",
            "ui_tree": {},
            "app_package": "com.example.app",
        },
    )
    assert observed.status_code == 409
