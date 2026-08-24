"""
Public routes: `/ping` plus utility JSON under `/api/*` that must register
before the DB REST router (so `/api/devices/live` is not swallowed by `/api/devices/{device_id}`).
"""

from __future__ import annotations

from datetime import datetime, timezone
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


def _device_health_projection(
    device: dict[str, object],
    *,
    heartbeat_at: object = None,
    evaluated_at: Optional[datetime] = None,
) -> dict[str, object]:
    """Return one operator-facing status projection without removing legacy fields."""
    now = evaluated_at or datetime.now(timezone.utc)
    state = str(device.get("state") or "UNKNOWN").upper()
    agent_connected = bool(device.get("agent_connected"))
    transport_connected = bool(device.get("stf_connected"))
    control_connected = agent_connected or transport_connected
    busy = (
        state == "BUSY"
        or str(device.get("usage_state") or "idle").lower() != "idle"
        or _cap_int(device.get("scenario_active"), 0) > 0
    )
    command_ready = control_connected and state not in _OFFLINE_LIVE_STATES

    media_connected = bool(device.get("media_adapter_connected"))
    stream_active = bool(device.get("media_stream_active"))
    stream_connected = bool(device.get("media_stream_connected"))
    last_frame_ms = _cap_int(device.get("media_stream_last_frame_unix_ms"), 0)
    if stream_active and stream_connected:
        stream_status = "ready"
        stream_reason = None
    elif media_connected:
        stream_status = "starting"
        stream_reason = "waiting_first_frame"
    elif control_connected:
        stream_status = "unavailable"
        stream_reason = "media_channel_unavailable"
    else:
        stream_status = "unavailable"
        stream_reason = "device_offline"

    if not control_connected or state in _OFFLINE_LIVE_STATES:
        overall = "offline"
        command_status = "unavailable"
        reason_codes = ["agent_offline"]
    elif busy:
        overall = "busy"
        command_status = "busy"
        reason_codes = ["device_busy"]
    elif command_ready:
        overall = "ready"
        command_status = "ready"
        reason_codes = []
    else:
        overall = "degraded"
        command_status = "unavailable"
        reason_codes = ["command_channel_unavailable"]

    heartbeat = heartbeat_at.isoformat() if hasattr(heartbeat_at, "isoformat") else heartbeat_at
    evaluated = now.isoformat()
    last_signal_at = evaluated if control_connected else heartbeat
    return {
        "overall": overall,
        "agent": {
            "status": "online" if control_connected else "offline",
            "observed_at": last_signal_at,
            "reason": None if control_connected else "agent_offline",
        },
        "stream": {
            "status": stream_status,
            "observed_at": (
                datetime.fromtimestamp(last_frame_ms / 1000, tz=timezone.utc).isoformat()
                if last_frame_ms > 0
                else None
            ),
            "reason": stream_reason,
        },
        "command": {
            "status": command_status,
            "reason": reason_codes[0] if reason_codes else None,
        },
        "heartbeat_at": heartbeat,
        "last_signal_at": last_signal_at,
        "last_signal_source": "live_transport" if control_connected else "heartbeat",
        "evaluated_at": evaluated,
        "reason_codes": reason_codes,
    }


def _cap_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _cap_int(value: object, default: int) -> int:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _cap_positive_int(value: object, default: int = 0) -> int:
    parsed = _cap_int(value, 0)
    return parsed if parsed > 0 else default


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


def _media_adapter_control():
    try:
        from runtime.transports.media_adapter_control_servicer import (
            get_media_adapter_servicer,
        )
    except Exception:
        return None
    try:
        return get_media_adapter_servicer()
    except Exception:
        return None


