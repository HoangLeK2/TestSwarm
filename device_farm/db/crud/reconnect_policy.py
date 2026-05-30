"""CRUD for reconnect_policies (DF-T-02-006)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.reconnect_policy import ReconnectPolicy

DEFAULT_INTERVAL_BASE_MS = 1000
DEFAULT_MAX_INTERVAL_MS = 60000
DEFAULT_MAX_ATTEMPTS = 20
DEFAULT_JITTER_FACTOR = 0.2


def default_policy(org_id: str) -> ReconnectPolicy:
    return ReconnectPolicy(
        org_id=org_id,
        interval_base_ms=DEFAULT_INTERVAL_BASE_MS,
        max_interval_ms=DEFAULT_MAX_INTERVAL_MS,
        max_attempts=DEFAULT_MAX_ATTEMPTS,
        jitter_factor=DEFAULT_JITTER_FACTOR,
        updated_at=datetime.now(timezone.utc),
        updated_by=None,
    )


async def get_reconnect_policy(
    db: AsyncSession,
    org_id: str,
) -> Optional[ReconnectPolicy]:
    result = await db.execute(
        select(ReconnectPolicy).where(ReconnectPolicy.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def upsert_reconnect_policy(
    db: AsyncSession,
    *,
    org_id: str,
    interval_base_ms: int,
    max_interval_ms: int,
    max_attempts: int,
    jitter_factor: float,
    updated_by: str,
) -> ReconnectPolicy:
    row = await get_reconnect_policy(db, org_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = ReconnectPolicy(org_id=org_id)
        db.add(row)
    row.interval_base_ms = interval_base_ms
    row.max_interval_ms = max_interval_ms
    row.max_attempts = max_attempts
    row.jitter_factor = jitter_factor
    row.updated_at = now
    row.updated_by = updated_by
    await db.flush()
    return row
