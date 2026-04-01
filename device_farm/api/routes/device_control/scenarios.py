"""Scenario preview/run on device or via MCP session."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from api.schemas.device_control import ScenarioPreviewRequest
from common.session_lock import SessionLockStore
from core.config import Config
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager


def run_scenario_on_device(
    manager: DeviceManager, serial: str, steps: List[Dict[str, Any]],
    on_step_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from tasks.scenario_task import run_scenario_task

    device = manager.get_device(serial)
    if not device:
        return {"error": f"Device {serial} not found"}
    if not steps:
        return {"error": "steps must be a non-empty array"}
    scenario: Dict[str, Any] = {"instructions": "", "steps": steps, "variables": variables or {}}
    return run_scenario_task(device, scenario, on_step_done=on_step_done)


async def _execute_scenario_body(
    manager: DeviceManager, serial: str, body: ScenarioPreviewRequest
):
    if not body.steps:
        return JSONResponse(
            {"error": "steps must be a non-empty array"},
            status_code=400,
        )
    loop = asyncio.get_running_loop()
    import functools
    fn = functools.partial(run_scenario_on_device, manager, serial, body.steps, None, body.variables)
    result = await loop.run_in_executor(None, fn)
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

    @router.post("/devices/{serial}/scenario/preview-stream")
    async def api_scenario_preview_stream(serial: str, body: ScenarioPreviewRequest):
        """
        SSE endpoint: streams step results as they complete.
        Each event is a JSON object with the step result.
        Final event has type "done" with full summary.
        """
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        if not body.steps:
            return JSONResponse({"error": "steps must be a non-empty array"}, status_code=400)

        # Queue for thread→async communication
        q: queue.Queue[Dict[str, Any] | None] = queue.Queue()

        def on_step_done(result: Dict[str, Any]) -> None:
            q.put(result)

        def run_in_thread() -> None:
            try:
                final = run_scenario_on_device(manager, serial, body.steps, on_step_done=on_step_done, variables=body.variables)
                q.put({"_event": "done", **final})
            except Exception as exc:
                q.put({"_event": "error", "error": str(exc)})
            finally:
                q.put(None)  # sentinel

        # Start execution in background thread
        threading.Thread(target=run_in_thread, daemon=True).start()

        async def event_generator():
            total_steps = len(body.steps)
            yield f"data: {json.dumps({'event': 'start', 'total_steps': total_steps})}\n\n"
            while True:
                # Poll queue with small sleep to avoid blocking event loop
                try:
                    item = await asyncio.get_event_loop().run_in_executor(None, q.get, True, 0.1)
                except queue.Empty:
                    continue
                if item is None:
                    break
                if "_event" in item:
                    evt_type = item.pop("_event")
                    yield f"data: {json.dumps({'event': evt_type, **item})}\n\n"
                else:
                    yield f"data: {json.dumps({'event': 'step_done', **item})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
        import functools
        fn = functools.partial(run_scenario_on_device, manager, device_id, body.steps, None, body.variables)
        result = await loop.run_in_executor(None, fn)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return {"session_id": session_id, "device_id": device_id, **result}

    return router
