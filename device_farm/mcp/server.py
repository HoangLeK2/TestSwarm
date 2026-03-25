from __future__ import annotations


import base64
import json
import os
import sys
import time
import traceback
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except Exception:
    pass

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

from urllib import request as urlrequest
from urllib.error import HTTPError, URLError


DEVICE_FARM_URL = os.environ.get("DEVICE_FARM_URL", "http://localhost:8081").rstrip("/")
SERVER_VERSION = "2.1.0"

# Tiered timeouts — match operation duration expectations
_TIMEOUT_FAST     = 10    # list, status reads
_TIMEOUT_CONTROL  = 30    # tap, swipe, key, open_url, shell
_TIMEOUT_SCENARIO = 300   # scenario/run (up to 5 min)
_TIMEOUT_CAMPAIGN = 600   # campaign/run (up to 10 min)

_MCP_TOKEN = (os.environ.get("DEVICE_FARM_MCP_TOKEN") or os.environ.get("MCP_AUTH_TOKEN") or "").strip() or None

_httpx_clients: Dict[int, Any] = {}  # keyed by timeout value


def _auth_headers() -> Dict[str, str]:
    if _MCP_TOKEN:
        return {"Authorization": f"Bearer {_MCP_TOKEN}"}
    return {}


def _get_client(timeout: int) -> Any:
    if not _HTTPX_AVAILABLE:
        return None
    if timeout not in _httpx_clients:
        headers = _auth_headers()
        _httpx_clients[timeout] = httpx.Client(
            base_url=DEVICE_FARM_URL,
            timeout=timeout,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers=headers if headers else None,
        )
    return _httpx_clients[timeout]


def _http_get(path: str, timeout: int = _TIMEOUT_FAST) -> bytes:
    client = _get_client(timeout)
    headers = _auth_headers()
    if client is not None:
        r = client.get(path, headers=headers or None)
        r.raise_for_status()
        return r.content
    url = f"{DEVICE_FARM_URL}{path}"
    req = urlrequest.Request(url, method="GET", headers=headers)
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_patch_json(path: str, body: Dict[str, Any], timeout: int = _TIMEOUT_CONTROL) -> Dict[str, Any]:
    client = _get_client(timeout)
    headers = _auth_headers()
    if client is not None:
        r = client.patch(path, json=body, headers=headers or None)
        r.raise_for_status()
        raw = r.content
        if not raw:
            return {}
        try:
            return r.json()
        except Exception:
            return {}
    url = f"{DEVICE_FARM_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="PATCH")
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}") from e
    except URLError as e:
        raise RuntimeError(f"HTTP error: {e.reason}") from e


def _http_post_json(path: str, body: Dict[str, Any], timeout: int = _TIMEOUT_CONTROL) -> Dict[str, Any]:
    client = _get_client(timeout)
    headers = _auth_headers()
    if client is not None:
        r = client.post(path, json=body, headers=headers or None)
        r.raise_for_status()
        raw = r.content
        if not raw:
            return {}
        try:
            return r.json()
        except Exception:
            return {}
    url = f"{DEVICE_FARM_URL}{path}"
    data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}") from e
    except URLError as e:
        raise RuntimeError(f"HTTP error: {e.reason}") from e


def _http_delete(path: str, timeout: int = _TIMEOUT_CONTROL) -> None:
    client = _get_client(timeout)
    headers = _auth_headers()
    if client is not None:
        r = client.delete(path, headers=headers or None)
        if r.status_code not in (200, 204):
            r.raise_for_status()
        return
    url = f"{DEVICE_FARM_URL}{path}"
    req = urlrequest.Request(url, method="DELETE", headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except HTTPError as e:
        if e.code not in (200, 204):
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}") from e
    except URLError as e:
        raise RuntimeError(f"HTTP error: {e.reason}") from e


def _resolve_device(args: Dict[str, Any]) -> str:
    session_id = args.get("session_id")
    if session_id:
        out = _http_get(f"/api/sessions/{session_id}", timeout=_TIMEOUT_FAST)
        data = json.loads(out.decode("utf-8"))
        if "device_id" not in data:
            raise RuntimeError(data.get("error", "Session not found"))
        return str(data["device_id"])
    device = args.get("device")
    if not device:
        raise ValueError("Provide either 'device' (serial) or 'session_id'")
    return str(device)


# ── Session & device locking ──────────────────────────────────────────────────

