from __future__ import annotations

"""
Minimal MCP stdio client + convenience wrappers.

This is structured version of the previous `mcp_mobile.py`:
- `StdIoMcpClient` implements a bare JSON-RPC client over stdio.
- `MobileActions` is a thin helper for calling mobile-mcp style tools.
"""

import queue
import subprocess
import threading
import uuid
from typing import Any, Dict, List, Optional

from common.fast_codec import dumps, loads


class StdIoMcpClient:
    """
    Minimal MCP stdio client.

    Expects the server to speak JSON-RPC 2.0 over stdin/stdout with
    `initialize`, `tools/list`, `tools/call` methods.
    """

    def __init__(self, cmd: List[str], client_name: str = "device_farm", client_version: str = "0.1.0") -> None:
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._pending: Dict[str, queue.Queue] = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._initialize(client_name, client_version)

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = loads(line)
            except Exception:
                continue
            msg_id = str(msg.get("id") or "")
            if msg_id and msg_id in self._pending:
                self._pending[msg_id].put(msg)

    def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = str(payload.get("id") or uuid.uuid4().hex)
        payload["id"] = msg_id
        if "jsonrpc" not in payload:
            payload["jsonrpc"] = "2.0"
        q: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            self._pending[msg_id] = q
            assert self._proc.stdin is not None
            self._proc.stdin.write(dumps(payload) + "\n")
            self._proc.stdin.flush()
        resp: Dict[str, Any] = q.get(timeout=30)
        with self._lock:
            self._pending.pop(msg_id, None)
        return resp

    def _initialize(self, client_name: str, client_version: str) -> None:
        init_req = {
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": client_name, "version": client_version},
                "capabilities": {},
            },
        }
        self._send(init_req)

    def list_tools(self) -> Dict[str, Any]:
        req = {
            "method": "tools/list",
            "params": {},
        }
        return self._send(req)

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        req = {
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": args,
            },
        }
        return self._send(req)

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:
            pass


class MobileActions:
    """
    Convenience wrapper around canonical mobile-mcp tools for one device.

    Use this when talking to the Node `mobile-mcp` server, *not* to the
    device_farm MCP server (which exposes `df_*` tools).
    """

    def __init__(self, client: StdIoMcpClient, device_id: str) -> None:
        self._client = client
        self._device_id = device_id

    # ── Primitive tools ──────────────────────────────────────────────────────

    def tap(self, x: int, y: int) -> None:
        self._client.call_tool(
            "mobile_click_on_screen_at_coordinates",
            {"device": self._device_id, "x": x, "y": y},
        )

    def double_tap(self, x: int, y: int) -> None:
        self._client.call_tool(
            "mobile_double_tap_on_screen",
            {"device": self._device_id, "x": x, "y": y},
        )

    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._client.call_tool(
            "mobile_long_press_on_screen_at_coordinates",
            {"device": self._device_id, "x": x, "y": y, "duration": duration_ms},
        )

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        if abs(x2 - x1) >= abs(y2 - y1):
            direction = "left" if x2 < x1 else "right"
            distance = abs(x2 - x1)
        else:
            direction = "up" if y2 < y1 else "down"
            distance = abs(y2 - y1)
        self._client.call_tool(
            "mobile_swipe_on_screen",
            {
                "device": self._device_id,
                "direction": direction,
                "x": x1,
                "y": y1,
                "distance": distance,
            },
        )

    def type_text(self, text: str, submit: bool = False) -> None:
        self._client.call_tool(
            "mobile_type_keys",
            {"device": self._device_id, "text": text, "submit": submit},
        )

    def press_button(self, button: str) -> None:
        self._client.call_tool(
            "mobile_press_button",
            {"device": self._device_id, "button": button},
        )

    def open_url(self, url: str) -> None:
        self._client.call_tool(
            "mobile_open_url",
            {"device": self._device_id, "url": url},
        )

    # ── Introspection helpers ────────────────────────────────────────────────

    def list_elements(self) -> Any:
        resp = self._client.call_tool(
            "mobile_list_elements_on_screen",
            {"device": self._device_id},
        )
        result = resp.get("result") or {}
        content = result.get("content") or []
        if not content:
            return []
        txt = content[0].get("text", "") or ""
        marker = "Found these elements on screen: "
        payload = txt
        if marker in txt:
            payload = txt.split(marker, 1)[1]
        try:
            return loads(payload)
        except Exception:
            return []

    def get_screenshot_base64(self) -> Optional[str]:
        resp = self._client.call_tool(
            "mobile_take_screenshot",
            {"device": self._device_id},
        )
        result = resp.get("result") or {}
        content = result.get("content") or []
        if not content:
            return None
        img = content[0]
        if img.get("type") != "image":
            return None
        return img.get("data")
