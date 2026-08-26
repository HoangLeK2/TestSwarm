"""
db/crud/execution.py — CRUD helpers for Execution, ExecutionDevice, ExecutionResult (DF-011).

All functions are async-compatible with AsyncSession.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import Campaign
from db.models.enums import ExecutionResultStatus, ExecutionStatus
from db.models.execution import Execution, ExecutionDevice, ExecutionResult
from db.models.device import Device
from db.models.utils import _now, _uuid


# ── Execution CRUD ────────────────────────────────────────────────────────────


async def create_execution(
    db: AsyncSession,
    *,
    run_type: str,
    campaign_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    device_config: Optional[dict] = None,
    loop_config: Optional[dict] = None,
    error_config: Optional[dict] = None,
    meta: Optional[dict] = None,
    user_id: Optional[str] = None,
    account_id: Optional[str] = None,
    status: str = "pending",
    kind: str = "campaign",
    organization_id: Optional[str] = None,
    org_id: Optional[str] = None,
) -> Execution:
    resolved_org_id = (org_id or organization_id or "").strip()
    if not resolved_org_id and campaign_id:
        from db.crud.campaign_entity import lookup_campaign_org_id

        resolved_org_id = (await lookup_campaign_org_id(db, campaign_id)) or ""
    if not resolved_org_id and user_id:
        from db.crud.user import get_user_org_id

        resolved_org_id = (await get_user_org_id(db, user_id)) or ""
    if not resolved_org_id:
        from tenancy.context import get_current_org_id

        resolved_org_id = get_current_org_id() or ""
    if not resolved_org_id:
        raise ValueError("org_id is required to create an execution")

    # Auto-snapshot scenario version when scenario_id is provided
    scenario_version_id = None
    if scenario_id is not None:
        from db.crud.scenario_version import create_scenario_version
        version = await create_scenario_version(db, scenario_id)
        scenario_version_id = version.id

    execution = Execution(
        run_type=run_type,
        kind=kind,
        status=status,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        scenario_version_id=scenario_version_id,
        org_id=resolved_org_id,
        device_config=device_config or {},
        loop_config=loop_config or {},
        error_config=error_config or {},
        meta=meta or {},
        user_id=user_id,
        account_id=account_id,
    )
    db.add(execution)
    await db.flush()
    return execution


async def get_execution(db: AsyncSession, execution_id: str) -> Optional[Execution]:
    result = await db.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    return result.scalar_one_or_none()


async def get_executions_by_ids(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, Execution]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    result = await db.execute(select(Execution).where(Execution.id.in_(ids)))
    return {execution.id: execution for execution in result.scalars().all()}


async def list_executions(
    db: AsyncSession,
    *,
    org_id: Optional[str] = None,
    user_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    run_type: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Execution], int]:
    q = select(Execution).order_by(Execution.created_at.desc())
    if kind == "preview":
        q = q.where(Execution.kind == "preview")
        if org_id:
            q = q.where(Execution.org_id == org_id)
        if user_id is not None:
            q = q.where(Execution.user_id == user_id)
    elif org_id:
        q = q.join(Campaign, Execution.campaign_id == Campaign.id).where(
            Campaign.org_id == org_id
        )
    elif user_id is not None:
        q = q.where(Execution.user_id == user_id)
    if campaign_id is not None:
        q = q.where(Execution.campaign_id == campaign_id)
    if scenario_id is not None:
        q = q.where(Execution.scenario_id == scenario_id)
    if run_type is not None:
        q = q.where(Execution.run_type == run_type)
    if kind is not None and kind != "preview":
        q = q.where(Execution.kind == kind)
    if status is not None:
        q = q.where(Execution.status == status)
    if since is not None:
        q = q.where(Execution.created_at >= since)

    total_result = await db.execute(
        select(func.count()).select_from(q.order_by(None).subquery())
    )
    total = total_result.scalar_one()

    items_result = await db.execute(q.offset(offset).limit(limit))
    return list(items_result.scalars().all()), total


async def update_execution(
    db: AsyncSession, execution_id: str, **kwargs
) -> Optional[Execution]:
    execution = await get_execution(db, execution_id)
    if execution is None:
        return None
    for key, value in kwargs.items():
        if hasattr(execution, key):
            setattr(execution, key, value)
    await db.flush()
    return execution


async def delete_execution(db: AsyncSession, execution_id: str) -> bool:
    execution = await get_execution(db, execution_id)
    if execution is None:
        return False
    await db.delete(execution)
    await db.flush()
    return True


async def start_execution(db: AsyncSession, execution_id: str) -> Optional[Execution]:
    """Set status=running and started_at=now."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        return None
    execution.status = "running"
    execution.started_at = datetime.now(timezone.utc)
    await db.flush()
    return execution


