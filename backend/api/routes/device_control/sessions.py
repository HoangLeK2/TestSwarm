"""MCP session lifecycle, reserve/release."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from api.auth import policy
from api.deps import caller_auth_from_request
from api.schemas.device_control import EndSessionRequest, StartSessionRequest
from common.session_lock import SessionLockStore
from core.config import Config
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager

log = logging.getLogger(__name__)


def _policy_exception_response(exc: BaseException, *, context: str) -> JSONResponse:
    """Map a policy-path exception to an HTTP response without swallowing infra errors.

    HTTPException -> pass through with its status_code + detail.
    Anything else -> 503 (infra) + structured log so operators see the real cause.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code
        )
    log.exception("%s: infrastructure error", context)
    return JSONResponse(
        {"error": "Backend unavailable", "context": context}, status_code=503
    )


def build_sessions_router(
    manager: DeviceManager,
    config: Config,
    session_store: SessionLockStore,
) -> APIRouter:
    router = APIRouter()

    @router.post("/sessions/start")
    async def api_sessions_start(body: StartSessionRequest, request: Request):
        ctx = caller_auth_from_request(request)
        if ctx is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        # DB is authoritative for session ownership. In lab mode (no DB) we
        # refuse session writes — the single-tenant API key dep already
        # gated the HTTP request, but sessions need a user_id we don't have.
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Session API requires database (multi-user) mode"},
                status_code=501,
            )

        device = manager.get_device(body.device_id)
        if not device:
            return JSONResponse({"error": f"Device {body.device_id} not found"}, status_code=404)

        try:
            owns = await policy.user_owns_device(ctx, body.device_id)
        except HTTPException as exc:
            return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
        except Exception as exc:
            return _policy_exception_response(exc, context="user_owns_device")
        if not owns:
            return JSONResponse(
                {"error": "Not authorized to start a session on this device"},
                status_code=403,
            )

        usage = session_store.get_usage(body.device_id)
        if usage not in ("idle", "reserved"):
            return JSONResponse(
                {"error": f"Device in use (usage_state={usage}). Reserve or wait."},
                status_code=409,
            )
        session_id = str(uuid.uuid4())
        # DB first, then mirror to cache — if DB fails, memory state doesn't
        # drift (cache stays idle so the device can be retried).
        async with AsyncSessionLocal() as db:
            try:
                await repo.create_mcp_session(
                    db, session_id, body.device_id, ctx.user_id
                )
                await db.commit()
            except Exception:
                await db.rollback()
                log.exception("sessions_start: DB write failed")
                return JSONResponse(
                    {"error": "Failed to persist session"}, status_code=503
                )
        session_store.start_session(body.device_id, session_id, user_id=ctx.user_id)
        return {"session_id": session_id, "device_id": body.device_id}

    @router.post("/sessions/end")
    async def api_sessions_end(body: EndSessionRequest, request: Request):
        ctx = caller_auth_from_request(request)
        if ctx is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Session API requires database (multi-user) mode"},
                status_code=501,
            )

        # Ownership check: HTTPException → pass-through; anything else is
        # infra (DB timeout, connection reset) and must surface as 503, not 404.
        try:
            await policy.assert_owns_session(ctx, body.session_id)
        except HTTPException as exc:
            return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
        except Exception as exc:
            return _policy_exception_response(exc, context="assert_owns_session")

        # DB first — mark ended. Only clear the cache on success.
        async with AsyncSessionLocal() as db:
            try:
                await repo.end_mcp_session(db, body.session_id)
                await db.commit()
            except Exception:
                await db.rollback()
                log.exception("sessions_end: DB write failed")
                return JSONResponse(
                    {"error": "Failed to persist session end"}, status_code=503
                )
        serial = session_store.end_session(body.session_id)
        return {"ok": True, "device_id": serial}

    @router.get("/sessions/{session_id}")
    async def api_sessions_get(session_id: str, request: Request):
        ctx = caller_auth_from_request(request)
        if ctx is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)
        if not config.database.enabled:
            return JSONResponse(
                {"error": "Session API requires database (multi-user) mode"},
                status_code=501,
            )
        try:
            device_serial = await policy.assert_owns_session(ctx, session_id)
        except HTTPException as exc:
            return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
        except Exception as exc:
            return _policy_exception_response(exc, context="assert_owns_session")
        return {"session_id": session_id, "device_id": device_serial, "status": "active"}

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