def _df_start_session(args: Dict[str, Any]) -> Dict[str, Any]:
    device_id = str(args["device_id"])
    user_id = args.get("user_id")
    body: Dict[str, Any] = {"device_id": device_id}
    if user_id is not None:
        body["user_id"] = str(user_id)
    out = _http_post_json("/api/sessions/start", body, timeout=_TIMEOUT_FAST)
    return {"session_id": out["session_id"], "device_id": out["device_id"]}


def _df_end_session(args: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(args["session_id"])
    return _http_post_json("/api/sessions/end", {"session_id": session_id}, timeout=_TIMEOUT_FAST)


def _df_reserve_device(args: Dict[str, Any]) -> Dict[str, Any]:
    device_id = str(args["device_id"])
    _http_post_json(f"/api/devices/{device_id}/reserve", {}, timeout=_TIMEOUT_FAST)
    return {"ok": True, "device_id": device_id, "usage_state": "reserved"}


def _df_release_device(args: Dict[str, Any]) -> Dict[str, Any]:
    device_id = str(args["device_id"])
    _http_post_json(f"/api/devices/{device_id}/release", {}, timeout=_TIMEOUT_FAST)
    return {"ok": True, "device_id": device_id, "usage_state": "idle"}


# ── Device control ────────────────────────────────────────────────────────────

def _df_list_devices(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = args or {}
    params: List[str] = []
    if args.get("state"):
        params.append(f"state={args['state']}")
    if args.get("model"):
        params.append(f"model={args['model']}")
    if args.get("limit") is not None:
        params.append(f"limit={int(args['limit'])}")
    if args.get("offset"):
        params.append(f"offset={int(args['offset'])}")
    qs = ("?" + "&".join(params)) if params else ""
    raw = _http_get(f"/api/devices/live{qs}", timeout=_TIMEOUT_FAST)
    result = json.loads(raw.decode("utf-8"))
    # Normalize: always return {total, offset, limit, devices:[]} regardless of backend shape
    if isinstance(result, list):
        return {"total": len(result), "offset": 0, "limit": None, "devices": result}
    return result


def _df_tap(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/tap/{serial}", {"x": int(args["x"]), "y": int(args["y"])}, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_swipe(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/swipe/{serial}", {
        "x1": int(args["x1"]), "y1": int(args["y1"]),
        "x2": int(args["x2"]), "y2": int(args["y2"]),
        "ms": int(args.get("ms", 300)),
    }, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_long_tap(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/devices/{serial}/long_tap", {
        "x": int(args["x"]), "y": int(args["y"]),
        "duration_ms": int(args.get("duration_ms", 800)),
    }, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_scroll(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/devices/{serial}/scroll", {
        "direction": str(args.get("direction", "down")),
        "distance": float(args.get("distance", 0.5)),
    }, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_input_text(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/devices/{serial}/input_text", {"text": str(args["text"])}, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_key(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/key/{serial}", {"key": str(args["key"])}, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_shell(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    cmd = str(args["cmd"])
    result = _http_post_json(f"/api/agent/{serial}/shell", {"cmd": cmd}, timeout=_TIMEOUT_CONTROL)
    # ADB mode returns output; agent (WS) mode returns note
    return {
        "ok": result.get("ok", True),
        "cmd": cmd,
        "output": result.get("output"),  # str if ADB mode, None if agent mode
        "note": result.get("note"),
    }


def _df_open_url(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    url = str(args["url"])
    pkg = (args.get("package") or "").strip() or "com.android.chrome"
    _http_post_json(f"/api/open_url/{serial}", {"url": url, "package": pkg}, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_hierarchy(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    refresh = bool(args.get("refresh", False))
    suffix = "?refresh=1" if refresh else ""
    raw = _http_get(f"/api/devices/{serial}/hierarchy{suffix}", timeout=_TIMEOUT_CONTROL)
    return {"xml": raw.decode("utf-8", errors="ignore")}


def _df_get_ui_elements(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get UI hierarchy as a structured, LLM-friendly element list.
    Server parses the XML and returns [{text, resource_id, content_desc, class_name,
    bounds, clickable, selector_by, selector_value}].
    LLM picks the right element and calls df_tap_selector with selector_by + selector_value.
    """
    serial = _resolve_device(args)
    refresh = bool(args.get("refresh", True))
    suffix = "?refresh=true" if refresh else "?refresh=false"
    raw = _http_get(f"/api/devices/{serial}/ui_elements{suffix}", timeout=_TIMEOUT_CONTROL)
    return json.loads(raw.decode("utf-8", errors="ignore"))


def _df_screenshot(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    raw = _http_get(f"/screenshot/{serial}", timeout=_TIMEOUT_CONTROL)
    b64 = base64.b64encode(raw).decode("ascii")
    return {"image": {"data": b64, "mimeType": "image/jpeg"}}


def _df_tap_selector(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    _http_post_json(f"/api/tap_selector/{serial}", {
        "by": str(args["by"]), "value": str(args["value"]),
    }, timeout=_TIMEOUT_CONTROL)
    return {"status": "ok"}


def _df_hit_test(args: Dict[str, Any]) -> Dict[str, Any]:
    serial = _resolve_device(args)
    return _http_post_json(f"/api/devices/{serial}/hit_test", {
        "x": int(args["x"]), "y": int(args["y"]),
    }, timeout=_TIMEOUT_CONTROL)


# ── Scenario & tasks ──────────────────────────────────────────────────────────

def _df_run_scenario(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute scenario steps on device or session. Waits for completion (up to 5 min)."""
    steps = args["steps"]
    if not isinstance(steps, list):
        raise ValueError("steps must be a list")
    session_id = args.get("session_id")
    if session_id:
        return _http_post_json(
            f"/api/sessions/{session_id}/scenario/run",
            {"steps": steps},
            timeout=_TIMEOUT_SCENARIO,
        )
    serial = _resolve_device(args)
    return _http_post_json(f"/api/devices/{serial}/scenario/run", {"steps": steps}, timeout=_TIMEOUT_SCENARIO)


def _df_fleet_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Broadcast scenario steps to ALL matching devices in one call.
    Backend dispatches tasks in parallel — suitable for 1000 devices.
    Returns run_id for monitoring with df_fleet_status.
    """
    body: Dict[str, Any] = {"steps": args["steps"]}
    if args.get("filter_state"):
        body["filter_state"] = str(args["filter_state"])
    if args.get("filter_model"):
        body["filter_model"] = str(args["filter_model"])
    if args.get("max_devices") is not None:
        body["max_devices"] = int(args["max_devices"])
    if args.get("priority") is not None:
        body["priority"] = int(args["priority"])
    if args.get("timeout") is not None:
        body["timeout"] = float(args["timeout"])
    if args.get("max_retries") is not None:
        body["max_retries"] = int(args["max_retries"])
    return _http_post_json("/api/fleet/run", body, timeout=_TIMEOUT_CAMPAIGN)


def _df_fleet_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get aggregate progress of a fleet run or all tasks."""
    run_id = args.get("run_id")
    qs = f"?run_id={run_id}" if run_id else ""
    raw = _http_get(f"/api/fleet/status{qs}", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_fleet_poll(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Poll df_fleet_status until all_complete=True or timeout.
    Blocks until done. Returns final status.
    """
    run_id = str(args["run_id"])
    timeout_s = float(args.get("timeout_seconds", 600))
    interval_s = float(args.get("interval_seconds", 5))
    deadline = time.monotonic() + timeout_s
    status: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            raw = _http_get(f"/api/fleet/status?run_id={run_id}", timeout=_TIMEOUT_FAST)
            status = json.loads(raw.decode("utf-8"))
            if status.get("all_complete"):
                break
        except Exception:
            pass
        time.sleep(min(interval_s, max(1.0, deadline - time.monotonic())))
    return status


def _df_enqueue_task(args: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "fn_name": str(args.get("fn_name", "example")),
        "priority": int(args.get("priority", 5)),
        "timeout": float(args.get("timeout", 300)),
        "max_retries": int(args.get("max_retries", 2)),
    }
    target = args.get("target")
    if target is not None:
        body["target"] = str(target)
    return _http_post_json("/api/task", body, timeout=_TIMEOUT_FAST)


def _df_list_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    ids = args.get("ids")
    path = "/api/tasks" + (f"?ids={ids}" if ids else "")
    raw = _http_get(path, timeout=_TIMEOUT_FAST)
    return {"tasks": json.loads(raw.decode("utf-8"))}


def _df_get_task(args: Dict[str, Any]) -> Dict[str, Any]:
    task_id = str(args["task_id"])
    raw = _http_get(f"/api/tasks/{task_id}", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_poll_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Poll a list of task IDs until all reach a terminal state (done/failed/cancelled)
    or until timeout_seconds elapses. Returns final status of each task.
    """
    task_ids: List[str] = list(args["task_ids"])
    timeout_s = float(args.get("timeout_seconds", 300))
    interval_s = float(args.get("interval_seconds", 3))
    deadline = time.monotonic() + timeout_s
    statuses: Dict[str, str] = {}
    TERMINAL = {"done", "failed", "cancelled", "error"}
    while time.monotonic() < deadline:
        pending = [tid for tid in task_ids if statuses.get(tid) not in TERMINAL]
        if not pending:
            break
        ids_param = ",".join(pending)
        try:
            raw = _http_get(f"/api/tasks?ids={ids_param}", timeout=_TIMEOUT_FAST)
            tasks = json.loads(raw.decode("utf-8"))
            for t in tasks if isinstance(tasks, list) else tasks.get("tasks", []):
                statuses[t["id"]] = t.get("status", "unknown")
        except Exception:
            pass
        remaining = [tid for tid in task_ids if statuses.get(tid) not in TERMINAL]
        if not remaining:
            break
        time.sleep(min(interval_s, max(0.5, deadline - time.monotonic())))
    # Mark anything we never heard about as unknown
    for tid in task_ids:
        if tid not in statuses:
            statuses[tid] = "unknown"
    all_done = all(statuses.get(tid) in TERMINAL for tid in task_ids)
    return {"completed": all_done, "task_statuses": statuses}


def _df_get_config() -> Dict[str, Any]:
    raw = _http_get("/api/config", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_connect_info() -> Dict[str, Any]:
    raw = _http_get("/api/connect/info", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_connect_register(args: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {"ip": str(args["ip"]), "port": int(args.get("port", 5555))}
    if args.get("device_key"):
        body["device_key"] = str(args["device_key"])
    return _http_post_json("/api/connect/register", body, timeout=_TIMEOUT_CONTROL)


# ── Campaign tools (require JWT) ──────────────────────────────────────────────

def _df_list_campaigns() -> Dict[str, Any]:
    raw = _http_get("/api/campaigns", timeout=_TIMEOUT_FAST)
    return {"campaigns": json.loads(raw.decode("utf-8"))}


def _df_get_campaign(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    raw = _http_get(f"/api/campaigns/{cid}", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_create_campaign(args: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "name": str(args["name"]),
        "description": str(args.get("description", "")),
        "scenario": args.get("scenario") if isinstance(args.get("scenario"), dict) else {},
        "device_ids": list(args["device_ids"]) if args.get("device_ids") else [],
    }
    return _http_post_json("/api/campaigns", body, timeout=_TIMEOUT_FAST)


def _df_update_campaign_scenario(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    scenario = args.get("scenario")
    if not isinstance(scenario, dict):
        raise ValueError("scenario must be a JSON object")
    return _http_patch_json(f"/api/campaigns/{cid}/scenario", {"scenario": scenario}, timeout=_TIMEOUT_FAST)


def _df_compile_campaign_scenario(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    body: Dict[str, Any] = {}
    if args.get("instructions"):
        body["instructions"] = str(args["instructions"])
    if args.get("device_serial"):
        body["device_serial"] = str(args["device_serial"])
    if args.get("ui_xml"):
        body["ui_xml"] = str(args["ui_xml"])
    if args.get("device_context") and isinstance(args["device_context"], dict):
        body["device_context"] = args["device_context"]
    return _http_post_json(f"/api/campaigns/{cid}/compile-scenario", body, timeout=_TIMEOUT_SCENARIO)


def _df_add_devices_to_campaign(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    device_ids = args.get("device_ids")
    if not isinstance(device_ids, list):
        device_ids = [device_ids] if device_ids else []
    added = []
    for did in device_ids:
        _http_post_json(f"/api/campaigns/{cid}/devices", {"device_id": str(did)}, timeout=_TIMEOUT_FAST)
        added.append(str(did))
    return {"campaign_id": cid, "added_device_ids": added}


def _df_remove_device_from_campaign(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    did = str(args["device_id"])
    _http_delete(f"/api/campaigns/{cid}/devices/{did}", timeout=_TIMEOUT_FAST)
    return {"ok": True, "campaign_id": cid, "device_id": did}


def _df_get_campaign_devices(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    raw = _http_get(f"/api/campaigns/{cid}/devices", timeout=_TIMEOUT_FAST)
    return {"campaign_id": cid, "devices": json.loads(raw.decode("utf-8"))}


def _df_update_campaign_status(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    return _http_patch_json(f"/api/campaigns/{cid}/status", {"status": str(args["status"])}, timeout=_TIMEOUT_FAST)


def _df_delete_campaign(args: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(args["campaign_id"])
    _http_delete(f"/api/campaigns/{cid}", timeout=_TIMEOUT_FAST)
    return {"ok": True, "campaign_id": cid}


def _df_run_campaign(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger campaign run. Returns task_ids for each device.
    Use df_poll_tasks(task_ids=[...]) to wait for completion.
    """
    campaign_id = str(args["campaign_id"])
    return _http_post_json(f"/api/campaigns/{campaign_id}/run", {}, timeout=_TIMEOUT_CAMPAIGN)


# ── Tool schema helpers ───────────────────────────────────────────────────────

_DEVICE_OR_SESSION = {
    "device": {"type": "string", "description": "Device serial from df_list_devices"},
    "session_id": {"type": "string", "description": "Session ID from df_start_session (preferred over device)"},
}

TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    # ── List & discovery ──────────────────────────────────────────────────────
    "df_list_devices": {
        "description": (
            "List live devices with optional filter and pagination. "
            "Returns {total, offset, limit, devices:[{serial, model, brand, screen_width, screen_height, "
            "state, usage_state, touch_method, android, sdk, battery, current_app}]}. "
            "For large fleets use limit/offset to paginate. "
            "For fleet automation use df_fleet_run instead of iterating devices manually."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state":  {"type": "string", "description": "Filter by device state: READY | BUSY | CONNECTING | DISCONNECTED"},
                "model":  {"type": "string", "description": "Substring filter on model name, e.g. 'Pixel'"},
                "limit":  {"type": "integer", "description": "Max devices to return (pagination)"},
                "offset": {"type": "integer", "description": "Skip N devices (pagination)", "default": 0},
            },
            "required": [],
        },
        "fn": _df_list_devices,
    },
    # ── Session management ────────────────────────────────────────────────────
    "df_start_session": {
        "description": (
            "Start an exclusive session bound to a device. Returns session_id. "
            "Use session_id instead of device in all subsequent tools. Call df_end_session when done. "
            "Device must be idle or reserved."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Device serial"},
                "user_id": {"type": "string", "description": "Optional user id for audit"},
            },
            "required": ["device_id"],
        },
        "fn": _df_start_session,
    },
    "df_end_session": {
        "description": "End session and release device. Always call after automation is done.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
        "fn": _df_end_session,
    },
    "df_reserve_device": {
        "description": "Reserve device (idle → reserved). Fails if device not idle.",
        "inputSchema": {
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
        },
        "fn": _df_reserve_device,
    },
    "df_release_device": {
        "description": "Release device (reserved/running → idle).",
        "inputSchema": {
            "type": "object",
            "properties": {"device_id": {"type": "string"}},
            "required": ["device_id"],
        },
        "fn": _df_release_device,
    },
    # ── Touch & input ─────────────────────────────────────────────────────────
    "df_tap": {
        "description": "Tap at (x, y) in physical pixels. Give device or session_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "x": {"type": "integer", "description": "X in physical pixels"},
                "y": {"type": "integer", "description": "Y in physical pixels"},
            },
            "required": ["x", "y"],
        },
        "fn": _df_tap,
    },
    "df_long_tap": {
        "description": "Long-press at (x, y). duration_ms default 800. Give device or session_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "duration_ms": {"type": "integer", "default": 800, "description": "Hold duration in ms"},
            },
            "required": ["x", "y"],
        },
        "fn": _df_long_tap,
    },
    "df_swipe": {
        "description": "Swipe from (x1,y1) to (x2,y2) in physical pixels. Give device or session_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "x1": {"type": "integer"}, "y1": {"type": "integer"},
                "x2": {"type": "integer"}, "y2": {"type": "integer"},
                "ms": {"type": "integer", "description": "Duration in ms", "default": 300},
            },
            "required": ["x1", "y1", "x2", "y2"],
        },
        "fn": _df_swipe,
    },
    "df_scroll": {
        "description": (
            "Scroll screen in a direction. direction: up|down|left|right. "
            "distance: 0.0–1.0 of screen size (default 0.5 = half screen). "
            "Give device or session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "default": "down"},
                "distance": {"type": "number", "minimum": 0.1, "maximum": 1.0, "default": 0.5},
            },
            "required": [],
        },
        "fn": _df_scroll,
    },
    "df_input_text": {
        "description": (
            "Type text into the currently focused input field. "
            "Tap the field first with df_tap or df_tap_selector, then call this. "
            "Give device or session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["text"],
        },
        "fn": _df_input_text,
    },
    "df_key": {
        "description": "Send key event: home, back, power, enter, tab, delete, etc. Give device or session_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "key": {"type": "string", "description": "Key name: home | back | power | enter | tab | delete | …"},
            },
            "required": ["key"],
        },
        "fn": _df_key,
    },
    # ── Shell ─────────────────────────────────────────────────────────────────
    "df_shell": {
        "description": (
            "Run ADB shell command on device. "
            "In ADB mode: output field contains stdout (useful for dumpsys, pm list, etc.). "
            "In WebSocket-agent mode: output is null (fire-and-forget, use for am start, settings put). "
            "Give device or session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "cmd": {"type": "string", "description": "Shell command, e.g. 'dumpsys battery'"},
            },
            "required": ["cmd"],
        },
        "fn": _df_shell,
    },
    # ── Screen & UI inspection ────────────────────────────────────────────────
    "df_screenshot": {
        "description": "Take JPEG screenshot. Returns image content Claude can see. Give device or session_id.",
        "inputSchema": {
            "type": "object",
            "properties": _DEVICE_OR_SESSION,
            "required": [],
        },
        "fn": _df_screenshot,
    },
    "df_hierarchy": {
        "description": (
            "Get UI hierarchy XML from uiautomator2. Use to find elements before tapping. "
            "refresh=true forces a fresh dump (default uses 2s cache). Give device or session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "refresh": {"type": "boolean", "default": False},
            },
            "required": [],
        },
        "fn": _df_hierarchy,
    },
    "df_get_ui_elements": {
        "description": (
            "⚡ PREFERRED for UI interaction. Get UI elements as structured list — server fetches hierarchy XML "
            "and parses into [{text, resource_id, content_desc, class_name, bounds, clickable, selector_by, selector_value}]. "
            "LLM workflow: call this → pick element matching intent → call df_tap_selector with selector_by + selector_value. "
            "This replaces df_tap(x,y) with reliable element-based interaction. "
            "If element_count < 5, XML is flat — enable Accessibility Service on device for full hierarchy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "refresh": {"type": "boolean", "default": True, "description": "Force fresh hierarchy dump (default true)"},
            },
            "required": [],
        },
        "fn": _df_get_ui_elements,
    },
    "df_tap_selector": {
        "description": (
            "Tap UI element by selector strategy. "
            "by: resource-id | text | xpath | class name. Give device or session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "by": {
                    "type": "string",
                    "enum": ["resource-id", "text", "xpath", "class name"],
                },
                "value": {"type": "string"},
            },
            "required": ["by", "value"],
        },
        "fn": _df_tap_selector,
    },
    "df_hit_test": {
        "description": "Given (x,y) pixels, return the best UI selector at that point from the hierarchy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
        "fn": _df_hit_test,
    },
    "df_open_url": {
        "description": "Open URL on device. Optional package (default: com.android.chrome). Give device or session_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "url": {"type": "string"},
                "package": {"type": "string", "description": "App package, e.g. com.android.chrome"},
            },
            "required": ["url"],
        },
        "fn": _df_open_url,
    },
    # ── Scenario ──────────────────────────────────────────────────────────────
    "df_run_scenario": {
        "description": (
            "Execute a sequence of scenario steps on device. Waits for all steps to complete (up to 5 min). "
            "PREFERRED u2 steps (element-based, reliable): "
            "{type:tap_selector, by:text|resource-id|xpath, value:..., fallback_rx:0.5, fallback_ry:0.5, timeout:5}, "
            "{type:wait_element, by:text, value:..., timeout:10}, "
            "{type:assert_element, by:text, value:..., timeout:5}, "
            "{type:input_selector, by:resource-id, value:..., text:..., clear_first:true}, "
            "{type:long_tap_selector, by:text, value:..., duration_ms:800}, "
            "{type:scroll_to, by:text, value:..., direction:down, max_swipes:5}. "
            "Coordinate fallbacks (use only when selector unknown): "
            "{type:tap_ratio, x:0.5, y:0.5}, {type:swipe_ratio, x1:0.5,y1:0.8,x2:0.5,y2:0.2}. "
            "Other: {type:launch_app, package:com.example, wait_after:2.5}, "
            "{type:open_url, url:https://...}, {type:wait, seconds:1}, "
            "{type:input_text, text:hello, via:u2}, {type:key, key:enter}, {type:scroll_down}. "
            "Use session_id when in session flow."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "steps": {
                    "type": "array",
                    "description": "Array of scenario step objects",
                    "items": {"type": "object"},
                },
            },
            "required": ["steps"],
        },
        "fn": _df_run_scenario,
    },
    # ── Fleet (1000-device scale) ─────────────────────────────────────────────
    "df_fleet_run": {
        "description": (
            "Run scenario steps on ALL matching devices simultaneously — designed for 1000+ devices. "
            "Backend dispatches tasks in parallel without any per-device round-trips. "
            "Returns run_id. Use df_fleet_poll(run_id) to wait for completion. "
            "filter_state defaults to READY. "
            "Example: df_fleet_run(steps=[{type:launch_app,package:com.example},{type:wait,seconds:2}])"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Scenario steps to run on every matched device",
                },
                "filter_state": {
                    "type": "string",
                    "default": "READY",
                    "description": "Only dispatch to devices in this state: READY | BUSY | CONNECTING",
                },
                "filter_model": {
                    "type": "string",
                    "description": "Optional: substring match on model name to target a device type",
                },
                "max_devices": {
                    "type": "integer",
                    "description": "Cap: run on at most N devices (default: all matching)",
                },
                "priority": {"type": "integer", "default": 5},
                "timeout":  {"type": "number", "default": 300, "description": "Per-device task timeout (seconds)"},
                "max_retries": {"type": "integer", "default": 1},
            },
            "required": ["steps"],
        },
        "fn": _df_fleet_run,
    },
    "df_fleet_status": {
        "description": (
            "Get aggregate progress of a fleet run. "
            "Returns: run_id, total, pending, running, done, failed, cancelled, progress_pct, all_complete. "
            "Pass run_id from df_fleet_run to scope to that run, or omit for global task stats."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "run_id from df_fleet_run (optional)"},
            },
            "required": [],
        },
        "fn": _df_fleet_status,
    },
    "df_fleet_poll": {
        "description": (
            "Block until a fleet run completes (all_complete=True) or timeout. "
            "Polls df_fleet_status every interval_seconds. Returns final aggregate status. "
            "Use after df_fleet_run when you need to wait for 1000 devices to finish."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id":           {"type": "string", "description": "run_id from df_fleet_run"},
                "timeout_seconds":  {"type": "number", "default": 600},
                "interval_seconds": {"type": "number", "default": 5},
            },
            "required": ["run_id"],
        },
        "fn": _df_fleet_poll,
    },
    # ── Tasks ─────────────────────────────────────────────────────────────────
    "df_enqueue_task": {
        "description": "Enqueue a background automation task. Returns task id. Use df_poll_tasks to wait.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fn_name": {"type": "string", "description": "Task function name, e.g. 'example'", "default": "example"},
                "priority": {"type": "integer", "default": 5},
                "target": {"type": "string", "description": "Target device serial (omit for any READY device)"},
                "timeout": {"type": "number", "description": "Task timeout in seconds", "default": 300},
                "max_retries": {"type": "integer", "default": 2},
            },
            "required": [],
        },
        "fn": _df_enqueue_task,
    },
    "df_list_tasks": {
        "description": "List tasks in the queue. Optional ids=comma-separated task IDs to filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ids": {"type": "string", "description": "Comma-separated task IDs to filter (optional)"},
            },
            "required": [],
        },
        "fn": _df_list_tasks,
    },
    "df_get_task": {
        "description": "Get a single task by ID. Returns id, name, status, target, created_at.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
        "fn": _df_get_task,
    },
    "df_poll_tasks": {
        "description": (
            "Poll a list of task IDs until all reach terminal state (done/failed/cancelled) or timeout. "
            "Returns {completed: bool, task_statuses: {task_id: status}}. "
            "Use after df_run_campaign or df_enqueue_task to block until tasks finish."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of task IDs to poll",
                },
                "timeout_seconds": {"type": "number", "default": 300, "description": "Max wait seconds"},
                "interval_seconds": {"type": "number", "default": 3, "description": "Poll interval seconds"},
            },
            "required": ["task_ids"],
        },
        "fn": _df_poll_tasks,
    },
    # ── Config & registration ─────────────────────────────────────────────────
    "df_get_config": {
        "description": "Get device_farm server config.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": _df_get_config,
    },
    "df_connect_info": {
        "description": "Get QR-scan device registration info.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": _df_connect_info,
    },
    "df_connect_register": {
        "description": "Register a device by WiFi IP (after QR scan).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Device WiFi IP"},
                "port": {"type": "integer", "default": 5555},
                "device_key": {"type": "string", "description": "Optional device_key from QR"},
            },
            "required": ["ip"],
        },
        "fn": _df_connect_register,
    },
    # ── Campaign management (requires JWT) ────────────────────────────────────
    "df_list_campaigns": {
        "description": "List campaigns of the authenticated user. Requires DEVICE_FARM_MCP_TOKEN.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "fn": _df_list_campaigns,
    },
    "df_get_campaign": {
        "description": "Get one campaign by ID. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {"campaign_id": {"type": "string"}},
            "required": ["campaign_id"],
        },
        "fn": _df_get_campaign,
    },
    "df_create_campaign": {
        "description": "Create a campaign with name, optional scenario and device_ids. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "scenario": {"type": "object", "description": "JSON scenario {instructions, steps}"},
                "device_ids": {"type": "array", "items": {"type": "string"}, "description": "Device UUIDs to attach"},
            },
            "required": ["name"],
        },
        "fn": _df_create_campaign,
    },
    "df_update_campaign_scenario": {
        "description": "Update campaign scenario JSON. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "scenario": {"type": "object", "description": "Full scenario {instructions, steps}"},
            },
            "required": ["campaign_id", "scenario"],
        },
        "fn": _df_update_campaign_scenario,
    },
    "df_compile_campaign_scenario": {
        "description": (
            "Compile scenario from natural language instructions using AI. "
            "Optionally provide device_serial to auto-fetch UI hierarchy. Requires auth token."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "instructions": {"type": "string"},
                "device_serial": {"type": "string"},
                "ui_xml": {"type": "string"},
                "device_context": {"type": "object"},
            },
            "required": ["campaign_id"],
        },
        "fn": _df_compile_campaign_scenario,
    },
    "df_add_devices_to_campaign": {
        "description": "Add devices to campaign by UUIDs. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "device_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["campaign_id", "device_ids"],
        },
        "fn": _df_add_devices_to_campaign,
    },
    "df_remove_device_from_campaign": {
        "description": "Remove a device from campaign. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "device_id": {"type": "string"},
            },
            "required": ["campaign_id", "device_id"],
        },
        "fn": _df_remove_device_from_campaign,
    },
    "df_get_campaign_devices": {
        "description": "List devices attached to a campaign. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {"campaign_id": {"type": "string"}},
            "required": ["campaign_id"],
        },
        "fn": _df_get_campaign_devices,
    },
    "df_update_campaign_status": {
        "description": "Update campaign status: draft | running | paused | completed. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "status": {"type": "string", "enum": ["draft", "running", "paused", "completed"]},
            },
            "required": ["campaign_id", "status"],
        },
        "fn": _df_update_campaign_status,
    },
    "df_delete_campaign": {
        "description": "Delete a campaign and its device links. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {"campaign_id": {"type": "string"}},
            "required": ["campaign_id"],
        },
        "fn": _df_delete_campaign,
    },
    "df_run_campaign": {
        "description": (
            "Trigger campaign run: enqueue tasks for all attached devices. "
            "Returns {task_ids: [...], device_serials: [...]}. "
            "Follow up with df_poll_tasks(task_ids=[...]) to wait for all tasks to complete."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
            },
            "required": ["campaign_id"],
        },
        "fn": _df_run_campaign,
    },
}


# ── MCP stdio server ──────────────────────────────────────────────────────────

@dataclass
class McpContext:
    initialized: bool = False


def handle_initialize(ctx: McpContext, msg: Dict[str, Any]) -> Dict[str, Any]:
    ctx.initialized = True
    return {
        "id": msg.get("id"),
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "device-farm-mcp", "version": SERVER_VERSION},
            "capabilities": {"tools": {"listChanged": True}},
        },
    }


def handle_tools_list(_ctx: McpContext, msg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": msg.get("id"),
        "jsonrpc": "2.0",
        "result": {
            "tools": [
                {"name": name, "description": meta["description"], "inputSchema": meta["inputSchema"]}
                for name, meta in TOOL_DEFS.items()
            ],
        },
    }


def handle_tools_call(_ctx: McpContext, msg: Dict[str, Any]) -> Dict[str, Any]:
    params = msg.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if name not in TOOL_DEFS:
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Unknown tool: {name}"},
        }
    fn = TOOL_DEFS[name]["fn"]
    try:
        import inspect as _inspect
        sig = _inspect.signature(fn)
        result = fn(args) if sig.parameters else fn()  # type: ignore[arg-type]
        content: List[Dict[str, Any]] = []
        if name == "df_screenshot":
            img = result["image"]
            content.append({"type": "image", "data": img["data"], "mimeType": img["mimeType"]})
        else:
            content.append({"type": "text", "text": json.dumps(result, ensure_ascii=False)})
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "result": {"content": content},
        }
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "error": {
                "code": -32000,
                "message": f"{type(e).__name__}: {e}",
                "data": tb,
            },
        }


def run_stdio_server() -> None:
    ctx = McpContext()
    handlers = {
        "initialize": handle_initialize,
        "tools/list": handle_tools_list,
        "tools/call": handle_tools_call,
    }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue

        # JSON-RPC notifications have no "id"; do not send a response.
        msg_id = msg.get("id")
        if msg_id is None:
            continue

        method = msg.get("method")
        handler = handlers.get(method)
        if handler is None:
            out = {
                "id": msg_id,
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        else:
            out = handler(ctx, msg)
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
