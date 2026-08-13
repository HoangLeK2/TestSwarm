"""
api/routes/executions.py — REST API for Execution coordinator (DF-011).

Endpoints:
    POST   /api/executions                              Create execution
    GET    /api/executions                              List executions (filterable)
    GET    /api/executions/{id}                         Get execution detail
    PATCH  /api/executions/{id}                         Update config fields
    DELETE /api/executions/{id}                         Delete execution (204)
    POST   /api/executions/{id}/start                   Mark as running
    POST   /api/executions/{id}/finish                  Mark as completed/failed/cancelled
    POST   /api/executions/{id}/pause                   Pause execution (Temporal signal)
    POST   /api/executions/{id}/resume                  Resume paused execution
    POST   /api/executions/{id}/cancel                  Cancel execution (body: reason)

    GET    /api/executions/{id}/devices                 List assigned devices
    POST   /api/executions/{id}/devices                 Add device
    DELETE /api/executions/{id}/devices/{device_id}     Remove device

    GET    /api/executions/{id}/results                 List per-device results
    GET    /api/executions/{id}/results/{device_id}     Get single device result
    PUT    /api/executions/{id}/results/{device_id}     Upsert device result
    GET    /api/executions/{id}/steps                   List normalized step rows
    GET    /api/executions/{id}/summary                 Aggregated summary
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.deps import CurrentUser, DB, require_permission
from api.deps_streaming import StreamingUser, require_streaming_permission
from api.org_scope import data_owner_user_id
from api.schemas.execution import (
    AddDeviceBody,
    ExecutionCancelBody,
    ExecutionControlOut,
    ExecutionCreate,
    ExecutionListOut,
    ExecutionOut,
    ExecutionPatch,
    ExecutionResultOut,
    ExecutionStepOut,
    ExecutionTaskLogOut,
    FinishBody,
    SummaryOut,
    UpsertResultBody,
)
from db.crud.execution import (
    add_device_to_execution,
    create_execution,
    delete_execution,
    execution_summary,
    get_execution,
    finish_execution,
    get_execution_result,
    list_execution_devices,
    list_execution_results,
    list_executions,
    remove_device_from_execution,
    start_execution,
    update_execution,
    upsert_execution_result,
)
from db.crud.device import get_device
from db.crud.campaign import get_campaign, get_scenario

log = logging.getLogger(__name__)

router = APIRouter(prefix="/executions", tags=["executions"])


def _dlq_scope_kwargs(user: CurrentUser) -> dict[str, str]:
    org_id = getattr(user, "org_id", None)
    if org_id:
        return {"org_id": str(org_id)}
    return {"user_id": str(user.id)}


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_or_404(db, execution_id: str, user: CurrentUser):
    from api.execution_access import get_execution_for_user

    return await get_execution_for_user(db, execution_id, user)


# ── Execution CRUD ────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ExecutionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("executions", "create"))],
)
async def create_execution_endpoint(body: ExecutionCreate, db: DB, user: CurrentUser):
    from db import crud as repo

    user_org = getattr(user, "org_id", None) or await repo.get_user_org_id(db, user.id)
    if body.campaign_id:
        campaign = await get_campaign(db, body.campaign_id)
        if campaign is None or (user_org and campaign.org_id != user_org):
            raise HTTPException(status_code=404, detail="Campaign not found")
    if body.scenario_id:
        scenario = await get_scenario(db, body.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        owner_campaign = await get_campaign(db, scenario.campaign_id)
        if owner_campaign is None or (user_org and owner_campaign.org_id != user_org):
            raise HTTPException(status_code=404, detail="Scenario not found")
        if body.campaign_id and scenario.campaign_id != body.campaign_id:
            raise HTTPException(status_code=400, detail="Scenario does not belong to campaign")

    for device_id in body.device_ids:
        device = await get_device(db, device_id)
        if device is None or (user_org and device.org_id != user_org):
            raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    ex = await create_execution(
        db,
        run_type=body.run_type,
        campaign_id=body.campaign_id,
        scenario_id=body.scenario_id,
        device_config=body.device_config,
        loop_config=body.loop_config,
        error_config=body.error_config,
        meta=body.meta,
        user_id=user.id,
    )
    # Attach devices if provided
    for device_id in body.device_ids:
        await add_device_to_execution(db, ex.id, device_id)
    from services.execution.event_publisher import enqueue_execution_event
    from services.execution.event_types import EXECUTION_CREATED

    await enqueue_execution_event(
        db,
        event_type=EXECUTION_CREATED,
        execution_id=ex.id,
        organization_id=str(user_org or ""),
        campaign_id=ex.campaign_id,
        payload={"run_type": ex.run_type, "status": ex.status},
        execution=ex,
    )
    return ExecutionOut.model_validate(ex)


@router.get(
    "",
    response_model=ExecutionListOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_executions_endpoint(
    db: DB,
    user: CurrentUser,
    run_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    campaign_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
):
    items, total = await list_executions(
        db,
        org_id=getattr(user, "org_id", None),
        user_id=data_owner_user_id(user),
        run_type=run_type,
        status=status_filter,
        campaign_id=campaign_id,
        scenario_id=scenario_id,
        offset=offset,
        limit=limit,
    )
    return ExecutionListOut(total=total, items=[ExecutionOut.model_validate(e) for e in items])


# ── DLQ endpoints ─────────────────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel, Field
from typing import Optional as _Optional
from datetime import datetime as _datetime, timezone as _timezone


class DLQEntryOut(_BaseModel):
    id: str
    execution_id: str
    device_serial: str
    error: _Optional[str]
    retry_count: int
    status: str
    last_attempt_at: _Optional[_datetime]
    created_at: _datetime
    campaign_id: _Optional[str] = None
    failed_step_id: _Optional[str] = None
    failure_reason: _Optional[str] = None
    failed_at: _Optional[_datetime] = None
    closed_by: _Optional[str] = None
    closed_at: _Optional[_datetime] = None
    close_reason: _Optional[str] = None
    replayed_to_execution_id: _Optional[str] = None
    artifact_refs: dict = Field(default_factory=dict)
    display_message: str = ""

    model_config = {"from_attributes": True}


async def _dlq_entries_to_out(db, entries) -> list[DLQEntryOut]:
    from services.campaign.dlq_message import enrich_dlq_display_messages

    messages = await enrich_dlq_display_messages(db, entries)
    out: list[DLQEntryOut] = []
    for entry, display_message in zip(entries, messages, strict=True):
        row = DLQEntryOut.model_validate(entry)
        row.display_message = display_message
        out.append(row)
    return out


async def _dlq_entry_to_out(db, entry) -> DLQEntryOut:
    rows = await _dlq_entries_to_out(db, [entry])
    return rows[0]


class DLQRetryBody(_BaseModel):
    from_checkpoint: bool = True


class DLQCloseBody(_BaseModel):
    reason: str = Field(min_length=1)


class DLQBulkRetryBody(_BaseModel):
    execution_ids: list[str] = Field(default_factory=list)
    dlq_ids: list[str] = Field(default_factory=list)
    from_checkpoint: bool = True


class DLQBulkRetryItemOut(_BaseModel):
    dlq_id: _Optional[str] = None
    execution_id: _Optional[str] = None
    status: str
    reason: _Optional[str] = None
    message: _Optional[str] = None
    replayed_to_execution_id: _Optional[str] = None
    entry_status: _Optional[str] = None


class DLQBulkRetryOut(_BaseModel):
    results: list[DLQBulkRetryItemOut]


class DLQSummaryOut(_BaseModel):
    pending_count: int
    alert_threshold: int
    alert: bool
    dismissed_offline_count: int = 0
    offline_dismiss_minutes: int


class ExecutionArtifactOut(_BaseModel):
    artifact_type: str
    execution_id: str
    device_serial: _Optional[str] = None
    step_index: _Optional[int] = None
    step_type: _Optional[str] = None
    ok: _Optional[bool] = None
    message: _Optional[str] = None
    url: _Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: _Optional[_datetime] = None


class ExecutionEventOut(_BaseModel):
    event_id: str
    event_type: str
    schema_version: str
    occurred_at: _datetime
    organization_id: str
    campaign_id: _Optional[str] = None
    execution_id: str
    step_id: _Optional[str] = None
    payload: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ExecutionEventListOut(_BaseModel):
    items: list[ExecutionEventOut]
    has_more: bool = False


def _dlq_offline_dismiss_minutes() -> int:
    raw = os.environ.get("DEVICE_FARM_DLQ_OFFLINE_DISMISS_MINUTES", "5")
    try:
        return max(1, min(10_080, int(raw)))
    except ValueError:
        return 5


def _dlq_alert_threshold() -> int:
    raw = os.environ.get("DEVICE_FARM_DLQ_ALERT_THRESHOLD", "10")
    try:
        return max(1, int(raw))
    except ValueError:
        return 10


def _normalize_dlq_status_filter(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = status.strip().lower()
    if normalized == "":
        return None
    if normalized == "open":
        return "pending"
    return normalized


def _temporal_from_request(request: Request) -> tuple[Any, Any, Any]:
    scheduler = getattr(request.app.state, "scheduler", None)
    temporal_client = getattr(scheduler, "_client", None) if scheduler is not None else None
    temporal_cfg = getattr(scheduler, "_cfg", None) if scheduler is not None else None
    manager = getattr(request.app.state, "manager", None)
    return temporal_client, temporal_cfg, manager


def _raise_dlq_http(exc: Exception) -> None:
    from services.campaign.dlq_errors import DLQError

    if isinstance(exc, DLQError):
        raise HTTPException(
            status_code=exc.http_status,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    raise exc


async def _dismiss_stale_offline_dlq(
    db,
    user_id: str,
    campaign_id: str | None,
    *,
    manager=None,
) -> int:
    from services.dlq_maintenance import dismiss_stale_offline_dlq_entries_for_user

    return await dismiss_stale_offline_dlq_entries_for_user(
        db,
        user_id=user_id,
        campaign_id=campaign_id,
        offline_after_minutes=_dlq_offline_dismiss_minutes(),
        manager=manager,
    )


async def _maybe_notify_dlq_threshold(
    request: Request,
    *,
    user_id: str,
    campaign_id: str | None,
    pending_count: int,
    threshold: int,
) -> None:
    cache = getattr(request.app.state, "dlq_alert_cache", None)
    if cache is None:
        cache = {}
        request.app.state.dlq_alert_cache = cache
    key = (user_id, campaign_id or "")
    if pending_count <= threshold:
        cache.pop(key, None)
        return
    if cache.get(key) == pending_count:
        return
    cache[key] = pending_count

    svc = getattr(request.app.state, "notification_service", None)
    if svc is None:
        return
    try:
        await svc.notify(
            "dlq.threshold",
            "DLQ threshold exceeded",
            f"DLQ has {pending_count} pending items, above threshold {threshold}.",
            {
                "campaign_id": campaign_id,
                "pending_count": pending_count,
                "threshold": threshold,
            },
            user_id=user_id,
        )
    except Exception as exc:
        log.warning("DLQ threshold notification failed: %s", exc)


@router.get(
    "/dlq",
    response_model=list[DLQEntryOut],
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_dlq(
    request: Request,
    db: DB,
    user: CurrentUser,
    status: _Optional[str] = None,
    campaign_id: _Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
):
    """List dead-letter queue entries (failed executions).

    Pass `campaign_id` to scope to a single campaign's failures.
    Empty-string query values (e.g. `?campaign_id=` or `?status=`) are
    coerced to `None` so they do not silently filter to zero rows.
    """
    from db.crud.execution_dlq import list_dlq_entries_for_user

    # Defensive coercion: FastAPI passes `?key=` as the empty string, not None.
    # Without this, an accidentally-empty filter would WHERE column='' → []
    # instead of falling back to the unfiltered view.
    norm_status = _normalize_dlq_status_filter(status)
    norm_campaign = campaign_id.strip() if campaign_id else None
    if norm_campaign == "":
        norm_campaign = None

    if norm_status in (None, "pending"):
        dismissed = await _dismiss_stale_offline_dlq(
            db,
            user.id,
            norm_campaign,
            manager=getattr(request.app.state, "manager", None),
        )
        if dismissed:
            await db.commit()

    entries = await list_dlq_entries_for_user(
        db,
        **_dlq_scope_kwargs(user),
        status=norm_status,
        campaign_id=norm_campaign,
        offset=max(offset, 0),
        limit=min(max(limit, 1), 200),
    )
    return await _dlq_entries_to_out(db, entries)


@router.get(
    "/dlq/summary",
    response_model=DLQSummaryOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def dlq_summary(
    request: Request,
    db: DB,
    user: CurrentUser,
    campaign_id: _Optional[str] = None,
):
    """Return DLQ counters for operator alerting."""
    from db.crud.execution_dlq import count_dlq_entries_for_user

    norm_campaign = campaign_id.strip() if campaign_id else None
    if norm_campaign == "":
        norm_campaign = None

    dismissed = await _dismiss_stale_offline_dlq(
        db,
        user.id,
        norm_campaign,
        manager=getattr(request.app.state, "manager", None),
    )
    if dismissed:
        await db.commit()

    pending_count = await count_dlq_entries_for_user(
        db,
        **_dlq_scope_kwargs(user),
        status="pending",
        campaign_id=norm_campaign,
    )
    threshold = _dlq_alert_threshold()
    await _maybe_notify_dlq_threshold(
        request,
        user_id=user.id,
        campaign_id=norm_campaign,
        pending_count=pending_count,
        threshold=threshold,
    )
    return DLQSummaryOut(
        pending_count=pending_count,
        alert_threshold=threshold,
        alert=pending_count > threshold,
        dismissed_offline_count=dismissed,
        offline_dismiss_minutes=_dlq_offline_dismiss_minutes(),
    )


@router.get(
    "/dlq/executions/{execution_id}",
    response_model=DLQEntryOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_dlq_by_execution(execution_id: str, db: DB, user: CurrentUser):
    """Return DLQ detail for a failed execution (DF-T-04-012)."""
    from services.campaign.dlq_errors import DLQNotFoundError
    from services.campaign.dlq_service import get_dlq_detail_for_user

    try:
        entry = await get_dlq_detail_for_user(
            db,
            execution_id=execution_id,
            user_id=_dlq_scope_kwargs(user).get("user_id"),
            org_id=_dlq_scope_kwargs(user).get("org_id"),
        )
    except DLQNotFoundError as exc:
        _raise_dlq_http(exc)
    return await _dlq_entry_to_out(db, entry)


@router.post(
    "/dlq/bulk-retry",
    response_model=DLQBulkRetryOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def bulk_retry_dlq(body: DLQBulkRetryBody, request: Request, db: DB, user: CurrentUser):
    """Bulk replay DLQ entries (max 50 per request)."""
    from services.campaign.dlq_service import bulk_replay_dlq

    ids = body.dlq_ids or body.execution_ids
    if not ids:
        raise HTTPException(status_code=400, detail={"code": "DLQ_BULK_EMPTY", "message": "No ids provided"})

    temporal_client, temporal_cfg, manager = _temporal_from_request(request)
    scope = _dlq_scope_kwargs(user)
    results = await bulk_replay_dlq(
        db,
        dlq_ids=body.dlq_ids or None,
        execution_ids=body.execution_ids or None,
        user_id=scope.get("user_id"),
        org_id=scope.get("org_id"),
        actor_user_id=user.id,
        from_checkpoint=body.from_checkpoint,
        temporal_client=temporal_client,
        temporal_config=temporal_cfg,
        manager=manager,
        offline_after_minutes=_dlq_offline_dismiss_minutes(),
    )
    await db.commit()
    return DLQBulkRetryOut(results=[DLQBulkRetryItemOut.model_validate(r) for r in results])


@router.post(
    "/dlq/{dlq_id}/retry",
    response_model=DLQEntryOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def retry_dlq(
    dlq_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    body: DLQRetryBody | None = None,
):
    """Replay a DLQ entry (Epic 04 checkpoint replay or legacy re-enqueue)."""
    from api.execution_access import get_execution_for_user
    from db.crud.execution_dlq import get_dlq_entry_for_user
    from services.campaign.dlq_errors import DLQError
    from services.campaign.dlq_service import (
        legacy_retry_dlq_entry,
        replay_dlq_entry,
        uses_epic04_replay,
    )

    body = body or DLQRetryBody()
    scope = _dlq_scope_kwargs(user)
    temporal_client, temporal_cfg, manager = _temporal_from_request(request)

    entry = await get_dlq_entry_for_user(db, dlq_id, **scope)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "DLQ_NOT_FOUND", "message": "DLQ entry not found"})

    try:
        execution = await get_execution_for_user(db, entry.execution_id, user)
    except HTTPException:
        raise HTTPException(
            status_code=404,
            detail={"code": "DLQ_NOT_FOUND", "message": "Execution not found"},
        ) from None

    try:
        if uses_epic04_replay(execution):
            entry, _, _ = await replay_dlq_entry(
                db,
                dlq_id=dlq_id,
                user_id=scope.get("user_id"),
                org_id=scope.get("org_id"),
                actor_user_id=user.id,
                from_checkpoint=body.from_checkpoint,
                temporal_client=temporal_client,
                temporal_config=temporal_cfg,
                manager=manager,
            )
        else:
            entry = await legacy_retry_dlq_entry(
                db,
                dlq_id=dlq_id,
                user_id=scope.get("user_id"),
                org_id=scope.get("org_id"),
                temporal_client=temporal_client,
                temporal_config=temporal_cfg,
                manager=manager,
                offline_after_minutes=_dlq_offline_dismiss_minutes(),
            )
    except DLQError as exc:
        await db.commit()
        _raise_dlq_http(exc)

    await db.commit()
    return await _dlq_entry_to_out(db, entry)


@router.post(
    "/dlq/{dlq_id}/close",
    response_model=DLQEntryOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def close_dlq(dlq_id: str, body: DLQCloseBody, db: DB, user: CurrentUser):
    """Close a DLQ entry without replaying (DF-T-04-012)."""
    from services.campaign.dlq_errors import DLQError
    from services.campaign.dlq_service import close_dlq_entry

    scope = _dlq_scope_kwargs(user)
    try:
        entry = await close_dlq_entry(
            db,
            dlq_id=dlq_id,
            user_id=scope.get("user_id"),
            org_id=scope.get("org_id"),
            closed_by=user.id,
            close_reason=body.reason,
        )
    except DLQError as exc:
        _raise_dlq_http(exc)
    await db.commit()
    return await _dlq_entry_to_out(db, entry)


@router.delete(
    "/dlq/{dlq_id}",
    status_code=204,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def dismiss_dlq(dlq_id: str, db: DB, user: CurrentUser):
    """Dismiss a DLQ entry without retrying."""
    from db.crud.execution_dlq import dismiss_dlq_entry_for_user
    ok = await dismiss_dlq_entry_for_user(db, dlq_id, **_dlq_scope_kwargs(user))
    if not ok:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    await db.commit()


# ── Execution CRUD ────────────────────────────────────────────────────────────


@router.get(
    "/{execution_id}/task-log",
    response_model=ExecutionTaskLogOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_execution_task_log(
    execution_id: str,
    db: DB,
    user: CurrentUser,
    since: _Optional[str] = None,
    event_limit: int = 200,
    step_limit: int = 500,
):
    """Unified trace for one execution: phone, account, steps, events, DLQ."""
    await _get_or_404(db, execution_id, user)
    from services.execution_trace import build_execution_task_log

    norm_since = since.strip() if since else None
    if norm_since == "":
        norm_since = None
    trace = await build_execution_task_log(
        db,
        execution_id,
        since_event_id=norm_since,
        event_limit=event_limit,
        step_limit=step_limit,
    )
    return ExecutionTaskLogOut.model_validate(trace)


@router.get(
    "/{execution_id}/run-trace",
    response_model=ExecutionTaskLogOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_execution_run_trace(
    execution_id: str,
    db: DB,
    user: CurrentUser,
    since: _Optional[str] = None,
    event_limit: int = 200,
    step_limit: int = 500,
):
    """Alias for task-log while the frontend migrates naming."""
    return await get_execution_task_log(
        execution_id,
        db,
        user,
        since=since,
        event_limit=event_limit,
        step_limit=step_limit,
    )


@router.get(
    "/{execution_id}",
    response_model=ExecutionOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_execution_endpoint(execution_id: str, db: DB, user: CurrentUser):
    ex = await _get_or_404(db, execution_id, user)
    return ExecutionOut.model_validate(ex)


def _event_out_from_row(row) -> ExecutionEventOut:
    envelope = row.to_envelope()
    return ExecutionEventOut.model_validate(envelope)


@router.get(
    "/{execution_id}/events",
    response_model=ExecutionEventListOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_execution_events(
    execution_id: str,
    db: DB,
    user: CurrentUser,
    since: _Optional[str] = None,
    limit: int = 100,
):
    """Catch-up endpoint — events after ``since`` event_id (exclusive), ordered."""
    await _get_or_404(db, execution_id, user)
    from db.crud.execution_events import list_execution_events

    norm_since = since.strip() if since else None
    if norm_since == "":
        norm_since = None
    page_limit = min(max(limit, 1), 500)
    rows = await list_execution_events(
        db,
        execution_id,
        since_event_id=norm_since,
        limit=page_limit + 1,
    )
    has_more = len(rows) > page_limit
    items = [_event_out_from_row(r) for r in rows[:page_limit]]
    return ExecutionEventListOut(items=items, has_more=has_more)


@router.get("/{execution_id}/events/stream")
async def stream_execution_events(
    execution_id: str,
    request: Request,
    user: StreamingUser,
    _perm: None = Depends(require_streaming_permission("executions", "read")),
):
    """SSE live stream with ``Last-Event-ID`` resume support (DF-T-04-013)."""
    import asyncio
    import contextlib
    import json

    from api.deps_streaming import load_execution_access
    from db.crud.execution_events import list_execution_events
    from db.database import AsyncSessionLocal
    from services.execution.event_bus import _SENTINEL, get_execution_event_bus

    await load_execution_access(user, execution_id)

    last_event_id = request.headers.get("last-event-id") or request.headers.get("Last-Event-ID")
    if last_event_id == "":
        last_event_id = None

    def _sse_frame(envelope: dict) -> str:
        return (
            f"id: {envelope['event_id']}\n"
            f"event: {envelope['event_type']}\n"
            f"data: {json.dumps(envelope)}\n\n"
        )

    backlog_frames: list[str] = []
    async with AsyncSessionLocal() as db:
        try:
            rows = await list_execution_events(
                db,
                execution_id,
                since_event_id=last_event_id,
                limit=500,
            )
            backlog_frames = [_sse_frame(row.to_envelope()) for row in rows]
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def event_generator():
        import time

        from api.streaming_utils import (
            client_disconnect_scope,
            client_gone,
            stream_expired,
        )

        started = time.monotonic()
        async with client_disconnect_scope(request) as disconnected:
            for frame in backlog_frames:
                if client_gone(disconnected) or stream_expired(started):
                    return
                yield frame

            local_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
            bus = get_execution_event_bus()

            async def pump(bus_queue: asyncio.Queue) -> None:
                try:
                    while True:
                        item = await bus_queue.get()
                        if item is _SENTINEL:
                            break
                        await local_queue.put(item)
                except asyncio.CancelledError:
                    raise

            async with bus.subscription(execution_id) as bus_queue:
                pump_task = asyncio.create_task(pump(bus_queue))
                try:
                    while True:
                        if client_gone(disconnected) or stream_expired(started):
                            break
                        get_task = asyncio.create_task(local_queue.get())
                        try:
                            done, _pending = await asyncio.wait({get_task}, timeout=2.0)
                        except Exception:
                            get_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await get_task
                            raise
                        if not done:
                            get_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await get_task
                            if client_gone(disconnected) or stream_expired(started):
                                break
                            yield ": keepalive\n\n"
                            continue
                        envelope = get_task.result()
                        yield _sse_frame(envelope)
                finally:
                    pump_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pump_task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{execution_id}/stats",
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_execution_stats_endpoint(execution_id: str, db: DB, user: CurrentUser):
    """Phase 5 — crawl stats for an execution: content count, LLM fallbacks,
    dedup skipped (from Execution.meta), latest checkpoint, run time per device.
    """
    from db.crud.content import count_by_execution
    from db.crud.execution import list_execution_results

    ex = await _get_or_404(db, execution_id, user)
    content_count = await count_by_execution(
        db, execution_id, user_id=data_owner_user_id(user)
    )
    results = await list_execution_results(db, execution_id)

    total_run_sec = 0.0
    passed = 0
    failed = 0
    for r in results:
        if r.run_time_sec:
            total_run_sec += float(r.run_time_sec)
        passed += len(r.passed_steps or [])
        failed += len(r.failed_steps or [])

    meta = ex.meta or {}
    return {
        "execution_id": execution_id,
        "status": ex.status,
        "checkpoint_step": ex.checkpoint_step,
        "started_at": ex.started_at.isoformat() if ex.started_at else None,
        "finished_at": ex.finished_at.isoformat() if ex.finished_at else None,
        "steps": {"passed": passed, "failed": failed},
        "devices": len(results),
        "run_time_sec": round(total_run_sec, 2),
        "content": {
            "extracted": content_count,
            "deduped_skipped": int(meta.get("deduped_count", 0)),
        },
        "llm_fallbacks": int(meta.get("llm_fallbacks", 0)),
        "llm_cost_usd": float(meta.get("llm_cost_usd", 0.0)),
    }


@router.patch(
    "/{execution_id}",
    response_model=ExecutionOut,
    dependencies=[Depends(require_permission("executions", "update"))],
)
async def patch_execution_endpoint(
    execution_id: str, body: ExecutionPatch, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user)
    patch = body.model_dump(exclude_none=True)
    ex = await update_execution(db, execution_id, **patch)
    return ExecutionOut.model_validate(ex)


@router.delete(
    "/{execution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("executions", "delete"))],
)
async def delete_execution_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user)
    await delete_execution(db, execution_id)


@router.post(
    "/{execution_id}/start",
    response_model=ExecutionOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def start_endpoint(execution_id: str, db: DB, user: CurrentUser):
    ex = await _get_or_404(db, execution_id, user)
    ex = await start_execution(db, execution_id)
    from services.execution.event_publisher import enqueue_execution_event
    from services.execution.event_types import EXECUTION_STARTED

    if ex:
        await enqueue_execution_event(
            db,
            event_type=EXECUTION_STARTED,
            execution_id=execution_id,
            payload={"status": ex.status},
            execution=ex,
        )
    return ExecutionOut.model_validate(ex)


@router.post(
    "/{execution_id}/finish",
    response_model=ExecutionOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def finish_endpoint(execution_id: str, body: FinishBody, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user)
    ex = await finish_execution(db, execution_id, status=body.status)
    from services.execution.event_publisher import enqueue_execution_event
    from services.execution.event_types import (
        EXECUTION_CANCELLED,
        EXECUTION_COMPLETED,
        EXECUTION_FAILED,
    )

    if ex:
        status = ex.status
        if status == "cancelled":
            event_type = EXECUTION_CANCELLED
        elif status == "completed":
            event_type = EXECUTION_COMPLETED
        else:
            event_type = EXECUTION_FAILED
        await enqueue_execution_event(
            db,
            event_type=event_type,
            execution_id=execution_id,
            payload={"status": status},
            execution=ex,
        )
    return ExecutionOut.model_validate(ex)


async def _temporal_client_from_request(request: Request):
    config = getattr(request.app.state, "config", None)
    if config is None or not getattr(config, "temporal", None) or not config.temporal.enabled:
        return None
    from temporal.worker import get_temporal_client

    return await get_temporal_client(config.temporal)


def _control_error(exc: Exception) -> HTTPException:
    from services.execution_control import ExecutionControlError

    if isinstance(exc, ExecutionControlError):
        return HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )
    raise exc


@router.post(
    "/{execution_id}/pause",
    response_model=ExecutionControlOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def pause_execution_endpoint(
    execution_id: str, request: Request, db: DB, user: CurrentUser,
):
    await _get_or_404(db, execution_id, user)
    from services.execution_control import pause_execution

    try:
        client = await _temporal_client_from_request(request)
        result = await pause_execution(
            db, execution_id, user_id=user.id, temporal_client=client,
        )
        await db.commit()
        return ExecutionControlOut(
            execution_id=result.execution_id,
            status=result.status,
            action=result.action,
            effective_transition=result.effective_transition,
            workflows_signalled=result.workflows_signalled,
        )
    except Exception as exc:
        raise _control_error(exc) from exc


@router.post(
    "/{execution_id}/resume",
    response_model=ExecutionControlOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def resume_execution_endpoint(
    execution_id: str, request: Request, db: DB, user: CurrentUser,
):
    await _get_or_404(db, execution_id, user)
    from services.execution_control import resume_execution

    try:
        client = await _temporal_client_from_request(request)
        result = await resume_execution(
            db, execution_id, user_id=user.id, temporal_client=client,
        )
        await db.commit()
        return ExecutionControlOut(
            execution_id=result.execution_id,
            status=result.status,
            action=result.action,
            effective_transition=result.effective_transition,
            workflows_signalled=result.workflows_signalled,
        )
    except Exception as exc:
        raise _control_error(exc) from exc


@router.post(
    "/{execution_id}/cancel",
    response_model=ExecutionControlOut,
    dependencies=[Depends(require_permission("executions", "execute"))],
)
async def cancel_endpoint(
    execution_id: str,
    request: Request,
    db: DB,
    user: CurrentUser,
    body: ExecutionCancelBody | None = None,
):
    await _get_or_404(db, execution_id, user)
    from services.execution_control import cancel_execution

    reason = (body.reason if body else "") or None
    session_store = getattr(request.app.state, "session_store", None)
    try:
        client = await _temporal_client_from_request(request)
        result = await cancel_execution(
            db,
            execution_id,
            user_id=user.id,
            reason=reason,
            temporal_client=client,
            session_store=session_store,
        )
        await db.commit()
        return ExecutionControlOut(
            execution_id=result.execution_id,
            status=result.status,
            action=result.action,
            effective_transition=result.effective_transition,
            workflows_signalled=result.workflows_signalled,
            warning=result.warning,
        )
    except Exception as exc:
        raise _control_error(exc) from exc


# ── Device management ─────────────────────────────────────────────────────────


@router.get(
    "/{execution_id}/devices",
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_devices_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user)
    devices = await list_execution_devices(db, execution_id)
    return [{"id": d.id, "serial": d.serial, "name": d.name} for d in devices]


@router.post(
    "/{execution_id}/devices",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("executions", "update"))],
)
async def add_device_endpoint(
    execution_id: str, body: AddDeviceBody, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user)
    from db import crud as repo

    user_org = getattr(user, "org_id", None) or await repo.get_user_org_id(db, user.id)
    device = await get_device(db, body.device_id)
    if device is None or (user_org and device.org_id != user_org):
        raise HTTPException(status_code=404, detail="Device not found")

    link = await add_device_to_execution(db, execution_id, body.device_id)
    return {"execution_id": link.execution_id, "device_id": link.device_id}


@router.delete(
    "/{execution_id}/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("executions", "update"))],
)
async def remove_device_endpoint(
    execution_id: str, device_id: str, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user)
    await remove_device_from_execution(db, execution_id, device_id)


# ── Result management ─────────────────────────────────────────────────────────


@router.get(
    "/{execution_id}/results",
    response_model=list[ExecutionResultOut],
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_results_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user)
    results = await list_execution_results(db, execution_id)
    return [ExecutionResultOut.model_validate(r) for r in results]


@router.get(
    "/{execution_id}/results/{device_id}",
    response_model=ExecutionResultOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def get_result_endpoint(execution_id: str, device_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user)
    er = await get_execution_result(db, execution_id, device_id)
    if er is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return ExecutionResultOut.model_validate(er)


@router.put(
    "/{execution_id}/results/{device_id}",
    response_model=ExecutionResultOut,
    dependencies=[Depends(require_permission("executions", "update"))],
)
async def upsert_result_endpoint(
    execution_id: str, device_id: str, body: UpsertResultBody, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user)
    from services.execution.step_store import slim_step_results

    er = await upsert_execution_result(
        db,
        execution_id=execution_id,
        device_id=device_id,
        status=body.status,
        passed_steps=slim_step_results(body.passed_steps),
        failed_steps=slim_step_results(body.failed_steps),
        error_detail=body.error_detail,
        run_time_sec=body.run_time_sec,
        started_at=body.started_at,
        finished_at=body.finished_at,
    )
    return ExecutionResultOut.model_validate(er)


@router.get(
    "/{execution_id}/steps",
    response_model=list[ExecutionStepOut],
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_execution_steps_endpoint(execution_id: str, db: DB, user: CurrentUser):
    """Normalized per-step rows including artifacts_json (DF-T-04-010)."""
    await _get_or_404(db, execution_id, user)
    from db.crud.execution_steps import list_execution_steps

    rows = await list_execution_steps(db, execution_id)
    return [ExecutionStepOut.model_validate(row) for row in rows]


@router.get(
    "/{execution_id}/summary",
    response_model=SummaryOut,
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def summary_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user)
    data = await execution_summary(db, execution_id)
    return SummaryOut(**data)


def _normalize_artifact_url(url: str | None) -> str | None:
    if not url:
        return None
    value = str(url).strip()
    if not value:
        return None
    if value.startswith(("http://", "https://", "/")):
        return value
    if "/captures/" in value:
        return value[value.index("/captures/") :]
    if value.startswith("captures/"):
        return f"/{value}"
    if "/screenshots/" in value:
        return value[value.index("/screenshots/") :]
    if value.startswith("screenshots/"):
        return f"/{value}"
    return value


def _artifact_proxy_url(artifact_id: str | None) -> str | None:
    aid = str(artifact_id or "").strip()
    if not aid:
        return None
    return f"/artifacts/{aid}/content"


_ARTIFACT_REF_FIELDS = (
    ("screenshot_url", "screenshot", "screenshot_artifact_id", "image/jpeg"),
    ("hierarchy_url", "hierarchy", "hierarchy_artifact_id", "application/xml"),
    ("selector_url", "selector", None, "application/xml"),
    ("element_url", "element", None, "image/jpeg"),
)


def _artifact_message_for_step(
    step: dict[str, Any],
    step_index: Any,
    step_type: Any,
) -> str | None:
    current_index = step.get("index")
    current_type = step.get("type")
    points_to_current = (
        step_index is None
        or step_index == current_index
    ) and (
        not step_type
        or step_type == current_type
    )
    if points_to_current:
        message = step.get("message")
        return str(message) if message is not None else None

    for nested in _nested_step_results_for_artifacts(step):
        if not isinstance(nested, dict):
            continue
        nested_index = nested.get("index")
        nested_type = nested.get("type")
        if step_index is not None and nested_index != step_index:
            continue
        if step_type and nested_type != step_type:
            continue
        message = nested.get("message")
        return str(message) if message is not None else None
    return None


def _extract_step_artifacts(execution_id: str, device_serial: str, steps: list, created_at: _datetime) -> list[ExecutionArtifactOut]:
    out: list[ExecutionArtifactOut] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        screenshots: list[tuple[str, str | None, dict[str, Any]]] = []
        if isinstance(step.get("screenshot"), str):
            screenshots.append(("screenshot", _normalize_artifact_url(step.get("screenshot")), {}))
        elif isinstance(step.get("screenshot"), dict):
            for key in ("full", "hierarchy", "selector"):
                if step["screenshot"].get(key):
                    screenshots.append(
                        (
                            f"screenshot.{key}",
                            _normalize_artifact_url(step["screenshot"].get(key)),
                            {},
                        )
                    )
        if isinstance(step.get("screenshot_pre"), dict):
            for key in ("full", "hierarchy", "selector"):
                if step["screenshot_pre"].get(key):
                    screenshots.append(
                        (
                            f"screenshot_pre.{key}",
                            _normalize_artifact_url(step["screenshot_pre"].get(key)),
                            {},
                        )
                    )

        for art in step.get("artifacts") or step.get("artifacts_json") or []:
            if not isinstance(art, dict):
                continue
            art_type = str(art.get("type") or "artifact")
            for url_key, label, id_key, content_type in _ARTIFACT_REF_FIELDS:
                artifact_id = str(art.get(id_key) or "").strip() if id_key else ""
                url = art.get(url_key)
                proxy_url = _artifact_proxy_url(artifact_id) if artifact_id else None
                resolved_url = proxy_url or _normalize_artifact_url(url)
                if not resolved_url:
                    continue
                metadata: dict[str, Any] = {"content_type": content_type}
                if artifact_id:
                    metadata["artifact_id"] = artifact_id
                for meta_key in (
                    "step_id",
                    "step_type",
                    "step_index",
                    "attempt_index",
                    "captured_at",
                    "device_state_summary",
                ):
                    if art.get(meta_key) is not None:
                        metadata[meta_key] = art.get(meta_key)
                screenshots.append((f"{art_type}.{label}", resolved_url, metadata))

        for art_type, url, metadata in screenshots:
            if not url:
                continue
            step_index = metadata.get("step_index", step.get("index"))
            step_type = metadata.get("step_type") or step.get("type")
            message = _artifact_message_for_step(step, step_index, step_type)
            out.append(
                ExecutionArtifactOut(
                    artifact_type=art_type,
                    execution_id=execution_id,
                    device_serial=device_serial,
                    step_index=step_index,
                    step_type=step_type,
                    ok=step.get("ok"),
                    message=message,
                    url=url,
                    metadata=metadata,
                    created_at=created_at,
                )
            )
        out.extend(
            _extract_step_artifacts(
                execution_id,
                device_serial,
                _nested_step_results_for_artifacts(step),
                created_at,
            )
        )
    return out


def _nested_step_results_for_artifacts(step: dict[str, Any]) -> list[dict[str, Any]]:
    nested: list[dict[str, Any]] = []

    sub_result = step.get("sub_result")
    if isinstance(sub_result, dict):
        nested.extend(
            item
            for item in (sub_result.get("step_results") or [])
            if isinstance(item, dict)
        )

    for entry in step.get("sub_results") or []:
        if not isinstance(entry, dict):
            continue
        result = entry.get("result")
        if isinstance(result, dict):
            nested.extend(
                item
                for item in (result.get("step_results") or [])
                if isinstance(item, dict)
            )
        elif isinstance(entry.get("step_results"), list):
            nested.extend(
                item for item in entry["step_results"] if isinstance(item, dict)
            )

    return nested


def _merge_step_artifact_context(
    persisted_steps: list[dict[str, Any]],
    result_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_index = {
        int(step.get("index")): step
        for step in result_steps
        if isinstance(step, dict) and isinstance(step.get("index"), int)
    }
    merged: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()

    for step in persisted_steps:
        out = dict(step)
        idx = step.get("index")
        if isinstance(idx, int):
            seen_indexes.add(idx)
            richer = by_index.get(idx)
            if richer:
                for key in ("sub_result", "sub_results"):
                    if key in richer and key not in out:
                        out[key] = richer[key]
                if not out.get("artifacts_json") and richer.get("artifacts_json"):
                    out["artifacts_json"] = richer["artifacts_json"]
                    out["artifacts"] = richer["artifacts_json"]
        merged.append(out)

    for step in result_steps:
        idx = step.get("index") if isinstance(step, dict) else None
        if isinstance(idx, int) and idx in seen_indexes:
            continue
        if isinstance(step, dict):
            merged.append(step)

    return merged


async def _legacy_step_dicts_for_artifacts(db, execution_id: str) -> list[dict[str, Any]]:
    from db.crud.execution import list_execution_results
    from db.crud.execution_steps import list_execution_steps
    from services.execution.step_store import execution_step_to_legacy_dict

    rows = await list_execution_steps(db, execution_id)
    results = await list_execution_results(db, execution_id)

    legacy: list[dict[str, Any]] = []
    for er in results:
        legacy.extend((er.passed_steps or []) + (er.failed_steps or []))
    if not rows:
        return legacy

    persisted = [execution_step_to_legacy_dict(row) for row in rows]
    return _merge_step_artifact_context(persisted, legacy)


@router.get(
    "/{execution_id}/artifacts",
    response_model=list[ExecutionArtifactOut],
    dependencies=[Depends(require_permission("executions", "read"))],
)
async def list_execution_artifacts(
    execution_id: str,
    db: DB,
    user: CurrentUser,
    content_offset: int = 0,
    content_limit: int = 200,
):
    """List execution artifacts from result step screenshots + saved content screenshots."""
    from db.crud.content import query_content
    from db.crud.device import get_device

    await _get_or_404(db, execution_id, user)
    artifacts: list[ExecutionArtifactOut] = []

    results = await list_execution_results(db, execution_id)
    step_dicts = await _legacy_step_dicts_for_artifacts(db, execution_id)
    step_by_index = {int(s.get("index", -1)): s for s in step_dicts if isinstance(s, dict)}

    for er in results:
        device = await get_device(db, er.device_id)
        serial = device.serial if device else None
        if step_by_index:
            steps_for_device = [
                step_by_index[idx]
                for idx in sorted(step_by_index)
                if idx >= 0
            ]
        else:
            steps_for_device = (er.passed_steps or []) + (er.failed_steps or [])
        artifacts.extend(
            _extract_step_artifacts(
                execution_id,
                serial or "unknown",
                steps_for_device,
                er.created_at,
            )
        )

    content_items, _ = await query_content(
        db,
        execution_id=execution_id,
        limit=min(content_limit, 500),
        offset=max(content_offset, 0),
    )
    for item in content_items:
        if item.screenshot_path:
            artifacts.append(
                ExecutionArtifactOut(
                    artifact_type="content_screenshot",
                    execution_id=execution_id,
                    device_serial=item.device_serial,
                    step_type=item.content_type,
                    url=_normalize_artifact_url(item.screenshot_path),
                    metadata={"content_id": item.id, "collection": item.collection},
                    created_at=item.extracted_at,
                )
            )

    floor = _datetime.min.replace(tzinfo=_timezone.utc)
    artifacts.sort(key=lambda x: x.created_at or floor, reverse=True)
    return artifacts


@router.post(
    "/{execution_id}/pin",
    dependencies=[Depends(require_permission("executions", "update"))],
)
async def pin_execution(execution_id: str, db: DB, user: CurrentUser):
    """Pin execution so artifacts skip retention cleanup (DF-T-06-011)."""
    from datetime import datetime, timezone

    execution = await _get_or_404(db, execution_id, user)
    execution.pinned_at = datetime.now(timezone.utc)
    execution.pinned_by = user.id
    meta = dict(execution.meta or {})
    meta["pinned_by_user"] = user.id
    execution.meta = meta
    await db.flush()
    try:
        from web.metrics import artifact_pinned_total

        artifact_pinned_total.inc()
    except Exception:
        pass
    return {"execution_id": execution_id, "pinned": True, "pinned_at": execution.pinned_at.isoformat()}


@router.delete(
    "/{execution_id}/pin",
    dependencies=[Depends(require_permission("executions", "update"))],
)
async def unpin_execution(execution_id: str, db: DB, user: CurrentUser):
    execution = await _get_or_404(db, execution_id, user)
    execution.pinned_at = None
    execution.pinned_by = None
    meta = dict(execution.meta or {})
    meta.pop("pinned_by_user", None)
    execution.meta = meta
    await db.flush()
    return {"execution_id": execution_id, "pinned": False}
