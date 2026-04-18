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
    POST   /api/executions/{id}/cancel                  Cancel execution

    GET    /api/executions/{id}/devices                 List assigned devices
    POST   /api/executions/{id}/devices                 Add device
    DELETE /api/executions/{id}/devices/{device_id}     Remove device

    GET    /api/executions/{id}/results                 List per-device results
    GET    /api/executions/{id}/results/{device_id}     Get single device result
    PUT    /api/executions/{id}/results/{device_id}     Upsert device result
    GET    /api/executions/{id}/summary                 Aggregated summary
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from api.deps import CurrentUser, DB
from api.schemas.execution import (
    AddDeviceBody,
    ExecutionCreate,
    ExecutionListOut,
    ExecutionOut,
    ExecutionPatch,
    ExecutionResultOut,
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


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_or_404(db, execution_id: str, user_id: str):
    ex = await get_execution(db, execution_id)
    if not ex or ex.user_id != user_id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ex


# ── Execution CRUD ────────────────────────────────────────────────────────────


@router.post("", response_model=ExecutionOut, status_code=status.HTTP_201_CREATED)
async def create_execution_endpoint(body: ExecutionCreate, db: DB, user: CurrentUser):
    if body.campaign_id:
        campaign = await get_campaign(db, body.campaign_id)
        if campaign is None or campaign.user_id != user.id:
            raise HTTPException(status_code=404, detail="Campaign not found")
    if body.scenario_id:
        scenario = await get_scenario(db, body.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        owner_campaign = await get_campaign(db, scenario.campaign_id)
        if owner_campaign is None or owner_campaign.user_id != user.id:
            raise HTTPException(status_code=404, detail="Scenario not found")
        if body.campaign_id and scenario.campaign_id != body.campaign_id:
            raise HTTPException(status_code=400, detail="Scenario does not belong to campaign")

    for device_id in body.device_ids:
        device = await get_device(db, device_id)
        if device is None or device.user_id != user.id:
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
    return ExecutionOut.model_validate(ex)


@router.get("", response_model=ExecutionListOut)
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
        user_id=user.id,
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

    model_config = {"from_attributes": True}


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


@router.get("/dlq", response_model=list[DLQEntryOut])
async def list_dlq(
    db: DB,
    user: CurrentUser,
    status: _Optional[str] = None,
    offset: int = 0,
    limit: int = 50,
):
    """List dead-letter queue entries (failed executions)."""
    from db.crud.execution_dlq import list_dlq_entries_for_user
    entries = await list_dlq_entries_for_user(
        db,
        user_id=user.id,
        status=status,
        offset=offset,
        limit=min(limit, 200),
    )
    return [DLQEntryOut.model_validate(e) for e in entries]


@router.post("/dlq/{dlq_id}/retry", response_model=DLQEntryOut)
async def retry_dlq(dlq_id: str, request: Request, db: DB, user: CurrentUser):
    """Re-enqueue a DLQ entry for retry with idempotent state transition."""
    from db.crud.execution_dlq import begin_dlq_retry_for_user, set_dlq_status
    from services.campaign_dispatch import enqueue_campaign_run_temporal

    entry, changed = await begin_dlq_retry_for_user(db, dlq_id, user.id)
    if entry is None:
        raise HTTPException(status_code=404, detail="DLQ entry not found")

    execution = await get_execution(db, entry.execution_id)
    if execution is None or execution.user_id != user.id:
        raise HTTPException(status_code=404, detail="Execution not found")
    if not execution.campaign_id:
        await set_dlq_status(
            db,
            dlq_id,
            "pending",
            error="DLQ retry only supports campaign-linked executions",
        )
        await db.commit()
        raise HTTPException(status_code=400, detail="Execution is not linked to a campaign")

    # Idempotency: retry already in progress/scheduled.
    if not changed:
        await db.commit()
        return DLQEntryOut.model_validate(entry)

    scheduler = getattr(request.app.state, "scheduler", None)
    temporal_client = getattr(scheduler, "_client", None) if scheduler is not None else None
    temporal_cfg = getattr(scheduler, "_cfg", None) if scheduler is not None else None
    if temporal_client is None:
        await set_dlq_status(db, dlq_id, "pending", error="Temporal client unavailable for retry")
        await db.commit()
        raise HTTPException(status_code=503, detail="Temporal is unavailable")

    try:
        payload, status_code = await enqueue_campaign_run_temporal(
            execution.campaign_id,
            temporal_client,
            temporal_cfg,
            device_serials_override=[entry.device_serial],
        )
        if status_code >= 400:
            error_msg = payload.get("error", "retry enqueue failed")
            await set_dlq_status(db, dlq_id, "pending", error=error_msg)
            await db.commit()
            raise HTTPException(status_code=status_code, detail=error_msg)

        await set_dlq_status(db, dlq_id, "resolved")
        await db.commit()
        return DLQEntryOut.model_validate(entry)
    except HTTPException:
        raise
    except Exception as exc:
        await set_dlq_status(db, dlq_id, "pending", error=str(exc))
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Retry enqueue failed: {exc}")


@router.delete("/dlq/{dlq_id}", status_code=204)
async def dismiss_dlq(dlq_id: str, db: DB, user: CurrentUser):
    """Dismiss a DLQ entry without retrying."""
    from db.crud.execution_dlq import dismiss_dlq_entry_for_user
    ok = await dismiss_dlq_entry_for_user(db, dlq_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="DLQ entry not found")
    await db.commit()


# ── Execution CRUD ────────────────────────────────────────────────────────────


@router.get("/{execution_id}", response_model=ExecutionOut)
async def get_execution_endpoint(execution_id: str, db: DB, user: CurrentUser):
    ex = await _get_or_404(db, execution_id, user.id)
    return ExecutionOut.model_validate(ex)


@router.get("/{execution_id}/stats")
async def get_execution_stats_endpoint(execution_id: str, db: DB, user: CurrentUser):
    """Phase 5 — crawl stats for an execution: content count, LLM fallbacks,
    dedup skipped (from Execution.meta), latest checkpoint, run time per device.
    """
    from db.crud.content import count_by_execution
    from db.crud.execution import list_execution_results

    ex = await _get_or_404(db, execution_id, user.id)
    content_count = await count_by_execution(db, execution_id, user_id=user.id)
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


@router.patch("/{execution_id}", response_model=ExecutionOut)
async def patch_execution_endpoint(
    execution_id: str, body: ExecutionPatch, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user.id)
    patch = body.model_dump(exclude_none=True)
    ex = await update_execution(db, execution_id, **patch)
    return ExecutionOut.model_validate(ex)


@router.delete("/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    await delete_execution(db, execution_id)


@router.post("/{execution_id}/start", response_model=ExecutionOut)
async def start_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    ex = await start_execution(db, execution_id)
    return ExecutionOut.model_validate(ex)


@router.post("/{execution_id}/finish", response_model=ExecutionOut)
async def finish_endpoint(execution_id: str, body: FinishBody, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    ex = await finish_execution(db, execution_id, status=body.status)
    return ExecutionOut.model_validate(ex)


@router.post("/{execution_id}/cancel", response_model=ExecutionOut)
async def cancel_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    ex = await finish_execution(db, execution_id, status="cancelled")
    return ExecutionOut.model_validate(ex)


# ── Device management ─────────────────────────────────────────────────────────


@router.get("/{execution_id}/devices")
async def list_devices_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    devices = await list_execution_devices(db, execution_id)
    return [{"id": d.id, "serial": d.serial, "name": d.name} for d in devices]


@router.post("/{execution_id}/devices", status_code=status.HTTP_201_CREATED)
async def add_device_endpoint(
    execution_id: str, body: AddDeviceBody, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user.id)
    device = await get_device(db, body.device_id)
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")

    link = await add_device_to_execution(db, execution_id, body.device_id)
    return {"execution_id": link.execution_id, "device_id": link.device_id}


@router.delete("/{execution_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_device_endpoint(
    execution_id: str, device_id: str, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user.id)
    await remove_device_from_execution(db, execution_id, device_id)


# ── Result management ─────────────────────────────────────────────────────────


@router.get("/{execution_id}/results", response_model=list[ExecutionResultOut])
async def list_results_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    results = await list_execution_results(db, execution_id)
    return [ExecutionResultOut.model_validate(r) for r in results]


@router.get("/{execution_id}/results/{device_id}", response_model=ExecutionResultOut)
async def get_result_endpoint(execution_id: str, device_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
    er = await get_execution_result(db, execution_id, device_id)
    if er is None:
        raise HTTPException(status_code=404, detail="Result not found")
    return ExecutionResultOut.model_validate(er)


@router.put("/{execution_id}/results/{device_id}", response_model=ExecutionResultOut)
async def upsert_result_endpoint(
    execution_id: str, device_id: str, body: UpsertResultBody, db: DB, user: CurrentUser
):
    await _get_or_404(db, execution_id, user.id)
    er = await upsert_execution_result(
        db,
        execution_id=execution_id,
        device_id=device_id,
        status=body.status,
        passed_steps=body.passed_steps,
        failed_steps=body.failed_steps,
        error_detail=body.error_detail,
        run_time_sec=body.run_time_sec,
        started_at=body.started_at,
        finished_at=body.finished_at,
    )
    return ExecutionResultOut.model_validate(er)


@router.get("/{execution_id}/summary", response_model=SummaryOut)
async def summary_endpoint(execution_id: str, db: DB, user: CurrentUser):
    await _get_or_404(db, execution_id, user.id)
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


def _extract_step_artifacts(execution_id: str, device_serial: str, steps: list, created_at: _datetime) -> list[ExecutionArtifactOut]:
    out: list[ExecutionArtifactOut] = []
    for step in steps or []:
        screenshots = []
        if isinstance(step.get("screenshot"), str):
            screenshots.append(("screenshot", step.get("screenshot")))
        elif isinstance(step.get("screenshot"), dict):
            for key in ("full", "element", "hierarchy", "selector"):
                if step["screenshot"].get(key):
                    screenshots.append((f"screenshot.{key}", step["screenshot"].get(key)))
        if isinstance(step.get("screenshot_pre"), dict):
            for key in ("full", "element", "hierarchy", "selector"):
                if step["screenshot_pre"].get(key):
                    screenshots.append((f"screenshot_pre.{key}", step["screenshot_pre"].get(key)))

        for art_type, url in screenshots:
            resolved_url = _normalize_artifact_url(url)
            out.append(
                ExecutionArtifactOut(
                    artifact_type=art_type,
                    execution_id=execution_id,
                    device_serial=device_serial,
                    step_index=step.get("index"),
                    step_type=step.get("type"),
                    ok=step.get("ok"),
                    message=step.get("message"),
                    url=resolved_url,
                    metadata={},
                    created_at=created_at,
                )
            )
    return out


@router.get("/{execution_id}/artifacts", response_model=list[ExecutionArtifactOut])
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

    await _get_or_404(db, execution_id, user.id)
    artifacts: list[ExecutionArtifactOut] = []

    results = await list_execution_results(db, execution_id)
    for er in results:
        device = await get_device(db, er.device_id)
        serial = device.serial if device else None
        artifacts.extend(
            _extract_step_artifacts(
                execution_id,
                serial or "unknown",
                (er.passed_steps or []) + (er.failed_steps or []),
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
