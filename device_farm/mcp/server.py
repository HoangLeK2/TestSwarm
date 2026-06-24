from __future__ import annotations


import base64
import contextvars
import hashlib
import json
import os
import sys
import time
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

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
SERVER_VERSION = "2.2.1"
CONTRACT_VERSION = "df-mcp-preview-2026-06-01"
PREVIEW_WARNING = (
    "Preview / Experimental: Device Farm MCP Agent Tools contract may change "
    "between releases and has no GA SLA."
)

_TIMEOUT_FAST     = 10    # list, status reads
_TIMEOUT_CONTROL  = 30    # tap, swipe, key, open_url, shell
_TIMEOUT_SCENARIO = 300   # scenario/run (up to 5 min)
_TIMEOUT_CAMPAIGN = 600   # campaign/run (up to 10 min)

_httpx_clients: Dict[int, Any] = {}  # keyed by timeout value
_httpx_lock = threading.Lock()
_rate_lock = threading.Lock()
_rate_windows: Dict[Tuple[str, str], List[float]] = {}


ERROR_CATALOG: Dict[str, Dict[str, Any]] = {
    "df.invalid_argument": {"retryable": False, "http_status": 400},
    "df.unauthorized": {"retryable": False, "http_status": 401},
    "df.permission_denied": {"retryable": False, "http_status": 403},
    "df.not_found": {"retryable": False, "http_status": 404},
    "df.conflict": {"retryable": False, "http_status": 409},
    "df.precondition_failed": {"retryable": False, "http_status": 412},
    "df.rate_limited": {"retryable": True, "http_status": 429},
    "df.quota_exceeded": {"retryable": False, "http_status": 429},
    "df.token_suspended": {"retryable": False, "http_status": 403},
    "df.timeout": {"retryable": True, "http_status": 504},
    "df.internal": {"retryable": True, "http_status": 500},
    "df.evidence_required": {"retryable": False, "http_status": 428},
    "df.session_not_owned": {"retryable": False, "http_status": 403},
}


class McpToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class TokenContext:
    token: Optional[str]
    token_id_hash: Optional[str]
    scope: Optional[str]
    owner_user_id: Optional[str] = None
    org_id: Optional[str] = None


_active_auth_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "device_farm_mcp_active_auth_token",
    default=None,
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]


def _scope_allows(token_scope: str, required_scope: str) -> bool:
    if required_scope == "any":
        return True
    if token_scope == "user":
        return True
    return token_scope == required_scope


def _runtime_token_context(required_scope: str = "any") -> TokenContext:
    token = (os.environ.get("MCP_AUTH_TOKEN") or "").strip()
    return _token_context_from_value(token, required_scope=required_scope)


def _token_context_from_value(token: str, *, required_scope: str) -> TokenContext:
    if not token:
        raise McpToolError(
            "df.unauthorized",
            "Tool requires MCP_AUTH_TOKEN",
            details={"required_scope": required_scope},
        )
    if token.startswith("dfmcp_"):
        from mcp.token_store import lookup_token

        record = lookup_token(token)
        if record is None:
            raise McpToolError("df.unauthorized", "MCP token is invalid or revoked")
        if not _scope_allows(record.scope_type, required_scope):
            raise McpToolError(
                "df.permission_denied",
                "MCP token scope does not allow this tool",
                details={"required_scope": required_scope, "token_scope": record.scope_type},
            )
        return TokenContext(
            token=token,
            token_id_hash=record.id,
            scope=record.scope_type,
            owner_user_id=record.owner_user_id,
            org_id=record.org_id,
        )

    org_id = None
    owner_user_id = None
    try:
        from api.auth.context import try_decode_access_token

        ctx = try_decode_access_token(token)
        if ctx is not None:
            org_id = ctx.org_id
            owner_user_id = ctx.user_id
    except Exception:
        pass
    return TokenContext(
        token=token,
        token_id_hash=_hash_token(token),
        scope="user",
        owner_user_id=owner_user_id,
        org_id=org_id,
    )


def _mcp_token() -> Optional[str]:
    return (os.environ.get("MCP_AUTH_TOKEN") or "").strip() or None


def _auth_headers() -> Dict[str, str]:
    token = _active_auth_token.get() or _mcp_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def _parse_rate_limit(raw: str) -> Tuple[int, float]:
    value = (raw or "120/minute").strip().lower()
    if "/" not in value:
        return max(1, int(value)), 60.0
    count_s, unit = value.split("/", 1)
    count = max(1, int(count_s))
    seconds = {
        "second": 1.0,
        "sec": 1.0,
        "s": 1.0,
        "minute": 60.0,
        "min": 60.0,
        "m": 60.0,
        "hour": 3600.0,
        "h": 3600.0,
    }.get(unit.strip(), 60.0)
    return count, seconds


