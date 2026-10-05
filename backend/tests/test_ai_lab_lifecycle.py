from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from db.models.ai_device_lab import RunAttempt, RunSlot, ServiceCampaign
from db.models.ai_device_lab_fleet import DeviceReservation
from db.models.ai_device_lab_lifecycle import FleetLifecycleOperation, LaneDeviceAssignment, ServiceExtension
from db.models.ai_device_lab_runtime import QuotaLedgerEntry
from db.models.ai_device_lab_secrets import JobSecretCapability
from db.models.device import Device
from services.ai_device_lab.fleet import ReserveCohort, record_hygiene_result, reserve_cohort
from services.ai_device_lab.billing import (
    AcceptPaymentEvent,
    CreateOrder,
    PriceSnapshot,
    accept_payment_event,
    create_order,
)
from services.ai_device_lab.lifecycle import (
    ExtendServiceCampaign,
    LifecycleInvariantError,
    ReplaceLaneDevice,
    cancel_service_campaign,
    complete_campaign_cancellation,
    complete_device_replacement,
    expire_service_campaign,
    extend_service_campaign,
    replace_lane_device,
)
from services.ai_device_lab.readiness import materialize_service_slots
from services.ai_device_lab.reporting import BuildReport, build_report_snapshot
from services.ai_device_lab.service_campaigns import CreateServiceCampaign, create_service_campaign
from tenancy.context import tenant_context
from tests.tenancy_test_support import ORG_A, USER_A, seed_two_org_fixture


async def _seed_reserved_campaign(db, runtime_campaign_id: str):
    starts_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
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
            id=f"adl-lifecycle-{ordinal:02d}",
            org_id=ORG_A,
            user_id=USER_A,
            serial=f"ADL-LIFECYCLE-{ordinal:02d}",
            name=f"ADL lifecycle {ordinal:02d}",
        )
        for ordinal in range(1, 14)
    ]
    db.add_all(devices)
    await db.flush()
    for device in devices[:12]:
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
    reservations = await reserve_cohort(
        db,
        ReserveCohort(
            org_id=ORG_A,
            service_campaign_id=campaign.id,
            device_ids=tuple(device.id for device in devices[:12]),
            starts_at=starts_at,
            ends_at=starts_at + timedelta(days=14),
            created_by=USER_A,
        ),
    )
    campaign.status = "running"
    campaign.started_at = starts_at
    campaign.end_at = starts_at + timedelta(days=14)
    await db.flush()
    return campaign, devices, reservations


