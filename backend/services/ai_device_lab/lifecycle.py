"""Recoverable device replacement and campaign cancellation sagas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import RunAttempt, RunSlot, ServiceCampaign, ServiceLane
from db.models.ai_device_lab_billing import ServiceEntitlement, ServiceOrder
from db.models.ai_device_lab_fleet import DeviceHygieneState, DeviceReservation
from db.models.ai_device_lab_lifecycle import FleetLifecycleOperation, LaneDeviceAssignment, ServiceExtension
from db.models.ai_device_lab_runtime import QuotaLedgerEntry
from db.models.ai_device_lab_secrets import JobSecretCapability


class LifecycleInvariantError(ValueError):
    pass


ACTIVE_ATTEMPT_STATES = ("queued", "dispatching", "running", "retrying")


@dataclass(frozen=True, slots=True)
class ReplaceLaneDevice:
    org_id: str
    service_campaign_id: str
    lane_id: str
    new_device_id: str
    idempotency_key: str
    actor_id: str
    reason: str
    now: datetime


@dataclass(frozen=True, slots=True)
class ExtendServiceCampaign:
    org_id: str
    service_campaign_id: str
    order_id: str
    entitlement_id: str
    idempotency_key: str
    actor_id: str
    added_service_days: int
    consent_snapshot: dict
    now: datetime


async def extend_service_campaign(
    db: AsyncSession,
    command: ExtendServiceCampaign,
) -> ServiceExtension:
    existing = (
        await db.execute(
            select(ServiceExtension).where(
                ServiceExtension.org_id == command.org_id,
                ServiceExtension.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.service_campaign_id != command.service_campaign_id
            or existing.order_id != command.order_id
            or existing.entitlement_id != command.entitlement_id
            or existing.added_service_days != command.added_service_days
            or existing.consent_snapshot != command.consent_snapshot
            or existing.created_by != command.actor_id
        ):
            raise LifecycleInvariantError("extension idempotency key was reused with different input")
        return existing
    if command.added_service_days <= 0:
        raise LifecycleInvariantError("extension days must be positive")
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None or campaign.started_at is None or campaign.end_at is None:
        raise LifecycleInvariantError("active campaign with a fixed end is required")
    if campaign.status not in {"active", "running", "needs_attention"}:
        raise LifecycleInvariantError("campaign state does not allow extension")
    order = (
        await db.execute(
            select(ServiceOrder).where(
                ServiceOrder.id == command.order_id,
                ServiceOrder.org_id == command.org_id,
                ServiceOrder.service_campaign_id == campaign.id,
            )
        )
    ).scalar_one_or_none()
    entitlement = (
        await db.execute(
            select(ServiceEntitlement).where(
                ServiceEntitlement.id == command.entitlement_id,
                ServiceEntitlement.org_id == command.org_id,
                ServiceEntitlement.order_id == command.order_id,
                ServiceEntitlement.service_campaign_id == campaign.id,
                ServiceEntitlement.state == "active",
            )
        )
    ).scalar_one_or_none()
    expected_slots = command.added_service_days * 12
    if (
        order is None
        or order.status != "paid"
        or entitlement is None
        or order.quota_snapshot.get("extension_service_days") != command.added_service_days
        or order.quota_snapshot.get("slots") != expected_slots
    ):
        raise LifecycleInvariantError("paid extension entitlement and exact quota delta are required")
    consent = command.consent_snapshot
    if (
        consent.get("accepted") is not True
        or consent.get("policy_version") != order.policy_version
        or consent.get("pricing_version") != order.pricing_version
        or consent.get("amount_minor") != order.amount_minor
        or str(consent.get("currency", "")).upper() != order.currency
    ):
        raise LifecycleInvariantError("consent snapshot does not match the paid order")
    reservations = list(
        (
            await db.execute(
                select(DeviceReservation)
                .where(
                    DeviceReservation.org_id == command.org_id,
                    DeviceReservation.service_campaign_id == campaign.id,
                    DeviceReservation.state.in_(("active", "draining")),
                )
                .with_for_update()
            )
        ).scalars()
    )
    if len(reservations) != 12:
        raise LifecycleInvariantError("extension requires twelve retained lane reservations")
    lanes = list(
        (
            await db.execute(
                select(ServiceLane)
                .where(
                    ServiceLane.org_id == command.org_id,
                    ServiceLane.service_campaign_id == campaign.id,
                )
                .order_by(ServiceLane.ordinal)
            )
        ).scalars()
    )
    if len(lanes) != 12:
        raise LifecycleInvariantError("extension requires twelve stable lanes")
    last_service_day = int(
        await db.scalar(
            select(func.max(RunSlot.service_day)).where(
                RunSlot.org_id == command.org_id,
                RunSlot.service_campaign_id == campaign.id,
            )
        )
        or 0
    )
    previous_end_at = campaign.end_at
    new_end_at = previous_end_at + timedelta(days=command.added_service_days)
    extension = ServiceExtension(
        org_id=command.org_id,
        service_campaign_id=campaign.id,
        previous_end_at=previous_end_at,
        new_end_at=new_end_at,
        added_service_days=command.added_service_days,
        consent_snapshot=dict(command.consent_snapshot),
        order_id=order.id,
        entitlement_id=entitlement.id,
        idempotency_key=command.idempotency_key,
        created_by=command.actor_id,
    )
    db.add(extension)
    for reservation in reservations:
        reservation.ends_at = new_end_at
    for offset in range(1, command.added_service_days + 1):
        service_day = last_service_day + offset
        for lane in lanes:
            db.add(
                RunSlot(
                    org_id=command.org_id,
                    service_campaign_id=campaign.id,
                    lane_id=lane.id,
                    service_day=service_day,
                    planned_at=campaign.started_at
                    + timedelta(days=service_day - 1, seconds=lane.ordinal - 1),
                    execution_status="scheduled",
                    play_participation_state="unknown",
                )
            )
    db.add(
        QuotaLedgerEntry(
            org_id=command.org_id,
            service_campaign_id=campaign.id,
            charge_key=f"extension:{extension.id}:slots",
            entry_type="adjusted",
            resource_type="slots",
            quantity=expected_slots,
            metadata_json={
                "extension_id": extension.id,
                "order_id": order.id,
                "added_service_days": command.added_service_days,
            },
            occurred_at=command.now,
        )
    )
    campaign.end_at = new_end_at
    await db.flush()
    return extension


async def replace_lane_device(
    db: AsyncSession,
    command: ReplaceLaneDevice,
) -> FleetLifecycleOperation:
    existing = (
        await db.execute(
            select(FleetLifecycleOperation).where(
                FleetLifecycleOperation.org_id == command.org_id,
                FleetLifecycleOperation.idempotency_key == command.idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.operation_type != "replace"
            or existing.service_campaign_id != command.service_campaign_id
            or existing.lane_id != command.lane_id
            or existing.payload.get("new_device_id") != command.new_device_id
            or existing.actor_id != command.actor_id
            or existing.reason != command.reason
        ):
            raise LifecycleInvariantError("replacement idempotency key was reused with different input")
        return existing
    lane = (
        await db.execute(
            select(ServiceLane)
            .where(
                ServiceLane.id == command.lane_id,
                ServiceLane.org_id == command.org_id,
                ServiceLane.service_campaign_id == command.service_campaign_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    current = (
        await db.execute(
            select(LaneDeviceAssignment)
            .where(
                LaneDeviceAssignment.org_id == command.org_id,
                LaneDeviceAssignment.service_campaign_id == command.service_campaign_id,
                LaneDeviceAssignment.lane_id == command.lane_id,
                LaneDeviceAssignment.ended_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    hygiene = await db.get(DeviceHygieneState, command.new_device_id)
    if lane is None or current is None or hygiene is None or hygiene.state != "verified_clean":
        raise LifecycleInvariantError("replacement requires a current lane and verified-clean spare")
    old_reservation = (
        await db.execute(
            select(DeviceReservation)
            .where(
                DeviceReservation.id == current.reservation_id,
                DeviceReservation.org_id == command.org_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    conflict = await db.scalar(
        select(DeviceReservation.id).where(
            DeviceReservation.device_id == command.new_device_id,
            DeviceReservation.state.in_(("active", "draining")),
            DeviceReservation.starts_at < old_reservation.ends_at,
            DeviceReservation.ends_at > command.now,
        )
    )
    if conflict is not None:
        raise LifecycleInvariantError("replacement device already has an overlapping reservation")
    active_old_run = bool(
        await db.scalar(
            select(func.count()).select_from(RunAttempt).where(
                RunAttempt.org_id == command.org_id,
                RunAttempt.service_campaign_id == command.service_campaign_id,
                RunAttempt.lane_id == command.lane_id,
                RunAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
            )
        )
    )
    pending = DeviceReservation(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        lane_id=command.lane_id,
        device_id=command.new_device_id,
        starts_at=command.now,
        ends_at=old_reservation.ends_at,
        state="pending",
        created_by=command.actor_id,
    )
    db.add(pending)
    await db.flush()
    old_reservation.state = "draining" if active_old_run else "released"
    old_reservation.release_reason = command.reason
    old_reservation.released_at = None if active_old_run else command.now
    operation = FleetLifecycleOperation(
        org_id=command.org_id,
        service_campaign_id=command.service_campaign_id,
        lane_id=command.lane_id,
        operation_type="replace",
        idempotency_key=command.idempotency_key,
        status="waiting" if active_old_run else "running",
        checkpoint="awaiting_old_run_drain" if active_old_run else "new_device_reserved",
        old_reservation_id=old_reservation.id,
        new_reservation_id=pending.id,
        payload={"new_device_id": command.new_device_id},
        actor_id=command.actor_id,
        reason=command.reason,
    )
    db.add(operation)
    await db.flush()
    if not active_old_run:
        await complete_device_replacement(
            db,
            org_id=command.org_id,
            service_campaign_id=command.service_campaign_id,
            operation_id=operation.id,
            now=command.now,
        )
    return operation


async def complete_device_replacement(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    operation_id: str,
    now: datetime,
) -> FleetLifecycleOperation:
    operation = (
        await db.execute(
            select(FleetLifecycleOperation)
            .where(
                FleetLifecycleOperation.id == operation_id,
                FleetLifecycleOperation.org_id == org_id,
                FleetLifecycleOperation.service_campaign_id == service_campaign_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise LifecycleInvariantError("replacement operation not found")
    if operation.status == "completed":
        return operation
    active_run_count = int(
        await db.scalar(
            select(func.count()).select_from(RunAttempt).where(
                RunAttempt.org_id == org_id,
                RunAttempt.service_campaign_id == operation.service_campaign_id,
                RunAttempt.lane_id == operation.lane_id,
                RunAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
            )
        )
        or 0
    )
    if active_run_count:
        raise LifecycleInvariantError("replacement cannot complete while the old lane run is active")
    old_reservation = (
        await db.execute(
            select(DeviceReservation).where(
                DeviceReservation.id == operation.old_reservation_id,
                DeviceReservation.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    new_reservation = (
        await db.execute(
            select(DeviceReservation).where(
                DeviceReservation.id == operation.new_reservation_id,
                DeviceReservation.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    current = (
        await db.execute(
            select(LaneDeviceAssignment).where(
                LaneDeviceAssignment.org_id == org_id,
                LaneDeviceAssignment.service_campaign_id == operation.service_campaign_id,
                LaneDeviceAssignment.lane_id == operation.lane_id,
                LaneDeviceAssignment.ended_at.is_(None),
            )
        )
    ).scalar_one()
    if old_reservation is None or new_reservation is None:
        raise LifecycleInvariantError("replacement reservations are missing")
    old_reservation.state = "released"
    old_reservation.released_at = now
    current.ended_at = now
    # Release the partial-unique active lane before activating its replacement.
    await db.flush()
    new_reservation.state = "active"
    db.add(
        LaneDeviceAssignment(
            org_id=org_id,
            service_campaign_id=operation.service_campaign_id,
            lane_id=operation.lane_id,
            reservation_id=new_reservation.id,
            device_id=new_reservation.device_id,
            started_at=now,
            assigned_by=operation.actor_id,
            reason=operation.reason,
        )
    )
    operation.status = "completed"
    operation.checkpoint = "assignment_switched"
    await db.flush()
    return operation


async def complete_campaign_cancellation(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    operation_id: str,
    now: datetime,
) -> FleetLifecycleOperation:
    operation = (
        await db.execute(
            select(FleetLifecycleOperation)
            .where(
                FleetLifecycleOperation.id == operation_id,
                FleetLifecycleOperation.org_id == org_id,
                FleetLifecycleOperation.service_campaign_id == service_campaign_id,
                FleetLifecycleOperation.operation_type.in_(("cancel", "expire")),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if operation is None:
        raise LifecycleInvariantError("campaign stop operation not found")
    if operation.status == "completed":
        return operation
    active_run_count = int(
        await db.scalar(
            select(func.count()).select_from(RunAttempt).where(
                RunAttempt.org_id == org_id,
                RunAttempt.service_campaign_id == operation.service_campaign_id,
                RunAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
            )
        )
        or 0
    )
    if active_run_count:
        raise LifecycleInvariantError("cancellation cannot complete while campaign runs are active")
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(
                ServiceCampaign.id == operation.service_campaign_id,
                ServiceCampaign.org_id == org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise LifecycleInvariantError("service campaign not found")
    capabilities = list(
        (
            await db.execute(
                select(JobSecretCapability).where(
                    JobSecretCapability.org_id == org_id,
                    JobSecretCapability.service_campaign_id == operation.service_campaign_id,
                    JobSecretCapability.revoked_at.is_(None),
                )
            )
        ).scalars()
    )
    for capability in capabilities:
        capability.revoked_at = now
    reservations = list(
        (
            await db.execute(
                select(DeviceReservation).where(
                    DeviceReservation.org_id == org_id,
                    DeviceReservation.service_campaign_id == operation.service_campaign_id,
                    DeviceReservation.state.in_(("active", "draining", "pending")),
                )
            )
        ).scalars()
    )
    for reservation in reservations:
        reservation.state = "released"
        reservation.released_at = now
        reservation.release_reason = operation.reason
    assignments = list(
        (
            await db.execute(
                select(LaneDeviceAssignment).where(
                    LaneDeviceAssignment.org_id == org_id,
                    LaneDeviceAssignment.service_campaign_id == operation.service_campaign_id,
                    LaneDeviceAssignment.ended_at.is_(None),
                )
            )
        ).scalars()
    )
    for assignment in assignments:
        assignment.ended_at = now
    campaign.status = "expired" if operation.operation_type == "expire" else "cancelled"
    operation.status = "completed"
    operation.checkpoint = "resources_released"
    await db.flush()
    return operation


async def cancel_service_campaign(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    idempotency_key: str,
    actor_id: str,
    reason: str,
    now: datetime,
) -> FleetLifecycleOperation:
    return await _begin_campaign_stop(
        db,
        org_id=org_id,
        service_campaign_id=service_campaign_id,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        reason=reason,
        now=now,
        operation_type="cancel",
    )


async def expire_service_campaign(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    idempotency_key: str,
    actor_id: str,
    reason: str,
    now: datetime,
) -> FleetLifecycleOperation:
    return await _begin_campaign_stop(
        db,
        org_id=org_id,
        service_campaign_id=service_campaign_id,
        idempotency_key=idempotency_key,
        actor_id=actor_id,
        reason=reason,
        now=now,
        operation_type="expire",
    )


async def _begin_campaign_stop(
    db: AsyncSession,
    *,
    org_id: str,
    service_campaign_id: str,
    idempotency_key: str,
    actor_id: str,
    reason: str,
    now: datetime,
    operation_type: str,
) -> FleetLifecycleOperation:
    if operation_type not in {"cancel", "expire"}:
        raise LifecycleInvariantError("unsupported campaign stop operation")
    existing = (
        await db.execute(
            select(FleetLifecycleOperation).where(
                FleetLifecycleOperation.org_id == org_id,
                FleetLifecycleOperation.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.operation_type != operation_type
            or existing.service_campaign_id != service_campaign_id
            or existing.actor_id != actor_id
            or existing.reason != reason
        ):
            label = "expiry" if operation_type == "expire" else "cancellation"
            raise LifecycleInvariantError(f"{label} idempotency key was reused with different input")
        return existing
    campaign = (
        await db.execute(
            select(ServiceCampaign)
            .where(ServiceCampaign.id == service_campaign_id, ServiceCampaign.org_id == org_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise LifecycleInvariantError("service campaign not found")
    if operation_type == "expire" and (campaign.end_at is None or now < campaign.end_at):
        raise LifecycleInvariantError("campaign cannot expire before its service end")
    active_run_count = int(
        await db.scalar(
            select(func.count()).select_from(RunAttempt).where(
                RunAttempt.org_id == org_id,
                RunAttempt.service_campaign_id == service_campaign_id,
                RunAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
            )
        )
        or 0
    )
    campaign.status = "expiring" if operation_type == "expire" else "cancelling"
    future_slots = list(
        (
            await db.execute(
                select(RunSlot).where(
                    RunSlot.org_id == org_id,
                    RunSlot.service_campaign_id == service_campaign_id,
                    RunSlot.execution_status.in_(("scheduled", "planned", "due")),
                )
            )
        ).scalars()
    )
    for slot in future_slots:
        slot.execution_status = "cancelled"
    operation = FleetLifecycleOperation(
        org_id=org_id,
        service_campaign_id=service_campaign_id,
        operation_type=operation_type,
        idempotency_key=idempotency_key,
        status="waiting" if active_run_count else "running",
        checkpoint="awaiting_run_drain" if active_run_count else "future_dispatch_stopped",
        payload={"requested_at": now.isoformat()},
        actor_id=actor_id,
        reason=reason,
    )
    db.add(operation)
    await db.flush()
    if active_run_count == 0:
        await complete_campaign_cancellation(
            db,
            org_id=org_id,
            service_campaign_id=service_campaign_id,
            operation_id=operation.id,
            now=now,
        )
    else:
        await db.flush()
    return operation
