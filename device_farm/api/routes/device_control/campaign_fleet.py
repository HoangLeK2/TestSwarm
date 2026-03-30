"""Campaign run via Temporal workflows + fleet-wide scenario dispatch."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import FleetRunRequest
from core.config import Config
from runtime.core import DeviceManager, TaskQueue
from services.campaign_dispatch import enqueue_campaign_run, enqueue_campaign_run_temporal
from services.fleet_dispatch import enqueue_fleet_scenario, fleet_run_status
from temporal.worker import get_temporal_client

log = logging.getLogger(__name__)


def build_campaign_fleet_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
) -> APIRouter:
    router = APIRouter()

    # ── Campaign → Temporal workflow ─────────────────────────────────

    @router.post("/campaigns/{campaign_id}/run")
    async def api_run_campaign(campaign_id: str):
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Database is disabled; campaigns are not available"},
                status_code=503,
            )

        temporal_exc: BaseException | None = None
        if config.temporal.enabled:
            try:
                temporal_client = await get_temporal_client(config.temporal)
                payload, status = await enqueue_campaign_run_temporal(
                    campaign_id, temporal_client, config.temporal,
                )
                if status != 200:
                    return JSONResponse(payload, status_code=status)
                log.info("Campaign %s dispatched via Temporal", campaign_id)
                return payload
            except BaseException as exc:
                temporal_exc = exc
                log.warning(
                    "Temporal unavailable (%s) — falling back to TaskQueue for campaign %s",
                    exc, campaign_id,
                )

        try:
            payload, status = await enqueue_campaign_run(campaign_id, queue)
            if status != 200:
                return JSONResponse(payload, status_code=status)
            log.info("Campaign %s dispatched via TaskQueue", campaign_id)
            if temporal_exc is not None and isinstance(payload, dict):
                payload = {
                    **payload,
                    "execution_engine": payload.get("execution_engine", "task_queue"),
                    "engine": payload.get("engine", "task_queue"),
                    "temporal_fallback": True,
                    "temporal_fallback_reason": f"{type(temporal_exc).__name__}: {temporal_exc}",
                }
            return payload
        except Exception as exc:
            log.exception("Campaign dispatch failed")
            return JSONResponse(
                {"error": f"Campaign dispatch failed: {exc}"},
                status_code=500,
            )

    @router.get("/execution/runtime")
    async def api_execution_runtime():
        """How campaign runs are executed — for UI/docs (Temporal vs in-process TaskQueue)."""
        return {
            "temporal": {
                "enabled": config.temporal.enabled,
                "server_url": config.temporal.server_url,
                "namespace": config.temporal.namespace,
                "task_queue": config.temporal.task_queue,
            },
            "campaign_run": {
                "primary_engine": "temporal" if config.temporal.enabled else "task_queue",
                "response_fields": (
                    "POST /api/campaigns/{id}/run returns execution_engine (temporal | task_queue). "
                    "If Temporal is enabled but unreachable, the API falls back to task_queue and sets "
                    "temporal_fallback=true."
                ),
            },
        }

    # ── Workflow monitoring & control ────────────────────────────────

    @router.get("/campaigns/{campaign_id}/workflows")
    async def api_list_campaign_workflows(campaign_id: str):
        """List top-level Temporal workflow runs for a campaign.

        Only returns ScenarioWorkflow entries (one per device×scenario).
        Child workflows (ScenarioStepsWorkflow) are excluded — they are an
        implementation detail and would flood the list.
        """
        if not config.temporal.enabled:
            return {
                "campaign_id": campaign_id,
                "workflows": [],
                "execution_engine": "task_queue",
                "temporal_available": False,
            }
        try:
            client = await get_temporal_client(config.temporal)
            workflows = []
            # Top-level IDs have pattern: campaign:{id}:device:{serial}:scenario:{scen_id}
            # Child IDs have extra suffixes like :steps, :repeat:…, :if_element:…
            # We match exactly 5 colon-separated segments to exclude children.
            prefix = f"campaign:{campaign_id}:"
            async for wf in client.list_workflows(
                f'WorkflowId STARTS_WITH "{prefix}"'
            ):
                # Top-level workflow IDs: campaign:X:device:Y:scenario:Z  (5 colons)
                # Child workflow IDs:     campaign:X:device:Y:scenario:Z:steps (6+ colons)
                if wf.id.count(":") > 5:
                    continue
                workflows.append({
                    "workflow_id": wf.id,
                    "run_id": wf.run_id,
                    "status": wf.status.name if wf.status else "UNKNOWN",
                    "start_time": wf.start_time.isoformat() if wf.start_time else None,
                })
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

    @router.get("/workflows/{workflow_id}/progress")
    async def api_workflow_progress(workflow_id: str):
        """Query real-time progress of a Temporal scenario workflow."""
        try:
            from temporal.workflows import ScenarioWorkflow

            client = await get_temporal_client(config.temporal)
            handle = client.get_workflow_handle(workflow_id)
            progress = await handle.query(ScenarioWorkflow.get_progress)
            return {
                "workflow_id": workflow_id,
                "status": progress.status,
                "current_step": progress.current_step,
                "total_steps": progress.total_steps,
                "current_step_type": progress.current_step_type,
                "loop_iteration": progress.loop_iteration,
                "message": progress.message,
                "device_serial": progress.device_serial,
            }
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to query progress: {exc}"}, status_code=500,
            )

    @router.post("/workflows/{workflow_id}/pause")
    async def api_workflow_pause(workflow_id: str):
        """Pause a running scenario workflow at the next step boundary."""
        try:
            from temporal.workflows import ScenarioWorkflow

            client = await get_temporal_client(config.temporal)
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal(ScenarioWorkflow.pause)
            return {"workflow_id": workflow_id, "action": "paused"}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to pause: {exc}"}, status_code=500,
            )

    @router.post("/workflows/{workflow_id}/resume")
    async def api_workflow_resume(workflow_id: str):
        """Resume a paused scenario workflow."""
        try:
            from temporal.workflows import ScenarioWorkflow

            client = await get_temporal_client(config.temporal)
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal(ScenarioWorkflow.resume)
            return {"workflow_id": workflow_id, "action": "resumed"}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to resume: {exc}"}, status_code=500,
            )

    @router.post("/workflows/{workflow_id}/cancel")
    async def api_workflow_cancel(workflow_id: str):
        """Cancel a scenario workflow gracefully."""
        try:
            from temporal.workflows import ScenarioWorkflow

            client = await get_temporal_client(config.temporal)
            handle = client.get_workflow_handle(workflow_id)
            await handle.signal(ScenarioWorkflow.cancel_scenario)
            return {"workflow_id": workflow_id, "action": "cancelled"}
        except Exception as exc:
            return JSONResponse(
                {"error": f"Failed to cancel: {exc}"}, status_code=500,
            )

    # ── Fleet dispatch (TaskQueue — non-campaign) ────────────────────

    @router.post("/fleet/run")
    async def api_fleet_run(body: FleetRunRequest):
        group_serials = None
        serial_tags = None
        filter_tags_list = None

        needs_db = (body.filter_group_id or body.filter_tags) and config.database.enabled
        if needs_db:
            from db.database import AsyncSessionLocal
            from db.crud.device_group import get_group_device_serials, get_all_device_serial_tags
            async with AsyncSessionLocal() as db:
                if body.filter_group_id:
                    group_serials = await get_group_device_serials(db, body.filter_group_id)
                if body.filter_tags:
                    filter_tags_list = [
                        t.strip().lower()
                        for t in body.filter_tags.split(",")
                        if t.strip()
                    ]
                    if filter_tags_list:
                        serial_tags = await get_all_device_serial_tags(db)

        payload, status = enqueue_fleet_scenario(
            manager,
            queue,
            steps=body.steps,
            filter_state=body.filter_state,
            filter_model=body.filter_model,
            max_devices=body.max_devices,
            priority=body.priority,
            timeout=body.timeout,
            max_retries=body.max_retries,
            group_serials=group_serials,
            filter_tags=filter_tags_list,
            serial_tags=serial_tags,
        )
        if status != 200:
            return JSONResponse(payload, status_code=status)
        return payload

    @router.get("/fleet/status")
    async def api_fleet_status(run_id: Optional[str] = None):
        return fleet_run_status(queue, run_id)

    return router
