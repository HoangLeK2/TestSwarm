"""
Public routes: `/ping` plus utility JSON under `/api/*` that must register
before the DB REST router (so `/api/devices/live` is not swallowed by `/api/devices/{device_id}`).
"""

from __future__ import annotations

import asyncio

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
_CONNECTING_LIVE_STATES = {"CONNECTING"}
_LIVE_DEVICE_INFO_KEY = "_live_device_info"


def _cap_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cap_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _live_device_aliases(serial: str, info: dict[str, object]) -> list[str]:
    aliases = info.get("relay_aliases")
    if isinstance(aliases, (list, tuple, set)):
        values = aliases
    else:
        values = [serial]

    out: list[str] = []
    for value in values:
        alias = str(value or "").strip()
        if alias and alias not in out:
            out.append(alias)

    serial = str(serial or "").strip()
    if serial and serial not in out:
        out.append(serial)
    return out


def _build_live_device_alias_index(
    allowed_devices: dict[str, dict[str, object]],
) -> dict[str, tuple[str, dict[str, object]]]:
    index: dict[str, tuple[str, dict[str, object]]] = {}
    for serial, info in allowed_devices.items():
        canonical_serial = str(serial or "").strip()
        if not canonical_serial:
            continue
        for alias in _live_device_aliases(canonical_serial, info):
            index[alias] = (canonical_serial, info)
    return index


def _match_live_device(
    runtime_serial: str,
    alias_index: dict[str, tuple[str, dict[str, object]]],
    *,
    relay=None,
) -> Optional[tuple[str, dict[str, object]]]:
    runtime_serial = str(runtime_serial or "").strip()
    if not runtime_serial:
        return None

    match = alias_index.get(runtime_serial)
    if match is not None:
        return match

    try:
        caps = relay.get_capabilities(runtime_serial) if relay is not None else None
    except Exception:
        caps = None
    if isinstance(caps, dict):
        hardware_serial = str(caps.get("hardware_serial") or "").strip()
        if hardware_serial:
            return alias_index.get(hardware_serial)
    return None


def _live_device_realtime_aliases(
    registered_serial: str,
    runtime_serial: str,
    info: dict[str, object],
) -> list[str]:
    aliases = _live_device_aliases(registered_serial, info)
    runtime_serial = str(runtime_serial or "").strip()
    if runtime_serial and runtime_serial not in aliases:
        aliases.append(runtime_serial)
    return aliases


def _relay_online_for_serial(serial: str, *, relay=None, ctrl=None) -> bool:
    serial = str(serial or "").strip()
    if not serial:
        return False
    try:
        if relay is not None and relay.relay_for_serial(serial):
            return True
    except Exception:
        pass
    try:
        if ctrl is not None and ctrl.conn_for_serial(serial):
            return True
    except Exception:
        pass
    return False


def _relay_online_for_live_device(
    serial: str,
    *,
    relay=None,
    ctrl=None,
    requires_relay: bool = False,
) -> bool:
    """Return the transport signal that should keep a live-grid device online."""
    if requires_relay:
        return _relay_online_for_serial(serial, ctrl=ctrl)
    return _relay_online_for_serial(serial, relay=relay, ctrl=ctrl)

def _relay_capabilities_for_serial(serial: str, *, relay=None) -> dict[str, object]:
    if relay is None:
        return {}
    try:
        caps = relay.get_capabilities(serial)
    except Exception:
        caps = None
    return caps if isinstance(caps, dict) else {}


def _resolve_relay_serial(serial: str, *, relay=None) -> str:
    serial = str(serial or "").strip()
    if not serial or relay is None:
        return serial
    try:
        resolved = str(relay.resolve_serial(serial) or "").strip()
    except Exception:
        resolved = ""
    return resolved or serial


def _relay_list_devices(relay=None) -> list[dict[str, object]]:
    if relay is None:
        return []
    try:
        devices = relay.list_devices()
    except Exception:
        return []
    if not isinstance(devices, list):
        return []
    return [device for device in devices if isinstance(device, dict)]


def _caps_match_registered_device(
    registered_serial: str,
    info: dict[str, object],
    runtime_serial: str,
    caps: dict[str, object],
) -> bool:
    aliases = {alias.lower() for alias in _live_device_aliases(registered_serial, info)}
    values = {
        runtime_serial,
        caps.get("serial"),
        caps.get("hardware_serial"),
        caps.get("device_serial"),
        caps.get("android_serial"),
        caps.get("adb_serial"),
    }
    wlan_ip = str(caps.get("wlan_ip") or "").strip()
    if wlan_ip:
        values.add(wlan_ip)
        values.add(f"{wlan_ip}:5555")
    return any(str(value or "").strip().lower() in aliases for value in values)