def _check_rate_limit(token_id_hash: str, tool_name: str) -> None:
    raw = os.environ.get("DEVICE_FARM_MCP_RATE_LIMIT", "120/minute")
    limit, window_s = _parse_rate_limit(raw)
    key = (token_id_hash, raw)
    now = time.monotonic()
    with _rate_lock:
        calls = [ts for ts in _rate_windows.get(key, []) if now - ts < window_s]
        if len(calls) >= limit:
            retry_after = max(0.001, window_s - (now - calls[0]))
            _rate_windows[key] = calls
            raise McpToolError(
                "df.rate_limited",
                f"MCP token exceeded {raw} rate limit",
                details={
                    "tool_name": tool_name,
                    "limit": limit,
                    "window_seconds": window_s,
                    "retry_after_ms": int(retry_after * 1000),
                },
            )
        calls.append(now)
        _rate_windows[key] = calls


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in ("token", "password", "secret", "cookie")):
                out[key] = "[REDACTED]"
            else:
                out[key] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _summarize_output(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        return {
            "keys": sorted(str(key) for key in result.keys())[:20],
            "size_bytes": len(json.dumps(result, ensure_ascii=False, default=str)),
        }
    if isinstance(result, list):
        return {"items": len(result)}
    return {"type": type(result).__name__}


def _tool_success_payload(name: str, result: Any) -> Dict[str, Any]:
    return {
        "preview": True,
        "contract_version": CONTRACT_VERSION,
        "tool_name": name,
        "result": result,
    }


def _tool_structured_content(name: str, result: Any) -> Dict[str, Any]:
    """Build MCP structuredContent that conforms to each tool's outputSchema."""
    if name == "df_screenshot" and isinstance(result, dict):
        img = result.get("image")
        if isinstance(img, dict):
            data = img.get("data")
            byte_length = None
            if isinstance(data, str):
                try:
                    byte_length = len(base64.b64decode(data))
                except Exception:
                    byte_length = None
            return {
                "image": {
                    "mimeType": img.get("mimeType"),
                    "byte_length": byte_length,
                    "note": "Image bytes are returned in content as an image block.",
                }
            }

    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"items": result}
    return {"value": result}


def _tool_call_content(name: str, result: Any) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = []
    if name == "df_screenshot" and isinstance(result, dict):
        img = result.get("image")
        if isinstance(img, dict) and img.get("data"):
            content.append(
                {
                    "type": "image",
                    "data": img["data"],
                    "mimeType": img.get("mimeType") or "image/jpeg",
                }
            )
    structured = _tool_structured_content(name, result)
    payload = _tool_success_payload(name, result)
    content.append({"type": "text", "text": json.dumps(payload, ensure_ascii=False)})
    return content


