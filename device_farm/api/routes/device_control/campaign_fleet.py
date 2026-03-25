"""Campaign run (DB) and fleet-wide scenario dispatch."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import FleetRunRequest
from core.config import Config
from runtime.core import DeviceManager, TaskQueue
from services.campaign_dispatch import enqueue_campaign_run
from services.fleet_dispatch import enqueue_fleet_scenario, fleet_run_status


def build_campaign_fleet_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
) -> APIRouter:
    router = APIRouter()

    @router.post("/campaigns/{campaign_id}/run")
    async def api_run_campaign(campaign_id: str):
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Database is disabled; campaigns are not available"},
                status_code=503,
            )
        payload, status = await enqueue_campaign_run(campaign_id, queue)
        if status != 200:
            return JSONResponse(payload, status_code=status)
        return payload

    @router.post("/fleet/run")
    async def api_fleet_run(body: FleetRunRequest):
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
        )
        if status != 200:
            return JSONResponse(payload, status_code=status)
        return payload

    @router.get("/fleet/status")
    async def api_fleet_status(run_id: Optional[str] = None):
        return fleet_run_status(queue, run_id)

    return router
