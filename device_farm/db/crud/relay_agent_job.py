from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.relay_agent import RelayAgentJob, RelayAgentJobItem
from db.models.utils import _now, _uuid


TERMINAL_ITEM_STATUSES = {"ok", "failed", "skipped"}


async def create_relay_job(
    db: AsyncSession,
    *,
    user_id: str,
    relay_id: str,
    kind: str,
    serials: list[str],
) -> RelayAgentJob:
    now = _now()
    job = RelayAgentJob(
        id=_uuid(),
        user_id=user_id,
        relay_id=relay_id,
        kind=kind,
        status="pending",
        total=len(serials),
        ok=0,
        failed=0,
        pending=len(serials),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    await db.flush()
    for serial in serials:
        db.add(
            RelayAgentJobItem(
                id=_uuid(),
                job_id=job.id,
                serial=serial,
                status="pending",
                result={},
                created_at=now,
                updated_at=now,
            )
        )
    await db.flush()
    return job


async def get_relay_job(
    db: AsyncSession,
    job_id: str,
    *,
    user_id: Optional[str] = None,
    relay_id: Optional[str] = None,
) -> Optional[RelayAgentJob]:
    stmt = select(RelayAgentJob).where(RelayAgentJob.id == job_id)
    if user_id is not None:
        stmt = stmt.where(RelayAgentJob.user_id == user_id)
    if relay_id is not None:
        stmt = stmt.where(RelayAgentJob.relay_id == relay_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_relay_job_items(
    db: AsyncSession,
    job_id: str,
    *,
    status: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
) -> list[RelayAgentJobItem]:
    stmt = (
        select(RelayAgentJobItem)
        .where(RelayAgentJobItem.job_id == job_id)
        .order_by(RelayAgentJobItem.created_at.asc(), RelayAgentJobItem.serial.asc())
        .limit(max(1, min(limit, 1000)))
        .offset(max(0, offset))
    )
    if status:
        stmt = stmt.where(RelayAgentJobItem.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_relay_job_item(db: AsyncSession, item_id: str) -> Optional[RelayAgentJobItem]:
    result = await db.execute(select(RelayAgentJobItem).where(RelayAgentJobItem.id == item_id))
    return result.scalar_one_or_none()


async def mark_relay_job_running(db: AsyncSession, job_id: str) -> None:
    now = _now()
    await db.execute(
        update(RelayAgentJob)
        .where(RelayAgentJob.id == job_id)
        .values(status="running", started_at=func.coalesce(RelayAgentJob.started_at, now), updated_at=now)
    )


async def mark_relay_job_item_running(db: AsyncSession, item_id: str, *, step: str) -> None:
    now = _now()
    await db.execute(
        update(RelayAgentJobItem)
        .where(RelayAgentJobItem.id == item_id)
        .values(
            status="running",
            step=step,
            attempts=RelayAgentJobItem.attempts + 1,
            started_at=func.coalesce(RelayAgentJobItem.started_at, now),
            updated_at=now,
        )
    )


async def finish_relay_job_item(
    db: AsyncSession,
    item_id: str,
    *,
    status: str,
    step: str = "",
    device_id: Optional[str] = None,
    error: str = "",
    result: Optional[dict] = None,
) -> None:
    now = _now()
    values = {
        "status": status,
        "step": step,
        "error": (error or "")[:2000],
        "result": result or {},
        "finished_at": now,
        "updated_at": now,
    }
    if device_id is not None:
        values["device_id"] = device_id
    await db.execute(update(RelayAgentJobItem).where(RelayAgentJobItem.id == item_id).values(**values))


async def recompute_relay_job_counts(db: AsyncSession, job_id: str) -> RelayAgentJob | None:
    job = await get_relay_job(db, job_id)
    if job is None:
        return None
    result = await db.execute(
        select(RelayAgentJobItem.status, func.count())
        .where(RelayAgentJobItem.job_id == job_id)
        .group_by(RelayAgentJobItem.status)
    )
    counts = {str(status): int(count) for status, count in result.all()}
    ok = counts.get("ok", 0)
    failed = counts.get("failed", 0) + counts.get("skipped", 0)
    pending = sum(count for status, count in counts.items() if status not in TERMINAL_ITEM_STATUSES)
    now = _now()
    await db.execute(
        update(RelayAgentJob)
        .where(RelayAgentJob.id == job_id)
        .values(ok=ok, failed=failed, pending=pending, updated_at=now)
    )
    job.ok = ok
    job.failed = failed
    job.pending = pending
    job.updated_at = now
    return job


async def finish_relay_job(db: AsyncSession, job_id: str) -> RelayAgentJob | None:
    job = await recompute_relay_job_counts(db, job_id)
    if job is None:
        return None
    status = "completed"
    if job.failed:
        status = "completed_with_errors" if job.ok else "failed"
    elif job.pending:
        status = "running"
    now = _now()
    values = {"status": status, "updated_at": now}
    if status != "running":
        values["finished_at"] = now
    await db.execute(update(RelayAgentJob).where(RelayAgentJob.id == job_id).values(**values))
    job.status = status
    job.updated_at = now
    if status != "running":
        job.finished_at = now
    return job
