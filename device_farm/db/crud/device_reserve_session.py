"""CRUD for control-plane device reserve sessions (DF-T-02-003)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device import Device
from db.models.device_reserve_session import DeviceReserveSession
from db.models.utils import _now


async def get_active_session(
    db: AsyncSession, device_id: str, *, for_update: bool = False
) -> Optional[DeviceReserveSession]:
    stmt = (
        select(DeviceReserveSession)
        .where(
            DeviceReserveSession.device_id == device_id,
            DeviceReserveSession.released_at.is_(None),
        )
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_session_by_id(
    db: AsyncSession, session_id: str, *, for_update: bool = False
) -> Optional[DeviceReserveSession]:
    stmt = select(DeviceReserveSession).where(DeviceReserveSession.id == session_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def lock_device_row(db: AsyncSession, device_id: str) -> Optional[Device]:
    result = await db.execute(
        select(Device).where(Device.id == device_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def create_reserve_session(
    db: AsyncSession,
    *,
    device_id: str,
    org_id: str,
    owner_type: str,
    owner_id: str,
    ttl_sec: int,
    ctx: dict | None,
    created_by_user_id: str | None,
    now: datetime | None = None,
) -> DeviceReserveSession:
    ts = now or _now()
    row = DeviceReserveSession(
        device_id=device_id,
        org_id=org_id,
        owner_type=owner_type,
        owner_id=owner_id,
        claimed_at=ts,
        last_heartbeat=ts,
        ttl_sec=ttl_sec,
        ctx=ctx,
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    await db.flush()
    return row


async def mark_session_released(
    db: AsyncSession,
    session: DeviceReserveSession,
    *,
    reason: str,
    released_at: datetime | None = None,
) -> None:
    session.released_at = released_at or _now()
    session.release_reason = reason
    await db.flush()


async def touch_session_heartbeat(
    db: AsyncSession, session: DeviceReserveSession, *, at: datetime | None = None
) -> None:
    session.last_heartbeat = at or _now()
    await db.flush()


async def list_expired_active_sessions(
    db: AsyncSession,
    *,
    limit: int = 200,
    now: datetime | None = None,
) -> list[DeviceReserveSession]:
    """Return active sessions that may be expired (caller applies thresholds).

    Intentionally does not take row locks: release_device_session locks
    device then session (same order as claim). Holding session locks here
    caused deadlocks with concurrent manual release/claim paths.
    HA idempotency is handled inside release_device_session.
    """
    _ = now  # reserved for future SQL-side filtering
    stmt = (
        select(DeviceReserveSession)
        .where(DeviceReserveSession.released_at.is_(None))
        .order_by(DeviceReserveSession.last_heartbeat.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
