"""CRUD for execution_events outbox/archive (DF-T-04-013)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.execution_event import ExecutionEvent
from db.models.utils import _uuid


@dataclass(frozen=True)
class UnpublishedEventStats:
    count: int
    oldest_age_seconds: float


@dataclass(frozen=True)
class ClaimedEventBatch:
    token: str
    rows: tuple[ExecutionEvent, ...]


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
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def claim_unpublished_events(
    db: AsyncSession,
    *,
    limit: int = 100,
    lease_seconds: float = 30.0,
    now: datetime | None = None,
) -> ClaimedEventBatch:
    """Lease a batch transactionally; caller must commit before publishing."""
    if now is None:
        clock_result = await db.execute(select(func.now()))
        claimed_at = clock_result.scalar_one()
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
    else:
        claimed_at = now
    lease_cutoff = claimed_at - timedelta(seconds=max(1.0, lease_seconds))
    token = _uuid()
    result = await db.execute(
        select(ExecutionEvent)
        .where(
            ExecutionEvent.published_at.is_(None),
            or_(
                ExecutionEvent.publish_claimed_at.is_(None),
                ExecutionEvent.publish_claimed_at <= lease_cutoff,
            ),
        )
        .order_by(ExecutionEvent.id.asc())
        .limit(min(max(limit, 1), 500))
        .with_for_update(skip_locked=True)
    )
    rows = tuple(result.scalars().all())
    if not rows:
        return ClaimedEventBatch(token=token, rows=())

    row_ids = [row.id for row in rows]
    await db.execute(
        update(ExecutionEvent)
        .where(
            ExecutionEvent.id.in_(row_ids),
            ExecutionEvent.published_at.is_(None),
        )
        .values(
            publish_claim_token=token,
            publish_claimed_at=claimed_at,
        )
    )
    await db.flush()
    return ClaimedEventBatch(token=token, rows=rows)


async def get_unpublished_event_stats(db: AsyncSession) -> UnpublishedEventStats:
    result = await db.execute(
        select(
            func.count(ExecutionEvent.id),
            func.min(ExecutionEvent.occurred_at),
        ).where(ExecutionEvent.published_at.is_(None))
    )
    count, oldest = result.one()
    if oldest is None:
        return UnpublishedEventStats(count=0, oldest_age_seconds=0.0)
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - oldest).total_seconds())
    return UnpublishedEventStats(count=int(count or 0), oldest_age_seconds=age)


async def mark_event_published(
    db: AsyncSession,
    event_row_id: int,
) -> None:
    await db.execute(
        update(ExecutionEvent)
        .where(ExecutionEvent.id == event_row_id)
        .values(published_at=datetime.now(timezone.utc))
    )


async def mark_claimed_events_published(
    db: AsyncSession,
    event_row_ids: list[int],
    *,
    claim_token: str,
) -> int:
    if not event_row_ids:
        return 0
    result = await db.execute(
        update(ExecutionEvent)
        .where(
            ExecutionEvent.id.in_(event_row_ids),
            ExecutionEvent.published_at.is_(None),
            ExecutionEvent.publish_claim_token == claim_token,
        )
        .values(
            published_at=datetime.now(timezone.utc),
            publish_claim_token=None,
            publish_claimed_at=None,
        )
    )
    return int(result.rowcount or 0)


async def release_event_claims(
    db: AsyncSession,
    event_row_ids: list[int],
    *,
    claim_token: str,
) -> int:
    if not event_row_ids:
        return 0
    result = await db.execute(
        update(ExecutionEvent)
        .where(
            ExecutionEvent.id.in_(event_row_ids),
            ExecutionEvent.published_at.is_(None),
            ExecutionEvent.publish_claim_token == claim_token,
        )
        .values(
            publish_claim_token=None,
            publish_claimed_at=None,
            publish_attempts=ExecutionEvent.publish_attempts + 1,
        )
    )
    return int(result.rowcount or 0)


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