def _audit_log_path() -> Path:
    configured = (os.environ.get("DEVICE_FARM_MCP_AUDIT_LOG_PATH") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "mcp_audit_log.jsonl"


def _record_audit(
    *,
    session_id: Optional[str],
    agent_id: Optional[str],
    token_id_hash: Optional[str],
    org_id: Optional[str],
    tool_name: str,
    input_args: Dict[str, Any],
    output_summary: Dict[str, Any],
    result_code: str,
    started_at: float,
    artifact_refs: Optional[List[str]] = None,
) -> None:
    entry = {
        "session_id": session_id,
        "agent_id": agent_id,
        "token_id_hash": token_id_hash,
        "org_id": org_id,
        "tool_name": tool_name,
        "input": _redact(input_args),
        "output_summary": output_summary,
        "result_code": result_code,
        "started_at": started_at,
        "ended_at": time.time(),
        "latency_ms": int((time.time() - started_at) * 1000),
        "artifact_refs": artifact_refs or [],
        "contract_version": CONTRACT_VERSION,
    }
    try:
        path = _audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _error_payload(code: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = ERROR_CATALOG.get(code, ERROR_CATALOG["df.internal"])
    return {
        "error": {
            "code": code if code in ERROR_CATALOG else "df.internal",
            "message": message,
            "retryable": bool(meta["retryable"]),
            "details": details or {},
        },
        "contract_version": CONTRACT_VERSION,
        "preview": True,
    }


def _exception_to_mcp_error(exc: Exception) -> McpToolError:
    if isinstance(exc, McpToolError):
        return exc
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return McpToolError("df.invalid_argument", str(exc))
    text = str(exc)
    if text.startswith("HTTP 401"):
        return McpToolError("df.unauthorized", "Downstream API rejected MCP token")
    if text.startswith("HTTP 403"):
        return McpToolError("df.permission_denied", "Downstream API denied this tool call")
    if text.startswith("HTTP 404"):
        return McpToolError("df.not_found", "Downstream resource not found")
    if text.startswith("HTTP 409"):
        return McpToolError("df.conflict", "Downstream resource conflict")
    if "timed out" in text.lower() or "timeout" in text.lower():
        return McpToolError("df.timeout", "Downstream API timed out")
    if text.startswith("HTTP error"):
        return McpToolError("df.timeout", "Downstream API unavailable")
    return McpToolError("df.internal", "MCP tool failed")


def validate_startup_config() -> None:
    if (os.environ.get("DEVICE_FARM_MCP_ALLOW_UNAUTH") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    if _mcp_token():
        return
    print(
        "Device Farm MCP server requires MCP_AUTH_TOKEN. "
        "Set DEVICE_FARM_MCP_ALLOW_UNAUTH=1 only for local contract tests.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _get_client(timeout: int) -> Any:
    if not _HTTPX_AVAILABLE:
        return None
    with _httpx_lock:
        if timeout not in _httpx_clients:
            _httpx_clients[timeout] = httpx.Client(
                base_url=DEVICE_FARM_URL,
                timeout=timeout,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
        return _httpx_clients[timeout]


def _http_get(path: str, timeout: int = _TIMEOUT_FAST) -> bytes:
    client = _get_client(timeout)
    if client is not None:
        try:
            r = client.get(path, headers=_auth_headers())
            r.raise_for_status()
            return r.content
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP error: {e}") from e
    headers = _auth_headers()
    url = f"{DEVICE_FARM_URL}{path}"
    req = urlrequest.Request(url, method="GET", headers=headers)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}") from e
    except URLError as e:
        raise RuntimeError(f"HTTP error: {e.reason}") from e


def _http_patch_json(path: str, body: Dict[str, Any], timeout: int = _TIMEOUT_CONTROL) -> Dict[str, Any]:
    client = _get_client(timeout)
    if client is not None:
        try:
            r = client.patch(path, json=body, headers=_auth_headers())
            r.raise_for_status()
            if not r.content:
                return {}
            try:
                return r.json()
            except Exception:
                return {}
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP error: {e}") from e
    headers = _auth_headers()
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
    if client is not None:
        try:
            r = client.post(path, json=body, headers=_auth_headers())
            r.raise_for_status()
            if not r.content:
                return {}
            try:
                return r.json()
            except Exception:
                return {}
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP error: {e}") from e
    headers = _auth_headers()
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
    if client is not None:
        try:
            r = client.delete(path, headers=_auth_headers())
            if r.status_code not in (200, 204):
                r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"HTTP error: {e}") from e
        return
    headers = _auth_headers()
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


def _df_get_session_info(args: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(args["session_id"])
    raw = _http_get(f"/api/sessions/{quote(session_id)}", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_device_claim(args: Dict[str, Any]) -> Dict[str, Any]:
    if args.get("device") and not args.get("device_id"):
        args = {**args, "device_id": args["device"]}
    return _df_start_session(args)


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
        params.append(f"state={quote(str(args['state']))}")
    if args.get("model"):
        params.append(f"model={quote(str(args['model']))}")
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
    bounds, clickable, selector_by, selector_value, selector_reason,
    selector_volatile}].
    LLM picks the right element, respects duplicate/volatile warnings, and calls
    df_tap_selector with selector_by + selector_value.
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
    # DF-004: group and tags filters
    if args.get("filter_group_id"):
        body["filter_group_id"] = str(args["filter_group_id"])
    if args.get("filter_tags"):
        body["filter_tags"] = str(args["filter_tags"])
    return _http_post_json("/api/fleet/run", body, timeout=_TIMEOUT_CAMPAIGN)


def _df_fleet_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get aggregate progress of a fleet run or all tasks."""
    run_id = args.get("run_id")
    qs = f"?run_id={quote(str(run_id))}" if run_id else ""
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
            raw = _http_get(f"/api/fleet/status?run_id={quote(run_id)}", timeout=_TIMEOUT_FAST)
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
    path = "/api/tasks" + (f"?ids={quote(str(ids))}" if ids else "")
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
        ids_param = quote(",".join(pending))
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
    body: Dict[str, Any] = {}
    if isinstance(args.get("target"), dict):
        body["target"] = args["target"]
    elif args.get("device_ids") or args.get("device_group_ids"):
        body["target"] = {
            "device_ids": list(args.get("device_ids") or []),
            "device_group_ids": list(args.get("device_group_ids") or []),
        }
    if args.get("dispatch_strategy"):
        body["dispatch_strategy"] = str(args["dispatch_strategy"])
    if args.get("allow_partial") is not None:
        body["allow_partial"] = bool(args["allow_partial"])
    if args.get("require_online") is not None:
        body["require_online"] = bool(args["require_online"])
    if body:
        return _http_post_json(f"/api/campaigns/{campaign_id}/dispatch", body, timeout=_TIMEOUT_CAMPAIGN)
    return _http_post_json(f"/api/campaigns/{campaign_id}/run", {}, timeout=_TIMEOUT_CAMPAIGN)


def _df_campaign_create(args: Dict[str, Any]) -> Dict[str, Any]:
    return _df_create_campaign(args)


def _df_campaign_run(args: Dict[str, Any]) -> Dict[str, Any]:
    return _df_run_campaign(args)


def _df_content_query(args: Dict[str, Any]) -> Dict[str, Any]:
    params: List[str] = []
    for name in (
        "collection",
        "platform",
        "content_type",
        "search",
        "device_serial",
        "campaign_id",
        "execution_id",
        "content_hash",
        "parent_id",
    ):
        if args.get(name) is not None:
            params.append(f"{name}={quote(str(args[name]))}")
    if args.get("limit") is not None:
        params.append(f"limit={int(args['limit'])}")
    if args.get("offset") is not None:
        params.append(f"offset={int(args['offset'])}")
    qs = ("?" + "&".join(params)) if params else ""
    raw = _http_get(f"/api/content{qs}", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_save_extraction(args: Dict[str, Any]) -> Dict[str, Any]:
    data = args.get("data") or args.get("extraction")
    if not isinstance(data, dict):
        raise ValueError("data must be a JSON object")
    body: Dict[str, Any] = {
        "data": data,
        "collection": str(args.get("collection") or "default"),
        "content_type": str(args.get("content_type") or "fb_post"),
    }
    for name in (
        "platform",
        "dedupe_field",
        "dedup_action",
        "tags",
        "device_serial",
        "campaign_id",
        "execution_id",
    ):
        if args.get(name) is not None:
            body[name] = args[name]
    return _http_post_json("/api/content/save", body, timeout=_TIMEOUT_FAST)


def _df_account_list(args: Dict[str, Any]) -> Dict[str, Any]:
    params: List[str] = []
    for name in ("platform", "status", "state", "tags"):
        if args.get(name) is not None:
            params.append(f"{name}={quote(str(args[name]))}")
    include_states = args.get("include_states")
    if isinstance(include_states, list):
        params.extend(f"include_states={quote(str(state))}" for state in include_states)
    if args.get("limit") is not None:
        params.append(f"limit={int(args['limit'])}")
    if args.get("offset") is not None:
        params.append(f"offset={int(args['offset'])}")
    qs = ("?" + "&".join(params)) if params else ""
    raw = _http_get(f"/api/accounts{qs}", timeout=_TIMEOUT_FAST)
    accounts = json.loads(raw.decode("utf-8"))
    return {"accounts": accounts, "total": len(accounts) if isinstance(accounts, list) else None}


def _df_mcp_registry(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    args = args or {}
    channel = str(args.get("channel") or "preview")
    tools = [
        _tool_descriptor(name, meta)
        for name, meta in TOOL_DEFS.items()
        if channel == "all" or meta.get("metadata", {}).get("channel") == channel
    ]
    return {
        "preview": True,
        "channel": channel,
        "contract_version": CONTRACT_VERSION,
        "warning": PREVIEW_WARNING,
        "tools": tools,
        "error_catalog": ERROR_CATALOG,
    }


# ── Scenario Template tools (DF-003) ──────────────────────────────────────────

def _df_list_scenario_templates(args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """List available scenario templates with optional category/tags filter."""
    args = args or {}
    params: List[str] = []
    if args.get("category"):
        params.append(f"category={quote(str(args['category']))}")
    if args.get("tags"):
        params.append(f"tags={quote(str(args['tags']))}")
    qs = ("?" + "&".join(params)) if params else ""
    raw = _http_get(f"/api/scenario-templates{qs}", timeout=_TIMEOUT_FAST)
    return {"templates": json.loads(raw.decode("utf-8"))}


def _df_get_scenario_template(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get a scenario template by ID."""
    tmpl_id = str(args["template_id"])
    raw = _http_get(f"/api/scenario-templates/{tmpl_id}", timeout=_TIMEOUT_FAST)
    return json.loads(raw.decode("utf-8"))


def _df_create_scenario_template(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new scenario template in the shared library."""
    body: Dict[str, Any] = {"name": str(args["name"])}
    if args.get("description") is not None:
        body["description"] = str(args["description"])
    if args.get("category") is not None:
        body["category"] = str(args["category"])
    if isinstance(args.get("steps"), list):
        body["steps"] = args["steps"]
    if isinstance(args.get("variables"), dict):
        body["variables"] = args["variables"]
    if args.get("tags") is not None:
        body["tags"] = str(args["tags"])
    return _http_post_json("/api/scenario-templates", body, timeout=_TIMEOUT_FAST)


def _df_update_scenario_template(args: Dict[str, Any]) -> Dict[str, Any]:
    """Update a non-builtin scenario template."""
    tmpl_id = str(args["template_id"])
    body: Dict[str, Any] = {}
    for field in ("name", "description", "category", "tags"):
        if args.get(field) is not None:
            body[field] = str(args[field])
    if isinstance(args.get("steps"), list):
        body["steps"] = args["steps"]
    if isinstance(args.get("variables"), dict):
        body["variables"] = args["variables"]
    return _http_patch_json(f"/api/scenario-templates/{tmpl_id}", body, timeout=_TIMEOUT_FAST)


def _df_delete_scenario_template(args: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a non-builtin scenario template."""
    tmpl_id = str(args["template_id"])
    _http_delete(f"/api/scenario-templates/{tmpl_id}", timeout=_TIMEOUT_FAST)
    return {"ok": True, "template_id": tmpl_id}


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
            "and parses into [{text, resource_id, content_desc, class_name, bounds, clickable, selector_by, selector_value, "
            "selector_reason, selector_volatile}]. "
            "LLM workflow: call this → pick element matching intent → call df_tap_selector with selector_by + selector_value. "
            "Prefer selector_by/selector_value over raw fields; avoid volatile selectors when a non-volatile candidate matches. "
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
            "by: resource-id | text | description | descriptionContains | "
            "descriptionStartsWith | xpath | class name. Give device or session_id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_DEVICE_OR_SESSION,
                "by": {
                    "type": "string",
                    "enum": [
                        "resource-id",
                        "text",
                        "description",
                        "descriptionContains",
                        "descriptionStartsWith",
                        "xpath",
                        "class name",
                    ],
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
                "filter_group_id": {
                    "type": "string",
                    "description": "DF-004: UUID of a DeviceGroup — only dispatch to devices in this group",
                },
                "filter_tags": {
                    "type": "string",
                    "description": "DF-004: Comma-separated tags (AND logic) — device must have ALL tags, e.g. 'fast,wifi'",
                },
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
        "description": "List campaigns of the authenticated user. Requires MCP_AUTH_TOKEN.",
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
        "description": "Update campaign status: idle | running. Requires auth token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "campaign_id": {"type": "string"},
                "status": {"type": "string", "enum": ["idle", "running"]},
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
    # ── Scenario Template management (DF-003) ─────────────────────────────────
    "df_list_scenario_templates": {
        "description": (
            "List scenario templates in the shared library. "
            "Templates can be referenced in scenario steps via "
            "{\"type\": \"run_scenario\", \"scenario_name\": \"<name>\"}. "
            "Optionally filter by category (general, utility, facebook, tiktok, ...) or "
            "comma-separated tags."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by category name (optional)"},
                "tags":     {"type": "string", "description": "Comma-separated tags to filter (optional)"},
            },
            "required": [],
        },
        "fn": _df_list_scenario_templates,
    },
    "df_get_scenario_template": {
        "description": "Get a scenario template by ID. Returns full template with steps and variables.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string", "description": "Template UUID"},
            },
            "required": ["template_id"],
        },
        "fn": _df_get_scenario_template,
    },
    "df_create_scenario_template": {
        "description": (
            "Create a new scenario template in the shared library. "
            "The template can then be used across campaigns via "
            "{\"type\": \"run_scenario\", \"scenario_name\": \"<name>\"}. "
            "Requires auth token."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Unique template name"},
                "description": {"type": "string", "default": ""},
                "category":    {"type": "string", "default": "general",
                                "description": "Category: general | utility | facebook | tiktok | ..."},
                "steps":       {"type": "array", "description": "Scenario steps (same schema as campaign steps)"},
                "variables":   {"type": "object", "description": "Default variable values for the template"},
                "tags":        {"type": "string", "description": "Comma-separated tags", "default": ""},
            },
            "required": ["name"],
        },
        "fn": _df_create_scenario_template,
    },
    "df_update_scenario_template": {
        "description": (
            "Update a non-builtin scenario template. "
            "Builtin templates (is_builtin=true) cannot be modified. "
            "Requires auth token."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string"},
                "name":        {"type": "string"},
                "description": {"type": "string"},
                "category":    {"type": "string"},
                "steps":       {"type": "array"},
                "variables":   {"type": "object"},
                "tags":        {"type": "string"},
            },
            "required": ["template_id"],
        },
        "fn": _df_update_scenario_template,
    },
    "df_delete_scenario_template": {
        "description": (
            "Delete a non-builtin scenario template. "
            "Returns 403 if the template is a builtin. "
            "Requires auth token."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string"},
            },
            "required": ["template_id"],
        },
        "fn": _df_delete_scenario_template,
    },
}