async def finish_execution(
    db: AsyncSession, execution_id: str, status: str = "completed"
) -> Optional[Execution]:
    """Set status and finished_at=now. Never downgrades 'failed' to 'completed'."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        return None
    if execution.status == "failed" and status == "completed":
        status = "failed"
    execution.status = status
    execution.finished_at = datetime.now(timezone.utc)
    await db.flush()
    return execution


async def close_open_execution_results(
    db: AsyncSession,
    execution_id: str,
    *,
    status: str,
    device_id: Optional[str] = None,
) -> int:
    """Settle per-device result rows still sitting at pending/running.

    An execution can reach a terminal state without its ExecutionResult rows
    ever being written: the row is created when a device starts a target, but
    only `finalize_campaign` writes the outcome, and the paths that finish an
    execution around it (cleanup after a failed crawl target, the orphan reaper)
    left the row at 'running' forever. Cumulative run stats read those rows, so
    the campaign kept a device in its in-flight count long after the phone was
    released — a run that reads busy with nothing running.

    Only non-terminal rows are touched, so a real outcome already recorded by
    `finalize_campaign` is never overwritten. Returns the number of rows closed.
    """
    er_status = (
        ExecutionResultStatus.PASSED.value
        if status == ExecutionStatus.COMPLETED.value
        else ExecutionResultStatus.FAILED.value
    )
    conditions = [
        ExecutionResult.execution_id == execution_id,
        ExecutionResult.status.in_(
            (
                ExecutionResultStatus.PENDING.value,
                ExecutionResultStatus.RUNNING.value,
            )
        ),
    ]
    if device_id:
        conditions.append(ExecutionResult.device_id == device_id)
    result = await db.execute(
        update(ExecutionResult)
        .where(*conditions)
        .values(status=er_status, finished_at=datetime.now(timezone.utc))
    )
    await db.flush()
    return int(result.rowcount or 0)


async def list_running_executions_for_campaign(
    db: AsyncSession, campaign_id: str
) -> list[Execution]:
    result = await db.execute(
        select(Execution).where(
            Execution.campaign_id == campaign_id,
            Execution.status.in_(("running", "paused")),
        )
    )
    return list(result.scalars().all())


async def list_running_executions_for_device(
    db: AsyncSession, device_id: str
) -> list[Execution]:
    """Running/paused executions linked to a device (Epic 04 fan-out / preview)."""
    result = await db.execute(
        select(Execution)
        .join(ExecutionDevice, ExecutionDevice.execution_id == Execution.id)
        .where(
            ExecutionDevice.device_id == device_id,
            Execution.status.in_(("running", "paused")),
        )
        .order_by(Execution.created_at.desc())
    )
    return list(result.scalars().all())


async def pause_execution_record(
    db: AsyncSession, execution_id: str, *, now: datetime | None = None
) -> tuple[Optional[Execution], bool]:
    """Mark execution paused. Returns (execution, transitioned) — False if already paused."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        return None, False
    if execution.status == "paused":
        return execution, False
    ts = now or datetime.now(timezone.utc)
    execution.status = "paused"
    execution.pause_signal_received_at = ts
    await db.flush()
    return execution, True


async def resume_execution_record(
    db: AsyncSession, execution_id: str
) -> Optional[Execution]:
    execution = await get_execution(db, execution_id)
    if execution is None:
        return None
    if execution.status != "paused":
        return execution
    execution.status = "running"
    await db.flush()
    return execution


