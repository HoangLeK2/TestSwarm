"""Task queue introspection, generic task enqueue, agent shell."""

from __future__ import annotations

import asyncio
from typing import Callable, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import TaskRequest
from runtime.core import DeviceManager, Task, TaskQueue


def build_tasks_queue_router(manager: DeviceManager, queue: TaskQueue) -> APIRouter:
    router = APIRouter()

    @router.get("/tasks/{task_id}")
    async def api_get_task(task_id: str):
        task = queue.get_task(task_id)
        if task is None:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        return {
            "id": task.id,
            "name": task.name,
            "status": task.status.value,
            "target": task.target,
            "created_at": task.created_at,
        }

    @router.post("/agent/{serial}/shell")
    async def api_shell(serial: str, body: dict):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        cmd = body.get("cmd", "").strip()
        if not cmd:
            return JSONResponse({"error": "cmd is required"}, status_code=400)
        from runtime.transports.adb_relay_server import get_relay_manager
        relay = get_relay_manager()
        if relay and relay.relay_for_serial(serial):
            try:
                actual = relay.resolve_serial(serial)
                output = await relay.adb_shell(actual, cmd, timeout=30.0)
                return {"ok": True, "cmd": cmd, "output": output or ""}
            except Exception as exc:
                return JSONResponse({"error": str(exc)}, status_code=500)
        if device._agent_send is None:
            return JSONResponse({"error": "Agent not connected"}, status_code=503)
        device._send_to_agent({"type": "shell", "cmd": cmd})
        return {"ok": True, "cmd": cmd, "output": None, "note": "output not available in agent mode"}

    @router.post("/task")
    async def api_enqueue_task(body: TaskRequest):
        from tasks.example_task import demo_u2_task

        fn_map: Dict[str, Callable] = {
            "example": demo_u2_task,
        }
        fn = fn_map.get(body.fn_name)
        if not fn:
            return JSONResponse({"error": f"Unknown task: {body.fn_name}"}, status_code=400)

        task = Task(
            fn=fn,
            priority=body.priority,
            target=body.target,
            timeout=body.timeout,
            max_retries=body.max_retries,
            name=body.fn_name,
        )
        queue.put(task)
        return {"id": task.id, "status": task.status.value}

    return router