_GENERIC_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
}


TOOL_DEFS.update(
    {
        "df_device_list": {
            "description": "Canonical Epic 10 alias for df_list_devices. Enumerate fleet devices for an AI agent.",
            "inputSchema": TOOL_DEFS["df_list_devices"]["inputSchema"],
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/devices/live",
                "token_scope": "any",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_list_devices,
        },
        "df_device_claim": {
            "description": "Reserve a device for an MCP agent session. Alias of df_start_session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "Device serial"},
                    "device": {"type": "string", "description": "Legacy alias for device_id"},
                    "user_id": {"type": "string", "description": "Optional user id for audit"},
                    "agent_id": {"type": "string", "description": "Optional agent runtime identifier"},
                },
                "required": [],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/sessions/start",
                "token_scope": "device",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_device_claim,
        },
        "df_get_session_info": {
            "description": "Get session ownership and device binding for an MCP session.",
            "inputSchema": {
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/sessions/{session_id}",
                "token_scope": "device",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_get_session_info,
        },
        "df_campaign_create": {
            "description": "Canonical Epic 10 alias for df_create_campaign.",
            "inputSchema": TOOL_DEFS["df_create_campaign"]["inputSchema"],
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/campaigns",
                "token_scope": "user",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_campaign_create,
        },
        "df_campaign_run": {
            "description": "Canonical Epic 10 campaign dispatch tool. Wraps campaign run/dispatch HTTP route.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "string"},
                    "target": {"type": "object"},
                    "device_ids": {"type": "array", "items": {"type": "string"}},
                    "device_group_ids": {"type": "array", "items": {"type": "string"}},
                    "dispatch_strategy": {"type": "string", "enum": ["parallel", "sequential"]},
                    "allow_partial": {"type": "boolean"},
                    "require_online": {"type": "boolean"},
                },
                "required": ["campaign_id"],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/campaigns/{campaign_id}/dispatch",
                "token_scope": "user",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_campaign_run,
        },
        "df_content_query": {
            "description": "Query extracted content through the Device Farm content HTTP API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "collection": {"type": "string"},
                    "platform": {"type": "string"},
                    "content_type": {"type": "string"},
                    "search": {"type": "string"},
                    "device_serial": {"type": "string"},
                    "campaign_id": {"type": "string"},
                    "execution_id": {"type": "string"},
                    "content_hash": {"type": "string"},
                    "parent_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
                "required": [],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/content",
                "token_scope": "user",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_content_query,
        },
        "df_save_extraction": {
            "description": "Persist extracted content and evidence through the content save HTTP route.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "data": {"type": "object"},
                    "extraction": {"type": "object"},
                    "collection": {"type": "string", "default": "default"},
                    "platform": {"type": "string"},
                    "content_type": {"type": "string", "default": "fb_post"},
                    "dedupe_field": {"type": "string"},
                    "dedup_action": {"type": "string", "default": "skip"},
                    "tags": {"type": "string"},
                    "device_serial": {"type": "string"},
                    "campaign_id": {"type": "string"},
                    "execution_id": {"type": "string"},
                    "artifact_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["data"],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/content/save",
                "token_scope": "user",
                "channel": "preview",
                "stability": "preview",
                "require_evidence": True,
            },
            "fn": _df_save_extraction,
        },
        "df_account_list": {
            "description": "List accounts available to bind into MCP-authored scenarios.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "platform": {"type": "string"},
                    "status": {"type": "string"},
                    "state": {"type": "string"},
                    "include_states": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
                "required": [],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/api/accounts",
                "token_scope": "user",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_account_list,
        },
        "df_mcp_registry": {
            "description": "Return the MCP Preview registry, tool metadata, route parity references, and error catalog.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": ["preview", "all"], "default": "preview"},
                },
                "required": [],
            },
            "outputSchema": _GENERIC_OUTPUT_SCHEMA,
            "metadata": {
                "route": "/mcp/tools/list",
                "token_scope": "any",
                "channel": "preview",
                "stability": "preview",
            },
            "fn": _df_mcp_registry,
        },
    }
)


