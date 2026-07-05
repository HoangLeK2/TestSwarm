"""Campaign run via Temporal workflows + fleet-wide scenario dispatch."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import Config
from api.deps import CurrentUser, DB, require_permission
from api.org_scope import campaign_visible_to_user, device_visible_to_user
from db import crud as repo
from runtime.core import DeviceManager, TaskQueue
from services.campaign_dispatch import enqueue_campaign_run_temporal
from temporal.worker import get_temporal_client


class CampaignRunBody(BaseModel):
   
    filter_state: str = "READY"          # e.g. READY, BUSY
    filter_model: str | None = None      # substring match on device.model
    filter_tags: str | None = None       # comma-separated, AND logic
    max_devices: int | None = None       # cap number of devices

log = logging.getLogger(__name__)

# Compiled once at import time — matches top-level ScenarioWorkflow IDs.
# Campaign runs use one sequence workflow per device:
#   campaign:<id>:device:<serial>:scenario:__sequence__
# Older/direct runs may still use:
#   campaign:<id>:device:<serial>:scenario:<scen_id>
# Device serial may contain colons (WiFi ADB: 192.168.1.1:5555) so we cannot
# count colons; instead we use a greedy .+ for the serial segment.
_TOP_LEVEL_WF_RE = re.compile(r"^campaign:[^:]+:device:.+:scenario:[^:]+$")
_WORKFLOW_CAMPAIGN_RE = re.compile(r"^campaign:([^:]+):")
_WORKFLOW_CONTEXT_RE = re.compile(
    r"^campaign:(?P<campaign_id>[^:]+):device:(?P<device_serial>.+):scenario:(?P<scenario_id>[^:]+)$"
)
_INTERRUPT_TEMPORAL_DEADLINE_S = 3.0
_INTERRUPT_CANCEL_TIMEOUT_S = 1.0
_INTERRUPT_CANCEL_CONCURRENCY = 16


def _add_interrupt_workflow_id(out: list[str], workflow_id: str | None) -> None:
    workflow_id = str(workflow_id or "").strip()
    if not workflow_id:
        return
    candidates = [workflow_id]
    if workflow_id.endswith(":steps"):
        candidates.append(workflow_id[:-6])
    else:
        candidates.append(f"{workflow_id}:steps")
    for candidate in candidates:
        if candidate and candidate not in out:
            out.append(candidate)


def _interrupt_workflow_ids_from_executions(executions) -> list[str]:
    workflow_ids: list[str] = []
    for execution in executions:
        meta = getattr(execution, "meta", None) or {}
        for workflow_id in meta.get("workflow_ids") or []:
            _add_interrupt_workflow_id(workflow_ids, workflow_id)
        _add_interrupt_workflow_id(workflow_ids, meta.get("workflow_id"))
        execution_id = str(getattr(execution, "id", "") or "").strip()
        if execution_id:
            _add_interrupt_workflow_id(workflow_ids, f"exec_{execution_id}")
    return workflow_ids


def _takeover_workflow_ids_from_execution(execution) -> list[str]:
    workflow_ids: list[str] = []

    def _add(workflow_id: str | None) -> None:
        workflow_id = str(workflow_id or "").strip()
        if not workflow_id:
            return
        if workflow_id.endswith(":steps"):
            workflow_id = workflow_id[:-6]
        if workflow_id and workflow_id not in workflow_ids:
            workflow_ids.append(workflow_id)

    meta = getattr(execution, "meta", None) or {}
    for workflow_id in meta.get("workflow_ids") or []:
        _add(workflow_id)
    _add(meta.get("workflow_id"))
    execution_id = str(getattr(execution, "id", "") or "").strip()
    if execution_id:
        _add(f"exec_{execution_id}")
    return workflow_ids


def _interrupt_execution_ids(executions) -> list[str]:
    ids: list[str] = []
    for execution in executions:
        execution_id = str(getattr(execution, "id", "") or "").strip()
        if execution_id and execution_id not in ids:
            ids.append(execution_id)
    return ids


def _workflow_context_from_workflow_id(workflow_id: str) -> dict:
    match = _WORKFLOW_CONTEXT_RE.match(workflow_id or "")
    if not match:
        return {}
    scenario_id = match.group("scenario_id")
    return {
        "campaign_id": match.group("campaign_id"),
        "campaign_name": None,
        "scenario_id": None if scenario_id == "__sequence__" else scenario_id,
        "scenario_name": None,
        "scenario_count": None,
        "device_serial": match.group("device_serial"),
        "workflow_kind": "main",
        "execution_id": None,
        "dispatch_source": None,
    }


async def _mark_interrupt_executions_cancelled(executions) -> None:
    execution_ids = _interrupt_execution_ids(executions)
    if not execution_ids:
        return
    from services.execution_pause_flags import clear_execution_paused, set_execution_cancelled

    async def _mark_one(execution_id: str) -> None:
        await clear_execution_paused(execution_id)
        await set_execution_cancelled(execution_id)

    await asyncio.gather(*(_mark_one(execution_id) for execution_id in execution_ids))


async def _cancel_interrupt_workflows(client, workflow_ids: list[str]) -> list[str]:
    sem = asyncio.Semaphore(_INTERRUPT_CANCEL_CONCURRENCY)

    async def _cancel_one(workflow_id: str) -> str | None:
        try:
            async with sem:
                await asyncio.wait_for(
                    client.get_workflow_handle(workflow_id).cancel(),
                    timeout=_INTERRUPT_CANCEL_TIMEOUT_S,
                )
            return workflow_id
        except Exception as exc:
            log.warning("interrupt: failed to cancel %s: %s", workflow_id, exc)
            return None

    results = await asyncio.gather(*(_cancel_one(workflow_id) for workflow_id in workflow_ids))
    return [workflow_id for workflow_id in results if workflow_id]


async def _pause_takeover_executions(
    db,
    executions,
    *,
    user_id: str | None,
    temporal_client,
) -> tuple[list[dict], int]:
    from services.execution_control import ExecutionControlError, pause_execution

    paused: list[dict] = []
    workflows_signalled = 0
    for execution in executions:
        if getattr(execution, "status", "running") not in ("running", "paused"):
            continue
        workflow_ids = _takeover_workflow_ids_from_execution(execution)
        try:
            result = await pause_execution(
                db,
                execution.id,
                user_id=user_id,
                temporal_client=temporal_client,
                workflow_ids=workflow_ids or None,
                signal_temporal=temporal_client is not None,
            )
            workflows_signalled += result.workflows_signalled
            paused.append(
                {
                    "execution_id": result.execution_id,
                    "status": result.status,
                    "effective_transition": result.effective_transition,
                    "workflows_signalled": result.workflows_signalled,
                }
            )
        except ExecutionControlError as exc:
            paused.append(
                {
                    "execution_id": execution.id,
                    "status": getattr(execution, "status", None),
                    "effective_transition": False,
                    "error": exc.message,
                }
            )
    return paused, workflows_signalled


async def _workflow_ui_status(client, workflow_id: str, temporal_status: str) -> str:
    if temporal_status != "RUNNING":
        return temporal_status
    try:
        from temporal.shared import WorkflowStatus
        from temporal.workflows import ScenarioWorkflow

        handle = client.get_workflow_handle(workflow_id)
        progress = await handle.query(ScenarioWorkflow.get_progress)
        ps = (getattr(progress, "status", None) or "").lower()
        if ps == WorkflowStatus.PAUSED.value:
            return "PAUSED"
        if ps == WorkflowStatus.PAUSED_ON_ERROR.value:
            return "paused_on_error"
    except Exception:
        log.debug("workflow status enrich failed id=%s", workflow_id, exc_info=True)
    return temporal_status


def build_campaign_fleet_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
) -> APIRouter:
    router = APIRouter()

    async def _get_campaign_or_404(db: DB, campaign_id: str, user: CurrentUser):
        campaign = await repo.get_campaign(db, campaign_id)
        if not await campaign_visible_to_user(db, user, campaign):
            return None
        return campaign

    async def _assert_campaign_owned(db: DB, campaign_id: str, user_id: str) -> None:
        campaign = await repo.get_campaign(db, campaign_id)
        if campaign is None or str(getattr(campaign, "user_id", "")) != str(user_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Campaign not found")

    async def _assert_workflow_owned(db: DB, workflow_id: str, user: CurrentUser) -> None:
        from fastapi import HTTPException
        from api.execution_access import get_execution_for_user

        if workflow_id.startswith("exec_"):
            execution_id = workflow_id[5:]
            if not execution_id:
                raise HTTPException(status_code=404, detail="Workflow not found")
            await get_execution_for_user(db, execution_id, user)
            return

        match = _WORKFLOW_CAMPAIGN_RE.match(workflow_id or "")
        if not match:
            raise HTTPException(status_code=404, detail="Workflow not found")
        campaign_id = match.group(1)
        campaign = await repo.get_campaign(db, campaign_id)
        if campaign is None or str(getattr(campaign, "user_id", "")) != str(user.id):
            raise HTTPException(status_code=404, detail="Workflow not found")

    async def _workflow_context_from_execution(
        db: DB,
        execution,
        *,
        device_serial: str | None = None,
        campaign_name_cache: dict[str, str | None] | None = None,
    ) -> dict:
        meta = getattr(execution, "meta", None) or {}
        cfg = getattr(execution, "device_config", None) or {}
        campaign_id = str(getattr(execution, "campaign_id", "") or "") or None
        scenario_ids = [
            str(item)
            for item in (meta.get("scenario_ids") or [])
            if str(item or "").strip()
        ]
        scenario_id = (
            str(getattr(execution, "scenario_id", "") or "")
            or str(meta.get("org_scenario_id") or "")
            or (scenario_ids[0] if len(scenario_ids) == 1 else "")
            or None
        )
        scenario_steps: list[dict] = []
        if scenario_ids:
            from db.crud import org_scenario as org_scenario_repo

            bodies = await org_scenario_repo.get_org_scenario_bodies_by_ids(
                db,
                str(getattr(execution, "org_id", "") or ""),
                scenario_ids,
            )
            names = await org_scenario_repo.get_org_scenario_names_by_ids(
                db,
                str(getattr(execution, "org_id", "") or ""),
                scenario_ids,
            )
            bodies_by_id = {
                sid: body if isinstance(body, dict) else {}
                for sid, _kind, body in bodies
            }
            if len(scenario_ids) == 1:
                body = bodies_by_id.get(scenario_ids[0]) or {}
                scenario_steps = list(body.get("steps") or [])
            else:
                for sid in scenario_ids:
                    body = bodies_by_id.get(sid) or {}
                    steps = list(body.get("steps") or [])
                    if not steps:
                        continue
                    scenario_steps.append(
                        {
                            "type": "run_scenario",
                            "scenario_id": sid,
                            "title": names.get(sid) or sid,
                            "steps": steps,
                        }
                    )
        campaign_name: str | None = None
        if campaign_id:
            cache = campaign_name_cache if campaign_name_cache is not None else {}
            if campaign_id not in cache:
                campaign = await repo.get_campaign(db, campaign_id)
                cache[campaign_id] = getattr(campaign, "name", None) if campaign else None
            campaign_name = cache.get(campaign_id)
        resolved_serial = (
            device_serial
            or str(cfg.get("device_serial") or "")
            or str(meta.get("device_serial") or "")
            or None
        )
        return {
            "execution_id": getattr(execution, "id", None),
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "scenario_id": scenario_id,
            "scenario_name": (
                meta.get("org_scenario_name")
                or meta.get("scenario_name")
                or None
            ),
            "scenario_steps": scenario_steps,
            "scenario_count": int(meta.get("scenarios_count") or len(scenario_ids) or 0)
            or None,
            "device_serial": resolved_serial,
            "workflow_kind": "main",
            "dispatch_source": meta.get("dispatch_source"),
        }

    # ── Campaign → Temporal workflow ─────────────────────────────────

    @router.post(
        "/campaigns/{campaign_id}/run",
        dependencies=[Depends(require_permission("campaigns", "execute"))],
    )
    async def api_run_campaign(
        campaign_id: str,
        db: DB,
        user: CurrentUser,
        body: CampaignRunBody = Body(default_factory=CampaignRunBody),
    ):
        await _assert_campaign_owned(db, campaign_id, user.id)
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Database is disabled; campaigns are not available"},
                status_code=503,
            )
        if not config.temporal.enabled:
            return JSONResponse(
                {"error": "Temporal is required for campaign execution"},
                status_code=503,
            )
        try:
            # Resolve live-device filter if any filter param was explicitly set.
            device_serials_override: list[str] | None = None
            use_live_filter = (
                body.filter_state != "READY"
                or body.filter_model is not None
                or body.filter_tags is not None
                or body.max_devices is not None
            )
            if use_live_filter:
                from services.fleet_dispatch import _device_has_all_tags

                _state = body.filter_state.strip().upper() or "READY"
                live = [d for d in manager.all_devices() if d.state.name.upper() == _state]

                if body.filter_model:
                    needle = body.filter_model.lower()
                    live = [d for d in live if needle in (d.model or "").lower()]

                if body.filter_tags:
                    from db.database import AsyncSessionLocal
                    from db.crud.device_group import get_all_device_serial_tags

                    filter_tags_list = [
                        t.strip().lower() for t in body.filter_tags.split(",") if t.strip()
                    ]
                    async with AsyncSessionLocal() as db:
                        serial_tags = await get_all_device_serial_tags(db)
                    live = [
                        d for d in live
                        if _device_has_all_tags(d.serial, serial_tags, filter_tags_list)
                    ]

                if body.max_devices is not None:
                    live = live[: body.max_devices]

                if not live:
                    return JSONResponse(
                        {"error": f"No live devices match the filter (state={body.filter_state!r})"},
                        status_code=400,
                    )
                device_serials_override = [d.serial for d in live]

            temporal_client = await get_temporal_client(config.temporal)
            payload, status = await enqueue_campaign_run_temporal(
                campaign_id,
                temporal_client,
                config.temporal,
                device_serials_override=device_serials_override,
            )
            if status != 200:
                return JSONResponse(payload, status_code=status)
            log.info("Campaign %s dispatched via Temporal", campaign_id)
            return payload
        except Exception as exc:
            log.exception("Campaign dispatch failed")
            return JSONResponse(
                {"error": f"Campaign dispatch failed: {exc}"},
                status_code=500,
            )

    @router.get(
        "/execution/runtime",
        dependencies=[Depends(require_permission("executions", "read"))],
    )
    async def api_execution_runtime():
        """How campaign runs are executed — for UI/docs."""
        from api.schemas.execution_runtime import (
            CampaignRunRuntimeInfo,
            ExecutionRuntimeOut,
            TemporalRuntimeInfo,
        )

        epic04_note = (
            "Epic 04 entity dispatch uses workflow_id=exec_{execution_id} per device execution. "
            "When Temporal is disabled or unreachable, dispatch_source=fallback runs in-process."
        )
        temporal = TemporalRuntimeInfo(
            enabled=config.temporal.enabled,
            server_url=config.temporal.server_url,
            namespace=config.temporal.namespace,
            task_queue=config.temporal.task_queue,
        )
        if not config.temporal.enabled:
            return ExecutionRuntimeOut(
                temporal=temporal,
                campaign_run=CampaignRunRuntimeInfo(
                    engine="fallback",
                    dispatch_source="fallback",
                    fallback_mode_active=True,
                    note=epic04_note,
                ),
            )
        return ExecutionRuntimeOut(
            temporal=temporal,
            campaign_run=CampaignRunRuntimeInfo(
                engine="temporal",
                dispatch_source="temporal",
                fallback_mode_active=False,
                note=epic04_note,
            ),
        )

    # ── Workflow monitoring & control ────────────────────────────────

    @router.get(
        "/campaigns/{campaign_id}/workflows",
        dependencies=[Depends(require_permission("campaigns", "read"))],
    )
    async def api_list_campaign_workflows(campaign_id: str, db: DB, user: CurrentUser):
        """List top-level Temporal workflow runs for a campaign.

        Only returns top-level ScenarioWorkflow entries (normally one per device).
        Child workflows (ScenarioStepsWorkflow) are excluded — they are an
        implementation detail and would flood the list.
        """
        await _assert_campaign_owned(db, campaign_id, user.id)
        if not config.temporal.enabled:
            return {
                "campaign_id": campaign_id,
                "workflows": [],
                "execution_engine": "task_queue",
                "temporal_available": False,
            }
        try:
            client = await get_temporal_client(config.temporal)
            raw_rows: list[tuple[str, str, str, datetime | None]] = []
            # Top-level IDs have pattern: campaign:{id}:device:{serial}:scenario:{id-or-sequence}
            # Child IDs have extra suffixes like :steps, :repeat:…, :if_element:…
            # We match exactly 5 colon-separated segments to exclude children.
            # Sanitize campaign_id before embedding in Temporal query string to
            # prevent injection through double-quote characters.
            safe_campaign_id = campaign_id.replace('"', "").replace("\\", "")
            prefix = f"campaign:{safe_campaign_id}:"
            async for wf in client.list_workflows(
                f'WorkflowId STARTS_WITH "{prefix}"'
            ):
                if not _TOP_LEVEL_WF_RE.match(wf.id):
                    continue
                temporal_st = wf.status.name if wf.status else "UNKNOWN"
                raw_rows.append(
                    (
                        wf.id,
                        wf.run_id,
                        temporal_st,
                        wf.start_time,
                    )
                )

            def _rank(row: tuple[str, str, str, datetime | None]) -> tuple[int, datetime, str]:
                _wf_id, run_id, _temporal_st, start_dt = row
                fallback_dt = datetime.min.replace(tzinfo=timezone.utc)
                return (1 if start_dt is not None else 0, start_dt or fallback_dt, run_id)

            latest_by_workflow_id: dict[str, tuple[str, str, str, datetime | None]] = {}
            for row in raw_rows:
                wf_id = row[0]
                prev = latest_by_workflow_id.get(wf_id)
                if prev is None or _rank(row) >= _rank(prev):
                    latest_by_workflow_id[wf_id] = row

            from db.crud.execution import list_running_executions_for_campaign

            execution_context_by_wf: dict[str, dict] = {}
            campaign_name_cache: dict[str, str | None] = {}
            for ex in await list_running_executions_for_campaign(db, campaign_id):
                wf_id = (ex.meta or {}).get("workflow_id")
                if wf_id:
                    execution_context_by_wf[str(wf_id)] = (
                        await _workflow_context_from_execution(
                            db,
                            ex,
                            campaign_name_cache=campaign_name_cache,
                        )
                    )
                if not wf_id or wf_id in latest_by_workflow_id:
                    continue
                try:
                    handle = client.get_workflow_handle(str(wf_id))
                    desc = await handle.describe()
                    temporal_st = desc.status.name if desc.status else "UNKNOWN"
                    latest_by_workflow_id[str(wf_id)] = (
                        str(wf_id),
                        desc.run_id,
                        temporal_st,
                        desc.start_time,
                    )
                except Exception:
                    log.debug("epic04 workflow describe failed: %s", wf_id, exc_info=True)

            async def _one(row: tuple[str, str, str, datetime | None]) -> dict:
                wf_id, run_id, temporal_st, start_time = row
                ui_st = await _workflow_ui_status(client, wf_id, temporal_st)
                return {
                    "workflow_id": wf_id,
                    "run_id": run_id,
                    "status": ui_st,
                    "start_time": start_time.isoformat() if start_time else None,
                    **_workflow_context_from_workflow_id(wf_id),
                    **execution_context_by_wf.get(wf_id, {}),
                }

            workflows = list(await asyncio.gather(*(_one(r) for r in latest_by_workflow_id.values())))
            return {
                "campaign_id": campaign_id,
                "workflows": workflows,
                "execution_engine": "temporal",
                "temporal_available": True,
            }
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to list workflows: {exc}"}, status_code=500,
            )

    @router.get(
        "/devices/{serial}/running-workflows",
        dependencies=[Depends(require_permission("executions", "read"))],
    )
    async def api_device_running_workflows(serial: str, db: DB, user: CurrentUser):
        """List RUNNING/PAUSED top-level scenario workflows for a specific device serial."""
        from fastapi import HTTPException

        from api.execution_access import get_execution_for_user
        from db.crud.execution import list_running_executions_for_device
        from services.campaign.execution_runtime import workflow_id_for_execution

        device = await repo.get_device_by_serial(db, serial)
        if not await device_visible_to_user(db, user, device):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Device not found")

        workflows_by_id: dict[str, dict] = {}
        campaign_name_cache: dict[str, str | None] = {}

        def _append_workflow(
            wf_id: str,
            *,
            run_id: str | None = None,
            status: str = "RUNNING",
            start_time: str | None = None,
            context: dict | None = None,
        ) -> None:
            prev = workflows_by_id.get(wf_id)
            if prev is not None and prev.get("status") == "RUNNING":
                return
            merged = {**(prev or {}), **(context or {})}
            workflows_by_id[wf_id] = {
                **merged,
                "workflow_id": wf_id,
                "run_id": run_id or (prev.get("run_id") if prev else None),
                "status": status,
                "start_time": start_time or (prev.get("start_time") if prev else None),
            }

        # Epic 04: workflow_id=exec_{execution_id} (no :device: segment in Temporal ID).
        for ex in await list_running_executions_for_device(db, device.id):
            try:
                await get_execution_for_user(db, ex.id, user)
            except HTTPException:
                continue
            meta = ex.meta or {}
            wf_id = str(meta.get("workflow_id") or workflow_id_for_execution(ex.id))
            ui_status = "PAUSED" if ex.status == "paused" else "RUNNING"
            _append_workflow(
                wf_id,
                status=ui_status,
                start_time=ex.started_at.isoformat() if ex.started_at else None,
                context=await _workflow_context_from_execution(
                    db,
                    ex,
                    device_serial=serial,
                    campaign_name_cache=campaign_name_cache,
                ),
            )

        if not config.temporal.enabled:
            return {
                "serial": serial,
                "workflows": list(workflows_by_id.values()),
                "temporal_available": False,
            }
        try:
            client = await get_temporal_client(config.temporal)
            # Legacy campaign dispatch IDs: campaign:{id}:device:{serial}:scenario:…
            safe_serial = serial.replace('"', "").replace("\\", "")
            needle = f":device:{safe_serial}:"
            async for wf in client.list_workflows('ExecutionStatus = "Running"'):
                if needle not in wf.id:
                    continue
                if not _TOP_LEVEL_WF_RE.match(wf.id):
                    continue
                _append_workflow(
                    wf.id,
                    run_id=wf.run_id,
                    status=wf.status.name if wf.status else "UNKNOWN",
                    start_time=wf.start_time.isoformat() if wf.start_time else None,
                    context=_workflow_context_from_workflow_id(wf.id),
                )

            # Enrich exec_* rows with live Temporal status when possible.
            for wf_id in list(workflows_by_id):
                if not wf_id.startswith("exec_"):
                    continue
                try:
                    handle = client.get_workflow_handle(wf_id)
                    desc = await handle.describe()
                    temporal_st = desc.status.name if desc.status else "UNKNOWN"
                    if temporal_st not in ("RUNNING", "PAUSED"):
                        workflows_by_id.pop(wf_id, None)
                        continue
                    ui_st = await _workflow_ui_status(client, wf_id, temporal_st)
                    row = workflows_by_id[wf_id]
                    row["run_id"] = desc.run_id
                    row["status"] = ui_st
                    if desc.start_time:
                        row["start_time"] = desc.start_time.isoformat()
                except Exception:
                    log.debug(
                        "device running workflow describe failed id=%s",
                        wf_id,
                        exc_info=True,
                    )

            return {
                "serial": serial,
                "workflows": list(workflows_by_id.values()),
                "temporal_available": True,
            }
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to list device workflows: {exc}"}, status_code=500,
            )

    @router.get(
        "/workflows/{workflow_id}/progress",
        dependencies=[Depends(require_permission("executions", "read"))],
    )
    async def api_workflow_progress(workflow_id: str, db: DB, user: CurrentUser):
        """Query real-time progress of a Temporal scenario workflow.

        When the child ScenarioStepsWorkflow is paused on error, status is
        overridden to 'paused_on_error' and error_message is populated.
        """
        await _assert_workflow_owned(db, workflow_id, user)
        try:
            from temporal.workflows import ScenarioWorkflow, ScenarioStepsWorkflow

            client = await get_temporal_client(config.temporal)
            handle = client.get_workflow_handle(workflow_id)
            progress = await handle.query(ScenarioWorkflow.get_progress)

            status = progress.status
            error_message: str | None = None

            # When parent shows RUNNING, check if child is paused on error
            if status == "running":
                child_id = f"{workflow_id}:steps"
                try:
                    child_handle = client.get_workflow_handle(child_id)
                    error_info = await child_handle.query(ScenarioStepsWorkflow.get_error_info)
                    if error_info.get("paused_on_error"):
                        status = "paused_on_error"
                        error_message = error_info.get("error_message") or None
                except Exception:
                    pass  # child not started yet or not queryable

            return {
                "workflow_id": workflow_id,
                "status": status,
                "current_step": progress.current_step,
                "total_steps": progress.total_steps,
                "current_step_type": progress.current_step_type,
                "loop_iteration": progress.loop_iteration,
                "message": error_message or progress.message,
                "device_serial": progress.device_serial,
                "error_message": error_message,
            }
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to query progress: {exc}"}, status_code=500,
            )

    @router.get(
        "/workflows/{workflow_id}/steps",
        dependencies=[Depends(require_permission("executions", "read"))],
    )
    async def api_workflow_steps(workflow_id: str, db: DB, user: CurrentUser):
        """Query step-by-step execution log for a scenario workflow.

        - While RUNNING: queries the child steps workflow (live, real-time).
        - After COMPLETED/FAILED: reads the final result from the parent workflow.

        Returns a flat list of step entries with index, type, ok, message, depth.
        """
        await _assert_workflow_owned(db, workflow_id, user)
        if not config.temporal.enabled:
            return JSONResponse({"error": "Temporal is not enabled"}, status_code=503)
        try:
            from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow
            from temporalio.service import RPCError

            client = await get_temporal_client(config.temporal)
            parent_handle = client.get_workflow_handle(workflow_id)

            # Determine current workflow status
            try:
                desc = await parent_handle.describe()
                wf_status = desc.status.name if desc.status else "UNKNOWN"
            except Exception:
                wf_status = "UNKNOWN"

            steps: list[dict] = []
            source = "unknown"

            if wf_status == "RUNNING":
                # Query the child steps workflow (id: {workflow_id}:steps)
                child_id = f"{workflow_id}:steps"
                child_handle = client.get_workflow_handle(child_id)
                try:
                    steps = await child_handle.query(ScenarioStepsWorkflow.get_step_log)
                    source = "live_query"
                except RPCError:
                    # Child may not have started yet
                    steps = []
                    source = "pending"
            else:
                # Completed/failed: get full step_results from the workflow result
                try:
                    result = await parent_handle.result(follow_runs=False)
                    steps = result.step_results or []
                    source = "final_result"
                except Exception:
                    # Result not available (e.g. cancelled before completion)
                    # Fall back to querying the child workflow anyway
                    child_id = f"{workflow_id}:steps"
                    child_handle = client.get_workflow_handle(child_id)
                    try:
                        steps = await child_handle.query(ScenarioStepsWorkflow.get_step_log)
                        source = "child_query_fallback"
                    except Exception:
                        steps = []
                        source = "unavailable"

            return {
                "workflow_id": workflow_id,
                "status": wf_status,
                "source": source,
                "steps_count": len(steps),
                "steps": steps,
            }
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to query steps: {exc}"}, status_code=500,
            )

    @router.post(
        "/workflows/{workflow_id}/pause",
        dependencies=[Depends(require_permission("executions", "execute"))],
    )
    async def api_workflow_pause(workflow_id: str, db: DB, user: CurrentUser):
        """Pause a running scenario workflow at the next step boundary.

        SECURITY NOTE: workflow_id is caller-supplied and not validated for
        ownership. Caller-supplied workflow IDs must resolve to a campaign owned
        by the current user before any Temporal handle is signalled.
        """
        await _assert_workflow_owned(db, workflow_id, user)
        try:
            from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

            client = await get_temporal_client(config.temporal)
            for wf_id, signal in [
                (workflow_id, ScenarioWorkflow.pause),
                (f"{workflow_id}:steps", ScenarioStepsWorkflow.pause),
            ]:
                try:
                    await client.get_workflow_handle(wf_id).signal(signal)
                except Exception:
                    pass
            return {"workflow_id": workflow_id, "action": "paused"}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to pause: {exc}"}, status_code=500,
            )

    @router.post(
        "/workflows/{workflow_id}/resume",
        dependencies=[Depends(require_permission("executions", "execute"))],
    )
    async def api_workflow_resume(workflow_id: str, db: DB, user: CurrentUser):
        """Resume a paused scenario workflow."""
        await _assert_workflow_owned(db, workflow_id, user)
        try:
            from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

            client = await get_temporal_client(config.temporal)
            for wf_id, signal in [
                (workflow_id, ScenarioWorkflow.resume),
                (f"{workflow_id}:steps", ScenarioStepsWorkflow.resume),
            ]:
                try:
                    await client.get_workflow_handle(wf_id).signal(signal)
                except Exception:
                    pass
            return {"workflow_id": workflow_id, "action": "resumed"}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to resume: {exc}"}, status_code=500,
            )

    @router.post(
        "/workflows/{workflow_id}/cancel",
        dependencies=[Depends(require_permission("executions", "execute"))],
    )
    async def api_workflow_cancel(workflow_id: str, db: DB, user: CurrentUser):
        """Cancel a scenario workflow — cancels both parent and child steps workflow."""
        await _assert_workflow_owned(db, workflow_id, user)
        try:
            client = await get_temporal_client(config.temporal)
            for wf_id in [workflow_id, f"{workflow_id}:steps"]:
                try:
                    await client.get_workflow_handle(wf_id).cancel()
                except Exception:
                    pass
            return {"workflow_id": workflow_id, "action": "cancelled"}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to cancel: {exc}"}, status_code=500,
            )

    @router.post(
        "/devices/{serial}/takeover",
        dependencies=[Depends(require_permission("devices", "execute"))],
    )
    async def api_device_takeover(serial: str, db: DB, user: CurrentUser):
        """Pause running scenarios on a device and allow manual input takeover."""
        db_device = await repo.get_device_by_serial(db, serial)
        if not await device_visible_to_user(db, user, db_device):
            raise HTTPException(status_code=404, detail="Device not found")
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        executions = await repo.list_running_executions_for_device(db, db_device.id)
        temporal_client = None
        if config.temporal.enabled:
            try:
                temporal_client = await asyncio.wait_for(
                    get_temporal_client(config.temporal),
                    timeout=_INTERRUPT_TEMPORAL_DEADLINE_S,
                )
            except asyncio.TimeoutError:
                log.warning("takeover: temporal connect timed out for %s", serial)
            except Exception as exc:
                log.warning("takeover: temporal unavailable for %s: %s", serial, exc)

        paused, workflows_signalled = await _pause_takeover_executions(
            db,
            executions,
            user_id=getattr(user, "id", None),
            temporal_client=temporal_client,
        )

        from services.manual_takeover import set_manual_takeover

        await set_manual_takeover(serial)
        publish = getattr(device, "_publish_status", None)
        if publish is not None:
            try:
                publish()
            except Exception:
                pass

        return {
            "ok": True,
            "serial": serial,
            "action": "paused_for_takeover",
            "paused_executions": paused,
            "workflows_signalled": workflows_signalled,
            "manual_takeover_active": True,
        }

    @router.post(
        "/devices/{serial}/interrupt",
        dependencies=[Depends(require_permission("devices", "execute"))],
    )
    async def api_device_interrupt(serial: str, db: DB, user: CurrentUser):
        """Cancel all running scenarios on a device to allow manual takeover.

        Cancels every matching Temporal workflow, then force-resets the
        in-process _scenario_active counter so the WebSocket input gate opens
        immediately without waiting for the activity to acknowledge cancellation.
        """
        db_device = await repo.get_device_by_serial(db, serial)
        if not await device_visible_to_user(db, user, db_device):
            raise HTTPException(status_code=404, detail="Device not found")
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        cancelled: list[str] = []
        if config.temporal.enabled:
            try:
                executions = await repo.list_running_executions_for_device(db, db_device.id)
                await _mark_interrupt_executions_cancelled(executions)
                workflow_ids = _interrupt_workflow_ids_from_executions(executions)

                async def _cancel_all() -> list[str]:
                    client = await get_temporal_client(config.temporal)
                    ids = list(workflow_ids)
                    if not ids:
                        safe_serial = serial.replace('"', "").replace("\\", "")
                        needle = f":device:{safe_serial}:"
                        query = 'WorkflowId STARTS_WITH "campaign:" AND ExecutionStatus = "Running"'
                        async for wf in client.list_workflows(query):
                            if needle in wf.id:
                                _add_interrupt_workflow_id(ids, wf.id)
                    return await _cancel_interrupt_workflows(client, ids)

                cancelled = await asyncio.wait_for(
                    _cancel_all(),
                    timeout=_INTERRUPT_TEMPORAL_DEADLINE_S,
                )
            except asyncio.TimeoutError:
                log.warning("interrupt: temporal cancel timed out for %s", serial)
            except Exception as exc:
                log.warning("interrupt: temporal unavailable for %s: %s", serial, exc)

        from api.routes.device_control.scenarios import cancel_all_previews_for_serial
        from tasks.scenario_task import force_clear_scenario_busy

        preview_cancelled = cancel_all_previews_for_serial(serial)
        force_clear_scenario_busy(device)

        return {
            "ok": True,
            "serial": serial,
            "cancelled_workflows": cancelled,
            "cancelled_previews": preview_cancelled,
        }

    return router
