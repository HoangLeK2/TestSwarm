from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from types import SimpleNamespace

from api.deps import _get_current_user
from services.ai_device_lab.participation import (
    RecordParticipation,
    record_participation,
)
from services.ai_device_lab.readiness import materialize_service_slots
from services.ai_device_lab.reporting import (
    BuildReport,
    attach_pdf_output,
    build_report_snapshot,
)
from tenancy.context import set_current_org_id
from tenancy.context import tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    build_tenancy_api_app,
    seed_two_org_fixture,
)


def _owner_override(user_id: str, org_id: str):
    async def _override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@example.com",
            name=user_id,
            role="owner",
            org_role="owner",
            is_active=True,
            org_id=org_id,
        )

    return _override


@pytest.mark.asyncio
async def test_service_campaign_api_persists_twelve_lanes_and_hides_cross_org_resource(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)

    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "draft-api-e2e-1",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.app",
                "timezone": "Asia/Ho_Chi_Minh",
                "plan_version": "adl-14d-v1",
            },
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["lane_count"] == 12
        assert payload["status"] == "draft"
        repeated_create = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "draft-api-e2e-1",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.app",
                "timezone": "Asia/Ho_Chi_Minh",
                "plan_version": "adl-14d-v1",
            },
        )
        assert repeated_create.status_code == 201, repeated_create.text
        assert repeated_create.json()["id"] == payload["id"]

        blocked = await client.post(
            f"/api/ai-device-lab/service-campaigns/{payload['id']}/start",
            json={"idempotency_key": "start-api-e2e-1"},
        )
        assert blocked.status_code == 200, blocked.text
        blocked_payload = blocked.json()
        assert blocked_payload["started"] is False
        assert blocked_payload["started_at"] is None
        assert {item["key"] for item in blocked_payload["checks"]} == {
            "entitlement",
            "scenario_approval",
            "reservations",
            "hygiene",
            "device_health",
            "participation",
            "secret",
            "operational_dependencies",
        }

        early_expiry = await client.post(
            f"/api/ai-device-lab/service-campaigns/{payload['id']}/expire",
            json={
                "idempotency_key": "expire-api-e2e-early",
                "reason": "scheduled service expiry",
            },
        )
        assert early_expiry.status_code == 409, early_expiry.text
        assert early_expiry.json()["detail"]["code"] == "EXPIRY_REJECTED"

        cancelled = await client.post(
            f"/api/ai-device-lab/service-campaigns/{payload['id']}/cancel",
            json={
                "idempotency_key": "cancel-api-e2e-1",
                "reason": "customer requested cancellation",
            },
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "completed"
        assert cancelled.json()["checkpoint"] == "resources_released"

        definition = await client.post(
            "/api/ai-device-lab/kpi/definitions",
            json={
                "version": "api-kpi-v1",
                "definitions": {
                    "self_serve_onboarding": "paid+ready without completion assistance",
                    "run_with_trace": "terminal execution with persisted step",
                    "window_timezone": "UTC",
                },
            },
        )
        assert definition.status_code == 200, definition.text
        window_start = datetime.now(timezone.utc) - timedelta(minutes=1)
        cohort_response = await client.post(
            "/api/ai-device-lab/kpi/cohorts",
            json={
                "cohort_key": "api-fixture-cohort",
                "definition_id": definition.json()["id"],
                "source_kind": "fixture",
                "window_start": window_start.isoformat(),
                "window_end": (window_start + timedelta(hours=1)).isoformat(),
                "timezone": "UTC",
                "service_campaign_ids": [payload["id"]],
            },
        )
        assert cohort_response.status_code == 200, cohort_response.text
        cohort_id = cohort_response.json()["id"]
        snapshot = await client.post(
            f"/api/ai-device-lab/kpi/cohorts/{cohort_id}/snapshots",
            json={"query_version": "api-query-v1"},
        )
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["result_status"] == "fixture_only"
        assert snapshot.json()["self_serve_denominator"] == 0
        assert snapshot.json()["details"]["threshold_evaluation"] == "not_evaluated"

        acceptance = await client.post(
            "/api/ai-device-lab/acceptance/candidates",
            json={
                "version": "api-fixture-candidate-v1",
                "source_kind": "fixture",
                "environment": "sqlite-api-test",
                "commit_sha": "fixture-commit",
                "schema_version": "154",
                "rollback_owner": None,
                "oncall_owner": None,
                "requirements": [
                    {
                        "requirement_key": "ADL-01:AC1:01-T1",
                        "adl_id": "ADL-01",
                        "acceptance_id": "AC1",
                        "test_id": "01-T1",
                        "expected": "real phone execution evidence",
                        "observed": "source test only",
                        "status": "blocked",
                        "required_evidence_level": "live",
                        "observed_evidence_level": "source",
                        "evidence_refs": [],
                        "reviewer_id": None,
                        "executed_at": None,
                        "blocker": "permitted phone not available",
                    }
                ],
            },
        )
        assert acceptance.status_code == 200, acceptance.text
        candidate_id = acceptance.json()["id"]
        evaluation = await client.post(
            f"/api/ai-device-lab/acceptance/candidates/{candidate_id}/evaluate",
            json={"evaluation_key": "api-evaluation-v1"},
        )
        assert evaluation.status_code == 200, evaluation.text
        assert evaluation.json()["verdict"] == "no_go"
        blocker_codes = {item["code"] for item in evaluation.json()["blockers"]}
        assert "MISSING_TASK" in blocker_codes
        assert "INSUFFICIENT_EVIDENCE_LEVEL" in blocker_codes

    app.dependency_overrides[_get_current_user] = _owner_override(USER_B, ORG_B)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as other_client:
        hidden = await other_client.get(
            f"/api/ai-device-lab/service-campaigns/{payload['id']}"
        )
        assert hidden.status_code == 404
        hidden_cancel = await other_client.post(
            f"/api/ai-device-lab/service-campaigns/{payload['id']}/cancel",
            json={
                "idempotency_key": "cancel-api-e2e-b",
                "reason": "object substitution attempt",
            },
        )
        assert hidden_cancel.status_code == 404
        hidden_kpi = await other_client.post(
            f"/api/ai-device-lab/kpi/cohorts/{cohort_id}/snapshots",
            json={"query_version": "api-query-cross-org"},
        )
        assert hidden_kpi.status_code == 404
        hidden_acceptance = await other_client.post(
            f"/api/ai-device-lab/acceptance/candidates/{candidate_id}/evaluate",
            json={"evaluation_key": "api-evaluation-cross-org"},
        )
        assert hidden_acceptance.status_code == 404


@pytest.mark.asyncio
async def test_wizard_api_retains_state_invalidates_approval_and_hides_other_org(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)

    def generated_scenario(*args, **kwargs):
        return {
            "steps": [
                {
                    "type": "launch_app",
                    "package": "com.example.wizard",
                    "semantic_action": "navigation.open",
                    "policy_target": "com.example.wizard",
                },
                {
                    "type": "assert_element",
                    "by": "text",
                    "value": "Home",
                    "timeout": 5,
                },
            ]
        }

    monkeypatch.setattr(
        "runtime.ai.ai_client.build_scenario_from_instructions",
        generated_scenario,
    )
    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "wizard-api-e2e-intent",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.wizard",
                "timezone": "UTC",
                "plan_version": "adl-14d-v1",
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]
        initial = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard"
        )
        assert initial.status_code == 200, initial.text
        assert initial.json()["current_step"] == "app"

        draft_body = {
            "expected_revision": 0,
            "package_name": "com.example.wizard",
            "closed_track_link": "https://play.google.com/store/apps/details?id=com.example.wizard",
            "test_goal": "Open the app and verify Home",
            "test_environment": {"locale": "en-US", "network": "wifi"},
            "build": {
                "version_name": "1.0.0",
                "version_code": "100",
                "source_kind": "closed_track",
                "source_ref": "play-closed-track",
                "checksum_sha256": None,
            },
        }
        saved = await client.put(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/app",
            json=draft_body,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["current_step"] == "scenario"
        assert saved.json()["intake"]["revision"] == 0

        generated = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/scenario/generate",
            json={"operation_id": "wizard-api-generation-1"},
        )
        assert generated.status_code == 200, generated.text
        generation = generated.json()["generation"]
        assert generation["status"] == "succeeded"
        assert generation["scenario"]["steps"][1]["type"] == "assert_element"

        approved = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/scenario/approve",
            json={
                "operation_id": generation["operation_id"],
                "scenario_version_id": generation["scenario_version_id"],
                "expected_content_hash": generation["content_hash"],
            },
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["current_step"] == "payment"
        assert (
            approved.json()["payment"]["blocker_code"] == "PAYMENT_PROVIDER_UNAVAILABLE"
        )
        repeated_approval = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/scenario/approve",
            json={
                "operation_id": generation["operation_id"],
                "scenario_version_id": generation["scenario_version_id"],
                "expected_content_hash": generation["content_hash"],
            },
        )
        assert repeated_approval.status_code == 200, repeated_approval.text
        assert (
            repeated_approval.json()["approval"]["id"]
            == approved.json()["approval"]["id"]
        )

        edited_body = {**draft_body, "test_goal": "Verify the edited profile journey"}
        edited = await client.put(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/app",
            json=edited_body,
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["intake"]["revision"] == 1
        assert edited.json()["approval"] is None
        assert edited.json()["generation"] is None
        stale_approval = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/scenario/approve",
            json={
                "operation_id": generation["operation_id"],
                "scenario_version_id": generation["scenario_version_id"],
                "expected_content_hash": generation["content_hash"],
            },
        )
        assert stale_approval.status_code == 409, stale_approval.text
        assert stale_approval.json()["detail"]["code"] == "CURRENT_GENERATION_REQUIRED"

        stale = await client.put(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard/app",
            json={**draft_body, "test_goal": "Stale browser tab"},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"] == {
            "code": "WIZARD_REVISION_CONFLICT",
            "current_revision": 1,
        }

    app.dependency_overrides[_get_current_user] = _owner_override(USER_B, ORG_B)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as other_client:
        hidden = await other_client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/wizard"
        )
        assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_workspace_detail_apis_paginate_masked_data_and_scope_report_download(
    tenancy_session_factory,
    monkeypatch,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "workspace-detail-api-e2e",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.detail",
                "timezone": "UTC",
                "plan_version": "adl-14d-v1",
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]

    cutoff = datetime(2026, 10, 18, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            from db.models.ai_device_lab import (
                RunAttempt,
                RunSlot,
                ServiceCampaign,
                ServiceLane,
            )
            from services.ai_device_lab.evidence import (
                RegisterEvidence,
                register_evidence,
            )

            campaign = await db.get(ServiceCampaign, campaign_id)
            assert campaign is not None
            campaign.started_at = datetime(2026, 10, 4, tzinfo=timezone.utc)
            campaign.status = "active"
            await materialize_service_slots(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign_id,
            )
            first_lane = await db.scalar(
                select(ServiceLane)
                .where(ServiceLane.service_campaign_id == campaign_id)
                .order_by(ServiceLane.ordinal)
            )
            assert first_lane is not None
            first_slot = await db.scalar(
                select(RunSlot)
                .where(
                    RunSlot.service_campaign_id == campaign_id,
                    RunSlot.lane_id == first_lane.id,
                )
                .order_by(RunSlot.service_day)
            )
            assert first_slot is not None
            attempt = RunAttempt(
                id="attempt-workspace-evidence",
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                lane_id=first_lane.id,
                slot_id=first_slot.id,
                attempt_no=1,
                execution_id="execution-workspace-evidence",
                scenario_version_id="scenario-workspace-evidence",
                app_build_id="build-workspace-evidence",
                idempotency_key="attempt-workspace-evidence",
                reason="scheduled",
            )
            db.add(attempt)
            await db.flush()
            available_evidence = await register_evidence(
                db,
                RegisterEvidence(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    step_path="steps[0]",
                    step_attempt_index=1,
                    kind="screenshot",
                    captured_at=cutoff,
                    retention_until=cutoff + timedelta(days=3650),
                    object_key="private/workspace-evidence.png",
                    content_type="image/png",
                    checksum_sha256="4" * 64,
                    storage_verified=True,
                ),
            )
            missing_evidence = await register_evidence(
                db,
                RegisterEvidence(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    step_path="steps[1]",
                    step_attempt_index=1,
                    kind="screenshot",
                    captured_at=cutoff,
                    retention_until=cutoff + timedelta(days=3650),
                    storage_verified=False,
                    capture_error_code="UPLOAD_TIMEOUT",
                ),
            )
            expired_evidence = await register_evidence(
                db,
                RegisterEvidence(
                    org_id=ORG_A,
                    run_attempt_id=attempt.id,
                    step_path="steps[2]",
                    step_attempt_index=1,
                    kind="screenshot",
                    captured_at=cutoff,
                    retention_until=cutoff - timedelta(days=1),
                    object_key="private/expired-evidence.png",
                    content_type="image/png",
                    checksum_sha256="5" * 64,
                    storage_verified=True,
                ),
            )
            expired_evidence.status = "expired"
            expired_evidence.deleted_at = cutoff
            await record_participation(
                db,
                RecordParticipation(
                    org_id=ORG_A,
                    package_name="com.example.detail",
                    track_name="closed",
                    pseudonymous_account_ref="private-stable-account-ref",
                    masked_label="tester-01",
                    event_type="opted_in",
                    source_type="operator_observation",
                    evidence_grade="operator_attested",
                    observed_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
                    recorded_by=USER_A,
                    reviewed_by=USER_A,
                    service_campaign_id=campaign_id,
                ),
            )
            report = await build_report_snapshot(
                db,
                BuildReport(
                    org_id=ORG_A,
                    service_campaign_id=campaign_id,
                    idempotency_key="workspace-report-v1",
                    schema_version="adl-report-v1",
                    builder_version="api-e2e",
                    cutoff_at=cutoff,
                    created_by=USER_A,
                ),
            )
            await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        lanes = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/lanes?offset=0&limit=2"
        )
        assert lanes.status_code == 200, lanes.text
        assert lanes.json()["total"] == 12
        assert len(lanes.json()["items"]) == 2
        lane_id = lanes.json()["items"][0]["id"]

        detail = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/lanes/{lane_id}?slot_offset=0&slot_limit=3"
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["slot_total"] == 14
        assert len(detail.json()["slots"]) == 3
        manifest_evidence = detail.json()["slots"][0]["attempts"][0]["evidence"]
        assert {item["status"] for item in manifest_evidence} == {
            "available",
            "missing",
            "expired",
        }
        assert all("object_key" not in item for item in manifest_evidence)

        unconfirmed = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/evidence/{available_evidence.id}/download-url"
        )
        assert unconfirmed.status_code == 503, unconfirmed.text
        assert unconfirmed.json()["detail"]["code"] == (
            "EVIDENCE_PRIVATE_STORAGE_UNCONFIRMED"
        )
        monkeypatch.setenv("AI_DEVICE_LAB_PRIVATE_EVIDENCE_STORAGE_CONFIRMED", "true")
        monkeypatch.setattr(
            "services.content.artifact_service.presigned_artifact_url",
            lambda *args, **kwargs: {
                "url": "https://storage.invalid/signed-evidence",
                "expires_at": "2026-10-04T00:05:00+00:00",
                "content_type": "image/png",
                "proxy_required": False,
            },
        )
        evidence_download = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/evidence/{available_evidence.id}/download-url"
        )
        assert evidence_download.status_code == 200, evidence_download.text
        assert evidence_download.json()["content_type"] == "image/png"
        assert "object_key" not in evidence_download.json()
        missing_download = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/evidence/{missing_evidence.id}/download-url"
        )
        assert missing_download.status_code == 409, missing_download.text
        assert missing_download.json()["detail"]["code"] == "EVIDENCE_NOT_AVAILABLE"
        expired_download = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/evidence/{expired_evidence.id}/download-url"
        )
        assert expired_download.status_code == 410, expired_download.text
        assert expired_download.json()["detail"]["code"] == "EVIDENCE_GONE"

        participation = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/participation"
        )
        assert participation.status_code == 200, participation.text
        participant = participation.json()["items"][0]
        assert participant["masked_label"] == "tester-01"
        assert "pseudonymous_account_ref" not in participant

        publish = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/reports/{report.id}/publish"
        )
        assert publish.status_code == 503, publish.text
        assert publish.json()["detail"]["code"] == "REPORT_PRIVATE_STORAGE_UNAVAILABLE"

        with tenant_context(ORG_A):
            async with tenancy_session_factory() as db:
                await attach_pdf_output(
                    db,
                    org_id=ORG_A,
                    report_id=report.id,
                    manifest_sha256=report.manifest_sha256,
                    object_key=f"reports/{report.id}.pdf",
                    pdf_sha256="3" * 64,
                )
                await db.commit()

        reports = await client.get(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/reports"
        )
        assert reports.status_code == 200, reports.text
        report_item = reports.json()["items"][0]
        assert report_item["download_available"] is True
        assert "pdf_object_key" not in report_item
        assert "manifest" not in report_item
        assert "source_ids" not in report_item["summary"]
        assert report_item["summary"]["service"]["planned_slots"] == 168

        monkeypatch.setattr(
            "services.content.artifact_service.presigned_artifact_url",
            lambda *args, **kwargs: {
                "url": "https://storage.invalid/signed-report",
                "expires_at": "2026-10-04T00:05:00+00:00",
                "content_type": "application/pdf",
                "proxy_required": False,
            },
        )
        download = await client.post(
            f"/api/ai-device-lab/service-campaigns/{campaign_id}/reports/{report.id}/download-url"
        )
        assert download.status_code == 200, download.text
        assert download.json()["url"].startswith("https://storage.invalid/")

    app.dependency_overrides[_get_current_user] = _owner_override(USER_B, ORG_B)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as other:
        assert (
            await other.get(f"/api/ai-device-lab/service-campaigns/{campaign_id}/lanes")
        ).status_code == 404
        assert (
            await other.post(
                f"/api/ai-device-lab/service-campaigns/{campaign_id}/reports/{report.id}/download-url"
            )
        ).status_code == 404
        assert (
            await other.post(
                f"/api/ai-device-lab/service-campaigns/{campaign_id}/evidence/{available_evidence.id}/download-url"
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_participation_issue_and_retest_api_preserve_tenant_and_sensitive_boundaries(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/ai-device-lab/service-campaigns",
            json={
                "creation_intent_key": "quality-api-e2e-1",
                "runtime_campaign_id": seeded["campaign_a"],
                "package_name": "com.example.quality",
                "timezone": "UTC",
                "plan_version": "adl-14d-v1",
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            from db.models.ai_device_lab import (
                AppBuild,
                RunAttempt,
                RunSlot,
                ServiceCampaign,
            )

            campaign = await db.get(ServiceCampaign, campaign_id)
            assert campaign is not None
            campaign.started_at = datetime(2026, 10, 4, tzinfo=timezone.utc)
            campaign.status = "active"
            await materialize_service_slots(
                db, org_id=ORG_A, service_campaign_id=campaign_id
            )
            slot = await db.scalar(
                select(RunSlot)
                .where(RunSlot.service_campaign_id == campaign_id)
                .order_by(RunSlot.service_day.asc(), RunSlot.lane_id.asc())
            )
            assert slot is not None
            source_build = AppBuild(
                id="quality-api-build-v1",
                org_id=ORG_A,
                package_name="com.example.quality",
                version_name="1",
                version_code="1",
                source_kind="uploaded_artifact",
                checksum_sha256="4" * 64,
            )
            target_build = AppBuild(
                id="quality-api-build-v2",
                org_id=ORG_A,
                package_name="com.example.quality",
                version_name="2",
                version_code="2",
                source_kind="uploaded_artifact",
                checksum_sha256="5" * 64,
            )
            attempt = RunAttempt(
                id="quality-api-failed-attempt",
                org_id=ORG_A,
                service_campaign_id=campaign_id,
                lane_id=slot.lane_id,
                slot_id=slot.id,
                attempt_no=1,
                execution_id="quality-api-execution",
                scenario_version_id="quality-api-scenario-v1",
                app_build_id=source_build.id,
                idempotency_key="quality-api-attempt-1",
                reason="scheduled",
                status="finished",
                outcome="fail",
                observed_build={"version_code": "1"},
                failure_reason="ASSERTION_FAILED",
            )
            db.add_all([source_build, target_build, attempt])
            await db.commit()
            lane_id = slot.lane_id

    participation_url = (
        f"/api/ai-device-lab/service-campaigns/{campaign_id}/participation"
    )
    issues_url = f"/api/ai-device-lab/service-campaigns/{campaign_id}/issues"
    participation_body = {
        "pseudonymous_account_ref": "sensitive-pseudonymous-ref",
        "masked_label": "te***11",
        "track_name": "closed",
        "event_type": "opted_in",
        "source_type": "operator_observation",
        "evidence_ref": "private://participation/evidence-1",
        "evidence_grade": "operator_attested",
        "observed_at": "2026-10-04T00:00:00Z",
        "approve": True,
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        participation = await client.post(
            participation_url,
            json=participation_body,
        )
        assert participation.status_code == 201, participation.text
        assert participation.json()["review_state"] == "approved"
        assert participation.json()["participation"]["current_status"] == "opted_in"
        assert "sensitive-pseudonymous-ref" not in participation.text
        listed_participation = await client.get(participation_url)
        assert "sensitive-pseudonymous-ref" not in listed_participation.text

        issue = await client.post(
            issues_url,
            json={
                "source_attempt_id": "quality-api-failed-attempt",
                "severity": "major",
                "assertion_key": "home-title-visible",
                "expected": "Home title",
                "actual": "Blank screen",
                "reproduction": {"step_path": "steps[4]"},
            },
        )
        assert issue.status_code == 201, issue.text
        issue_id = issue.json()["id"]
        assert issue.json()["retest_count"] == 0

        retest_body = {
            "target_build_id": "quality-api-build-v2",
            "target_scenario_version_id": "quality-api-scenario-v1",
            "lane_scope": [lane_id],
            "idempotency_key": "quality-api-retest-1",
            "consent": {"accepted": True, "device_minutes": 15, "price_minor": 0},
        }
        retest = await client.post(f"{issues_url}/{issue_id}/retests", json=retest_body)
        assert retest.status_code == 201, retest.text
        repeated = await client.post(
            f"{issues_url}/{issue_id}/retests", json=retest_body
        )
        assert repeated.status_code == 201, repeated.text
        assert repeated.json()["id"] == retest.json()["id"]
        listed_issues = await client.get(issues_url)
        assert listed_issues.status_code == 200, listed_issues.text
        assert listed_issues.json()["items"][0]["retest_count"] == 1

    app.dependency_overrides[_get_current_user] = _owner_override(USER_B, ORG_B)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as other:
        assert (await other.get(issues_url)).status_code == 404
        assert (
            await other.post(participation_url, json=participation_body)
        ).status_code == 404
        assert (
            await other.post(f"{issues_url}/{issue_id}/retests", json=retest_body)
        ).status_code == 404
