from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab_runtime import QuotaLedgerEntry
from services.ai_device_lab.quota import (
    AppendQuotaEntry,
    QuotaInvariantError,
    append_quota_entry,
)
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


@pytest.mark.asyncio
async def test_quota_replay_is_idempotent_and_balance_cannot_be_negative(
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
            reserve = AppendQuotaEntry(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                charge_key="quota-reserve-1",
                entry_type="reserved",
                resource_type="device_seconds",
                quantity=900,
                occurred_at=now,
            )
            first = await append_quota_entry(db, reserve)
            replay = await append_quota_entry(db, reserve)
            with pytest.raises(QuotaInvariantError, match="charge key"):
                await append_quota_entry(
                    db,
                    AppendQuotaEntry(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        charge_key="quota-reserve-1",
                        entry_type="reserved",
                        resource_type="device_seconds",
                        quantity=901,
                        occurred_at=now,
                    ),
                )
            await append_quota_entry(
                db,
                AppendQuotaEntry(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    charge_key="quota-consume-1",
                    entry_type="consumed",
                    resource_type="device_seconds",
                    quantity=600,
                    occurred_at=now,
                ),
            )
            with pytest.raises(QuotaInvariantError):
                await append_quota_entry(
                    db,
                    AppendQuotaEntry(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        charge_key="quota-overconsume",
                        entry_type="consumed",
                        resource_type="device_seconds",
                        quantity=301,
                        occurred_at=now,
                    ),
                )
            count = await db.scalar(select(func.count()).select_from(QuotaLedgerEntry))

    assert replay.id == first.id
    assert count == 2