_TOOL_METADATA_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "df_list_devices": {"route": "/api/devices/live", "token_scope": "any"},
    "df_start_session": {"route": "/api/sessions/start", "token_scope": "device"},
    "df_end_session": {"route": "/api/sessions/end", "token_scope": "device"},
    "df_reserve_device": {"route": "/api/devices/{device_id}/reserve", "token_scope": "device"},
    "df_release_device": {"route": "/api/devices/{device_id}/release", "token_scope": "device"},
    "df_tap": {"route": "/api/tap/{serial}", "token_scope": "device"},
    "df_long_tap": {"route": "/api/devices/{serial}/long_tap", "token_scope": "device"},
    "df_swipe": {"route": "/api/swipe/{serial}", "token_scope": "device"},
    "df_scroll": {"route": "/api/devices/{serial}/scroll", "token_scope": "device"},
    "df_input_text": {"route": "/api/devices/{serial}/input_text", "token_scope": "device"},
    "df_key": {"route": "/api/key/{serial}", "token_scope": "device"},
    "df_shell": {"route": "/api/agent/{serial}/shell", "token_scope": "device"},
    "df_screenshot": {"route": "/screenshot/{serial}", "token_scope": "device"},
    "df_hierarchy": {"route": "/api/devices/{serial}/hierarchy", "token_scope": "device"},
    "df_get_ui_elements": {"route": "/api/devices/{serial}/ui_elements", "token_scope": "device"},
    "df_tap_selector": {"route": "/api/tap_selector/{serial}", "token_scope": "device"},
    "df_hit_test": {"route": "/api/devices/{serial}/hit_test", "token_scope": "device"},
    "df_open_url": {"route": "/api/open_url/{serial}", "token_scope": "device"},
    "df_run_scenario": {"route": "/api/devices/{serial}/scenario/run", "token_scope": "user"},
    "df_fleet_run": {"route": "/api/fleet/run", "token_scope": "user"},
    "df_fleet_status": {"route": "/api/fleet/status", "token_scope": "user"},
    "df_fleet_poll": {"route": "/api/fleet/status", "token_scope": "user"},
    "df_enqueue_task": {"route": "/api/task", "token_scope": "device"},
    "df_list_tasks": {"route": "/api/tasks", "token_scope": "device"},
    "df_get_task": {"route": "/api/tasks/{task_id}", "token_scope": "device"},
    "df_poll_tasks": {"route": "/api/tasks", "token_scope": "device"},
    "df_get_config": {"route": "/api/config", "token_scope": "any"},
    "df_connect_info": {"route": "/api/connect/info", "token_scope": "any"},
    "df_connect_register": {"route": "/api/connect/register", "token_scope": "device"},
    "df_list_campaigns": {"route": "/api/campaigns", "token_scope": "user"},
    "df_get_campaign": {"route": "/api/campaigns/{campaign_id}", "token_scope": "user"},
    "df_create_campaign": {"route": "/api/campaigns", "token_scope": "user"},
    "df_update_campaign_scenario": {"route": "/api/campaigns/{campaign_id}/scenario", "token_scope": "user"},
    "df_compile_campaign_scenario": {"route": "/api/campaigns/{campaign_id}/compile-scenario", "token_scope": "user"},
    "df_add_devices_to_campaign": {"route": "/api/campaigns/{campaign_id}/devices", "token_scope": "user"},
    "df_remove_device_from_campaign": {"route": "/api/campaigns/{campaign_id}/devices/{device_id}", "token_scope": "user"},
    "df_get_campaign_devices": {"route": "/api/campaigns/{campaign_id}/devices", "token_scope": "user"},
    "df_update_campaign_status": {"route": "/api/campaigns/{campaign_id}/status", "token_scope": "user"},
    "df_delete_campaign": {"route": "/api/campaigns/{campaign_id}", "token_scope": "user"},
    "df_run_campaign": {"route": "/api/campaigns/{campaign_id}/run", "token_scope": "user"},
    "df_list_scenario_templates": {"route": "/api/scenario-templates", "token_scope": "user"},
    "df_get_scenario_template": {"route": "/api/scenario-templates/{template_id}", "token_scope": "user"},
    "df_create_scenario_template": {"route": "/api/scenario-templates", "token_scope": "user"},
    "df_update_scenario_template": {"route": "/api/scenario-templates/{template_id}", "token_scope": "user"},
    "df_delete_scenario_template": {"route": "/api/scenario-templates/{template_id}", "token_scope": "user"},
}


