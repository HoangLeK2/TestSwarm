"""
Public routes: `/ping` plus utility JSON under `/api/*` that must register
before the DB REST router (so `/api/devices/live` is not swallowed by `/api/devices/{device_id}`).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from jose import JWTError, jwt

from core.config import Config
from core.security import jwt_algorithm, jwt_secret_key
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager, TaskQueue


async def _get_live_allowed_serials(request: Request, db_enabled: bool) -> Optional[set[str]]:
    if not db_enabled:
        return None

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, jwt_secret_key(), algorithms=[jwt_algorithm()])
        user_id = str(payload.get("sub") or "").strip()
        token_type = payload.get("type")
        if not user_id or token_type == "refresh":
            raise HTTPException(status_code=401, detail="Invalid or expired token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with AsyncSessionLocal() as db:
        db_devices = await repo.list_devices(db, user_id=user_id)
        return {d.serial for d in db_devices if d.serial}


def build_public_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
    db_enabled: bool,
) -> APIRouter:
    router = APIRouter()

    @router.get("/ping")
    async def ping():
        return {"ok": True, "service": "device-farm"}

    api = APIRouter(prefix="/api")

    @api.get("/devices/live")
    async def api_devices_live(
        request: Request,
        state: Optional[str] = None,
        model: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ):
        allowed_serials = await _get_live_allowed_serials(request, db_enabled)
        devices = [d.status_dict() for d in manager.all_devices()]
        if allowed_serials is not None:
            devices = [d for d in devices if d.get("serial") in allowed_serials]
        store = getattr(request.app.state, "session_store", None)
        for d in devices:
            serial = d.get("serial", "")
            d["usage_state"] = store.get_usage(serial) if store else "idle"
        if state:
            devices = [d for d in devices if d.get("state", "").upper() == state.upper()]
        if model:
            devices = [d for d in devices if model.lower() in (d.get("model") or "").lower()]
        total = len(devices)
        if offset:
            devices = devices[offset:]
        if limit is not None:
            devices = devices[:limit]
        return {"total": total, "offset": offset, "limit": limit, "devices": devices}

    @api.get("/config")
    async def api_config():
        out: dict[str, object] = {}
        wd = getattr(config, "wifi_densepose", None)
        if wd and getattr(wd, "enabled", False) and getattr(wd, "url", None):
            out["wifi_densepose_url"] = wd.url
        return out

    @api.get("/tasks")
    async def api_tasks(ids: Optional[str] = None, name_prefix: Optional[str] = None):
        all_tasks = queue.all_tasks()
        if ids:
            want = {x.strip() for x in ids.split(",") if x.strip()}
            all_tasks = [t for t in all_tasks if t.id in want]
        if name_prefix:
            all_tasks = [t for t in all_tasks if t.name.startswith(name_prefix)]
        return [t.to_dict() for t in all_tasks]

    router.include_router(api)
    return router
