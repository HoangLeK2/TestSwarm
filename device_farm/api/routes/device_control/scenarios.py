"""Scenario preview/run on device or via MCP session."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import ScenarioPreviewRequest
from common.session_lock import SessionLockStore
from core.config import Config
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager


def run_scenario_on_device(
    manager: DeviceManager, serial: str, steps: List[Dict[str, Any]]
) -> Dict[str, Any]:
    from tasks.scenario_task import run_scenario_task

    device = manager.get_device(serial)
    if not device:
        return {"error": f"Device {serial} not found"}
    if not steps:
        return {"error": "steps must be a non-empty array"}
    scenario: Dict[str, Any] = {"instructions": "", "steps": steps}
    return run_scenario_task(device, scenario)


async def _execute_scenario_body(
    manager: DeviceManager, serial: str, body: ScenarioPreviewRequest
):
    if not body.steps:
        return JSONResponse(
            {"error": "steps must be a non-empty array"},
            status_code=400,
        )
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, run_scenario_on_device, manager, serial, body.steps)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


def build_scenarios_router(
    manager: DeviceManager,
    config: Config,
    session_store: SessionLockStore,
) -> APIRouter:
    router = APIRouter()

    @router.post("/devices/{serial}/scenario/preview")
    async def api_scenario_preview(serial: str, body: ScenarioPreviewRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        return await _execute_scenario_body(manager, serial, body)

    @router.post("/devices/{serial}/scenario/run")
    async def api_scenario_run(serial: str, body: ScenarioPreviewRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        return await _execute_scenario_body(manager, serial, body)

    @router.post("/sessions/{session_id}/scenario/run")
    async def api_sessions_scenario_run(session_id: str, body: ScenarioPreviewRequest):
        device_id = session_store.get_device_for_session(session_id)
        if device_id is None and config.database.enabled:
            async with AsyncSessionLocal() as db:
                row = await repo.get_mcp_session(db, session_id)
                if row and row.status == "active":
                    device_id = row.device_serial
        if not device_id:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        if not body.steps:
            return JSONResponse(
                {"error": "steps must be a non-empty array"},
                status_code=400,
            )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, run_scenario_on_device, manager, device_id, body.steps
        )
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return {"session_id": session_id, "device_id": device_id, **result}

    return router