def _normalize_tool_definitions() -> None:
    for name, meta in TOOL_DEFS.items():
        meta.setdefault("outputSchema", _GENERIC_OUTPUT_SCHEMA)
        metadata = dict(_TOOL_METADATA_DEFAULTS.get(name, {}))
        metadata.update(meta.get("metadata") or {})
        metadata.setdefault("route", "/api/unknown")
        metadata.setdefault("token_scope", "any")
        metadata.setdefault("channel", "preview")
        metadata.setdefault("stability", "preview")
        metadata["preview"] = True
        metadata["contract_version"] = CONTRACT_VERSION
        meta["metadata"] = metadata


def _tool_descriptor(name: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": name,
        "description": meta["description"],
        "inputSchema": meta["inputSchema"],
        "outputSchema": meta["outputSchema"],
        "metadata": meta["metadata"],
    }


_normalize_tool_definitions()

# Pre-compute which tool functions accept arguments (avoids inspect on every call)
import inspect as _inspect
_TOOL_TAKES_ARGS: Dict[str, bool] = {
    name: bool(_inspect.signature(meta["fn"]).parameters)
    for name, meta in TOOL_DEFS.items()
}
del _inspect


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
            "preview": True,
            "contract_version": CONTRACT_VERSION,
            "server_status": "preview",
            "warning": PREVIEW_WARNING,
            "tools": [_tool_descriptor(name, meta) for name, meta in TOOL_DEFS.items()],
        },
    }


