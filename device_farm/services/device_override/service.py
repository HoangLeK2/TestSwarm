"""Admin force-release and state reset (DF-T-02-011)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import device_reserve_session as reserve_repo
from db.crud.device_state import get_device_state
from db.models.enums import DeviceFsmEvent, DeviceFsmState, DeviceReserveReleaseReason
from services.device_reserve.service import release_device_session
from services.device_state.exceptions import DeviceStateError, IllegalDeviceTransitionError
from services.device_state.service import ApplyOutcome, DeviceStateService
from services.security_audit import emit_security_event

_fsm = DeviceStateService()


class AdminOverrideError(DeviceStateError):
    def __init__(self, message: str, *, code: str = "INVALID_STATE") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AdminOverrideResult:
    device_id: str
    from_state: str
    to_state: str
    old_owner_type: Optional[str]
    old_owner_id: Optional[str]
    session_id: Optional[str]
    reason: str
    actor: str


async def admin_force_release_device(
    db: AsyncSession,
    *,
    device_id: str,
    org_id: str,
    actor_user_id: str,
    reason: str,
    session_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AdminOverrideResult:
    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise AdminOverrideError("reason is required", code="REASON_REQUIRED")

    device = await reserve_repo.lock_device_row(db, device_id)
    if not device or device.org_id != org_id:
        raise AdminOverrideError("device not found", code="NOT_FOUND")

    state_row = await get_device_state(db, device_id)
    from_state = state_row.state if state_row else DeviceFsmState.UNKNOWN.value

    active = await reserve_repo.get_active_session(db, device_id, for_update=True)
    old_owner_type = active.owner_type if active else None
    old_owner_id = active.owner_id if active else None
    active_session_id = active.id if active else None

    if active is not None:
        target_session_id = session_id or active.id
        await release_device_session(
            db,
            device_id=device_id,
            session_id=target_session_id,
            org_id=org_id,
            actor_user_id=actor_user_id,
            is_admin=True,
            reason=DeviceReserveReleaseReason.FORCE.value,
            ip_address=ip_address,
            user_agent=user_agent,
            audit_action="session.force_released",
        )
    elif state_row and state_row.state == DeviceFsmState.BUSY.value:
        event_id = str(uuid.uuid4())
        result = await _fsm.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.ADMIN_FORCE_ONLINE.value,
            source="admin",
            event_id=event_id,
            payload={"reason": cleaned_reason, "actor": actor_user_id},
        )
        if result.outcome not in {ApplyOutcome.APPLIED, ApplyOutcome.NO_OP, ApplyOutcome.DEDUPED}:
            raise IllegalDeviceTransitionError(
                f"cannot force-release BUSY device {device_id} (outcome={result.outcome.value})"
            )
    else:
        return AdminOverrideResult(
            device_id=device_id,
            from_state=from_state,
            to_state=from_state,
            old_owner_type=old_owner_type,
            old_owner_id=old_owner_id,
            session_id=active_session_id,
            reason=cleaned_reason,
            actor=actor_user_id,
        )

    state_row = await get_device_state(db, device_id)
    to_state = state_row.state if state_row else DeviceFsmState.UNKNOWN.value

    await emit_security_event(
        db,
        action="device.force_released",
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "reason": cleaned_reason,
            "from_state": from_state,
            "to_state": to_state,
            "old_owner_type": old_owner_type,
            "old_owner_id": old_owner_id,
            "session_id": active_session_id,
        },
    )
    return AdminOverrideResult(
        device_id=device_id,
        from_state=from_state,
        to_state=to_state,
        old_owner_type=old_owner_type,
        old_owner_id=old_owner_id,
        session_id=active_session_id,
        reason=cleaned_reason,
        actor=actor_user_id,
    )


async def admin_reset_device_state(
    db: AsyncSession,
    *,
    device_id: str,
    org_id: str,
    actor_user_id: str,
    reason: str,
    target_state: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AdminOverrideResult:
    cleaned_reason = (reason or "").strip()
    if not cleaned_reason:
        raise AdminOverrideError("reason is required", code="REASON_REQUIRED")

    device = await reserve_repo.lock_device_row(db, device_id)
    if not device or device.org_id != org_id:
        raise AdminOverrideError("device not found", code="NOT_FOUND")

    state_row = await get_device_state(db, device_id)
    current = DeviceFsmState(state_row.state) if state_row else DeviceFsmState.UNKNOWN
    from_state = current.value

    active = await reserve_repo.get_active_session(db, device_id)
    old_owner_type = active.owner_type if active else None
    old_owner_id = active.owner_id if active else None
    active_session_id = active.id if active else None

    target = (target_state or "").strip().lower() or None
    event_id = str(uuid.uuid4())

    if current == DeviceFsmState.DEAD:
        result = await _fsm.revive(
            db,
            device_id,
            actor=actor_user_id,
            device_serial=device.serial,
        )
        to_state = result.to_state.value if result.to_state else DeviceFsmState.CONNECTING.value
    elif current == DeviceFsmState.RECONNECTING:
        if target == DeviceFsmState.ONLINE.value:
            event = DeviceFsmEvent.ADMIN_FORCE_ONLINE.value
        else:
            event = DeviceFsmEvent.ADMIN_RESET.value
        result = await _fsm.apply_event(
            db,
            device_id,
            event=event,
            source="admin",
            event_id=event_id,
            payload={"reason": cleaned_reason, "actor": actor_user_id},
        )
        if result.outcome not in {ApplyOutcome.APPLIED, ApplyOutcome.DEDUPED}:
            raise IllegalDeviceTransitionError(
                f"reset not applied for device {device_id} (state={current.value})"
            )
        to_state = result.to_state.value if result.to_state else current.value
    elif current == DeviceFsmState.BUSY:
        if active is not None:
            await release_device_session(
                db,
                device_id=device_id,
                session_id=active.id,
                org_id=org_id,
                actor_user_id=actor_user_id,
                is_admin=True,
                reason=DeviceReserveReleaseReason.FORCE.value,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_action="session.force_released",
            )
        result = await _fsm.apply_event(
            db,
            device_id,
            event=DeviceFsmEvent.ADMIN_FORCE_ONLINE.value,
            source="admin",
            event_id=f"{event_id}-online",
            payload={"reason": cleaned_reason, "actor": actor_user_id},
        )
        if result.outcome not in {ApplyOutcome.APPLIED, ApplyOutcome.NO_OP, ApplyOutcome.DEDUPED}:
            raise IllegalDeviceTransitionError(
                f"reset not applied for BUSY device {device_id}"
            )
        to_state = DeviceFsmState.ONLINE.value
    else:
        raise AdminOverrideError(
            f"state reset not allowed from {current.value}",
            code="INVALID_TRANSITION",
        )

    await emit_security_event(
        db,
        action="device.state_reset",
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "reason": cleaned_reason,
            "from_state": from_state,
            "to_state": to_state,
            "old_owner_type": old_owner_type,
            "old_owner_id": old_owner_id,
            "session_id": active_session_id,
        },
    )
    return AdminOverrideResult(
        device_id=device_id,
        from_state=from_state,
        to_state=to_state,
        old_owner_type=old_owner_type,
        old_owner_id=old_owner_id,
        session_id=active_session_id,
        reason=cleaned_reason,
        actor=actor_user_id,
    )
