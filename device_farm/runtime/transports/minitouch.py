
from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class MinitouchInfo:
    version: int
    max_contacts: int
    max_x: int
    max_y: int
    max_pressure: int
    pid: int


class MinitouchSender:
    """
    Thread-safe wrapper for sending touch events to a device via minitouch.
    Coordinates are given in screen pixels and scaled internally.
    """

    def __init__(
        self,
        serial: str,
        host: str,
        port: int,
        virtual_width: int,
        virtual_height: int,
    ) -> None:
        self.serial = serial
        self.host = host
        self.port = port
        self.virtual_width = virtual_width
        self.virtual_height = virtual_height

        self._logger = logging.getLogger(f"minitouch.{serial}")
        self._lock = threading.Lock()
        self._sock: Optional[socket.socket] = None
        self._info: Optional[MinitouchInfo] = None
        self._connected = False

    # ── Public API ──────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Open socket connection and read minitouch header."""
        with self._lock:
            self._do_connect()

    def disconnect(self) -> None:
        with self._lock:
            self._do_disconnect()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_info(self) -> Optional[MinitouchInfo]:
        return self._info

    def tap(self, screen_x: int, screen_y: int, pressure: int = 50) -> None:
        """Send a single-finger tap."""
        tx, ty = self._scale(screen_x, screen_y)
        cmd = f"r\nd 0 {tx} {ty} {pressure}\nc\nu 0\nc\n"
        self._send(cmd)

    def long_tap(self, screen_x: int, screen_y: int, duration_ms: int = 800) -> None:
        """Send a long press."""
        tx, ty = self._scale(screen_x, screen_y)
        cmd = f"r\nd 0 {tx} {ty} 50\nc\nw {duration_ms}\nu 0\nc\n"
        self._send(cmd)

    def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
        steps: int = 10,
    ) -> None:
        """Smooth swipe from (x1,y1) to (x2,y2) over duration_ms."""
        tx1, ty1 = self._scale(x1, y1)
        tx2, ty2 = self._scale(x2, y2)

        lines = [f"r\nd 0 {tx1} {ty1} 50\nc\n"]
        wait_per_step = max(1, duration_ms // steps)
        for i in range(1, steps + 1):
            ix = tx1 + (tx2 - tx1) * i // steps
            iy = ty1 + (ty2 - ty1) * i // steps
            lines.append(f"m 0 {ix} {iy} 50\nc\nw {wait_per_step}\n")
        lines.append("u 0\nc\n")

        self._send("".join(lines))

    def double_tap(self, screen_x: int, screen_y: int) -> None:
        tx, ty = self._scale(screen_x, screen_y)
        cmd = (
            f"r\nd 0 {tx} {ty} 50\nc\nu 0\nc\n"
            f"w 50\n"
            f"d 0 {tx} {ty} 50\nc\nu 0\nc\n"
        )
        self._send(cmd)

    def reset(self) -> None:
        """Clear any stuck touches."""
        self._send("r\nc\n")

    # ── Internal ────────────────────────────────────────────────────────────

    def _scale(self, sx: int, sy: int) -> tuple[int, int]:
        """Scale screen pixels to minitouch coordinate space."""
        if self._info is None or self.virtual_width == 0 or self.virtual_height == 0:
            return sx, sy
        tx = int(sx * self._info.max_x / self.virtual_width)
        ty = int(sy * self._info.max_y / self.virtual_height)
        # Clamp to valid range
        tx = max(0, min(tx, self._info.max_x))
        ty = max(0, min(ty, self._info.max_y))
        return tx, ty

    def _do_connect(self) -> None:
        if self._connected:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((self.host, self.port))
        # Banner can be delayed (server may wait 2.5s for tunnel_data); allow up to 12s
        sock.settimeout(12.0)

        # Read header lines until we have all three
        buf = ""
        version = max_contacts = max_x = max_y = max_pressure = pid = 0
        header_lines_received = 0
        while header_lines_received < 3:
            try:
                chunk = sock.recv(256).decode("utf-8", errors="replace")
            except socket.timeout:
                raise ConnectionError("minitouch banner timeout (no full header in 12s)")
            if not chunk:
                raise ConnectionError("minitouch closed before sending header")
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line.startswith("v "):
                    version = int(line.split()[1])
                    header_lines_received += 1
                elif line.startswith("^ "):
                    parts = line.split()
                    max_contacts = int(parts[1])
                    max_x = int(parts[2])
                    max_y = int(parts[3])
                    max_pressure = int(parts[4])
                    header_lines_received += 1
                elif line.startswith("$ "):
                    pid = int(line.split()[1])
                    header_lines_received += 1

        self._info = MinitouchInfo(
            version=version,
            max_contacts=max_contacts,
            max_x=max_x,
            max_y=max_y,
            max_pressure=max_pressure,
            pid=pid,
        )
        self._sock = sock
        self._connected = True
        self._logger.info(
            f"[{self.serial}] minitouch connected: "
            f"max_contacts={max_contacts} "
            f"max_x={max_x} max_y={max_y}"
        )
        # Clear any lingering touches from a previous session
        self._sock.sendall(b"r\nc\n")

    def _do_disconnect(self) -> None:
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _send(self, cmd: str, _retry: bool = True) -> None:
        """Send raw command string. Reconnects once on failure."""
        with self._lock:
            if not self._connected or self._sock is None:
                self._logger.warning(f"[{self.serial}] minitouch not connected; skipping command")
                return
            try:
                self._sock.sendall(cmd.encode("utf-8"))
            except OSError as exc:
                self._logger.warning(f"[{self.serial}] minitouch send error: {exc}")
                self._do_disconnect()
                if _retry:
                    try:
                        self._do_connect()
                        self._sock.sendall(cmd.encode("utf-8"))
                    except Exception as e:
                        self._logger.error(f"[{self.serial}] minitouch reconnect/send failed: {e}")
