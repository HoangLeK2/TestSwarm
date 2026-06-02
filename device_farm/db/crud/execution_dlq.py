"""db/crud/execution_dlq.py — CRUD helpers for ExecutionDLQ."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Campaign
from db.models.execution_dlq import ExecutionDLQ
from db.models.execution import Execution
from db.models.utils import _uuid


def _execution_scope_where(
    org_id: str | None,
    user_id: str | None,
):
    if org_id:
        return Execution.id.in_(
            select(Execution.id)
            .join(Campaign, Execution.campaign_id == Campaign.id)
            .where(Campaign.org_id == org_id)
        )
    return Execution.user_id == user_id


async def create_dlq_entry(
    db: AsyncSession,
    *,
    execution_id: str,
    device_serial: str,
    error: Optional[str] = None,
    failed_step_id: Optional[str] = None,
    failure_reason: Optional[str] = None,
    failed_at: datetime | None = None,
    campaign_id: Optional[str] = None,
    artifact_refs: Optional[dict] = None,
) -> ExecutionDLQ:
    """Create a new DLQ entry for a failed execution."""
    if failed_at is None:
        failed_at = datetime.now(timezone.utc)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        payload = {
            "id": _uuid(),
            "execution_id": execution_id,
            "device_serial": device_serial,
            "error": error,
            "status": "pending",
            "retry_count": 0,
            "failed_step_id": failed_step_id,
            "failure_reason": failure_reason or error,
            "failed_at": failed_at,
            "campaign_id": campaign_id,
            "artifact_refs": artifact_refs or {},
        }
        stmt = (
            pg_insert(ExecutionDLQ)
            .values(**payload)
            .on_conflict_do_update(
                index_elements=[ExecutionDLQ.execution_id, ExecutionDLQ.device_serial],
                # Keep this predicate literal so Postgres can match the partial unique index.
                index_where=text("status IN ('pending','retrying')"),
                set_={
                    "error": error if error is not None else ExecutionDLQ.error,
                    "failure_reason": (
                        failure_reason
                        or error
                        or ExecutionDLQ.failure_reason
                    ),
                },
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
        failed_step_id=failed_step_id,
        failure_reason=failure_reason or error,
        failed_at=failed_at,
        campaign_id=campaign_id,
        artifact_refs=artifact_refs or {},
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
    user_id: str | None = None,
    org_id: str | None = None,
    status: Optional[str] = None,
    execution_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> list[ExecutionDLQ]:
    q = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .order_by(ExecutionDLQ.created_at.desc())
    )
    if org_id:
        q = q.join(Campaign, Execution.campaign_id == Campaign.id).where(
            Campaign.org_id == org_id
        )
    elif user_id:
        q = q.where(Execution.user_id == user_id)
    if status is not None:
        q = q.where(ExecutionDLQ.status == status)
    if execution_id is not None:
        q = q.where(ExecutionDLQ.execution_id == execution_id)
    if campaign_id is not None:
        q = q.where(Execution.campaign_id == campaign_id)
    result = await db.execute(q.offset(offset).limit(limit))
    return list(result.scalars().all())


async def count_dlq_entries_for_user(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    status: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> int:
    q = select(func.count(ExecutionDLQ.id)).join(
        Execution, Execution.id == ExecutionDLQ.execution_id
    )
    if org_id:
        q = q.join(Campaign, Execution.campaign_id == Campaign.id).where(
            Campaign.org_id == org_id
        )
    elif user_id:
        q = q.where(Execution.user_id == user_id)
    if status is not None:
        q = q.where(ExecutionDLQ.status == status)
    if campaign_id is not None:
        q = q.where(Execution.campaign_id == campaign_id)
    return int((await db.execute(q)).scalar() or 0)


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
    user_id: str | None = None,
    *,
    org_id: str | None = None,
) -> tuple[Optional[ExecutionDLQ], bool]:
    """
    User-scoped idempotent retry transition.

    Returns (entry, changed):
      - changed=True  → row was 'pending' and is now 'retrying'; retry_count
                        incremented; last_attempt_at updated.
      - changed=False → row was already in a non-pending state (retrying,
                        resolved, dismissed) — no field was modified by this
                        call.

    NOTE on retry_count semantics: this counter tracks **user-initiated retry
    attempts**, not successful enqueues. If the route handler later bails
    out (no campaign_id, Temporal unavailable, enqueue 4xx/5xx) the increment
    is intentionally preserved on commit — the user did press retry, even if
    the system could not satisfy the request. Failed attempts are
    distinguishable from successes by `status` ('pending' with non-empty
    `error` ⇒ retry attempted but failed; 'resolved' ⇒ at least one
    successful enqueue).

    Concurrency: the UPDATE is conditional on status='pending' so two
    racing requests cannot both flip the row — the DB row lock guarantees
    only one transaction returns changed=True.
    """
    now = datetime.now(timezone.utc)
    transition_stmt = (
        update(ExecutionDLQ)
        .where(
            ExecutionDLQ.id == dlq_id,
            ExecutionDLQ.execution_id.in_(
                select(Execution.id).where(_execution_scope_where(org_id, user_id))
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
        .where(ExecutionDLQ.id == dlq_id, _execution_scope_where(org_id, user_id))
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


async def get_dlq_entry_for_execution(
    db: AsyncSession,
    execution_id: str,
    *,
    device_serial: str | None = None,
) -> Optional[ExecutionDLQ]:
    q = (
        select(ExecutionDLQ)
        .where(ExecutionDLQ.execution_id == execution_id)
        .order_by(ExecutionDLQ.created_at.desc())
    )
    if device_serial:
        q = q.where(ExecutionDLQ.device_serial == device_serial)
    result = await db.execute(q.limit(1))
    return result.scalar_one_or_none()


async def get_dlq_entry_for_user(
    db: AsyncSession,
    dlq_id: str,
    user_id: str | None = None,
    *,
    org_id: str | None = None,
) -> Optional[ExecutionDLQ]:
    stmt = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .where(ExecutionDLQ.id == dlq_id, _execution_scope_where(org_id, user_id))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_dlq_by_execution_for_user(
    db: AsyncSession,
    execution_id: str,
    user_id: str | None = None,
    *,
    org_id: str | None = None,
) -> Optional[ExecutionDLQ]:
    stmt = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .where(ExecutionDLQ.execution_id == execution_id, _execution_scope_where(org_id, user_id))
        .order_by(ExecutionDLQ.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def mark_dlq_replayed(
    db: AsyncSession,
    dlq_id: str,
    *,
    replayed_to_execution_id: str,
) -> Optional[ExecutionDLQ]:
    entry = await get_dlq_entry(db, dlq_id)
    if entry is None:
        return None
    entry.status = "replayed"
    entry.replayed_to_execution_id = replayed_to_execution_id
    await db.flush()
    return entry


async def close_dlq_entry_for_user(
    db: AsyncSession,
    dlq_id: str,
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    closed_by: str | None = None,
    close_reason: str | None = None,
) -> Optional[ExecutionDLQ]:
    entry = await get_dlq_entry_for_user(db, dlq_id, user_id, org_id=org_id)
    if entry is None:
        return None
    now = datetime.now(timezone.utc)
    entry.status = "closed"
    entry.closed_by = closed_by
    entry.closed_at = now
    entry.close_reason = close_reason
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


async def dismiss_dlq_entry_for_user(
    db: AsyncSession,
    dlq_id: str,
    user_id: str | None = None,
    *,
    org_id: str | None = None,
) -> bool:
    stmt = (
        select(ExecutionDLQ)
        .join(Execution, Execution.id == ExecutionDLQ.execution_id)
        .where(ExecutionDLQ.id == dlq_id, _execution_scope_where(org_id, user_id))
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
    "count_dlq_entries_for_user",
    "get_dlq_entry",
    "get_dlq_entry_for_execution",
    "get_dlq_entry_for_user",
    "get_dlq_by_execution_for_user",
    "list_dlq_entries",
    "list_dlq_entries_for_user",
    "mark_dlq_retrying",
    "begin_dlq_retry",
    "begin_dlq_retry_for_user",
    "set_dlq_status",
    "mark_dlq_resolved",
    "mark_dlq_replayed",
    "close_dlq_entry_for_user",
    "dismiss_dlq_entry",
    "dismiss_dlq_entry_for_user",
]