def _relay_candidate_serials_for_registered(
    registered_serial: str,
    info: dict[str, object],
    *,
    relay=None,
) -> list[str]:
    candidates: list[str] = []

    def add(serial: object) -> None:
        value = str(serial or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    for alias in _live_device_aliases(registered_serial, info):
        add(alias)
        add(_resolve_relay_serial(alias, relay=relay))

    for device in _relay_list_devices(relay):
        runtime_serial = str(device.get("serial") or "").strip()
        if not runtime_serial:
            continue
        if _caps_match_registered_device(
            registered_serial,
            info,
            runtime_serial,
            device,
        ):
            add(runtime_serial)

    return candidates


def _synthesize_live_device_from_relay(
    registered_serial: str,
    info: dict[str, object],
    *,
    relay=None,
    ctrl=None,
) -> Optional[dict]:
    """Build a live device row from relay/control state when DeviceManager lags."""
    runtime_serial = ""
    relay_online = False
    for candidate in _relay_candidate_serials_for_registered(
        registered_serial,
        info,
        relay=relay,
    ):
        if _relay_online_for_serial(candidate, relay=relay, ctrl=ctrl):
            runtime_serial = candidate
            relay_online = _relay_online_for_serial(candidate, relay=relay)
            break
    if not runtime_serial:
        return None

    caps = _relay_capabilities_for_serial(runtime_serial, relay=relay)
    if not caps:
        for alias in _live_device_aliases(registered_serial, info):
            caps = _relay_capabilities_for_serial(alias, relay=relay)
            if caps:
                break

    has_u2 = _cap_bool(caps.get("has_u2") or caps.get("u2_ready"))
    minitouch_ready = _cap_bool(caps.get("minitouch_ready"))
    agent_connected = _relay_online_for_serial(runtime_serial, ctrl=ctrl)
    brand = str(caps.get("brand") or "").strip()
    model = str(caps.get("model") or "").strip()
    touch_method = "u2" if has_u2 else "none"
    control_ready = agent_connected or has_u2 or minitouch_ready
    return {
        "type": "status",
        "serial": runtime_serial,
        "registered_serial": registered_serial,
        "name": info.get("name", ""),
        "display_name": info.get("display_name", runtime_serial),
        "brand": brand,
        "model": model,
        "state": "READY" if control_ready else "CONNECTING",
        "battery": -1,
        "current_app": "",
        "screen_width": _cap_int(caps.get("screen_width"), 1080),
        "screen_height": _cap_int(caps.get("screen_height"), 1920),
        "agent_connected": agent_connected,
        "u2_ready": has_u2,
        "minitouch_ready": minitouch_ready,
        "touch_method": touch_method,
        "stf_connected": relay_online,
        _LIVE_DEVICE_INFO_KEY: info,
    }


def _apply_realtime_connectivity(
    device: dict,
    *,
    relay_online: bool = False,
    requires_relay: bool = False,
) -> None:
    """Downshift stale runtime entries that no longer have any live transport."""
    state = str(device.get("state") or "").upper()
    agent_connected = bool(device.get("agent_connected"))
    u2_ready = bool(device.get("u2_ready"))
    minitouch_ready = bool(device.get("minitouch_ready"))
    touch_ready = u2_ready or minitouch_ready

    if requires_relay and not relay_online:
        device["state"] = "DISCONNECTED"
        device["agent_connected"] = False
        device["touch_method"] = "none"
        device["stf_connected"] = False
        return
    if requires_relay and relay_online:
        device["agent_connected"] = True
        agent_connected = True

    if state == "DEAD":
        if agent_connected or touch_ready:
            device["state"] = "READY"
        return
    if state in _OFFLINE_LIVE_STATES:
        if agent_connected or touch_ready:
            device["state"] = "READY"
        elif relay_online:
            device["state"] = "CONNECTING"
        return
    if state in _CONNECTING_LIVE_STATES:
        if agent_connected or touch_ready:
            device["state"] = "READY"
            return

    if requires_relay and not relay_online:
        device["state"] = "DISCONNECTED"
        device["agent_connected"] = False
        device["touch_method"] = "none"
        device["stf_connected"] = False
        return

    if agent_connected or touch_ready:
        return
    if relay_online:
        device["state"] = "CONNECTING"
        device["touch_method"] = "none"
        device["stf_connected"] = True
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


async def _get_live_device_map(
    request: Request, db_enabled: bool
) -> Optional[dict[str, dict[str, object]]]:
    if not db_enabled:
        return None

    state = getattr(request, "state", None)
    cached_auth = getattr(state, "auth", None)
    user_id = str(getattr(cached_auth, "user_id", "") or "").strip()
    if not user_id:
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
        org_id = getattr(state, "org_id", None)
        if org_id is None:
            org_id = await resolve_effective_org_id_for_user_id(request, db, user_id)
        db_devices = await repo.list_devices(db, org_id=org_id, user_id=user_id)
        out: dict[str, dict[str, object]] = {}
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


async def _enrich_live_manual_control_state(devices: list[dict]) -> None:
    try:
        from services import redis_store
        from services.manual_takeover import is_manual_takeover_active
    except Exception:
        return

    redis_client = redis_store.client() if redis_store.enabled() else None
    async def _enrich_one(d: dict) -> None:
        serial = str(d.get("serial") or "").strip()
        if not serial:
            return
        scenario_active = _cap_int(d.get("scenario_active"), 0)
        if redis_client is not None:
            try:
                raw = await redis_client.get(
                    redis_store.key(f"device:{serial}:scenario_active")
                )
                scenario_active = max(scenario_active, _cap_int(raw, 0))
            except Exception:
                pass
        d["scenario_active"] = scenario_active
        try:
            d["manual_takeover_active"] = bool(
                await is_manual_takeover_active(serial)
            )
        except Exception:
            d["manual_takeover_active"] = bool(d.get("manual_takeover_active"))

    await asyncio.gather(*(_enrich_one(d) for d in devices))


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
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            from runtime.transports.agent_control_servicer import get_control_servicer

            relay = get_relay_manager()
            ctrl = get_control_servicer()
        except Exception:
            relay = None
            ctrl = None

        allowed_devices = await _get_live_device_map(request, db_enabled)
        devices = [d.status_dict() for d in manager.all_devices()]
        if allowed_devices is not None:
            alias_index = _build_live_device_alias_index(allowed_devices)
            visible_devices = []
            seen_registered_serials = set()
            for d in devices:
                serial = str(d.get("serial") or "").strip()
                match = _match_live_device(serial, alias_index, relay=relay)
                if match is None:
                    continue
                registered_serial, info = match
                d["registered_serial"] = registered_serial
                d[_LIVE_DEVICE_INFO_KEY] = info
                d["name"] = info.get("name", "")
                d["display_name"] = info.get("display_name", d.get("serial", ""))
                visible_devices.append(d)
                seen_registered_serials.add(registered_serial)
            for registered_serial, info in allowed_devices.items():
                if registered_serial in seen_registered_serials:
                    continue
                relay_device = _synthesize_live_device_from_relay(
                    registered_serial,
                    info,
                    relay=relay,
                    ctrl=ctrl,
                )
                if relay_device is not None:
                    visible_devices.append(relay_device)
            devices = visible_devices

        await _enrich_live_manual_control_state(devices)

        for d in devices:
            serial = str(d.get("serial") or "")
            info = d.get(_LIVE_DEVICE_INFO_KEY, {}) if allowed_devices else {}
            if not isinstance(info, dict):
                info = {}
            requires_relay = bool(info.get("requires_relay"))
            aliases = _live_device_realtime_aliases(
                str(d.get("registered_serial") or serial),
                serial,
                info,
            )
            relay_online = any(
                _relay_online_for_live_device(
                    str(alias),
                    relay=relay,
                    ctrl=ctrl,
                    requires_relay=requires_relay,
                )
                for alias in aliases
            )
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
            serials = [
                str(d.get("registered_serial") or d.get("serial") or "")
                for d in devices
                if d.get("registered_serial") or d.get("serial")
            ]
            try:
                async with AsyncSessionLocal() as db:
                    pref_map = await repo.get_relay_scrcpy_enabled_map(db, serials)
                for d in devices:
                    s = str(d.get("registered_serial") or d.get("serial") or "")
                    d["relay_scrcpy_enabled"] = pref_map.get(s, True)
            except Exception:
                for d in devices:
                    d["relay_scrcpy_enabled"] = True
        for d in devices:
            d.pop(_LIVE_DEVICE_INFO_KEY, None)
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
                getattr(st, "auto_attach_scrcpy_on_connect", False)
            )
            out["streaming_dashboard_preview_mjpeg"] = bool(
                getattr(st, "dashboard_grid_preview_mjpeg", True)
            )
            out["streaming_auto_attach_scrcpy_on_relay_online"] = bool(
                getattr(st, "auto_attach_scrcpy_on_relay_online", False)
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
