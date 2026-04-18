"""Scenario preview/run on device or via MCP session."""

from __future__ import annotations

import asyncio
import json
import logging
import importlib
import queue
import threading
from uuid import uuid4
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt

from api.schemas.device_control import ScenarioPreviewRequest
from common.session_lock import SessionLockStore
from core.config import Config
from core.security import jwt_algorithm, jwt_secret_key
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager

log = logging.getLogger(__name__)
trace_log = importlib.import_module("structlog").get_logger("scenario_trace")


def run_scenario_on_device(
    manager: DeviceManager, serial: str, steps: List[Dict[str, Any]],
    on_step_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    variables: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    trace_source: str = "api.preview",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    from tasks.scenario_task import run_scenario_task

    device = manager.get_device(serial)
    if not device:
        return {"error": f"Device {serial} not found"}
    if not steps:
        return {"error": "steps must be a non-empty array"}
    scenario: Dict[str, Any] = {
        "instructions": "",
        "steps": steps,
        "variables": variables or {},
        "_trace_id": trace_id or f"scn-{uuid4().hex[:10]}",
        "_trace_source": trace_source,
        "_campaign_vars": {"__USER_ID__": str(user_id)} if user_id else {},
    }
    return run_scenario_task(device, scenario, on_step_done=on_step_done)


def _resolve_user_id_from_request(request: Request) -> Optional[str]:
    auth_header = (request.headers.get("authorization") or "").strip()
    raw_token = ""
    if auth_header.lower().startswith("bearer "):
        raw_token = auth_header[7:].strip()
    if not raw_token:
        raw_token = str(request.query_params.get("token") or "").strip()
    if not raw_token:
        return None
    try:
        payload = jwt.decode(raw_token, jwt_secret_key(), algorithms=[jwt_algorithm()])
        user_id = str(payload.get("sub") or "").strip()
        token_type = payload.get("type")
        if not user_id or token_type == "refresh":
            return None
        return user_id
    except JWTError:
        return None


async def _execute_scenario_body(
    manager: DeviceManager,
    serial: str,
    body: ScenarioPreviewRequest,
    trace_source: str = "api.preview",
    user_id: Optional[str] = None,
):
    if not body.steps:
        return JSONResponse(
            {"error": "steps must be a non-empty array"},
            status_code=400,
        )
    loop = asyncio.get_running_loop()
    import functools
    trace_id = f"scn-{uuid4().hex[:10]}"
    trace_log.info(
        "scenario_request",
        trace_id=trace_id,
        serial=serial,
        source=trace_source,
        total_steps=len(body.steps),
    )
    fn = functools.partial(
        run_scenario_on_device,
        manager,
        serial,
        body.steps,
        None,
        body.variables,
        trace_id,
        trace_source,
        user_id,
    )
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
    async def api_scenario_preview(serial: str, body: ScenarioPreviewRequest, request: Request):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        user_id = _resolve_user_id_from_request(request)
        return await _execute_scenario_body(
            manager, serial, body, trace_source="api.preview", user_id=user_id
        )

    @router.post("/devices/{serial}/scenario/preview-stream")
    async def api_scenario_preview_stream(serial: str, body: ScenarioPreviewRequest, request: Request):
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
        trace_id = f"scn-{uuid4().hex[:10]}"
        trace_log.info(
            "scenario_stream_request",
            trace_id=trace_id,
            serial=serial,
            source="api.preview_stream",
            total_steps=len(body.steps),
        )
        user_id = _resolve_user_id_from_request(request)

        # Queue for thread→async communication
        q: queue.Queue[Dict[str, Any] | None] = queue.Queue()

        def on_step_done(result: Dict[str, Any]) -> None:
            q.put(result)

        def run_in_thread() -> None:
            try:
                final = run_scenario_on_device(
                    manager,
                    serial,
                    body.steps,
                    on_step_done=on_step_done,
                    variables=body.variables,
                    trace_id=trace_id,
                    trace_source="api.preview_stream",
                    user_id=user_id,
                )
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
    async def api_scenario_run(serial: str, body: ScenarioPreviewRequest, request: Request):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        user_id = _resolve_user_id_from_request(request)
        return await _execute_scenario_body(
            manager, serial, body, trace_source="api.run", user_id=user_id
        )

    @router.post("/sessions/{session_id}/scenario/run")
    async def api_sessions_scenario_run(session_id: str, body: ScenarioPreviewRequest, request: Request):
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
        trace_id = f"scn-{uuid4().hex[:10]}"
        trace_log.info(
            "scenario_session_request",
            trace_id=trace_id,
            serial=device_id,
            source="api.session_run",
            total_steps=len(body.steps),
            session_id=session_id,
        )
        user_id = _resolve_user_id_from_request(request)
        fn = functools.partial(
            run_scenario_on_device,
            manager,
            device_id,
            body.steps,
            None,
            body.variables,
            trace_id,
            "api.session_run",
            user_id,
        )
        result = await loop.run_in_executor(None, fn)
        if "error" in result:
            return JSONResponse(result, status_code=400)
        return {"session_id": session_id, "device_id": device_id, **result}

    return router