def handle_tools_call(ctx: McpContext, msg: Dict[str, Any]) -> Dict[str, Any]:
    if not ctx.initialized:
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "error": {"code": -32002, "message": "Server not initialized"},
        }
    params = msg.get("params") or {}
    name = params.get("name")
    args = params.get("arguments") or {}
    if name not in TOOL_DEFS:
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Unknown tool: {name}"},
        }
    meta = TOOL_DEFS[name]
    fn = meta["fn"]
    started_at = time.time()
    session_id = str(args["session_id"]) if args.get("session_id") else None
    agent_id = str(args["agent_id"]) if args.get("agent_id") else None
    token_ctx: TokenContext | None = None
    active_token_reset: contextvars.Token[str | None] | None = None
    try:
        token_ctx = _runtime_token_context(str(meta["metadata"].get("token_scope", "any")))
        active_token_reset = _active_auth_token.set(token_ctx.token)
        if token_ctx.token_id_hash:
            _check_rate_limit(token_ctx.token_id_hash, name)
        if meta["metadata"].get("require_evidence") and not args.get("artifact_refs"):
            raise McpToolError(
                "df.evidence_required",
                "This MCP tool requires artifact_refs evidence before persisting output",
                details={"tool_name": name},
            )
        result = fn(args) if _TOOL_TAKES_ARGS[name] else fn()  # type: ignore[arg-type]
        _record_audit(
            session_id=session_id,
            agent_id=agent_id,
            token_id_hash=token_ctx.token_id_hash,
            org_id=token_ctx.org_id,
            tool_name=name,
            input_args=args,
            output_summary=_summarize_output(result),
            result_code="success",
            started_at=started_at,
            artifact_refs=args.get("artifact_refs") if isinstance(args.get("artifact_refs"), list) else None,
        )
        content = _tool_call_content(name, result)
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "result": {
                "content": content,
                "structuredContent": _tool_structured_content(name, result),
            },
        }
    except Exception as e:
        err = _exception_to_mcp_error(e)
        payload = _error_payload(err.code, err.message, err.details)
        _record_audit(
            session_id=session_id,
            agent_id=agent_id,
            token_id_hash=token_ctx.token_id_hash if token_ctx else None,
            tool_name=str(name),
            input_args=args,
            output_summary={"error": payload["error"]["code"]},
            result_code=payload["error"]["code"],
            started_at=started_at,
            org_id=token_ctx.org_id if token_ctx else None,
        )
        return {
            "id": msg.get("id"),
            "jsonrpc": "2.0",
            "result": {
                "isError": True,
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
                ],
            },
        }
    finally:
        if active_token_reset is not None:
            _active_auth_token.reset(active_token_reset)


def run_stdio_server() -> None:
    validate_startup_config()
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
