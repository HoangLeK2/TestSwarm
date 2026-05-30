"""CRUD for per-tenant settings (DF-T-02-005)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.tenant_settings import DEFAULT_DEAD_THRESHOLD_SEC, TenantSettings


async def get_tenant_settings(
    db: AsyncSession, org_id: str
) -> Optional[TenantSettings]:
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_dead_threshold_sec(db: AsyncSession, org_id: str) -> int:
    row = await get_tenant_settings(db, org_id)
    if row is None:
        return DEFAULT_DEAD_THRESHOLD_SEC
    return max(1, int(row.dead_threshold_sec))


async def get_dead_thresholds_map(
    db: AsyncSession, org_ids: list[str]
) -> dict[str, int]:
    if not org_ids:
        return {}
    result = await db.execute(
        select(TenantSettings).where(TenantSettings.org_id.in_(org_ids))
    )
    found = {row.org_id: max(1, int(row.dead_threshold_sec)) for row in result.scalars()}
    return {
        org_id: found.get(org_id, DEFAULT_DEAD_THRESHOLD_SEC) for org_id in org_ids
    }


async def upsert_dead_threshold_sec(
    db: AsyncSession, org_id: str, dead_threshold_sec: int
) -> TenantSettings:
    row = await get_tenant_settings(db, org_id)
    value = max(1, int(dead_threshold_sec))
    if row is None:
        row = TenantSettings(org_id=org_id, dead_threshold_sec=value)
        db.add(row)
    else:
        row.dead_threshold_sec = value
    await db.flush()
    return row
