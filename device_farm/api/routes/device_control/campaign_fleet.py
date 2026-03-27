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
