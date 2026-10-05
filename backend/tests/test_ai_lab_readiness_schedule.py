from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab import RunSlot
from db.models.ai_device_lab_billing import ServiceEntitlement
from db.models.ai_device_lab_runtime import SchedulingIntent
from services.ai_device_lab.readiness import (
    ReadinessPolicy,
    StartCampaign,
    materialize_service_slots,
    start_campaign,
)
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


@pytest.mark.asyncio
async def test_paid_campaign_with_missing_approval_and_devices_does_not_start(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
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
                ),
            )
            db.add(
                ServiceEntitlement(
                    org_id=ORG_A,
                    order_id="order-placeholder",
                    service_campaign_id=campaign.id,
                    state="active",
                )
            )
            await db.flush()
            result = await start_campaign(
                db,
                StartCampaign(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="start-blocked-1",
                    now=now,
                    policy=ReadinessPolicy(
                        version="readiness-v1",
                        require_participation=False,
                    ),
                ),
            )
            intent_count = await db.scalar(select(func.count()).select_from(SchedulingIntent))

    reasons = {check.check_key: check.reason_code for check in result.checks}
    assert result.started is False
    assert campaign.started_at is None
    assert intent_count == 0
    assert reasons["scenario_approval"] == "APPROVED_SCENARIO_REQUIRED"
    assert reasons["reservations"] == "TWELVE_ACTIVE_RESERVATIONS_REQUIRED"


@pytest.mark.asyncio
async def test_materializer_is_idempotent_with_168_slots_and_twelve_per_day(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
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
                ),
            )
            campaign.started_at = now
            campaign.end_at = now.replace(day=19)
            campaign.status = "active"
            await db.flush()
            first = await materialize_service_slots(
                db, org_id=ORG_A, service_campaign_id=campaign.id
            )
            second = await materialize_service_slots(
                db, org_id=ORG_A, service_campaign_id=campaign.id
            )
            await db.commit()
            rows = list((await db.execute(select(RunSlot))).scalars().all())

    assert len(first) == 168
    assert len(second) == 168
    assert len(rows) == 168
    assert Counter(slot.service_day for slot in rows) == {day: 12 for day in range(1, 15)}
