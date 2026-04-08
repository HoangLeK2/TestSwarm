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

from fastapi import APIRouter, HTTPException, status

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
    finish_execution,
    get_execution,
    get_execution_result,
    list_execution_devices,
    list_execution_results,
    list_executions,
    remove_device_from_execution,
    start_execution,
    update_execution,
    upsert_execution_result,
)

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


@router.get("/{execution_id}", response_model=ExecutionOut)
async def get_execution_endpoint(execution_id: str, db: DB, user: CurrentUser):
    ex = await _get_or_404(db, execution_id, user.id)
    return ExecutionOut.model_validate(ex)


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
