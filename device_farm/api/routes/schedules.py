"""
api/routes/schedules.py — REST API for Schedule management (DF-008).

Endpoints:
    GET    /api/schedules                  List schedules
    POST   /api/schedules                  Create schedule
    GET    /api/schedules/{id}             Get schedule detail
    PATCH  /api/schedules/{id}             Update schedule
    DELETE /api/schedules/{id}             Delete schedule
    POST   /api/schedules/{id}/toggle      Enable/disable
    POST   /api/schedules/{id}/run-now     Trigger manual run

    GET    /api/schedules/{id}/runs        List run history
    GET    /api/schedules/{id}/runs/{rid}  Get run detail
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.deps import CurrentUser, DB, require_permission
from api.org_scope import data_owner_user_id
from api.schemas.schedule import (
    ScheduleCreate,
    ScheduleOut,
    SchedulePatch,
    ScheduleRunOut,
    TriggerResponse,
)
from db import crud as repo
from db.crud.schedule import (
    get_schedule,
    list_schedules,
    list_schedule_runs,
    get_schedule_run,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_scheduler(request: Request):
    """Get SchedulerService from app state."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler service not initialized",
        )
    return scheduler


async def _get_schedule_or_404(db, schedule_id: str, user: CurrentUser):
    schedule = await get_schedule(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    owner_id = data_owner_user_id(user)
    if owner_id and schedule.user_id != owner_id:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


def _to_out(s) -> ScheduleOut:
    return ScheduleOut(
        id=s.id,
        name=s.name,
        description=s.description or "",
        target_type=s.target_type,
        target_id=s.target_id,
        inline_steps=s.inline_steps,
        inline_variables=s.inline_variables or {},
        device_group_id=s.device_group_id,
        filter_state=s.filter_state,
        filter_model=s.filter_model,
        max_devices=s.max_devices,
        cron_expression=s.cron_expression,
        timezone=s.timezone,
        random_delay_min=s.random_delay_min,
        random_delay_max=s.random_delay_max,
        stagger_devices=s.stagger_devices,
        stagger_interval_seconds=s.stagger_interval_seconds,
        is_enabled=s.is_enabled,
        last_run_at=s.last_run_at,
        next_run_at=s.next_run_at,
        run_count=s.run_count,
        user_id=s.user_id,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _run_to_out(r) -> ScheduleRunOut:
    return ScheduleRunOut(
        id=r.id,
        schedule_id=r.schedule_id,
        status=r.status,
        started_at=r.started_at,
        finished_at=r.finished_at,
        devices_dispatched=r.devices_dispatched,
        devices_succeeded=r.devices_succeeded,
        devices_failed=r.devices_failed,
        task_ids=r.task_ids or [],
        error_message=r.error_message,
        created_at=r.created_at,
    )


# ── Schedule CRUD ─────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[ScheduleOut],
    dependencies=[Depends(require_permission("schedules", "read"))],
)
async def list_schedules_endpoint(
    db: DB,
    user: CurrentUser,
    offset: int = 0,
    limit: int = 50,
):
    schedules = await list_schedules(
        db, user_id=data_owner_user_id(user), offset=offset, limit=limit
    )
    return [_to_out(s) for s in schedules]


@router.post(
    "",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("schedules", "create"))],
)
async def create_schedule_endpoint(
    body: ScheduleCreate,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    # Validate target consistency
    if body.target_type in ("campaign", "template") and not body.target_id:
        raise HTTPException(
            status_code=400,
            detail=f"target_id is required when target_type={body.target_type!r}",
        )
    if body.target_type == "fleet" and not body.inline_steps:
        raise HTTPException(
            status_code=400,
            detail="inline_steps is required when target_type='fleet'",
        )

    scheduler = _get_scheduler(request)
    schedule = await scheduler.create(
        db,
        name=body.name,
        description=body.description,
        target_type=body.target_type,
        target_id=body.target_id,
        inline_steps=body.inline_steps,
        inline_variables=body.inline_variables,
        device_group_id=body.device_group_id,
        filter_state=body.filter_state,
        filter_model=body.filter_model,
        max_devices=body.max_devices,
        cron_expression=body.cron_expression,
        timezone_name=body.timezone,
        random_delay_min=body.random_delay_min,
        random_delay_max=body.random_delay_max,
        stagger_devices=body.stagger_devices,
        stagger_interval_seconds=body.stagger_interval_seconds,
        is_enabled=body.is_enabled,
        user_id=user.id,
    )
    return _to_out(schedule)


@router.get(
    "/{schedule_id}",
    response_model=ScheduleOut,
    dependencies=[Depends(require_permission("schedules", "read"))],
)
async def get_schedule_endpoint(schedule_id: str, db: DB, user: CurrentUser):
    schedule = await _get_schedule_or_404(db, schedule_id, user)
    return _to_out(schedule)


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleOut,
    dependencies=[Depends(require_permission("schedules", "update"))],
)
async def update_schedule_endpoint(
    schedule_id: str,
    body: SchedulePatch,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    await _get_schedule_or_404(db, schedule_id, user)

    scheduler = _get_scheduler(request)
    patch = body.model_dump(exclude_none=True)

    # Remap timezone field to timezone_name for the service layer
    if "timezone" in patch:
        patch["timezone_name"] = patch.pop("timezone")

    schedule = await scheduler.update(db, schedule_id, patch)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _to_out(schedule)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("schedules", "delete"))],
)
async def delete_schedule_endpoint(
    schedule_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    await _get_schedule_or_404(db, schedule_id, user)
    scheduler = _get_scheduler(request)
    deleted = await scheduler.delete(db, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")


@router.post(
    "/{schedule_id}/toggle",
    response_model=ScheduleOut,
    dependencies=[Depends(require_permission("schedules", "update"))],
)
async def toggle_schedule_endpoint(
    schedule_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    existing = await _get_schedule_or_404(db, schedule_id, user)
    scheduler = _get_scheduler(request)
    schedule = await scheduler.toggle(db, schedule_id, not existing.is_enabled)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _to_out(schedule)


@router.post(
    "/{schedule_id}/run-now",
    response_model=TriggerResponse,
    dependencies=[Depends(require_permission("schedules", "execute"))],
)
async def run_now_endpoint(
    schedule_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
):
    await _get_schedule_or_404(db, schedule_id, user)
    scheduler = _get_scheduler(request)
    try:
        run_id = await scheduler.trigger_now(db, schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return TriggerResponse(run_id=run_id)


# ── Run History ───────────────────────────────────────────────────────────────


@router.get(
    "/{schedule_id}/runs",
    response_model=list[ScheduleRunOut],
    dependencies=[Depends(require_permission("schedules", "read"))],
)
async def list_runs_endpoint(
    schedule_id: str,
    db: DB,
    user: CurrentUser,
    offset: int = 0,
    limit: int = 50,
):
    await _get_schedule_or_404(db, schedule_id, user)
    runs = await list_schedule_runs(db, schedule_id, offset=offset, limit=limit)
    return [_run_to_out(r) for r in runs]


@router.get(
    "/{schedule_id}/runs/{run_id}",
    response_model=ScheduleRunOut,
    dependencies=[Depends(require_permission("schedules", "read"))],
)
async def get_run_endpoint(
    schedule_id: str,
    run_id: str,
    db: DB,
    user: CurrentUser,
):
    await _get_schedule_or_404(db, schedule_id, user)
    run = await get_schedule_run(db, run_id)
    if not run or run.schedule_id != schedule_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_out(run)
