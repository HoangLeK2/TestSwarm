"""
Public routes: `/ping` plus utility JSON under `/api/*` that must register
before the DB REST router (so `/api/devices/live` is not swallowed by `/api/devices/{device_id}`).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt

from api.deps import require_request_permission, resolve_effective_org_id_for_user_id
from core.config import Config
from core.security import jwt_algorithm, jwt_secret_key
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager, TaskQueue


_OFFLINE_LIVE_STATES = {"DISCONNECTED", "DEAD"}


def _apply_realtime_connectivity(
    device: dict,
    *,
    relay_online: bool = False,
    requires_relay: bool = False,
) -> None:
    """Downshift stale runtime entries that no longer have any live transport."""
    state = str(device.get("state") or "").upper()
    if state in _OFFLINE_LIVE_STATES:
        return

    if requires_relay and not relay_online:
        device["state"] = "DISCONNECTED"
        device["touch_method"] = "none"
        device["stf_connected"] = False
        return

    agent_connected = bool(device.get("agent_connected"))
    u2_ready = bool(device.get("u2_ready"))
    if agent_connected or u2_ready or relay_online:
        return

    device["state"] = "DISCONNECTED"
    device["touch_method"] = "none"
    device["stf_connected"] = False


def _verify_token_only(request: Request) -> None:
    """Verify JWT is present and valid. Always enforced regardless of db_enabled.
    Does NOT query the DB — use for endpoints where identity is needed but no
    per-resource ownership check is required."""
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


async def _get_live_device_map(request: Request, db_enabled: bool) -> Optional[dict[str, dict[str, str]]]:
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
        org_id = await resolve_effective_org_id_for_user_id(request, db, user_id)
        db_devices = await repo.list_devices(db, org_id=org_id, user_id=user_id)
        out: dict[str, dict[str, str]] = {}
        for device in db_devices:
            serial = str(getattr(device, "serial", "") or "").strip()
            if not serial:
                continue
            name = str(getattr(device, "name", "") or "").strip()
            brand = str(getattr(device, "brand", "") or "").strip()
            model = str(getattr(device, "model", "") or "").strip()
            display_name = name or " ".join(p for p in [brand, model] if p).strip() or serial
            aliases = {serial}
            adb_serial = str(getattr(device, "adb_serial", "") or "").strip()
            if adb_serial:
                aliases.add(adb_serial)
            adb_ip = str(getattr(device, "adb_ip", "") or "").strip()
            adb_port = int(getattr(device, "adb_port", 5555) or 5555)
            if adb_ip:
                aliases.add(adb_ip)
                aliases.add(f"{adb_ip}:{adb_port}")
            out[serial] = {
                "name": name,
                "display_name": display_name,
                "requires_relay": bool(adb_serial or adb_ip),
                "relay_aliases": sorted(aliases),
            }
        return out


async def _get_live_allowed_serials(request: Request, db_enabled: bool) -> Optional[set[str]]:
    device_map = await _get_live_device_map(request, db_enabled)
    if device_map is None:
        return None
    return set(device_map.keys())


def build_public_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
    db_enabled: bool,
) -> APIRouter:
    router = APIRouter()
    devices_read = require_request_permission(db_enabled, "devices", "read")
    executions_read = require_request_permission(db_enabled, "executions", "read")

    @router.get("/ping")
    async def ping():
        return {"ok": True, "service": "device-farm"}

    api = APIRouter(prefix="/api")

    @api.get("/devices/live", dependencies=[Depends(devices_read)])
    async def api_devices_live(
        request: Request,
        state: Optional[str] = None,
        model: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ):
        allowed_devices = await _get_live_device_map(request, db_enabled)
        devices = [d.status_dict() for d in manager.all_devices()]
        if allowed_devices is not None:
            devices = [d for d in devices if d.get("serial") in allowed_devices]
            for d in devices:
                info = allowed_devices.get(str(d.get("serial") or ""), {})
                d["name"] = info.get("name", "")
                d["display_name"] = info.get("display_name", d.get("serial", ""))
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            from runtime.transports.agent_control_servicer import get_control_servicer

            relay = get_relay_manager()
            ctrl = get_control_servicer()
        except Exception:
            relay = None
            ctrl = None

        def _relay_online_for_serial(serial: str) -> bool:
            serial = str(serial or "").strip()
            if not serial:
                return False
            if relay is not None and relay.relay_for_serial(serial):
                return True
            if ctrl is not None and ctrl.conn_for_serial(serial):
                return True
            return False

        for d in devices:
            serial = str(d.get("serial") or "")
            info = allowed_devices.get(serial, {}) if allowed_devices else {}
            requires_relay = bool(info.get("requires_relay"))
            aliases = info.get("relay_aliases") or ([serial] if serial else [])
            relay_online = any(_relay_online_for_serial(str(alias)) for alias in aliases)
            _apply_realtime_connectivity(
                d,
                relay_online=relay_online,
                requires_relay=requires_relay,
            )
        store = getattr(request.app.state, "session_store", None)
        for d in devices:
            serial = d.get("serial", "")
            d["usage_state"] = store.get_usage(serial) if store else "idle"
        if db_enabled and devices:
            serials = [str(d.get("serial") or "") for d in devices if d.get("serial")]
            try:
                async with AsyncSessionLocal() as db:
                    pref_map = await repo.get_relay_scrcpy_enabled_map(db, serials)
                for d in devices:
                    s = str(d.get("serial") or "")
                    d["relay_scrcpy_enabled"] = pref_map.get(s, True)
            except Exception:
                for d in devices:
                    d["relay_scrcpy_enabled"] = True
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
        st = getattr(config, "streaming", None)
        if st is not None:
            out["streaming_mode"] = getattr(st, "mode", "periodic")
            out["streaming_auto_attach_scrcpy"] = bool(
                getattr(st, "auto_attach_scrcpy_on_connect", True)
            )
            out["streaming_dashboard_preview_mjpeg"] = bool(
                getattr(st, "dashboard_grid_preview_mjpeg", True)
            )
            out["streaming_auto_attach_scrcpy_on_relay_online"] = bool(
                getattr(st, "auto_attach_scrcpy_on_relay_online", True)
            )
        dev = getattr(config, "device", None)
        if dev is not None:
            out["scrcpy_max_fps"] = getattr(dev, "scrcpy_max_fps", 30)
        return out

    @api.get("/events", dependencies=[Depends(devices_read)])
    async def api_events(
        request: Request,
        serial: Optional[str] = None,
        event: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Return device events — from DB if available, else in-memory buffer."""
        _verify_token_only(request)
        allowed_serials = await _get_live_allowed_serials(request, db_enabled)

        # Try DB first (persistent history)
        if db_enabled:
            try:
                from db.models.device_event import DeviceEvent
                from sqlalchemy import select, func, desc

                async with AsyncSessionLocal() as db:
                    if allowed_serials is not None and not allowed_serials:
                        return {"total": 0, "offset": offset, "limit": limit, "events": []}
                    if allowed_serials is not None and serial and serial not in allowed_serials:
                        return {"total": 0, "offset": offset, "limit": limit, "events": []}
                    q = select(DeviceEvent)
                    count_q = select(func.count(DeviceEvent.id))
                    if allowed_serials is not None:
                        q = q.where(DeviceEvent.serial.in_(allowed_serials))
                        count_q = count_q.where(DeviceEvent.serial.in_(allowed_serials))
                    if serial:
                        q = q.where(DeviceEvent.serial == serial)
                        count_q = count_q.where(DeviceEvent.serial == serial)
                    if event:
                        q = q.where(DeviceEvent.event == event)
                        count_q = count_q.where(DeviceEvent.event == event)
                    total = (await db.execute(count_q)).scalar() or 0
                    rows = (
                        await db.execute(
                            q.order_by(desc(DeviceEvent.created_at))
                            .offset(offset)
                            .limit(limit)
                        )
                    ).scalars().all()
                    events_out = [
                        {
                            "id": r.id,
                            "serial": r.serial,
                            "event": r.event,
                            "reason": r.reason,
                            "old_state": r.old_state,
                            "new_state": r.new_state,
                            "device_model": r.device_model,
                            "device_brand": r.device_brand,
                            "extra_data": r.extra_data,
                            "created_at": r.created_at.isoformat() if r.created_at else None,
                        }
                        for r in rows
                    ]
                    return {"total": total, "offset": offset, "limit": limit, "events": events_out}
            except Exception:
                pass  # fallback to in-memory

        # Fallback: in-memory buffer
        recorder = getattr(request.app.state, "event_recorder", None)
        if recorder is None:
            return {"total": 0, "offset": offset, "limit": limit, "events": []}
        events = recorder.get_recent(limit=limit + offset, serial=serial, event_type=event)
        if allowed_serials is not None:
            events = [
                item for item in events
                if str(item.get("serial") or "") in allowed_serials
            ]
        total = len(events)
        events = events[offset : offset + limit]
        return {"total": total, "offset": offset, "limit": limit, "events": events}

    @api.get("/tasks", dependencies=[Depends(executions_read)])
    async def api_tasks(
        request: Request,
        ids: Optional[str] = None,
        name_prefix: Optional[str] = None,
    ):
        # Always require a valid JWT — task list is never public.
        _verify_token_only(request)
        all_tasks = queue.all_tasks()
        # In DB mode, restrict to tasks targeting the user's own devices.
        # Tasks with target=None (any-device / fleet) are visible to all authed users.
        if db_enabled:
            allowed_serials = await _get_live_allowed_serials(request, db_enabled)
            if allowed_serials is not None:
                all_tasks = [
                    t for t in all_tasks
                    if t.target is None or t.target in allowed_serials
                ]
        if ids:
            want = {x.strip() for x in ids.split(",") if x.strip()}
            all_tasks = [t for t in all_tasks if t.id in want]
        if name_prefix:
            all_tasks = [t for t in all_tasks if t.name.startswith(name_prefix)]
        return [t.to_dict() for t in all_tasks]

    router.include_router(api)
    return router
