"""CRUD helpers for device FSM tables (DF-T-02-002)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.device_fsm import DeviceFsmSnapshot
from db.models.enums import DeviceFsmState
from db.models.utils import _now


async def get_device_state(
    db: AsyncSession, device_id: str
) -> Optional[DeviceFsmSnapshot]:
    result = await db.execute(
        select(DeviceFsmSnapshot).where(DeviceFsmSnapshot.device_id == device_id)
    )
    return result.scalar_one_or_none()


async def get_device_states_map(
    db: AsyncSession, device_ids: list[str]
) -> dict[str, DeviceFsmSnapshot]:
    if not device_ids:
        return {}
    result = await db.execute(
        select(DeviceFsmSnapshot).where(DeviceFsmSnapshot.device_id.in_(device_ids))
    )
    return {row.device_id: row for row in result.scalars().all()}


async def ensure_device_state(
    db: AsyncSession, device_id: str
) -> DeviceFsmSnapshot:
    row = await get_device_state(db, device_id)
    if row is not None:
        return row
    row = DeviceFsmSnapshot(
        device_id=device_id,
        state=DeviceFsmState.UNKNOWN.value,
        updated_at=_now(),
    )
    db.add(row)
    await db.flush()
    return row
