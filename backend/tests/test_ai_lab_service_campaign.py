from __future__ import annotations

import pytest
from datetime import datetime, timezone

from sqlalchemy import func, select

from db.models.ai_device_lab import AppBuild, RunAttempt, RunSlot, ServiceCampaign, ServiceLane
from db.models.campaign import Scenario
from db.models.scenario_version import ScenarioVersion
from services.ai_device_lab.service_campaigns import (
    AllocateRunAttempt,
    CreateRunSlot,
    CreateServiceCampaign,
    ServiceCampaignInvariantError,
    allocate_run_attempt,
    create_run_slot,
    create_service_campaign,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


@pytest.mark.asyncio
async def test_create_service_campaign_builds_twelve_stable_lanes(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="Asia/Ho_Chi_Minh",
                    plan_version="adl-14d-v1",
                ),
            )
            await db.commit()

            lanes = list(
                (
                    await db.execute(
                        select(ServiceLane)
                        .where(ServiceLane.service_campaign_id == campaign.id)
                        .order_by(ServiceLane.ordinal)
                    )
                )
                .scalars()
                .all()
            )

    assert campaign.status == "draft"
    assert campaign.started_at is None
    assert [lane.ordinal for lane in lanes] == list(range(1, 13))
    assert [lane.tester_label for lane in lanes] == [
        f"Tester {ordinal:02d}" for ordinal in range(1, 13)
    ]


@pytest.mark.asyncio
async def test_same_attempt_intent_is_idempotent_and_does_not_add_a_slot(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)

    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign = await create_service_campaign(
                db,
                CreateServiceCampaign(
                    org_id=ORG_A,
                    owner_id=USER_A,
                    runtime_campaign_id=seeded["campaign_a"],
                    package_name="com.example.app",
                    timezone="UTC",
                    plan_version="adl-14d-v1",
                    lane_count=1,
                ),
            )
            lane = (
                await db.execute(
                    select(ServiceLane).where(
                        ServiceLane.service_campaign_id == campaign.id
                    )
                )
            ).scalar_one()
            build = AppBuild(
                org_id=ORG_A,
                package_name="com.example.app",
                version_name="1.0.0",
                version_code="100",
                source_kind="uploaded_artifact",
                checksum_sha256="a" * 64,
            )
            scenario = Scenario(
                id="adl-scenario-1",
                campaign_id=seeded["campaign_a"],
                name="Approved journey",
                steps=[{"type": "take_screenshot"}],
            )
            version = ScenarioVersion(
                id="adl-scenario-version-1",
                scenario_id=scenario.id,
                version=1,
                steps=scenario.steps,
            )
            db.add_all([build, scenario, version])
            await db.flush()
            slot = await create_run_slot(
                db,
                CreateRunSlot(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    lane_id=lane.id,
                    service_day=1,
                    planned_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
                ),
            )
            command = AllocateRunAttempt(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=lane.id,
                slot_id=slot.id,
                execution_id="execution-adl-1",
                scenario_version_id=version.id,
                app_build_id=build.id,
                idempotency_key="attempt-intent-1",
                reason="scheduled",
            )

            first = await allocate_run_attempt(db, command)
            second = await allocate_run_attempt(db, command)
            with pytest.raises(ServiceCampaignInvariantError, match="attempt idempotency key"):
                await allocate_run_attempt(
                    db,
                    AllocateRunAttempt(
                        org_id=command.org_id,
                        service_campaign_id=command.service_campaign_id,
                        lane_id=command.lane_id,
                        slot_id=command.slot_id,
                        execution_id="execution-adl-different",
                        scenario_version_id=command.scenario_version_id,
                        app_build_id=command.app_build_id,
                        idempotency_key=command.idempotency_key,
                        reason=command.reason,
                    ),
                )
            await db.commit()

            slot_count = await db.scalar(select(func.count()).select_from(RunSlot))
            attempt_count = await db.scalar(select(func.count()).select_from(RunAttempt))

    assert second.id == first.id
    assert first.attempt_no == 1
    assert slot_count == 1
    assert attempt_count == 1
