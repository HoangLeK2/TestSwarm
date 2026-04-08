"""
db/crud/schedule.py — CRUD helpers for Schedule + ScheduleRun (DF-008).

All functions are async-compatible with AsyncSession.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.schedule import Schedule, ScheduleRun
from db.models.utils import _now


# ── Schedule CRUD ─────────────────────────────────────────────────────────────


async def create_schedule(
    db: AsyncSession,
    *,
    name: str,
    description: str = "",
    target_type: str,
    target_id: Optional[str] = None,
    inline_steps: Optional[list] = None,
    inline_variables: Optional[dict] = None,
    device_group_id: Optional[str] = None,
    filter_state: str = "READY",
    filter_model: Optional[str] = None,
    max_devices: Optional[int] = None,
    cron_expression: str,
    timezone_name: str = "Asia/Ho_Chi_Minh",
    random_delay_min: int = 0,
    random_delay_max: int = 0,
    stagger_devices: bool = False,
    stagger_interval_seconds: int = 60,
    is_enabled: bool = True,
    next_run_at: Optional[datetime] = None,
    user_id: Optional[str] = None,
) -> Schedule:
    schedule = Schedule(
        name=name,
        description=description,
        target_type=target_type,
        target_id=target_id,
        inline_steps=inline_steps,
        inline_variables=inline_variables or {},
        device_group_id=device_group_id,
        filter_state=filter_state,
        filter_model=filter_model,
        max_devices=max_devices,
        cron_expression=cron_expression,
        timezone=timezone_name,
        random_delay_min=random_delay_min,
        random_delay_max=random_delay_max,
        stagger_devices=stagger_devices,
        stagger_interval_seconds=stagger_interval_seconds,
        is_enabled=is_enabled,
        next_run_at=next_run_at,
        user_id=user_id,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def get_schedule(
    db: AsyncSession, schedule_id: str
) -> Optional[Schedule]:
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id)
    )
    return result.scalar_one_or_none()


async def list_schedules(
    db: AsyncSession,
    user_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Schedule]:
    q = select(Schedule).order_by(Schedule.created_at.desc())
    if user_id is not None:
        q = q.where(Schedule.user_id == user_id)
    q = q.offset(offset).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_schedule(
    db: AsyncSession, schedule_id: str, **kwargs
) -> Optional[Schedule]:
    schedule = await get_schedule(db, schedule_id)
    if schedule is None:
        return None
    # Map timezone kwarg to model attribute name
    if "timezone_name" in kwargs:
        kwargs["timezone"] = kwargs.pop("timezone_name")
    for key, value in kwargs.items():
        if hasattr(schedule, key):
            setattr(schedule, key, value)
    schedule.updated_at = _now()
    await db.flush()
    return schedule


async def delete_schedule(db: AsyncSession, schedule_id: str) -> bool:
    schedule = await get_schedule(db, schedule_id)
    if schedule is None:
        return False
    await db.delete(schedule)
    await db.flush()
    return True


async def get_due_schedules(
    db: AsyncSession, now: Optional[datetime] = None
) -> list[Schedule]:
    """Return enabled schedules whose next_run_at is <= now (due to fire)."""
    if now is None:
        now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Schedule).where(
            Schedule.is_enabled.is_(True),
            Schedule.next_run_at <= now,
            Schedule.next_run_at.is_not(None),
        )
    )
    return list(result.scalars().all())


async def update_schedule_after_run(
    db: AsyncSession,
    schedule_id: str,
    *,
    last_run_at: datetime,
    next_run_at: Optional[datetime],
) -> None:
    """Increment run_count, set last_run_at and next_run_at after a run."""
    schedule = await get_schedule(db, schedule_id)
    if schedule is None:
        return
    schedule.last_run_at = last_run_at
    schedule.next_run_at = next_run_at
    schedule.run_count = (schedule.run_count or 0) + 1
    schedule.updated_at = _now()
    await db.flush()


# ── ScheduleRun CRUD ──────────────────────────────────────────────────────────


async def create_schedule_run(
    db: AsyncSession,
    *,
    schedule_id: str,
    status: str = "pending",
) -> ScheduleRun:
    run = ScheduleRun(
        schedule_id=schedule_id,
        status=status,
    )
    db.add(run)
    await db.flush()
    return run


async def get_schedule_run(
    db: AsyncSession, run_id: str
) -> Optional[ScheduleRun]:
    result = await db.execute(
        select(ScheduleRun).where(ScheduleRun.id == run_id)
    )
    return result.scalar_one_or_none()


async def list_schedule_runs(
    db: AsyncSession,
    schedule_id: str,
    offset: int = 0,
    limit: int = 50,
) -> list[ScheduleRun]:
    result = await db.execute(
        select(ScheduleRun)
        .where(ScheduleRun.schedule_id == schedule_id)
        .order_by(ScheduleRun.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_schedule_run(
    db: AsyncSession,
    run_id: str,
    **kwargs,
) -> Optional[ScheduleRun]:
    run = await get_schedule_run(db, run_id)
    if run is None:
        return None
    for key, value in kwargs.items():
        if hasattr(run, key):
            setattr(run, key, value)
    await db.flush()
    return run


__all__ = [
    "create_schedule",
    "get_schedule",
    "list_schedules",
    "update_schedule",
    "delete_schedule",
    "get_due_schedules",
    "update_schedule_after_run",
    "create_schedule_run",
    "get_schedule_run",
    "list_schedule_runs",
    "update_schedule_run",
]
