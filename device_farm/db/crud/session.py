from __future__ import annotations

from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DeviceSession
from db.models.utils import _now


async def open_session(db: AsyncSession, device_id: str, client_ip: str) -> DeviceSession:
    session = DeviceSession(device_id=device_id, client_ip=client_ip)
    db.add(session)
    await db.flush()
    return session


async def close_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(
        update(DeviceSession)
        .where(DeviceSession.id == session_id)
        .values(disconnected_at=_now())
    )


async def list_sessions(
    db: AsyncSession, device_id: str, limit: int = 20
) -> List[DeviceSession]:
    result = await db.execute(
        select(DeviceSession)
        .where(DeviceSession.device_id == device_id)
        .order_by(DeviceSession.connected_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())