async def cancel_execution_record(
    db: AsyncSession,
    execution_id: str,
    *,
    reason: str | None = None,
    now: datetime | None = None,
) -> tuple[Optional[Execution], bool]:
    """Mark execution cancelled. Returns (execution, transitioned)."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        return None, False
    if execution.status == "cancelled":
        return execution, False
    ts = now or datetime.now(timezone.utc)
    execution.status = "cancelled"
    execution.cancel_reason = reason
    execution.cancel_signal_received_at = ts
    execution.cancelled_at = ts
    execution.finished_at = ts
    await db.flush()
    return execution, True


# ── ExecutionDevice (join) ────────────────────────────────────────────────────


async def add_device_to_execution(
    db: AsyncSession, execution_id: str, device_id: str
) -> ExecutionDevice:
    link = ExecutionDevice(execution_id=execution_id, device_id=device_id)
    db.add(link)
    await db.flush()
    return link


async def add_devices_to_execution(
    db: AsyncSession, execution_id: str, device_ids: list[str]
) -> list[ExecutionDevice]:
    links = [
        ExecutionDevice(execution_id=execution_id, device_id=device_id)
        for device_id in device_ids
    ]
    if not links:
        return []
    db.add_all(links)
    await db.flush()
    return links


async def remove_device_from_execution(
    db: AsyncSession, execution_id: str, device_id: str
) -> None:
    result = await db.execute(
        select(ExecutionDevice).where(
            ExecutionDevice.execution_id == execution_id,
            ExecutionDevice.device_id == device_id,
        )
    )
    link = result.scalar_one_or_none()
    if link is not None:
        await db.delete(link)
        await db.flush()


async def list_execution_devices(
    db: AsyncSession, execution_id: str
) -> list[Device]:
    result = await db.execute(
        select(Device)
        .join(ExecutionDevice, ExecutionDevice.device_id == Device.id)
        .where(ExecutionDevice.execution_id == execution_id)
    )
    return list(result.scalars().all())


# ── ExecutionResult ───────────────────────────────────────────────────────────


async def upsert_execution_result(
    db: AsyncSession,
    *,
    execution_id: str,
    device_id: str,
    status: str = "pending",
    passed_steps: Optional[list] = None,
    failed_steps: Optional[list] = None,
    error_detail: Optional[str] = None,
    run_time_sec: Optional[float] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> ExecutionResult:
    result = await db.execute(
        select(ExecutionResult).where(
            ExecutionResult.execution_id == execution_id,
            ExecutionResult.device_id == device_id,
        )
    )
    er = result.scalar_one_or_none()

    if er is None:
        execution = await get_execution(db, execution_id)
        if execution is None:
            raise ValueError(f"execution not found: {execution_id}")
        er = ExecutionResult(
            org_id=execution.org_id,
            execution_id=execution_id,
            device_id=device_id,
            status=status,
            passed_steps=passed_steps or [],
            failed_steps=failed_steps or [],
            error_detail=error_detail,
            run_time_sec=run_time_sec,
            started_at=started_at,
            finished_at=finished_at,
        )
        db.add(er)
    else:
        er.status = status
        if passed_steps is not None:
            er.passed_steps = passed_steps
        if failed_steps is not None:
            er.failed_steps = failed_steps
        if error_detail is not None:
            er.error_detail = error_detail
        if run_time_sec is not None:
            er.run_time_sec = run_time_sec
        if started_at is not None:
            er.started_at = started_at
        if finished_at is not None:
            er.finished_at = finished_at

    await db.flush()
    return er


async def get_execution_result(
    db: AsyncSession, execution_id: str, device_id: str
) -> Optional[ExecutionResult]:
    result = await db.execute(
        select(ExecutionResult).where(
            ExecutionResult.execution_id == execution_id,
            ExecutionResult.device_id == device_id,
        )
    )
    return result.scalar_one_or_none()


async def list_execution_results(
    db: AsyncSession, execution_id: str
) -> list[ExecutionResult]:
    result = await db.execute(
        select(ExecutionResult)
        .where(ExecutionResult.execution_id == execution_id)
        .order_by(ExecutionResult.created_at)
    )
    return list(result.scalars().all())


async def execution_summary(db: AsyncSession, execution_id: str) -> dict:
    """Aggregated summary: device counts by status + total content items."""
    status_counts = await db.execute(
        select(ExecutionResult.status, func.count().label("cnt"))
        .where(ExecutionResult.execution_id == execution_id)
        .group_by(ExecutionResult.status)
    )
    counts: dict[str, int] = {row.status: row.cnt for row in status_counts}

    from db.models.content import ContentItem
    content_count_result = await db.execute(
        select(func.count()).where(ContentItem.execution_id == execution_id)
    )
    total_content = content_count_result.scalar_one()

    total_devices = sum(counts.values())
    return {
        "total_devices": total_devices,
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "running": counts.get("running", 0),
        "pending": counts.get("pending", 0),
        "error": counts.get("error", 0),
        "total_content_items": total_content,
    }


async def campaign_run_stats(db: AsyncSession, campaign_id: str) -> dict:
    """Cumulative run stats across all executions for a campaign."""
    status_counts = await db.execute(
        select(ExecutionResult.status, func.count().label("cnt"))
        .join(Execution, ExecutionResult.execution_id == Execution.id)
        .where(Execution.campaign_id == campaign_id)
        .group_by(ExecutionResult.status)
    )
    counts: dict[str, int] = {row.status: row.cnt for row in status_counts}

    from db.models.content import ContentItem
    content_count_result = await db.execute(
        select(func.count()).where(ContentItem.campaign_id == campaign_id)
    )
    total_content = content_count_result.scalar_one()

    recent_executions_result = await db.execute(
        select(Execution)
        .where(Execution.campaign_id == campaign_id)
        .order_by(Execution.created_at.desc())
        .limit(1000)
    )
    latest_dispatch_timing = _latest_campaign_dispatch_timing(
        list(recent_executions_result.scalars().all())
    )

    total_runs = sum(counts.values())
    return {
        "total_devices": total_runs,
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0),
        "running": counts.get("running", 0),
        "pending": counts.get("pending", 0),
        "error": counts.get("error", 0),
        "total_content_items": total_content,
        **latest_dispatch_timing,
    }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if start.tzinfo is None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    elif start.tzinfo is not None and end.tzinfo is None:
        end = end.replace(tzinfo=start.tzinfo)
    return max(0.0, (end - start).total_seconds() * 1000.0)


def _percentile_float(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, p)) * (len(ordered) - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= len(ordered) - 1:
        return ordered[-1]
    return ordered[idx] + (ordered[idx + 1] - ordered[idx]) * frac


def _latest_campaign_dispatch_timing(executions: list[Execution]) -> dict:
    if not executions:
        return {}

    newest = executions[0]
    newest_meta = newest.meta or {}
    latest_dispatch_id = newest_meta.get("dispatch_id")
    if latest_dispatch_id:
        latest_rows = [
            row
            for row in executions
            if (row.meta or {}).get("dispatch_id") == latest_dispatch_id
        ]
    else:
        latest_rows = [newest]

    if not latest_rows:
        return {}

    terminal_statuses = {"completed", "failed", "cancelled", "dlq_closed"}
    created_values = [row.created_at for row in latest_rows if row.created_at]
    started_values = [row.started_at for row in latest_rows if row.started_at]
    finished_values = [row.finished_at for row in latest_rows if row.finished_at]
    first_created_at = min(created_values) if created_values else None
    first_started_at = min(started_values) if started_values else None
    latest_finished_at = max(finished_values) if finished_values else None
    terminal_count = sum(1 for row in latest_rows if row.status in terminal_statuses)
    running_count = sum(1 for row in latest_rows if row.status in {"running", "paused"})
    pending_count = sum(1 for row in latest_rows if row.status == "pending")
    failed_count = sum(1 for row in latest_rows if row.status == "failed")
    workflow_started_count = sum(
        1 for row in latest_rows if (row.meta or {}).get("workflow_id")
    )
    fallback_count = sum(
        1 for row in latest_rows if (row.meta or {}).get("dispatch_source") == "fallback"
    )
    dispatch_to_start_ms = [
        duration
        for row in latest_rows
        if (
            duration := _duration_ms(row.created_at, row.started_at)
        )
        is not None
    ]
    terminal_at = (
        latest_finished_at
        if terminal_count == len(latest_rows) and latest_finished_at
        else None
    )
    elapsed_end = terminal_at or datetime.now(timezone.utc)

    return {
        "latest_dispatch_id": str(latest_dispatch_id) if latest_dispatch_id else None,
        "latest_dispatch_target_count": len(latest_rows),
        "latest_dispatch_finished_count": terminal_count,
        "latest_dispatch_running_count": running_count,
        "latest_dispatch_pending_count": pending_count,
        "latest_dispatch_failed_count": failed_count,
        "latest_dispatch_workflow_started_count": workflow_started_count,
        "latest_dispatch_fallback_count": fallback_count,
        "latest_dispatch_created_at": _iso(first_created_at),
        "latest_dispatch_first_started_at": _iso(first_started_at),
        "latest_dispatch_latest_finished_at": _iso(latest_finished_at),
        "latest_dispatch_elapsed_ms": _duration_ms(first_created_at, elapsed_end),
        "latest_dispatch_terminal_ms": _duration_ms(first_created_at, terminal_at),
        "latest_dispatch_to_first_start_ms": _duration_ms(
            first_created_at,
            first_started_at,
        ),
        "latest_dispatch_to_start_p95_ms": _percentile_float(
            dispatch_to_start_ms,
            0.95,
        ),
    }


__all__ = [
    # Execution
    "create_execution",
    "get_execution",
    "get_executions_by_ids",
    "list_executions",
    "update_execution",
    "delete_execution",
    "start_execution",
    "finish_execution",
    "list_running_executions_for_campaign",
    "list_running_executions_for_device",
    "pause_execution_record",
    "resume_execution_record",
    "cancel_execution_record",
    # ExecutionDevice
    "add_device_to_execution",
    "remove_device_from_execution",
    "list_execution_devices",
    # ExecutionResult
    "upsert_execution_result",
    "get_execution_result",
    "list_execution_results",
    "execution_summary",
    "campaign_run_stats",
]
