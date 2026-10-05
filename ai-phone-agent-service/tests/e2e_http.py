from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8095"


def request(method: str, path: str, payload: dict | None = None) -> dict | str:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        text = response.read().decode("utf-8")
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return json.loads(text)
        return text


def wait_for_ready() -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            ready = request("GET", "/health/ready")
            if isinstance(ready, dict) and ready.get("status") == "ok":
                return
        except (ConnectionResetError, OSError, TimeoutError, urllib.error.URLError):
            time.sleep(1)
    raise RuntimeError("service did not become ready")


def main() -> int:
    wait_for_ready()
    plan = request(
        "POST",
        "/v1/plans",
        {
            "org_id": "org-e2e",
            "intake_id": "intake-e2e",
            "intake_version": 1,
            "intake_hash": "sha256:e2e",
            "app_package": "com.example.e2e",
            "goal": "Launch the app and verify the first screen",
            "capability_snapshot": {"target_type": "emulator", "serial": "emulator-local"},
            "idempotency_key": "e2e-plan",
            "correlation_id": "e2e-corr-plan",
        },
    )
    assert isinstance(plan, dict)
    assert plan["status"] == "succeeded"
    assert plan["draft"]["steps"][0]["type"] == "launch"

    session = request(
        "POST",
        "/v1/sessions",
        {
            "org_id": "org-e2e",
            "execution_id": "exec-e2e",
            "approved_scenario_hash": "sha256:e2e-scenario",
            "policy_version": "policy-v1",
            "lease_id": "lease-e2e",
            "fencing_token": "fence-e2e",
            "app_package": "com.example.e2e",
            "allowed_operations": ["launch", "tap", "wait", "finish"],
            "budget": {
                "max_steps": 5,
                "deadline_epoch_ms": 4102444800000,
                "max_model_calls": 5,
                "max_cost_usd": 1.0,
            },
            "idempotency_key": "e2e-session",
            "correlation_id": "e2e-corr-session",
        },
    )
    assert isinstance(session, dict)

    observation = request(
        "POST",
        f"/v1/sessions/{session['session_id']}/observations",
        {
            "correlation_id": "e2e-corr-observation",
            "observation_id": "obs-e2e",
            "ui_tree": {"nodes": [{"resource_id": "start", "text": "Start", "clickable": True}]},
            "screenshot_ref": "artifact://e2e/screen",
            "evidence_ref": "artifact://e2e/evidence",
            "app_package": "com.example.e2e",
        },
    )
    assert isinstance(observation, dict)
    assert observation["action"]["operation"] == "launch"

    metrics = request("GET", "/metrics")
    assert isinstance(metrics, str)
    assert "ai_phone_agent_plans_total" in metrics
    print(json.dumps({"plan_id": plan["job_id"], "session_id": session["session_id"], "action": observation["action"]["operation"]}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"E2E failed: {exc}", file=sys.stderr)
        raise
