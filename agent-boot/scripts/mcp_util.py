"""Shared Device Farm MCP stdio helpers for agent-boot scripts."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
MCP_CMD = ["sh", str(_REPO / "scripts" / "run_device_farm_mcp.sh")]


def parse_tool_payload(resp: dict) -> dict | None:
    result = resp.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        text = (content[0].get("text") if content else "")[:800]
        return {"error": text or "mcp_tool_error"}
    content = result.get("content") or []
    if not content:
        return result if isinstance(result, dict) else None
    text = content[0].get("text") or ""
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:400]}
    if isinstance(outer, dict) and "result" in outer:
        return outer["result"]
    return outer if isinstance(outer, dict) else None


def ensure_mcp_token() -> str:
    token = (os.environ.get("MCP_AUTH_TOKEN") or "").strip()
    if token.startswith("eyJ"):
        return token
    if token.startswith("dfmcp_"):
        from mcp.token_store import lookup_token

        if lookup_token(token) is not None:
            return token
    import urllib.request

    base = os.environ.get("DEVICE_FARM_URL", "http://localhost:8081").rstrip("/")
    email = os.environ.get("DF_LOGIN_EMAIL", "dev@gmail.com")
    password = os.environ.get("DF_LOGIN_PASSWORD", "11111111")
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
    jwt = (body.get("access_token") or "").strip()
    if not jwt:
        raise RuntimeError(f"login failed: {body}")
    return jwt


class _StdIoMcpClientExt:
    """StdIoMcpClient with configurable per-call timeout (scenario runs can take minutes)."""

    call_timeout: float = 60.0

    def __init__(self, cmd: list[str]) -> None:
        from mcp.client import StdIoMcpClient

        self._inner = StdIoMcpClient(cmd)
        self._orig_send = self._inner._send

        def _send_with_timeout(payload: dict[str, Any]) -> dict[str, Any]:
            msg_id = str(payload.get("id") or "")
            # Reimplement timeout by temporarily patching queue get
            import queue as _queue
            import uuid

            payload = dict(payload)
            msg_id = str(payload.get("id") or uuid.uuid4().hex)
            payload["id"] = msg_id
            if "jsonrpc" not in payload:
                payload["jsonrpc"] = "2.0"
            q: _queue.Queue = _queue.Queue(maxsize=1)
            with self._inner._lock:
                self._inner._pending[msg_id] = q
                assert self._inner._proc.stdin is not None
                self._inner._proc.stdin.write(json.dumps(payload) + "\n")
                self._inner._proc.stdin.flush()
            resp: dict[str, Any] = q.get(timeout=self.call_timeout)
            with self._inner._lock:
                self._inner._pending.pop(msg_id, None)
            return resp

        self._inner._send = _send_with_timeout

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return self._inner.call_tool(name, args)

    def close(self) -> None:
        self._inner.close()


class McpRunner:
    """Thin wrapper around StdIoMcpClient with timing + JWT auth."""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._client: Any = None

    def _client_instance(self) -> Any:
        if self._client is None:
            token = ensure_mcp_token()
            os.environ["MCP_AUTH_TOKEN"] = token
            os.environ.setdefault("DEVICE_FARM_URL", "http://localhost:8081")
            self._client = _StdIoMcpClientExt(MCP_CMD)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def call(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        *,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        payload = dict(args or {})
        payload.setdefault("device", self.serial)
        client = self._client_instance()
        if timeout_s is not None:
            client.call_timeout = timeout_s
        elif tool == "df_run_scenario":
            client.call_timeout = 300.0
        else:
            client.call_timeout = 60.0
        t0 = time.perf_counter()
        resp = self._client_instance().call_tool(tool, payload)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        parsed = parse_tool_payload(resp)
        ok = parsed is not None and not (isinstance(parsed, dict) and parsed.get("error"))
        return {
            "tool": tool,
            "ok": ok,
            "ms": ms,
            "args": {k: v for k, v in payload.items() if k != "device"},
            "result": parsed,
        }

    def hierarchy(self, *, refresh: bool = True) -> tuple[str | None, dict[str, Any]]:
        row = self.call("df_hierarchy", {"refresh": refresh})
        parsed = row.get("result") or {}
        if not row.get("ok"):
            return None, row
        xml = parsed.get("xml")
        if not isinstance(xml, str) or not xml.strip():
            row["ok"] = False
            row["error"] = "empty_xml"
            return None, row
        row["bytes"] = len(xml.encode("utf-8"))
        row["element_count"] = parsed.get("element_count")
        return xml, row
