"""MCP session lifecycle, reserve/release."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import EndSessionRequest, StartSessionRequest
from common.session_lock import SessionLockStore
from core.config import Config
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager


def build_sessions_router(
    manager: DeviceManager,
    config: Config,
    session_store: SessionLockStore,
) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions/start")
    async def api_sessions_start(body: StartSessionRequest):
        device = manager.get_device(body.device_id)
        if not device:
            return JSONResponse({"error": f"Device {body.device_id} not found"}, status_code=404)
        usage = session_store.get_usage(body.device_id)
        if usage not in ("idle", "reserved"):
            return JSONResponse(
                {"error": f"Device in use (usage_state={usage}). Reserve or wait."},
                status_code=409,
            )
        session_id = str(uuid.uuid4())
        session_store.start_session(body.device_id, session_id)
        if config.database.enabled:
            async with AsyncSessionLocal() as db:
                try:
                    await repo.create_mcp_session(
                        db, session_id, body.device_id, body.user_id
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
        return {"session_id": session_id, "device_id": body.device_id}

    @router.post("/sessions/end")
    async def api_sessions_end(body: EndSessionRequest):
        serial = session_store.end_session(body.session_id)
        if serial is None:
            return JSONResponse({"error": "Session not found or already ended"}, status_code=404)
        if config.database.enabled:
            async with AsyncSessionLocal() as db:
                try:
                    await repo.end_mcp_session(db, body.session_id)
                    await db.commit()
                except Exception:
                    await db.rollback()
        return {"ok": True, "device_id": serial}

    @router.get("/sessions/{session_id}")
    async def api_sessions_get(session_id: str):
        device_id = session_store.get_device_for_session(session_id)
        if device_id is None and config.database.enabled:
            async with AsyncSessionLocal() as db:
                row = await repo.get_mcp_session(db, session_id)
                if row and row.status == "active":
                    device_id = row.device_serial
        if device_id is None:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return {"session_id": session_id, "device_id": device_id, "status": "active"}

    @router.post("/devices/{serial}/reserve")
    async def api_devices_reserve(serial: str):
        if not manager.get_device(serial):
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        if not session_store.reserve_device(serial):
            return JSONResponse(
                {"error": "Device not idle (already reserved or in session)"},
                status_code=409,
            )
        return {"ok": True, "device_id": serial, "usage_state": "reserved"}

    @router.post("/devices/{serial}/release")
    async def api_devices_release(serial: str):
        if not manager.get_device(serial):
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        session_store.release_device(serial)
        return {"ok": True, "device_id": serial, "usage_state": "idle"}

    return router
