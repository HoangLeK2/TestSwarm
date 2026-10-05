from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from api.deps import _get_current_user
from db.models.ai_device_lab import (
    AppBuild,
    RunAttempt,
    RunSlot,
    ScenarioApproval,
    ServiceCampaign,
    ServiceLane,
)
from db.models.ai_device_lab_delivery import FarmEventInbox, FarmJob, FarmJobOutbox
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.device import Device
from db.models.execution import Execution
from services.ai_device_lab.delivery import AcceptFarmEvent, accept_farm_event
from tenancy.context import set_current_org_id, tenant_context
from tests.tenancy_test_support import (
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    build_tenancy_api_app,
)
from tests.test_ai_lab_billing_checkout import _seed_approved_campaign


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


async def _seed_dispatchable_run(session_factory) -> dict[str, str]:
    campaign_id, approval_id = await _seed_approved_campaign(session_factory)
    now = datetime.now(UTC).replace(microsecond=0)
    with tenant_context(ORG_A):
        async with session_factory() as db:
            campaign = await db.get(ServiceCampaign, campaign_id)
            approval = await db.get(ScenarioApproval, approval_id)
            lane = await db.scalar(
                select(ServiceLane)
                .where(ServiceLane.service_campaign_id == campaign_id)
                .order_by(ServiceLane.ordinal)
                .limit(1)
            )
            assert campaign is not None and approval is not None and lane is not None
            device = Device(
                id="adl-farm-api-emulator",
                org_id=ORG_A,
                user_id=USER_A,
                serial="emulator-5580",
                name="ADL API emulator",
                last_seen=now,
            )
            build = AppBuild(
                id="adl-farm-api-build",
                org_id=ORG_A,
                package_name=approval.package_name,
                version_name="1.0.0",
                version_code="100",
                source_kind="closed_track",
                source_ref="play-closed-track",
            )
            slot = RunSlot(
                id="adl-farm-api-slot",
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=lane.id,
                service_day=1,
                planned_at=now,
                execution_status="scheduled",
                play_participation_state="unknown",
            )
            execution = Execution(
                id="adl-farm-api-execution",
                run_type="ai_device_lab",
                kind="campaign",
                status="pending",
                org_id=ORG_A,
                campaign_id=campaign.runtime_campaign_id,
                scenario_version_id=approval.scenario_version_id,
                user_id=USER_A,
                device_config={"device_id": device.id, "device_serial": device.serial},
                meta={"target_type": "emulator"},
            )
            reservation = DeviceReservation(
                id="adl-farm-api-reservation",
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=lane.id,
                device_id=device.id,
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(days=14),
                state="active",
                created_by=USER_A,
            )
            db.add_all([device, build, slot, execution, reservation])
            await db.commit()
            return {
                "campaign_id": campaign.id,
                "lane_id": lane.id,
                "slot_id": slot.id,
                "execution_id": execution.id,
                "scenario_version_id": approval.scenario_version_id,
                "app_build_id": build.id,
                "reservation_id": reservation.id,
                "approval_id": approval.id,
            }


@pytest.mark.asyncio
async def test_farm_run_api_is_idempotent_traceable_and_tenant_scoped(
    tenancy_session_factory,
) -> None:
    refs = await _seed_dispatchable_run(tenancy_session_factory)
    app = build_tenancy_api_app(tenancy_session_factory)
    app.dependency_overrides[_get_current_user] = _owner_override(USER_A, ORG_A)
    deadline = datetime.now(UTC) + timedelta(minutes=5)
    body = {
        **{key: value for key, value in refs.items() if key != "campaign_id"},
        "idempotency_key": "adl-farm-api-idempotency",
        "deadline_at": deadline.isoformat(),
        "reason": "scheduled",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            f"/api/ai-device-lab/service-campaigns/{refs['campaign_id']}/farm-runs",
            json=body,
        )
        replay = await client.post(
            f"/api/ai-device-lab/service-campaigns/{refs['campaign_id']}/farm-runs",
            json=body,
        )
        assert first.status_code == 201, first.text
        assert replay.status_code == 201, replay.text
        assert replay.json() == first.json()
        created = first.json()
        assert created["execution_id"] == refs["execution_id"]
        assert created["slot_id"] == refs["slot_id"]
        assert created["lane_id"] == refs["lane_id"]
        assert created["reservation_id"] == refs["reservation_id"]
        assert created["schema_version"] == "adl-farm-job-v1"

        occurred_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        completed_body = {
            "schema_version": "adl-farm-event-v1",
            "execution_id": refs["execution_id"],
            "source": "emulator-runtime",
            "event_id": "emulator-5580-complete-1",
            "event_type": "completed",
            "occurred_at": occurred_at,
            "sequence": 2,
            "reason_code": "ASSERTIONS_PASSED",
            "assertion_passed": True,
            "step_path": "steps[0]",
            "step_attempt_index": 0,
            "artifact_refs": ["evidence://adl-16/emulator-5580/screenshot.png"],
        }
        rejected_terminal = await client.post(
            f"/api/ai-device-lab/farm-jobs/{created['job_id']}/events",
            json=completed_body,
        )
        step_body = {
            **completed_body,
            "event_id": "emulator-5580-step-1",
            "event_type": "step",
            "reason_code": None,
            "assertion_passed": None,
        }
        accepted_step = await client.post(
            f"/api/ai-device-lab/farm-jobs/{created['job_id']}/events",
            json=step_body,
        )
        assert rejected_terminal.status_code == 403
        assert accepted_step.status_code == 200, accepted_step.text

        with tenant_context(ORG_A):
            async with tenancy_session_factory() as db:
                await accept_farm_event(
                    db,
                    AcceptFarmEvent(
                        org_id=ORG_A,
                        job_id=created["job_id"],
                        schema_version="adl-farm-event-v1",
                        execution_id=refs["execution_id"],
                        source="emulator-runtime-internal",
                        event_id="emulator-5580-complete-1",
                        event_type="completed",
                        occurred_at=datetime.now(UTC),
                        reason_code="ASSERTIONS_PASSED",
                        assertion_passed=True,
                        artifact_refs=("evidence://adl-16/emulator-5580/screenshot.png",),
                    ),
                )
                await db.commit()
        inspected = await client.get(
            f"/api/ai-device-lab/farm-jobs/{created['job_id']}"
        )
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["verdict"] == "pass"

        app.dependency_overrides[_get_current_user] = _owner_override(USER_B, ORG_B)
        hidden = await client.get(
            f"/api/ai-device-lab/farm-jobs/{created['job_id']}"
        )
        assert hidden.status_code == 404

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(RunAttempt)) == 1
            assert await db.scalar(select(func.count()).select_from(FarmJob)) == 1
            assert await db.scalar(select(func.count()).select_from(FarmJobOutbox)) == 1
            events = list((await db.execute(select(FarmEventInbox))).scalars())
            slot = await db.get(RunSlot, refs["slot_id"])
            assert slot is not None
            assert slot.execution_status == "completed"
            assert slot.app_verdict == "pass"
            assert len(events) == 2
            terminal = next(event for event in events if event.event_type == "completed")
            assert terminal.schema_version == "adl-farm-event-v1"
            assert terminal.execution_id == refs["execution_id"]
            assert terminal.artifact_refs == [
                "evidence://adl-16/emulator-5580/screenshot.png"
            ]
