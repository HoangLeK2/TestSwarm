"""Campaign run via Temporal workflows + fleet-wide scenario dispatch."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import Config
from api.deps import CurrentUser, DB
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

    async def _get_campaign_or_404(db: DB, campaign_id: str, user_id: str):
        campaign = await repo.get_campaign(db, campaign_id)
        if not campaign or campaign.user_id != user_id:
            return None
        return campaign

    async def _assert_campaign_owned(db: DB, campaign_id: str, user_id: str) -> None:
        if not await _get_campaign_or_404(db, campaign_id, user_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Campaign not found")

    async def _assert_workflow_owned(db: DB, workflow_id: str, user_id: str) -> None:
        from fastapi import HTTPException

        match = _WORKFLOW_CAMPAIGN_RE.match(workflow_id or "")
        if not match:
            raise HTTPException(status_code=404, detail="Workflow not found")
        campaign_id = match.group(1)
        await _assert_campaign_owned(db, campaign_id, user_id)

    # ── Campaign → Temporal workflow ─────────────────────────────────

    @router.post("/campaigns/{campaign_id}/run")
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

    @router.get("/execution/runtime")
    async def api_execution_runtime():
        """How campaign runs are executed — for UI/docs."""
        return {
            "temporal": {
                "enabled": config.temporal.enabled,
                "server_url": config.temporal.server_url,
                "namespace": config.temporal.namespace,
                "task_queue": config.temporal.task_queue,
            },
            "campaign_run": {
                "engine": "temporal",
                "note": (
                    "All campaign executions use Temporal workflows. "
                    "POST /api/campaigns/{id}/run returns 503 if Temporal is disabled or unreachable."
                ),
            },
        }

    # ── Workflow monitoring & control ────────────────────────────────

    @router.get("/campaigns/{campaign_id}/workflows")
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

            async def _one(row: tuple[str, str, str, datetime | None]) -> dict:
                wf_id, run_id, temporal_st, start_time = row
                ui_st = await _workflow_ui_status(client, wf_id, temporal_st)
                return {
                    "workflow_id": wf_id,
                    "run_id": run_id,
                    "status": ui_st,
                    "start_time": start_time.isoformat() if start_time else None,
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

    @router.get("/devices/{serial}/running-workflows")
    async def api_device_running_workflows(serial: str, db: DB, user: CurrentUser):
        """List RUNNING/PAUSED top-level scenario workflows for a specific device serial."""
        device = await repo.get_device_by_serial(db, serial)
        if not device or device.user_id != user.id:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Device not found")
        if not config.temporal.enabled:
            return {"serial": serial, "workflows": [], "temporal_available": False}
        try:
            client = await get_temporal_client(config.temporal)
            # Temporal query language has no CONTAINS operator — fetch all
            # running workflows and filter by serial client-side.
            safe_serial = serial.replace('"', "").replace("\\", "")
            needle = f":device:{safe_serial}:"
            workflows = []
            async for wf in client.list_workflows('ExecutionStatus = "Running"'):
                if needle not in wf.id:
                    continue
                if not _TOP_LEVEL_WF_RE.match(wf.id):
                    continue
                workflows.append({
                    "workflow_id": wf.id,
                    "run_id": wf.run_id,
                    "status": wf.status.name if wf.status else "UNKNOWN",
                    "start_time": wf.start_time.isoformat() if wf.start_time else None,
                })
            return {"serial": serial, "workflows": workflows, "temporal_available": True}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to list device workflows: {exc}"}, status_code=500,
            )

    @router.get("/workflows/{workflow_id}/progress")
    async def api_workflow_progress(workflow_id: str, db: DB, user: CurrentUser):
        """Query real-time progress of a Temporal scenario workflow.

        When the child ScenarioStepsWorkflow is paused on error, status is
        overridden to 'paused_on_error' and error_message is populated.
        """
        await _assert_workflow_owned(db, workflow_id, user.id)
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

    @router.get("/workflows/{workflow_id}/steps")
    async def api_workflow_steps(workflow_id: str, db: DB, user: CurrentUser):
        """Query step-by-step execution log for a scenario workflow.

        - While RUNNING: queries the child steps workflow (live, real-time).
        - After COMPLETED/FAILED: reads the final result from the parent workflow.

        Returns a flat list of step entries with index, type, ok, message, depth.
        """
        await _assert_workflow_owned(db, workflow_id, user.id)
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

    @router.post("/workflows/{workflow_id}/pause")
    async def api_workflow_pause(workflow_id: str, db: DB, user: CurrentUser):
        """Pause a running scenario workflow at the next step boundary.

        SECURITY NOTE: workflow_id is caller-supplied and not validated for
        ownership. Any authenticated caller can pause any workflow whose ID they
        know. Add campaign-ownership middleware before exposing this to untrusted
        users.
        """
        await _assert_workflow_owned(db, workflow_id, user.id)
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

    @router.post("/workflows/{workflow_id}/resume")
    async def api_workflow_resume(workflow_id: str, db: DB, user: CurrentUser):
        """Resume a paused scenario workflow."""
        await _assert_workflow_owned(db, workflow_id, user.id)
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

    @router.post("/workflows/{workflow_id}/cancel")
    async def api_workflow_cancel(workflow_id: str, db: DB, user: CurrentUser):
        """Cancel a scenario workflow — cancels both parent and child steps workflow."""
        await _assert_workflow_owned(db, workflow_id, user.id)
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

    @router.post("/devices/{serial}/interrupt")
    async def api_device_interrupt(serial: str):
        """Cancel all running scenarios on a device to allow manual takeover.

        Cancels every matching Temporal workflow, then force-resets the
        in-process _scenario_active counter so the WebSocket input gate opens
        immediately without waiting for the activity to acknowledge cancellation.
        """
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)

        cancelled: list[str] = []
        if config.temporal.enabled:
            try:
                client = await get_temporal_client(config.temporal)
                safe_serial = serial.replace('"', "").replace("\\", "")
                needle = f":device:{safe_serial}:"
                async for wf in client.list_workflows('ExecutionStatus = "Running"'):
                    if needle not in wf.id:
                        continue
                    try:
                        await client.get_workflow_handle(wf.id).cancel()
                        cancelled.append(wf.id)
                    except Exception as exc:
                        log.warning("interrupt: failed to cancel %s: %s", wf.id, exc)
            except Exception as exc:
                log.warning("interrupt: temporal unavailable for %s: %s", serial, exc)

        # Force-reset so ws gate opens immediately (activity cancel is async)
        device._scenario_active = 0

        return {"ok": True, "serial": serial, "cancelled_workflows": cancelled}

    return router
