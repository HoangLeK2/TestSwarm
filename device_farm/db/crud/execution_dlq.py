"""db/crud/execution_dlq.py — CRUD helpers for ExecutionDLQ."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.execution_dlq import ExecutionDLQ
from db.models.execution import Execution
from db.models.utils import _uuid


async def create_dlq_entry(
    db: AsyncSession,
    *,
    execution_id: str,
    device_serial: str,
    error: Optional[str] = None,
) -> ExecutionDLQ:
    """Create a new DLQ entry for a failed execution."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        payload = {
            "id": _uuid(),
            "execution_id": execution_id,
            "device_serial": device_serial,
            "error": error,
            "status": "pending",
            "retry_count": 0,
        }
        stmt = (
            pg_insert(ExecutionDLQ)
            .values(**payload)
            .on_conflict_do_update(
                index_elements=[ExecutionDLQ.execution_id, ExecutionDLQ.device_serial],
                # Keep this predicate literal so Postgres can match the partial unique index.
                index_where=text("status IN ('pending','retrying')"),
                set_={"error": error if error is not None else ExecutionDLQ.error},
            )
            .returning(ExecutionDLQ.id)
        )
        inserted = await db.execute(stmt)
        row = inserted.first()
        if row:
            result = await db.execute(select(ExecutionDLQ).where(ExecutionDLQ.id == row[0]))
            entry = result.scalar_one_or_none()
            if entry is not None:
                return entry

    existing_q = await db.execute(
        select(ExecutionDLQ).where(
            ExecutionDLQ.execution_id == execution_id,
            ExecutionDLQ.device_serial == device_serial,
            ExecutionDLQ.status.in_(("pending", "retrying")),
        )
    )
    existing = existing_q.scalar_one_or_none()
    if existing is not None:
        if error:
            existing.error = error
            await db.flush()
        return existing

    entry = ExecutionDLQ(
        execution_id=execution_id,
        device_serial=device_serial,
        error=error,
        status="pending",
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_dlq_entry(db: AsyncSession, dlq_id: str) -> Optional[ExecutionDLQ]:
    result = await db.execute(
        select(ExecutionDLQ).where(ExecutionDLQ.id == dlq_id)
    )
    return result.scalar_one_or_none()


async def list_dlq_entries(
    db: AsyncSession,
    *,
    status: Optional[str] = None,
    execution_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> list[ExecutionDLQ]:
    q = select(ExecutionDLQ).order_by(ExecutionDLQ.created_at.desc())
    if status is not None:
        q = q.where(ExecutionDLQ.status == status)
    if execution_id is not None:
        q = q.where(ExecutionDLQ.execution_id == execution_id)
    result = await db.execute(q.offset(offset).limit(limit))
    return list(result.scalars().all())


async def list_dlq_entries_for_user(
    db: AsyncSession,
    *,
    user_id: str,
    status: Optional[str] = None,
    execution_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> list[ExecutionDLQ]:
    q = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .where(Execution.user_id == user_id)
        .order_by(ExecutionDLQ.created_at.desc())
    )
    if status is not None:
        q = q.where(ExecutionDLQ.status == status)
    if execution_id is not None:
        q = q.where(ExecutionDLQ.execution_id == execution_id)
    result = await db.execute(q.offset(offset).limit(limit))
    return list(result.scalars().all())


async def mark_dlq_retrying(db: AsyncSession, dlq_id: str) -> Optional[ExecutionDLQ]:
    """Mark entry as retrying and increment retry_count."""
    entry = await get_dlq_entry(db, dlq_id)
    if entry is None:
        return None
    entry.status = "retrying"
    entry.retry_count += 1
    entry.last_attempt_at = datetime.now(timezone.utc)
    await db.flush()
    return entry


async def begin_dlq_retry(db: AsyncSession, dlq_id: str) -> tuple[Optional[ExecutionDLQ], bool]:
    """
    Idempotent retry state transition helper.

    Returns (entry, changed):
      - changed=True when pending -> retrying transition is applied
      - changed=False when already retrying/resolved/dismissed
    """
    entry = await get_dlq_entry(db, dlq_id)
    if entry is None:
        return None, False
    if entry.status != "pending":
        return entry, False
    entry.status = "retrying"
    entry.retry_count += 1
    entry.last_attempt_at = datetime.now(timezone.utc)
    await db.flush()
    return entry, True


async def begin_dlq_retry_for_user(
    db: AsyncSession,
    dlq_id: str,
    user_id: str,
) -> tuple[Optional[ExecutionDLQ], bool]:
    """
    User-scoped idempotent retry transition.

    Returns (entry, changed) and guarantees the row belongs to user_id.
    """
    now = datetime.now(timezone.utc)
    transition_stmt = (
        update(ExecutionDLQ)
        .where(
            ExecutionDLQ.id == dlq_id,
            ExecutionDLQ.execution_id.in_(
                select(Execution.id).where(Execution.user_id == user_id)
            ),
            ExecutionDLQ.status == "pending",
        )
        .values(
            status="retrying",
            retry_count=ExecutionDLQ.retry_count + 1,
            last_attempt_at=now,
        )
        .returning(ExecutionDLQ.id)
    )
    transition = await db.execute(transition_stmt)
    changed = transition.first() is not None

    stmt = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .where(ExecutionDLQ.id == dlq_id, Execution.user_id == user_id)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return None, False
    return entry, changed


async def set_dlq_status(
    db: AsyncSession,
    dlq_id: str,
    status: str,
    *,
    error: Optional[str] = None,
) -> Optional[ExecutionDLQ]:
    """Set final DLQ status after retry scheduling attempt."""
    entry = await get_dlq_entry(db, dlq_id)
    if entry is None:
        return None
    entry.status = status
    if error:
        entry.error = error
    await db.flush()
    return entry


async def mark_dlq_resolved(db: AsyncSession, dlq_id: str) -> Optional[ExecutionDLQ]:
    entry = await get_dlq_entry(db, dlq_id)
    if entry is None:
        return None
    entry.status = "resolved"
    await db.flush()
    return entry


async def dismiss_dlq_entry(db: AsyncSession, dlq_id: str) -> bool:
    """Dismiss (soft-delete) a DLQ entry — marks as 'dismissed'."""
    entry = await get_dlq_entry(db, dlq_id)
    if entry is None:
        return False
    entry.status = "dismissed"
    await db.flush()
    return True


async def dismiss_dlq_entry_for_user(db: AsyncSession, dlq_id: str, user_id: str) -> bool:
    stmt = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .where(ExecutionDLQ.id == dlq_id, Execution.user_id == user_id)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    entry.status = "dismissed"
    await db.flush()
    return True


__all__ = [
    "create_dlq_entry",
    "get_dlq_entry",
    "list_dlq_entries",
    "list_dlq_entries_for_user",
    "mark_dlq_retrying",
    "begin_dlq_retry",
    "begin_dlq_retry_for_user",
    "set_dlq_status",
    "mark_dlq_resolved",
    "dismiss_dlq_entry",
    "dismiss_dlq_entry_for_user",
]
