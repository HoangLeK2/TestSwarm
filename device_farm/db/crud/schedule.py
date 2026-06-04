"""
db/crud/schedule.py — CRUD helpers for Schedule + ScheduleRun (DF-008).

All functions are async-compatible with AsyncSession.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
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
    cron_expression: Optional[str],
    timezone_name: str = "Asia/Ho_Chi_Minh",
    schedule_kind: str = "cron",
    run_at: Optional[datetime] = None,
    skip_dates: Optional[list] = None,
    skip_windows: Optional[list] = None,
    misfire_policy: str = "skip",
    random_delay_min: int = 0,
    random_delay_max: int = 0,
    stagger_devices: bool = False,
    stagger_interval_seconds: int = 60,
    is_enabled: bool = True,
    status: Optional[str] = None,
    priority: str = "normal",
    max_concurrent_per_device: int = 1,
    account_rate_limit_per_hour: Optional[int] = None,
    quota_policy: Optional[dict] = None,
    next_run_at: Optional[datetime] = None,
    user_id: Optional[str] = None,
    org_id: Optional[str] = None,
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
        schedule_kind=schedule_kind,
        run_at=run_at,
        skip_dates=skip_dates or [],
        skip_windows=skip_windows or [],
        misfire_policy=misfire_policy,
        random_delay_min=random_delay_min,
        random_delay_max=random_delay_max,
        stagger_devices=stagger_devices,
        stagger_interval_seconds=stagger_interval_seconds,
        is_enabled=is_enabled,
        status=status or ("enabled" if is_enabled else "disabled"),
        priority=priority,
        max_concurrent_per_device=max_concurrent_per_device,
        account_rate_limit_per_hour=account_rate_limit_per_hour,
        quota_policy=quota_policy or {},
        next_run_at=next_run_at,
        user_id=user_id,
        org_id=org_id,
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def lookup_schedule_org_id(db: AsyncSession, schedule_id: str) -> str | None:
    """Resolve schedule org without tenant context (Temporal/background paths)."""
    table = Schedule.__table__
    result = await db.execute(
        select(table.c.org_id).where(table.c.id == schedule_id).limit(1)
    )
    return result.scalar_one_or_none()


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
    q = select(Schedule).where(Schedule.status != "deleted").order_by(Schedule.created_at.desc())
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
    now = _now()
    schedule.is_enabled = False
    schedule.status = "deleted"
    schedule.next_run_at = None
    schedule.deleted_at = now
    schedule.updated_at = now
    await db.flush()
    return True


async def get_due_schedules(
    db: AsyncSession, now: Optional[datetime] = None
) -> list[Schedule]:
    """Return enabled schedules whose next_run_at is <= now (due to fire).

    NOTE: Prefer `claim_due_schedules` for executor code paths — plain SELECT
    here is non-atomic and will return the same row to concurrent pollers.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Schedule).where(
            Schedule.is_enabled.is_(True),
            Schedule.status == "enabled",
            Schedule.next_run_at <= now,
            Schedule.next_run_at.is_not(None),
        )
    )
    return list(result.scalars().all())


async def claim_due_schedules(
    db: AsyncSession,
    now: Optional[datetime] = None,
    lease_seconds: int = 300,
) -> list[Schedule]:
    """Atomically claim due schedules by advancing next_run_at to a lease.

    Prevents double-dispatch under concurrent pollers (multi-instance or
    overlapping poll cycles). Uses UPDATE … RETURNING which acquires a row
    lock per match; the second poller sees the bumped next_run_at and skips.

    The lease is a tentative placeholder — successful dispatch MUST call
    update_schedule_after_run to replace it with the real cron-computed
    next_run_at. If the process crashes mid-dispatch, the schedule stays
    quiet until `lease_seconds` elapse, then gets claimed again.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=lease_seconds)

    stmt = (
        update(Schedule)
        .where(
            Schedule.is_enabled.is_(True),
            Schedule.status == "enabled",
            Schedule.next_run_at <= now,
            Schedule.next_run_at.is_not(None),
        )
        .values(next_run_at=lease_until, updated_at=_now())
        .returning(Schedule)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    claimed = list(result.scalars().all())
    await db.commit()
    return claimed


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
    if schedule.schedule_kind == "one_shot":
        schedule.is_enabled = False
        schedule.status = "completed"
    schedule.updated_at = _now()
    await db.flush()


# ── ScheduleRun CRUD ──────────────────────────────────────────────────────────


async def create_schedule_run(
    db: AsyncSession,
    *,
    schedule_id: str,
    status: str = "pending",
    trigger_source: str = "cron",
    scheduled_at: Optional[datetime] = None,
    deferred_until: Optional[datetime] = None,
    was_catch_up: bool = False,
    execution_id: Optional[str] = None,
    error_code: Optional[str] = None,
    org_id: Optional[str] = None,
) -> ScheduleRun:
    if org_id is None:
        try:
            from tenancy.context import get_current_org_id

            org_id = get_current_org_id()
        except Exception:
            org_id = None
    run = ScheduleRun(
        schedule_id=schedule_id,
        status=status,
        trigger_source=trigger_source,
        scheduled_at=scheduled_at,
        deferred_until=deferred_until,
        was_catch_up=was_catch_up,
        execution_id=execution_id,
        error_code=error_code,
        org_id=org_id,
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
    status_filter: Optional[str] = None,
) -> list[ScheduleRun]:
    q = select(ScheduleRun).where(ScheduleRun.schedule_id == schedule_id)
    if status_filter:
        q = q.where(ScheduleRun.status == status_filter)
    q = q.order_by(ScheduleRun.started_at.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
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