@pytest.mark.asyncio
async def test_initial_reservation_creates_current_assignment_for_every_lane(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            await _seed_reserved_campaign(db, seeded["campaign_a"])
            assignments = list((await db.execute(select(LaneDeviceAssignment))).scalars())

    assert len(assignments) == 12
    assert len({assignment.lane_id for assignment in assignments}) == 12
    assert all(assignment.ended_at is None for assignment in assignments)


@pytest.mark.asyncio
async def test_replacement_waits_for_active_run_then_switches_assignment_once(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    requested_at = datetime(2026, 10, 7, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, devices, reservations = await _seed_reserved_campaign(db, seeded["campaign_a"])
            await record_hygiene_result(
                db,
                device_id=devices[-1].id,
                actor_id=USER_A,
                protocol_version="hygiene-v1",
                reset_succeeded=True,
                readback_clean=True,
                evidence_ref="evidence/spare-clean",
                active_run=False,
            )
            active_attempt = RunAttempt(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=reservations[0].lane_id,
                slot_id="slot-replace-active",
                attempt_no=1,
                execution_id="execution-replace-active",
                scenario_version_id="scenario-version-replace",
                app_build_id="build-replace",
                idempotency_key="attempt-replace-active",
                reason="scheduled",
                status="running",
            )
            db.add(active_attempt)
            await db.flush()
            command = ReplaceLaneDevice(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=reservations[0].lane_id,
                new_device_id=devices[-1].id,
                idempotency_key="replace-lane-1",
                actor_id=USER_A,
                reason="device health degraded",
                now=requested_at,
            )
            operation = await replace_lane_device(db, command)
            repeated = await replace_lane_device(db, command)
            with pytest.raises(LifecycleInvariantError, match="replacement idempotency key"):
                await replace_lane_device(
                    db,
                    ReplaceLaneDevice(
                        org_id=command.org_id,
                        service_campaign_id=command.service_campaign_id,
                        lane_id=command.lane_id,
                        new_device_id=command.new_device_id,
                        idempotency_key=command.idempotency_key,
                        actor_id=command.actor_id,
                        reason="different replacement reason",
                        now=command.now,
                    ),
                )
            current_before = (
                await db.execute(
                    select(LaneDeviceAssignment).where(
                        LaneDeviceAssignment.lane_id == reservations[0].lane_id,
                        LaneDeviceAssignment.ended_at.is_(None),
                    )
                )
            ).scalar_one()

            assert repeated.id == operation.id
            assert operation.status == "waiting"
            assert reservations[0].state == "draining"
            assert current_before.device_id == reservations[0].device_id

            with pytest.raises(LifecycleInvariantError, match="old lane run is active"):
                await complete_device_replacement(
                    db,
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    operation_id=operation.id,
                    now=requested_at + timedelta(minutes=4),
                )
            active_attempt.status = "succeeded"
            await db.flush()
            completed = await complete_device_replacement(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id=operation.id,
                now=requested_at + timedelta(minutes=5),
            )
            completed_again = await complete_device_replacement(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id=operation.id,
                now=requested_at + timedelta(minutes=6),
            )
            assignments = list(
                (
                    await db.execute(
                        select(LaneDeviceAssignment).where(
                            LaneDeviceAssignment.lane_id == reservations[0].lane_id
                        )
                    )
                ).scalars()
            )
            active = list(
                (
                    await db.execute(
                        select(DeviceReservation).where(
                            DeviceReservation.lane_id == reservations[0].lane_id,
                            DeviceReservation.state == "active",
                        )
                    )
                ).scalars()
            )

    assert completed.status == "completed"
    assert completed_again.id == completed.id
    assert len(assignments) == 2
    assert len([assignment for assignment in assignments if assignment.ended_at is None]) == 1
    assert active[0].device_id == devices[-1].id


@pytest.mark.asyncio
async def test_replacement_rejects_spare_without_verified_hygiene(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, devices, reservations = await _seed_reserved_campaign(db, seeded["campaign_a"])
            with pytest.raises(LifecycleInvariantError, match="verified-clean"):
                await replace_lane_device(
                    db,
                    ReplaceLaneDevice(
                        org_id=ORG_A,
                        service_campaign_id=campaign.id,
                        lane_id=reservations[0].lane_id,
                        new_device_id=devices[-1].id,
                        idempotency_key="replace-dirty-spare",
                        actor_id=USER_A,
                        reason="test guard",
                        now=datetime(2026, 10, 7, tzinfo=timezone.utc),
                    ),
                )
            operation_count = await db.scalar(select(func.count()).select_from(FleetLifecycleOperation))

    assert operation_count == 0


@pytest.mark.asyncio
async def test_paid_consented_extension_adds_delta_without_mutating_frozen_report(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, _devices, reservations = await _seed_reserved_campaign(db, seeded["campaign_a"])
            original_slots = await materialize_service_slots(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
            )
            report = await build_report_snapshot(
                db,
                BuildReport(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="report-before-extension",
                    schema_version="report-v1",
                    builder_version="builder-v1",
                    cutoff_at=datetime.now(timezone.utc) + timedelta(minutes=1),
                    created_by=USER_A,
                ),
            )
            original_report_hash = report.manifest_sha256
            original_manifest = dict(report.manifest)
            order = await create_order(
                db,
                CreateOrder(
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="extension-order-1",
                    created_by=USER_A,
                    price=PriceSnapshot(
                        plan_version=campaign.plan_version,
                        pricing_version="extension-price-v1",
                        policy_version="extension-policy-v1",
                        amount_minor=19900,
                        currency="USD",
                        quota={"extension_service_days": 2, "slots": 24},
                    ),
                ),
            )
            _event, entitlement = await accept_payment_event(
                db,
                AcceptPaymentEvent(
                    org_id=ORG_A,
                    order_id=order.id,
                    provider="sandbox",
                    provider_event_id="extension-paid-1",
                    event_type="payment.settled",
                    source_occurred_at=now,
                    signature_verified=True,
                    amount_minor=19900,
                    currency="USD",
                ),
            )
            assert entitlement is not None
            command = ExtendServiceCampaign(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                order_id=order.id,
                entitlement_id=entitlement.id,
                idempotency_key="extend-campaign-1",
                actor_id=USER_A,
                added_service_days=2,
                consent_snapshot={
                    "accepted": True,
                    "accepted_at": now.isoformat(),
                    "policy_version": "extension-policy-v1",
                    "pricing_version": "extension-price-v1",
                    "amount_minor": 19900,
                    "currency": "USD",
                },
                now=now,
            )
            extension = await extend_service_campaign(db, command)
            repeated = await extend_service_campaign(db, command)
            with pytest.raises(LifecycleInvariantError, match="extension idempotency key"):
                await extend_service_campaign(
                    db,
                    ExtendServiceCampaign(
                        org_id=command.org_id,
                        service_campaign_id=command.service_campaign_id,
                        order_id=command.order_id,
                        entitlement_id=command.entitlement_id,
                        idempotency_key=command.idempotency_key,
                        actor_id=command.actor_id,
                        added_service_days=command.added_service_days + 1,
                        consent_snapshot=command.consent_snapshot,
                        now=command.now,
                    ),
                )
            slots = list(
                (
                    await db.execute(
                        select(RunSlot).where(RunSlot.service_campaign_id == campaign.id)
                    )
                ).scalars()
            )
            quota = (
                await db.execute(
                    select(QuotaLedgerEntry).where(
                        QuotaLedgerEntry.service_campaign_id == campaign.id,
                        QuotaLedgerEntry.entry_type == "adjusted",
                    )
                )
            ).scalar_one()
            extension_count = await db.scalar(select(func.count()).select_from(ServiceExtension))

    assert len(original_slots) == 168
    assert repeated.id == extension.id
    assert extension_count == 1
    assert len(slots) == 192
    assert len([slot for slot in slots if slot.service_day in {15, 16}]) == 24
    assert quota.quantity == 24
    assert campaign.end_at == extension.new_end_at
    assert all(reservation.ends_at == extension.new_end_at for reservation in reservations)
    assert report.manifest_sha256 == original_report_hash
    assert report.manifest == original_manifest


@pytest.mark.asyncio
async def test_cancel_waits_for_runs_then_revokes_and_releases_idempotently(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    requested_at = datetime(2026, 10, 7, tzinfo=timezone.utc)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, devices, reservations = await _seed_reserved_campaign(db, seeded["campaign_a"])
            lane_id = reservations[0].lane_id
            slot = RunSlot(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=lane_id,
                service_day=3,
                planned_at=requested_at + timedelta(hours=1),
                execution_status="planned",
            )
            capability = JobSecretCapability(
                org_id=ORG_A,
                capability_ref="cap-cancel-test",
                secret_record_id="secret-placeholder",
                service_campaign_id=campaign.id,
                lane_id=lane_id,
                run_attempt_id="attempt-placeholder",
                device_id=devices[0].id,
                worker_principal="worker-test",
                allowed_operation="resolve",
                expires_at=requested_at + timedelta(hours=2),
            )
            db.add_all([slot, capability])
            active_attempt = RunAttempt(
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                lane_id=lane_id,
                slot_id="slot-cancel-active",
                attempt_no=1,
                execution_id="execution-cancel-active",
                scenario_version_id="scenario-version-cancel",
                app_build_id="build-cancel",
                idempotency_key="attempt-cancel-active",
                reason="scheduled",
                status="running",
            )
            db.add(active_attempt)
            await db.flush()

            operation = await cancel_service_campaign(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                idempotency_key="cancel-campaign-1",
                actor_id=USER_A,
                reason="customer cancellation",
                now=requested_at,
            )
            repeated = await cancel_service_campaign(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                idempotency_key="cancel-campaign-1",
                actor_id=USER_A,
                reason="customer cancellation",
                now=requested_at,
            )
            with pytest.raises(LifecycleInvariantError, match="cancellation idempotency key"):
                await cancel_service_campaign(
                    db,
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="cancel-campaign-1",
                    actor_id=USER_A,
                    reason="different cancellation reason",
                    now=requested_at,
                )

            assert operation.status == "waiting"
            assert repeated.id == operation.id
            assert slot.execution_status == "cancelled"
            assert capability.revoked_at is None
            assert all(reservation.state == "active" for reservation in reservations)

            with pytest.raises(LifecycleInvariantError, match="campaign runs are active"):
                await complete_campaign_cancellation(
                    db,
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    operation_id=operation.id,
                    now=requested_at + timedelta(minutes=9),
                )
            active_attempt.status = "succeeded"
            await db.flush()
            completed = await complete_campaign_cancellation(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id=operation.id,
                now=requested_at + timedelta(minutes=10),
            )
            completed_again = await complete_campaign_cancellation(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                operation_id=operation.id,
                now=requested_at + timedelta(minutes=11),
            )
            current_assignment_count = await db.scalar(
                select(func.count())
                .select_from(LaneDeviceAssignment)
                .where(LaneDeviceAssignment.ended_at.is_(None))
            )
            refreshed_campaign = await db.get(ServiceCampaign, campaign.id)

    assert completed.status == "completed"
    assert completed_again.id == completed.id
    assert refreshed_campaign.status == "cancelled"
    assert capability.revoked_at == requested_at + timedelta(minutes=10)
    assert all(reservation.state == "released" for reservation in reservations)
    assert current_assignment_count == 0


@pytest.mark.asyncio
async def test_expiry_is_due_only_idempotent_and_releases_resources(
    tenancy_session_factory,
) -> None:
    seeded = await seed_two_org_fixture(tenancy_session_factory)
    with tenant_context(ORG_A):
        async with tenancy_session_factory() as db:
            campaign, _devices, reservations = await _seed_reserved_campaign(
                db, seeded["campaign_a"]
            )
            assert campaign.end_at is not None
            with pytest.raises(LifecycleInvariantError, match="before its service end"):
                await expire_service_campaign(
                    db,
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="expire-campaign-early",
                    actor_id=USER_A,
                    reason="scheduled service expiry",
                    now=campaign.end_at - timedelta(seconds=1),
                )

            operation = await expire_service_campaign(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                idempotency_key="expire-campaign-due",
                actor_id=USER_A,
                reason="scheduled service expiry",
                now=campaign.end_at,
            )
            repeated = await expire_service_campaign(
                db,
                org_id=ORG_A,
                service_campaign_id=campaign.id,
                idempotency_key="expire-campaign-due",
                actor_id=USER_A,
                reason="scheduled service expiry",
                now=campaign.end_at + timedelta(minutes=1),
            )
            with pytest.raises(LifecycleInvariantError, match="expiry idempotency key"):
                await expire_service_campaign(
                    db,
                    org_id=ORG_A,
                    service_campaign_id=campaign.id,
                    idempotency_key="expire-campaign-due",
                    actor_id=USER_A,
                    reason="different expiry reason",
                    now=campaign.end_at + timedelta(minutes=1),
                )
            refreshed_campaign = await db.get(ServiceCampaign, campaign.id)

    assert operation.operation_type == "expire"
    assert operation.status == "completed"
    assert operation.checkpoint == "resources_released"
    assert repeated.id == operation.id
    assert refreshed_campaign.status == "expired"
    assert all(reservation.state == "released" for reservation in reservations)
