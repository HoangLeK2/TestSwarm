"""
minitouch_ws.py — MinitouchWsClient: sends minitouch protocol commands directly
via WebSocket tunnel_data, bypassing the TCP socket layer entirely.

Architecture (old, broken):
  MinitouchSender → TCP socket → TcpWsTunnel → WS → Agent → LocalSocket → MinitouchAgent

Architecture (new, simple):
  MinitouchWsClient → WS tunnel_data → Agent → LocalSocket → MinitouchAgent

No TCP socket, no banner handshake, no timing issues.
MinitouchAgent (in-app, abstract:"minitouchagent") handles rotation + touch injection.
"""
from __future__ import annotations

import base64
import logging
import threading
from typing import Any, Callable, Dict


class MinitouchWsClient:
    """
    Encodes minitouch wire-protocol commands and sends them directly as
    WebSocket tunnel_data messages to the Android agent.

    The agent's ServiceTunnel writes these bytes to the abstract socket
    "minitouchagent", where MinitouchAgent reads and injects touch events.

    Coordinates are screen pixels (same as what the server receives in hello).
    MinitouchAgent handles rotation internally via calculateCoordsForScreen().

    Command subset used:
        r                       — reset all contacts
        d <c> <x> <y> <p>      — finger down (contact, x, y, pressure)
        m <c> <x> <y> <p>      — finger move
        u <c>                  — finger up
        c                      — commit (execute pending events)
        w <ms>                 — wait milliseconds
    """

    def __init__(
        self,
        serial: str,
        send_fn: Callable[[Dict[str, Any]], None],
        screen_width: int = 1080,
        screen_height: int = 1920,
    ) -> None:
        self.serial = serial
        self.screen_width = screen_width
        self.screen_height = screen_height
        self._send = send_fn
        self._lock = threading.Lock()
        self._logger = logging.getLogger(f"minitouch_ws.{serial}")
        self._logger.info(
            f"[{serial}] MinitouchWsClient ready "
            f"(direct WS, screen={screen_width}x{screen_height})"
        )

    @property
    def is_connected(self) -> bool:
        return self._send is not None

    def disconnect(self) -> None:
        self._send = None

    # ── Public API (same as MinitouchSender) ─────────────────────────────────

    def tap(self, x: int, y: int, pressure: int = 50) -> None:
        self._send_cmd(f"r\nd 0 {x} {y} {pressure}\nc\nu 0\nc\n")

    def long_tap(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._send_cmd(f"r\nd 0 {x} {y} 50\nc\nw {duration_ms}\nu 0\nc\n")

    def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
        steps: int = 10,
    ) -> None:
        lines = [f"r\nd 0 {x1} {y1} 50\nc\n"]
        wait_per_step = max(1, duration_ms // steps)
        for i in range(1, steps + 1):
            ix = x1 + (x2 - x1) * i // steps
            iy = y1 + (y2 - y1) * i // steps
            lines.append(f"m 0 {ix} {iy} 50\nc\nw {wait_per_step}\n")
        lines.append("u 0\nc\n")
        self._send_cmd("".join(lines))

    def double_tap(self, x: int, y: int) -> None:
        self._send_cmd(
            f"r\nd 0 {x} {y} 50\nc\nu 0\nc\n"
            f"w 50\n"
            f"d 0 {x} {y} 50\nc\nu 0\nc\n"
        )

    def pinch(self, cx: int, cy: int, scale: float, duration_ms: int = 300, steps: int = 10) -> None:
        """Two-finger pinch/spread centered at (cx, cy)."""
        offset = int(min(self.screen_width, self.screen_height) * 0.15)
        x1s, y1s = cx - offset, cy
        x2s, y2s = cx + offset, cy
        factor = max(0.2, min(scale, 3.0))
        x1e = int(cx + (x1s - cx) * factor)
        y1e = int(cy + (y1s - cy) * factor)
        x2e = int(cx + (x2s - cx) * factor)
        y2e = int(cy + (y2s - cy) * factor)
        wait_per_step = max(1, duration_ms // steps)
        lines = [
            f"r\n"
            f"d 0 {x1s} {y1s} 50\nd 1 {x2s} {y2s} 50\nc\n"
        ]
        for i in range(1, steps + 1):
            ix1 = x1s + (x1e - x1s) * i // steps
            iy1 = y1s + (y1e - y1s) * i // steps
            ix2 = x2s + (x2e - x2s) * i // steps
            iy2 = y2s + (y2e - y2s) * i // steps
            lines.append(f"m 0 {ix1} {iy1} 50\nm 1 {ix2} {iy2} 50\nc\nw {wait_per_step}\n")
        lines.append("u 0\nu 1\nc\n")
        self._send_cmd("".join(lines))

    def reset(self) -> None:
        self._send_cmd("r\nc\n")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _send_cmd(self, cmd: str) -> None:
        fn = self._send
        if fn is None:
            return
        data = base64.b64encode(cmd.encode("utf-8")).decode("ascii")
        with self._lock:
            try:
                fn({
                    "type":    "tunnel_data",
                    "channel": "minitouch",
                    "data":    data,
                })
            except Exception as exc:
                self._logger.warning(f"[{self.serial}] minitouch_ws send error: {exc}")
