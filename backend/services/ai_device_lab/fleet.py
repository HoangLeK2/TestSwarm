"""Atomic service reservations and fail-closed physical hygiene state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ai_device_lab import ServiceCampaign, ServiceLane
from db.models.ai_device_lab_fleet import (
    DeviceHygieneAudit,
    DeviceHygieneState,
    DeviceReservation,
    ReservationAudit,
)
from db.models.ai_device_lab_lifecycle import LaneDeviceAssignment
from db.models.device import Device


class FleetInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReserveCohort:
    org_id: str
    service_campaign_id: str
    device_ids: tuple[str, ...]
    starts_at: datetime
    ends_at: datetime
    created_by: str


async def record_hygiene_result(
    db: AsyncSession,
    *,
    device_id: str,
    actor_id: str,
    protocol_version: str,
    reset_succeeded: bool,
    readback_clean: bool,
    evidence_ref: str | None,
    active_run: bool,
    service_campaign_id: str | None = None,
    target_type: str = "physical",
) -> DeviceHygieneState:
    if target_type not in {"physical", "emulator"}:
        raise FleetInvariantError("unsupported device target type")
    # The hygiene row does not exist for a device's first observation, so a
    # SELECT FOR UPDATE on that table alone cannot serialize concurrent
    # initializers. Lock the canonical device row first; subsequent state and
    # audit writes for one device are then ordered while different devices can
    # still proceed independently.
    device_exists = await db.scalar(
        select(Device.id).where(Device.id == device_id).with_for_update()
    )
    if device_exists is None:
        raise FleetInvariantError("device does not exist")
    state = (
        await db.execute(
            select(DeviceHygieneState)
            .where(DeviceHygieneState.device_id == device_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if state is None:
        state = DeviceHygieneState(
            device_id=device_id,
            state="dirty",
            protocol_version=protocol_version,
        )
        db.add(state)
        await db.flush()
    previous = state.state
    if active_run:
        next_state, reason = "draining", "ACTIVE_RUN_DRAIN_REQUIRED"
    elif not reset_succeeded:
        next_state, reason = "quarantined", "RESET_FAILED"
    elif not readback_clean or not evidence_ref:
        next_state, reason = "quarantined", "CLEAN_READBACK_NOT_PROVEN"
    else:
        next_state, reason = "verified_clean", "CLEAN_READBACK_VERIFIED"
    state.state = next_state
    state.protocol_version = protocol_version
    state.last_service_campaign_id = service_campaign_id
    state.verification_evidence_ref = evidence_ref if next_state == "verified_clean" else None
    state.completed_at = datetime.now(timezone.utc) if next_state == "verified_clean" else None
    state.verified_by = actor_id if next_state == "verified_clean" else None
    state.reason_code = reason
    db.add(
        DeviceHygieneAudit(
            device_id=device_id,
            actor_id=actor_id,
            from_state=previous,
            to_state=next_state,
            protocol_version=protocol_version,
            evidence_ref=evidence_ref,
            reason_code=reason,
            details={
                "target_type": target_type,
                "reset_succeeded": reset_succeeded,
                "readback_clean": readback_clean,
            },
        )
    )
    await db.flush()
    return state


async def reserve_cohort(
    db: AsyncSession,
    command: ReserveCohort,
) -> tuple[DeviceReservation, ...]:
    if command.starts_at >= command.ends_at:
        raise FleetInvariantError("reservation interval must be non-empty")
    campaign = (
        await db.execute(
            select(ServiceCampaign).where(
                ServiceCampaign.id == command.service_campaign_id,
                ServiceCampaign.org_id == command.org_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise FleetInvariantError("campaign is outside reservation scope")
    lanes = list(
        (
            await db.execute(
                select(ServiceLane)
                .where(
                    ServiceLane.org_id == command.org_id,
                    ServiceLane.service_campaign_id == command.service_campaign_id,
                )
                .order_by(ServiceLane.ordinal)
            )
        )
        .scalars()
        .all()
    )
    device_ids = tuple(sorted(set(command.device_ids)))
    if len(lanes) != 12 or len(device_ids) != 12:
        raise FleetInvariantError("exactly 12 lanes and 12 distinct devices are required")

    devices = list(
        (
            await db.execute(
                select(Device)
                .where(Device.id.in_(device_ids))
                .order_by(Device.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(devices) != 12:
        raise FleetInvariantError("one or more devices do not exist")
    hygiene = {
        item.device_id: item
        for item in (
            await db.execute(
                select(DeviceHygieneState).where(DeviceHygieneState.device_id.in_(device_ids))
            )
        )
        .scalars()
        .all()
    }
    if any(hygiene.get(device_id) is None or hygiene[device_id].state != "verified_clean" for device_id in device_ids):
        raise FleetInvariantError("all devices must have verified-clean hygiene evidence")
    overlaps = list(
        (
            await db.execute(
                select(DeviceReservation.id).where(
                    DeviceReservation.device_id.in_(device_ids),
                    DeviceReservation.state.in_(("active", "draining")),
                    DeviceReservation.starts_at < command.ends_at,
                    DeviceReservation.ends_at > command.starts_at,
                )
            )
        ).scalars()
    )
    if overlaps:
        raise FleetInvariantError("reservation interval overlaps an active allocation")

    reservations = tuple(
        DeviceReservation(
            org_id=command.org_id,
            service_campaign_id=command.service_campaign_id,
            lane_id=lane.id,
            device_id=device.id,
            starts_at=command.starts_at,
            ends_at=command.ends_at,
            state="active",
            created_by=command.created_by,
        )
        for lane, device in zip(lanes, devices, strict=True)
    )
    db.add_all(reservations)
    await db.flush()
    db.add_all(
        [
            LaneDeviceAssignment(
                org_id=command.org_id,
                service_campaign_id=command.service_campaign_id,
                lane_id=reservation.lane_id,
                reservation_id=reservation.id,
                device_id=reservation.device_id,
                started_at=command.starts_at,
                assigned_by=command.created_by,
                reason="initial_cohort_reservation",
            )
            for reservation in reservations
        ]
    )
    await db.flush()
    return reservations


async def release_reservation(
    db: AsyncSession,
    *,
    org_id: str,
    reservation_id: str,
    actor_id: str,
    reason: str,
    active_run: bool,
) -> DeviceReservation:
    reservation = (
        await db.execute(
            select(DeviceReservation)
            .where(
                DeviceReservation.id == reservation_id,
                DeviceReservation.org_id == org_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if reservation is None:
        raise FleetInvariantError("reservation not found")
    if reservation.state == "released":
        return reservation
    reservation.state = "draining" if active_run else "released"
    reservation.release_reason = reason
    reservation.released_at = None if active_run else datetime.now(timezone.utc)
    db.add(
        ReservationAudit(
            org_id=org_id,
            reservation_id=reservation.id,
            actor_id=actor_id,
            action="release",
            reason=reason,
            outcome=reservation.state,
        )
    )
    await db.flush()
    return reservation