def _media_adapter_status_for_aliases(
    aliases: list[str],
    *,
    media_ctrl=None,
    online_serials: Optional[set[str]] = None,
    streams: Optional[dict[str, dict]] = None,
) -> tuple[bool, Optional[dict]]:
    if media_ctrl is None and online_serials is None and streams is None:
        return False, None
    connected = False
    for alias in aliases:
        serial = str(alias or "").strip()
        if not serial:
            continue
        if online_serials is not None and serial in online_serials:
            connected = True
        if streams is not None:
            stream = streams.get(serial)
            if isinstance(stream, dict):
                return True, stream
            continue
        try:
            if media_ctrl.has_serial(serial):
                connected = True
        except Exception:
            pass
        try:
            stream = media_ctrl.stream_for_serial(serial)
        except Exception:
            stream = None
        if isinstance(stream, dict):
            return True, stream
    return connected, None


def _snapshot_serials(owner, method_name: str) -> set[str]:
    if owner is None:
        return set()
    try:
        method = getattr(owner, method_name)
    except Exception:
        return set()
    try:
        return {str(s) for s in method()}
    except Exception:
        return set()


def _snapshot_media_streams(media_ctrl) -> dict[str, dict]:
    if media_ctrl is None:
        return {}
    try:
        streams = media_ctrl.streams_snapshot()
    except Exception:
        return {}
    if not isinstance(streams, dict):
        return {}
    return {
        str(serial): dict(stream)
        for serial, stream in streams.items()
        if serial and isinstance(stream, dict)
    }


def _aliases_have_live_transport(
    aliases: list[str],
    *,
    relay_online_serials: set[str],
    control_online_serials: set[str],
    requires_relay: bool,
) -> bool:
    lookup = (
        control_online_serials
        if requires_relay
        else relay_online_serials | control_online_serials
    )
    return any(str(alias or "").strip() in lookup for alias in aliases)


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
    relay_devices: Optional[list[dict[str, object]]] = None,
) -> list[str]:
    candidates: list[str] = []

    def add(serial: object) -> None:
        value = str(serial or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    for alias in _live_device_aliases(registered_serial, info):
        add(alias)
        add(_resolve_relay_serial(alias, relay=relay))

    for device in (
        relay_devices if relay_devices is not None else _relay_list_devices(relay)
    ):
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


def _apply_live_screen_size_from_info(device: dict, info: dict[str, object]) -> None:
    db_width = _cap_positive_int(info.get("screen_width"))
    db_height = _cap_positive_int(info.get("screen_height"))
    if db_width > 0 and _cap_positive_int(device.get("screen_width")) <= 0:
        device["screen_width"] = db_width
    if db_height > 0 and _cap_positive_int(device.get("screen_height")) <= 0:
        device["screen_height"] = db_height


def _synthesize_live_device_from_relay(
    registered_serial: str,
    info: dict[str, object],
    *,
    relay=None,
    ctrl=None,
    relay_devices: Optional[list[dict[str, object]]] = None,
    relay_online_serials: Optional[set[str]] = None,
    control_online_serials: Optional[set[str]] = None,
) -> Optional[dict]:
    """Build a live device row from relay/control state when DeviceManager lags."""
    runtime_serial = ""
    relay_online = False
    relay_lookup = relay_online_serials or set()
    control_lookup = control_online_serials or set()
    for candidate in _relay_candidate_serials_for_registered(
        registered_serial,
        info,
        relay=relay,
        relay_devices=relay_devices,
    ):
        if relay_online_serials is not None or control_online_serials is not None:
            candidate_online = candidate in relay_lookup or candidate in control_lookup
        else:
            candidate_online = _relay_online_for_serial(candidate, relay=relay, ctrl=ctrl)
        if candidate_online:
            runtime_serial = candidate
            relay_online = (
                candidate in relay_lookup
                if relay_online_serials is not None
                else _relay_online_for_serial(candidate, relay=relay)
            )
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
    agent_connected = (
        runtime_serial in control_lookup
        if control_online_serials is not None
        else _relay_online_for_serial(runtime_serial, ctrl=ctrl)
    )
    brand = str(caps.get("brand") or "").strip()
    model = str(caps.get("model") or "").strip()
    touch_method = "u2" if has_u2 else "none"
    control_ready = agent_connected or has_u2 or minitouch_ready
    db_width = _cap_positive_int(info.get("screen_width"))
    db_height = _cap_positive_int(info.get("screen_height"))
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
        "screen_width": _cap_positive_int(caps.get("screen_width"), db_width),
        "screen_height": _cap_positive_int(caps.get("screen_height"), db_height),
        "agent_connected": agent_connected,
        "u2_ready": has_u2,
        "minitouch_ready": minitouch_ready,
        "touch_method": touch_method,
        "stf_connected": relay_online,
        _LIVE_DEVICE_INFO_KEY: info,
    }


