from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.device import Device
from services.ai_device_lab.fleet import (
    FleetInvariantError,
    ReserveCohort,
    record_hygiene_result,
    release_reservation,
    reserve_cohort,
)
from services.ai_device_lab.service_campaigns import (
    CreateServiceCampaign,
    create_service_campaign,
)
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


def test_reservation_model_declares_interval_and_overlap_guards() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in DeviceReservation.__table__.constraints
        if constraint.name
    }

    assert (
        constraints["chk_device_reservation_interval"].__class__.__name__
        == "CheckConstraint"
    )
    assert (
        constraints["ex_device_reservation_overlap"].__class__.__name__
        == "ExcludeConstraint"
    )


async def _seed_campaign_and_devices(db, runtime_campaign_id: str, count: int = 12):
    campaign = await create_service_campaign(
        db,
        CreateServiceCampaign(
            org_id=ORG_A,
            owner_id=USER_A,
            runtime_campaign_id=runtime_campaign_id,
            package_name="com.example.app",
            timezone="UTC",
            plan_version="adl-14d-v1",
        ),
    )
    devices = [
        Device(
            id=f"adl-fleet-{ordinal:02d}",
            org_id=ORG_A,
            user_id=USER_A,
            serial=f"ADL-FLEET-{ordinal:02d}",
            name=f"ADL fleet {ordinal:02d}",
        )
        for ordinal in range(1, count + 1)
    ]
    db.add_all(devices)
    await db.flush()
    for device in devices:
        await record_hygiene_result(
            db,
            device_id=device.id,
            actor_id=USER_A,
            protocol_version="hygiene-v1",
            reset_succeeded=True,
            readback_clean=True,
            evidence_ref=f"evidence/{device.id}",
            active_run=False,
        )
    return campaign, devices


@pytest.mark.asyncio
async def test_reserve_requires_twelve_and_commits_twelve_clean_devices(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    starts = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, devices = await _seed_campaign_and_devices(
                db, seeded["campaign_a"]
            )
            reservations = await reserve_cohort(
                db,
                ReserveCohort(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    device_ids=tuple(device.id for device in devices),
                    starts_at=starts,
                    ends_at=starts + timedelta(days=14),
                    created_by=USER_A,
                ),
            )
            await db.commit()
            count = await db.scalar(select(func.count()).select_from(DeviceReservation))

    assert len(reservations) == 12
    assert count == 12
    assert len({row.device_id for row in reservations}) == 12


@pytest.mark.asyncio
async def test_eleven_devices_leave_zero_reservations_and_failed_clean_is_quarantined(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    starts = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, devices = await _seed_campaign_and_devices(
                db, seeded["campaign_a"]
            )
            quarantined = await record_hygiene_result(
                db,
                device_id=devices[-1].id,
                actor_id=USER_A,
                protocol_version="hygiene-v1",
                reset_succeeded=True,
                readback_clean=False,
                evidence_ref="evidence/dirty-readback",
                active_run=False,
            )
            with pytest.raises(FleetInvariantError):
                await reserve_cohort(
                    db,
                    ReserveCohort(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        device_ids=tuple(device.id for device in devices[:11]),
                        starts_at=starts,
                        ends_at=starts + timedelta(days=14),
                        created_by=USER_A,
                    ),
                )
            count = await db.scalar(select(func.count()).select_from(DeviceReservation))

    assert quarantined.state == "quarantined"
    assert count == 0


@pytest.mark.asyncio
async def test_release_drains_active_run_and_is_idempotent_after_terminal(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    starts = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, devices = await _seed_campaign_and_devices(
                db, seeded["campaign_a"]
            )
            reservations = await reserve_cohort(
                db,
                ReserveCohort(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    device_ids=tuple(device.id for device in devices),
                    starts_at=starts,
                    ends_at=starts + timedelta(days=14),
                    created_by=USER_A,
                ),
            )
            draining = await release_reservation(
                db,
                org_id=ORG_A,
                reservation_id=reservations[0].id,
                actor_id=USER_A,
                reason="campaign cancelled",
                active_run=True,
            )
            assert draining.state == "draining"
            released = await release_reservation(
                db,
                org_id=ORG_A,
                reservation_id=reservations[0].id,
                actor_id=USER_A,
                reason="drain confirmed",
                active_run=False,
            )
            repeated = await release_reservation(
                db,
                org_id=ORG_A,
                reservation_id=reservations[0].id,
                actor_id=USER_A,
                reason="repeat",
                active_run=False,
            )

    assert released.state == "released"
    assert repeated.id == released.id
