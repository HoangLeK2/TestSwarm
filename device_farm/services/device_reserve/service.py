"""Claim / release / heartbeat for device reserve sessions (DF-T-02-003)."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import device_reserve_session as reserve_repo
from db.crud.device_state import get_device_state
from db.crud.tenant_settings import get_session_idle_threshold_sec
from db.models.enums import DeviceFsmState, DeviceRegistryStatus, DeviceReserveOwnerType, DeviceReserveReleaseReason
from services.device_reserve.exceptions import (
    DeviceBusyError,
    DeviceInSessionError,
    DeviceSessionError,
    NotSessionOwnerError,
    ReserveSessionView,
    SessionNotFoundError,
    TtlOutOfRangeError,
)
from services.device_state.exceptions import DeviceNotAvailableError, IllegalDeviceTransitionError
from services.device_state.service import ApplyOutcome, DeviceStateService
from services.security_audit import emit_security_event

log = logging.getLogger(__name__)

DEFAULT_TTL_SEC = int(os.environ.get("DEVICE_RESERVE_DEFAULT_TTL_SEC", "1800"))
MAX_TTL_SEC = int(os.environ.get("DEVICE_RESERVE_MAX_TTL_SEC", "28800"))

_fsm = DeviceStateService()


def _validate_owner_type(owner_type: str) -> str:
    value = (owner_type or "").strip().lower()
    allowed = {t.value for t in DeviceReserveOwnerType}
    if value not in allowed:
        raise DeviceSessionError(
            f"invalid owner_type {owner_type!r}",
            code="INVALID_OWNER_TYPE",
        )
    return value


def _validate_ttl(ttl_sec: int | None) -> int:
    ttl = DEFAULT_TTL_SEC if ttl_sec is None else int(ttl_sec)
    if ttl < 60 or ttl > MAX_TTL_SEC:
        raise TtlOutOfRangeError(
            f"ttl_sec must be between 60 and {MAX_TTL_SEC}, got {ttl}"
        )
    return ttl


def _to_view(row) -> ReserveSessionView:
    return ReserveSessionView(
        session_id=row.id,
        device_id=row.device_id,
        owner_type=row.owner_type,
        owner_id=row.owner_id,
        claimed_at=row.claimed_at.isoformat(),
        last_heartbeat=row.last_heartbeat.isoformat(),
        ttl_sec=row.ttl_sec,
        ctx=row.ctx,
    )


async def get_active_session_view(
    db: AsyncSession, device_id: str
) -> Optional[ReserveSessionView]:
    row = await reserve_repo.get_active_session(db, device_id)
    return _to_view(row) if row else None


async def claim_device_session(
    db: AsyncSession,
    *,
    device_id: str,
    org_id: str,
    actor_user_id: str,
    owner_type: str,
    owner_id: str,
    ttl_sec: int | None = None,
    ctx: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ReserveSessionView:
    owner_type = _validate_owner_type(owner_type)
    ttl = _validate_ttl(ttl_sec)
    owner_id = (owner_id or actor_user_id or "").strip()
    if not owner_id:
        raise DeviceSessionError("owner_id is required", code="INVALID_OWNER_ID")

    device = await reserve_repo.lock_device_row(db, device_id)
    if not device or device.org_id != org_id:
        raise SessionNotFoundError("device not found")

    if getattr(device, "status", DeviceRegistryStatus.PAIRED.value) == DeviceRegistryStatus.UNPAIRED.value:
        raise DeviceNotAvailableError(
            f"device {device_id} is unpaired",
        )

    active = await reserve_repo.get_active_session(db, device_id, for_update=True)
    if active:
        raise DeviceBusyError(
            f"device {device_id} already has active session",
            current_session_id=active.id,
            owner_id=active.owner_id,
            owner_type=active.owner_type,
        )

    state_row = await get_device_state(db, device_id)
    current_state = (
        DeviceFsmState(state_row.state)
        if state_row
        else DeviceFsmState.UNKNOWN
    )
    if current_state != DeviceFsmState.ONLINE:
        raise DeviceNotAvailableError(
            f"device {device_id} not available for claim (state={current_state.value})"
        )

    session = await reserve_repo.create_reserve_session(
        db,
        device_id=device_id,
        org_id=org_id,
        owner_type=owner_type,
        owner_id=owner_id,
        ttl_sec=ttl,
        ctx=ctx,
        created_by_user_id=actor_user_id,
    )

    event_id = str(uuid.uuid4())
    try:
        result = await _fsm.claim(
            db,
            device_id,
            session.id,
            event_id=event_id,
            payload={
                "owner_type": owner_type,
                "owner_id": owner_id,
            },
        )
    except (DeviceNotAvailableError, IllegalDeviceTransitionError):
        raise

    if result.outcome not in {ApplyOutcome.APPLIED, ApplyOutcome.DEDUPED, ApplyOutcome.NO_OP}:
        raise DeviceNotAvailableError(
            f"claim FSM not applied for device {device_id} (outcome={result.outcome.value})"
        )

    await emit_security_event(
        db,
        action="session.claimed",
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "session_id": session.id,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "ttl_sec": ttl,
        },
    )
    return _to_view(session)


def _actor_owns_session(session, actor_user_id: str, is_admin: bool) -> bool:
    if is_admin:
        return True
    if session.created_by_user_id and session.created_by_user_id == actor_user_id:
        return True
    if session.owner_type == DeviceReserveOwnerType.MANUAL.value:
        return session.owner_id == actor_user_id
    return False


async def release_device_session(
    db: AsyncSession,
    *,
    device_id: str,
    session_id: str,
    org_id: str,
    actor_user_id: str,
    is_admin: bool = False,
    reason: str = DeviceReserveReleaseReason.MANUAL.value,
    ip_address: str | None = None,
    user_agent: str | None = None,
    audit_action: str = "session.released",
) -> None:
    device = await reserve_repo.lock_device_row(db, device_id)
    if not device or device.org_id != org_id:
        raise SessionNotFoundError("device not found")

    session = await reserve_repo.get_active_session(db, device_id, for_update=True)
    if session is None or session.id != session_id:
        stale = await reserve_repo.get_session_by_id(db, session_id)
        if stale and stale.released_at is not None and stale.device_id == device_id:
            return
        if session and session.id != session_id:
            raise NotSessionOwnerError("session id does not match active session")
        raise SessionNotFoundError("session not found")

    if not _actor_owns_session(session, actor_user_id, is_admin):
        raise NotSessionOwnerError("not session owner")

    await reserve_repo.mark_session_released(db, session, reason=reason)

    event_id = str(uuid.uuid4())
    try:
        await _fsm.release(
            db,
            device_id,
            session_id,
            event_id=event_id,
            payload={"release_reason": reason},
        )
    except IllegalDeviceTransitionError as exc:
        log.warning("release FSM skipped device=%s session=%s: %s", device_id, session_id, exc)

    await emit_security_event(
        db,
        action=audit_action,
        user_id=actor_user_id,
        org_id=org_id,
        entity_type="device",
        entity_id=device_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={
            "session_id": session_id,
            "release_reason": reason,
            "owner_type": session.owner_type,
            "owner_id": session.owner_id,
        },
    )


async def heartbeat_device_session(
    db: AsyncSession,
    *,
    session_id: str,
    org_id: str,
    actor_user_id: str,
    is_admin: bool = False,
) -> ReserveSessionView:
    session = await reserve_repo.get_session_by_id(db, session_id, for_update=True)
    if session is None or session.org_id != org_id or session.released_at is not None:
        raise SessionNotFoundError("session not found")
    if not _actor_owns_session(session, actor_user_id, is_admin):
        raise NotSessionOwnerError("not session owner")
    await reserve_repo.touch_session_heartbeat(db, session)
    return _to_view(session)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def session_is_expired(
    db: AsyncSession,
    session,
    *,
    now: datetime | None = None,
) -> tuple[bool, int]:
    ts = _as_utc(now or datetime.now(timezone.utc))
    idle_threshold = await get_session_idle_threshold_sec(db, session.org_id, session.owner_type)
    last_hb = _as_utc(session.last_heartbeat)
    claimed = _as_utc(session.claimed_at)
    idle_seconds = (ts - last_hb).total_seconds()
    ttl_elapsed = (ts - claimed).total_seconds()
    expired_idle = idle_seconds > idle_threshold
    expired_ttl = ttl_elapsed > session.ttl_sec
    return expired_idle or expired_ttl, int(idle_seconds)


async def auto_release_expired_sessions(
    db: AsyncSession,
    *,
    limit: int = 200,
    now: datetime | None = None,
) -> int:
    """Release timed-out sessions; returns count released."""
    ts = now or datetime.now(timezone.utc)
    candidates = await reserve_repo.list_expired_active_sessions(db, limit=limit, now=ts)
    released = 0
    for session in candidates:
        expired, idle_seconds = await session_is_expired(db, session, now=ts)
        if not expired:
            continue
        try:
            await release_device_session(
                db,
                device_id=session.device_id,
                session_id=session.id,
                org_id=session.org_id,
                actor_user_id=session.created_by_user_id or session.owner_id,
                is_admin=True,
                reason=DeviceReserveReleaseReason.TIMEOUT.value,
                audit_action="session.auto_released",
            )
            released += 1
        except Exception:
            log.warning(
                "auto_release failed session=%s device=%s",
                session.id,
                session.device_id,
                exc_info=True,
            )
    return released