def _synthesize_live_device_from_media_adapter(
    registered_serial: str,
    info: dict[str, object],
    *,
    media_ctrl=None,
    media_online_serials: Optional[set[str]] = None,
    media_streams: Optional[dict[str, dict]] = None,
) -> Optional[dict]:
    """Build a live device row when media-plane is alive but control-plane lags."""
    aliases = _live_device_aliases(registered_serial, info)
    media_connected, stream = _media_adapter_status_for_aliases(
        aliases,
        media_ctrl=media_ctrl,
        online_serials=media_online_serials,
        streams=media_streams,
    )
    if not media_connected:
        return None

    runtime_serial = str((stream or {}).get("serial") or registered_serial).strip()
    db_width = _cap_positive_int(info.get("screen_width"))
    db_height = _cap_positive_int(info.get("screen_height"))
    width = _cap_positive_int((stream or {}).get("width"), db_width)
    height = _cap_positive_int((stream or {}).get("height"), db_height)
    return {
        "type": "status",
        "serial": runtime_serial,
        "registered_serial": registered_serial,
        "name": info.get("name", ""),
        "display_name": info.get("display_name", runtime_serial),
        "brand": str(info.get("brand") or "").strip(),
        "model": str(info.get("model") or "").strip(),
        "state": "MEDIA_READY",
        "battery": -1,
        "current_app": "",
        "screen_width": width,
        "screen_height": height,
        "agent_connected": False,
        "u2_ready": False,
        "minitouch_ready": False,
        "touch_method": "none",
        "stf_connected": False,
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


def _apply_media_adapter_status(
    device: dict,
    *,
    media_connected: bool,
    stream: Optional[dict],
) -> None:
    device["media_adapter_connected"] = bool(media_connected)
    device["media_stream_active"] = bool(stream and stream.get("active"))
    device["media_stream_connected"] = bool(stream and stream.get("connected"))
    if not stream:
        return
    stream_name = str(stream.get("stream_name") or "").strip()
    if stream_name:
        device["media_stream_name"] = stream_name
    stream_source = str(stream.get("stream_source") or "").strip()
    if stream_source:
        device["media_stream_source"] = stream_source
    last_frame = _cap_int(stream.get("last_frame_unix_ms"), 0)
    if last_frame > 0:
        device["media_stream_last_frame_unix_ms"] = last_frame


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
                "brand": brand,
                "model": model,
                "display_name": display_name,
                "screen_width": int(getattr(device, "screen_width", 0) or 0),
                "screen_height": int(getattr(device, "screen_height", 0) or 0),
                "requires_relay": bool(adb_serial or adb_ip),
                "relay_aliases": sorted(aliases),
                "relay_scrcpy_enabled": bool(
                    getattr(device, "relay_scrcpy_enabled", True)
                ),
                "last_seen": getattr(device, "last_seen", None),
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
        from services.manual_takeover import is_manual_takeover_local
    except Exception:
        return

    serials = [str(d.get("serial") or "").strip() for d in devices]
    if not any(serials):
        return

    scenario_by_serial: dict[str, int] = {}
    manual_by_serial = {
        serial: is_manual_takeover_local(serial)
        for serial in serials
        if serial
    }
    redis_client = redis_store.client() if redis_store.enabled() else None
    if redis_client is not None:
        redis_serials = [serial for serial in serials if serial]
        try:
            scenario_keys = [
                redis_store.key(f"device:{serial}:scenario_active")
                for serial in redis_serials
            ]
            scenario_values = await redis_client.mget(scenario_keys)
            scenario_by_serial.update(
                {
                    serial: _cap_int(value, 0)
                    for serial, value in zip(redis_serials, scenario_values)
                }
            )
        except Exception:
            scenario_by_serial.clear()
        try:
            manual_keys = [
                redis_store.key(f"device:{serial}:manual_takeover")
                for serial in redis_serials
            ]
            manual_values = await redis_client.mget(manual_keys)
            manual_by_serial.update(
                {
                    serial: manual_by_serial.get(serial, False) or value is not None
                    for serial, value in zip(redis_serials, manual_values)
                }
            )
        except Exception:
            pass

    for d in devices:
        serial = str(d.get("serial") or "").strip()
        if not serial:
            continue
        d["scenario_active"] = max(
            _cap_int(d.get("scenario_active"), 0),
            scenario_by_serial.get(serial, 0),
        )
        d["manual_takeover_active"] = bool(
            manual_by_serial.get(serial, d.get("manual_takeover_active"))
        )


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
            media_ctrl = _media_adapter_control()
        except Exception:
            relay = None
            ctrl = None
            media_ctrl = _media_adapter_control()
        relay_online_serials = _snapshot_serials(relay, "list_online_serials")
        control_online_serials = _snapshot_serials(ctrl, "online_serials_snapshot")
        media_online_serials = _snapshot_serials(media_ctrl, "online_serials_snapshot")
        relay_devices = _relay_list_devices(relay)
        media_streams = _snapshot_media_streams(media_ctrl)
        media_online_lookup = media_online_serials or None
        media_stream_lookup = media_streams or None

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
                _apply_live_screen_size_from_info(d, info)
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
                    relay_devices=relay_devices,
                    relay_online_serials=relay_online_serials,
                    control_online_serials=control_online_serials,
                )
                if relay_device is not None:
                    visible_devices.append(relay_device)
                    seen_registered_serials.add(registered_serial)
                    continue
                media_device = _synthesize_live_device_from_media_adapter(
                    registered_serial,
                    info,
                    media_ctrl=media_ctrl,
                    media_online_serials=media_online_lookup,
                    media_streams=media_stream_lookup,
                )
                if media_device is not None:
                    visible_devices.append(media_device)
                    seen_registered_serials.add(registered_serial)
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
            relay_online = _aliases_have_live_transport(
                aliases,
                relay_online_serials=relay_online_serials,
                control_online_serials=control_online_serials,
                requires_relay=requires_relay,
            )
            _apply_realtime_connectivity(
                d,
                relay_online=relay_online,
                requires_relay=requires_relay,
            )
            media_connected, media_stream = _media_adapter_status_for_aliases(
                aliases,
                media_ctrl=media_ctrl,
                online_serials=media_online_lookup,
                streams=media_stream_lookup,
            )
            _apply_media_adapter_status(
                d,
                media_connected=media_connected,
                stream=media_stream,
            )
        store = getattr(request.app.state, "session_store", None)
        for d in devices:
            serial = d.get("serial", "")
            d["usage_state"] = store.get_usage(serial) if store else "idle"
        if db_enabled and devices:
            for d in devices:
                info = d.get(_LIVE_DEVICE_INFO_KEY, {}) if allowed_devices else {}
                d["relay_scrcpy_enabled"] = bool(
                    info.get("relay_scrcpy_enabled", True)
                    if isinstance(info, dict)
                    else True
                )
        for d in devices:
            info = d.pop(_LIVE_DEVICE_INFO_KEY, None)
            heartbeat_at = info.get("last_seen") if isinstance(info, dict) else None
            d["health"] = _device_health_projection(d, heartbeat_at=heartbeat_at)
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
            out["webrtc_enabled"] = bool(getattr(st, "webrtc_enabled", False))
            out["media_adapter_url_configured"] = bool(
                getattr(st, "media_adapter_url", "")
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
