"""CRUD for execution_events outbox/archive (DF-T-04-013)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.execution_event import ExecutionEvent
from db.models.utils import _uuid


async def insert_execution_event(
    db: AsyncSession,
    *,
    event_type: str,
    organization_id: str,
    execution_id: str,
    payload: Optional[dict[str, Any]] = None,
    campaign_id: Optional[str] = None,
    step_id: Optional[str] = None,
    schema_version: str = "1",
    occurred_at: Optional[datetime] = None,
    event_id: Optional[str] = None,
) -> ExecutionEvent:
    now = occurred_at or datetime.now(timezone.utc)
    row = ExecutionEvent(
        event_id=event_id or _uuid(),
        event_type=event_type,
        schema_version=schema_version,
        org_id=organization_id,
        campaign_id=campaign_id,
        execution_id=execution_id,
        step_id=step_id,
        payload=payload or {},
        occurred_at=now,
        published_at=None,
        publish_attempts=0,
    )
    db.add(row)
    await db.flush()
    return row


async def list_execution_events(
    db: AsyncSession,
    execution_id: str,
    *,
    since_event_id: Optional[str] = None,
    limit: int = 100,
) -> list[ExecutionEvent]:
    since_row_id: Optional[int] = None
    if since_event_id:
        anchor = await db.execute(
            select(ExecutionEvent.id).where(
                ExecutionEvent.execution_id == execution_id,
                ExecutionEvent.event_id == since_event_id,
            )
        )
        since_row_id = anchor.scalar_one_or_none()

    q = (
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id)
        .order_by(ExecutionEvent.id.asc())
    )
    if since_row_id is not None:
        q = q.where(ExecutionEvent.id > since_row_id)
    result = await db.execute(q.limit(min(max(limit, 1), 500)))
    return list(result.scalars().all())


async def fetch_unpublished_events(
    db: AsyncSession,
    *,
    limit: int = 100,
) -> list[ExecutionEvent]:
    result = await db.execute(
        select(ExecutionEvent)
        .where(ExecutionEvent.published_at.is_(None))
        .order_by(ExecutionEvent.id.asc())
        .limit(min(max(limit, 1), 500))
    )
    return list(result.scalars().all())


async def mark_event_published(
    db: AsyncSession,
    event_row_id: int,
) -> None:
    await db.execute(
        update(ExecutionEvent)
        .where(ExecutionEvent.id == event_row_id)
        .values(published_at=datetime.now(timezone.utc))
    )


async def increment_publish_attempt(
    db: AsyncSession,
    event_row_id: int,
) -> None:
    await db.execute(
        update(ExecutionEvent)
        .where(ExecutionEvent.id == event_row_id)
        .values(publish_attempts=ExecutionEvent.publish_attempts + 1)
    )


async def purge_events_older_than(
    db: AsyncSession,
    *,
    cutoff: datetime,
) -> int:
    from sqlalchemy import delete

    result = await db.execute(
        delete(ExecutionEvent).where(
            ExecutionEvent.created_at < cutoff,
            ExecutionEvent.published_at.is_not(None),
        )
    )
    return int(result.rowcount or 0)
