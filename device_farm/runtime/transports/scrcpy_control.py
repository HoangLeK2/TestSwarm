"""
scrcpy_control.py — Send touch/key/text/scroll events via scrcpy control socket.

scrcpy v3.x binary protocol for control messages:
  INJECT_KEYCODE       = 0
  INJECT_TEXT           = 1
  INJECT_TOUCH_EVENT   = 2
  INJECT_SCROLL_EVENT  = 3

All methods are blocking (time.sleep for swipe/long_tap). Call from a thread, not asyncio.
"""
from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from typing import Any

# ── scrcpy control message types ──────────────────────────────────────────────
MSG_INJECT_KEYCODE     = 0
MSG_INJECT_TEXT        = 1
MSG_INJECT_TOUCH       = 2
MSG_INJECT_SCROLL      = 3
# SC_CONTROL_MSG_TYPE_RESET_VIDEO (scrcpy v3.2+): 1-byte message that tells the
# encoder to output an IDR (keyframe) immediately. Safe to send on older versions
# — unknown type is silently ignored by the server.
MSG_RESET_VIDEO        = 16

# ── Android MotionEvent actions ───────────────────────────────────────────────
ACTION_DOWN = 0
ACTION_UP   = 1
ACTION_MOVE = 2

# ── Android KeyEvent actions ──────────────────────────────────────────────────
KEY_ACTION_DOWN = 0
KEY_ACTION_UP   = 1

# Pressure: 0xFFFF = fully pressed
PRESSURE_MAX = 0xFFFF
PRESSURE_NONE = 0

# scrcpy pointer IDs (signed i64):
#   -1 = POINTER_ID_MOUSE (treated as mouse — may not trigger touch UI)
#   -2 = POINTER_ID_GENERIC_FINGER (finger touch — what we want)
POINTER_ID_GENERIC_FINGER = 0xFFFF_FFFF_FFFF_FFFE  # -2 as unsigned u64

# Android KEYCODE constants (lowercase name → int)
KEYCODES = {
    "home":       3,
    "back":       4,
    "menu":       82,
    "power":      26,
    "enter":      66,
    "volumeup":   24,
    "volumedown": 25,
    "recent":     187,
    "app_switch": 187,
    "del":        67,
    "delete":     67,
    "tab":        61,
    "space":      62,
    "escape":     111,
    "dpad_up":    19,
    "dpad_down":  20,
    "dpad_left":  21,
    "dpad_right": 22,
    "dpad_center": 23,
}


class ScrcpyControl:
    """Send input events through scrcpy's control socket (binary protocol)."""

    def __init__(
        self,
        control_sock: socket.socket,
        screen_width: int,
        screen_height: int,
        serial: str = "",
    ) -> None:
        self._sock = control_sock
        self._lock = threading.Lock()
        self._connected = True
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.serial = serial
        self._logger = logging.getLogger(f"scrcpy_ctrl.{serial}")
        self._last_idr_request_at = 0.0
        self._idr_min_interval_s = 1.0
        # TCP_NODELAY: disable Nagle algorithm so each 32-byte touch event is sent
        # immediately without waiting for a full segment or ACK. Without this,
        # rapid tap/swipe sequences can be delayed up to 40ms per packet.
        try:
            control_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False
        try:
            self._sock.close()
        except Exception:
            pass

    def request_idr(self) -> bool:
        """Send MSG_RESET_VIDEO (scrcpy v3.2+) to request an immediate IDR keyframe.
        On older scrcpy versions the server ignores the unknown message type silently."""
        try:
            self._send(struct.pack(">B", MSG_RESET_VIDEO))
            return True
        except Exception:
            return False

    def _request_idr_throttled(self, min_interval_s: float | None = None) -> None:
        interval = self._idr_min_interval_s if min_interval_s is None else float(min_interval_s)
        now = time.monotonic()
        if now - self._last_idr_request_at < interval:
            return
        if self.request_idr():
            self._last_idr_request_at = now

    # ── Touch ─────────────────────────────────────────────────────────────────

    def tap(self, x: int, y: int, pressure: int = PRESSURE_MAX) -> None:
        self._logger.debug(f"tap({x},{y}) screen={self.screen_width}x{self.screen_height}")
        self._inject_touch(ACTION_DOWN, x, y, pressure)
        self._inject_touch(ACTION_UP, x, y, PRESSURE_NONE)

    def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> None:
        self._logger.debug(f"swipe({x1},{y1})→({x2},{y2}) ms={duration_ms}")
        self._inject_touch(ACTION_DOWN, x1, y1, PRESSURE_MAX)
        delay = duration_ms / 1000.0 / steps
        for i in range(1, steps + 1):
            t = i / steps
            cx = int(x1 + (x2 - x1) * t)
            cy = int(y1 + (y2 - y1) * t)
            time.sleep(delay)
            if not self._connected:
                return
            self._inject_touch(ACTION_MOVE, cx, cy, PRESSURE_MAX)
        for _ in range(5):
            self._inject_touch(ACTION_MOVE, x2, y2, PRESSURE_MAX)
        self._inject_touch(ACTION_UP, x2, y2, PRESSURE_NONE)

    def long_tap(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._inject_touch(ACTION_DOWN, x, y, PRESSURE_MAX)
        time.sleep(duration_ms / 1000.0)
        self._inject_touch(ACTION_UP, x, y, PRESSURE_NONE)

    def double_tap(self, x: int, y: int) -> None:
        self.tap(x, y)
        time.sleep(0.05)
        self.tap(x, y)

    # ── Key ───────────────────────────────────────────────────────────────────

    def key(self, key_name: str) -> None:
        """Inject key press. Accepts friendly names ('home','back') or numeric keycode."""
        k = key_name.strip().lower()
        keycode = KEYCODES.get(k)
        if keycode is None:
            # Strip KEYCODE_ prefix if present, then try as int
            raw = k
            if raw.startswith("keycode_"):
                raw = raw[8:]  # len("keycode_") = 8
            try:
                keycode = int(raw)
            except (ValueError, TypeError):
                self._logger.warning(f"Unknown key: {key_name}")
                return
        self._inject_keycode(KEY_ACTION_DOWN, keycode)
        self._inject_keycode(KEY_ACTION_UP, keycode)

    # ── Text ──────────────────────────────────────────────────────────────────

    def input_text(self, text: str) -> None:
        encoded = text.encode("utf-8")
        msg = struct.pack(">BI", MSG_INJECT_TEXT, len(encoded)) + encoded
        self._send(msg)

    # ── Scroll ────────────────────────────────────────────────────────────────

    def scroll(self, x: int, y: int, hscroll: int = 0, vscroll: int = -1) -> None:
        """Inject scroll event. vscroll: -1 = one line down, 1 = one line up."""
        msg = struct.pack(
            ">B"      # type
            "ii"      # x, y (signed 32-bit)
            "HH"      # screen_width, screen_height
            "ii"      # hscroll, vscroll (signed 32-bit)
            "I",      # buttons
            MSG_INJECT_SCROLL,
            x, y,
            self.screen_width, self.screen_height,
            int(hscroll), int(vscroll),
            0,
        )
        self._send(msg)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _inject_touch(
        self,
        action: int,
        x: int,
        y: int,
        pressure: int,
        pointer_id: int = POINTER_ID_GENERIC_FINGER,
        action_button: int = 0,
        buttons: int = 0,
    ) -> None:
        """INJECT_TOUCH_EVENT: 32 bytes total."""
        msg = struct.pack(
            ">BBQiiHHHII",
            MSG_INJECT_TOUCH,
            action,
            pointer_id,
            x, y,
            self.screen_width, self.screen_height,
            pressure,
            action_button,
            buttons,
        )
        self._send(msg)

    def _inject_keycode(
        self,
        action: int,
        keycode: int,
        repeat: int = 0,
        metastate: int = 0,
    ) -> None:
        """INJECT_KEYCODE: 14 bytes total."""
        msg = struct.pack(
            ">BBIII",
            MSG_INJECT_KEYCODE,
            action,
            keycode,
            repeat,
            metastate,
        )
        self._send(msg)

    def _send(self, data: bytes) -> None:
        if not self._connected:
            self._logger.debug("_send skipped: not connected")
            return
        with self._lock:
            try:
                self._sock.sendall(data)
            except Exception as exc:
                self._connected = False
                self._logger.warning(f"control send failed: {exc}")


# ─── Relay-mode control ───────────────────────────────────────────────────────

class RelayScrcpyControl:
    """
    Identical API to ScrcpyControl, but routes binary packets through
    AdbRelayManager.send_scrcpy_control() instead of a local socket.

    DeviceClient uses this transparently when the relay is active.
    """

    def __init__(
        self,
        serial: str,
        relay_manager: "Any",   # AdbRelayManager (avoid circular import)
        loop: "Any",            # asyncio.AbstractEventLoop from DeviceClient
        screen_width: int = 0,
        screen_height: int = 0,
    ) -> None:
        self._serial = serial
        self._relay = relay_manager
        self._loop = loop
        self._connected = True
        self._lock = threading.Lock()
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.serial = serial
        self._logger = logging.getLogger(f"relay_ctrl.{serial}")
        self._last_idr_request_at = 0.0
        self._idr_min_interval_s = 1.0

    @property
    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self._connected = False

    # ── Public API (mirrors ScrcpyControl) ────────────────────────────────────

    def request_idr(self) -> bool:
        """Send MSG_RESET_VIDEO (scrcpy v3.2+) to request an immediate IDR keyframe."""
        try:
            self._send(struct.pack(">B", MSG_RESET_VIDEO))
            return True
        except Exception:
            return False

    def _request_idr_throttled(self, min_interval_s: float | None = None) -> None:
        interval = self._idr_min_interval_s if min_interval_s is None else float(min_interval_s)
        now = time.monotonic()
        if now - self._last_idr_request_at < interval:
            return
        if self.request_idr():
            self._last_idr_request_at = now

    def tap(self, x: int, y: int, pressure: int = PRESSURE_MAX) -> None:
        self._inject_touch(ACTION_DOWN, x, y, pressure)
        self._inject_touch(ACTION_UP, x, y, PRESSURE_NONE)

    def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
        steps: int = 12,
    ) -> None:
        self._inject_touch(ACTION_DOWN, x1, y1, PRESSURE_MAX)
        delay = duration_ms / 1000.0 / steps
        for i in range(1, steps + 1):
            t = i / steps
            cx = int(x1 + (x2 - x1) * t)
            cy = int(y1 + (y2 - y1) * t)
            time.sleep(delay)
            if not self._connected:
                return
            self._inject_touch(ACTION_MOVE, cx, cy, PRESSURE_MAX)
        for _ in range(5):
            self._inject_touch(ACTION_MOVE, x2, y2, PRESSURE_MAX)
        self._inject_touch(ACTION_UP, x2, y2, PRESSURE_NONE)

    def long_tap(self, x: int, y: int, duration_ms: int = 800) -> None:
        self._inject_touch(ACTION_DOWN, x, y, PRESSURE_MAX)
        time.sleep(duration_ms / 1000.0)
        self._inject_touch(ACTION_UP, x, y, PRESSURE_NONE)

    def double_tap(self, x: int, y: int) -> None:
        self.tap(x, y)
        time.sleep(0.05)
        self.tap(x, y)

    def key(self, key_name: str) -> None:
        k = key_name.strip().lower()
        keycode = KEYCODES.get(k)
        if keycode is None:
            raw = k
            if raw.startswith("keycode_"):
                raw = raw[8:]
            try:
                keycode = int(raw)
            except (ValueError, TypeError):
                self._logger.warning(f"Unknown key: {key_name}")
                return
        self._inject_keycode(KEY_ACTION_DOWN, keycode)
        self._inject_keycode(KEY_ACTION_UP, keycode)

    def input_text(self, text: str) -> None:
        encoded = text.encode("utf-8")
        msg = struct.pack(">BI", MSG_INJECT_TEXT, len(encoded)) + encoded
        self._send(msg)

    def scroll(self, x: int, y: int, hscroll: int = 0, vscroll: int = -1) -> None:
        msg = struct.pack(
            ">B" "ii" "HH" "ii" "I",
            MSG_INJECT_SCROLL,
            x, y,
            self.screen_width, self.screen_height,
            int(hscroll), int(vscroll),
            0,
        )
        self._send(msg)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _inject_touch(
        self,
        action: int,
        x: int,
        y: int,
        pressure: int,
        pointer_id: int = POINTER_ID_GENERIC_FINGER,
        action_button: int = 0,
        buttons: int = 0,
    ) -> None:
        msg = struct.pack(
            ">BBQiiHHHII",
            MSG_INJECT_TOUCH,
            action,
            pointer_id,
            x, y,
            self.screen_width, self.screen_height,
            pressure,
            action_button,
            buttons,
        )
        self._send(msg)

    def _inject_keycode(
        self,
        action: int,
        keycode: int,
        repeat: int = 0,
        metastate: int = 0,
    ) -> None:
        msg = struct.pack(
            ">BBIII",
            MSG_INJECT_KEYCODE,
            action,
            keycode,
            repeat,
            metastate,
        )
        self._send(msg)

    def _send(self, data: bytes) -> None:
        if not self._connected:
            return
        with self._lock:
            import asyncio
            try:
                from runtime.transports.grpc_relay_server import _GrpcWriteQueue
                _grpc_queue_cls = _GrpcWriteQueue
            except ImportError:
                _grpc_queue_cls = None
            try:
                # Fast path: if the relay connection uses a _GrpcWriteQueue,
                # put_nowait is called via call_soon_threadsafe to avoid the
                # overhead of creating a coroutine Future for every tap/swipe.
                conn = self._relay.relay_for_serial(self._serial)
                write_q = getattr(conn, "_write_queue", None) if conn else None
                if _grpc_queue_cls is not None and isinstance(write_q, _grpc_queue_cls):
                    # _GrpcWriteQueue: build binary frame, convert via put_nowait
                    serial_b = self._serial.encode()
                    frame = bytes([0x43, len(serial_b)]) + serial_b + data
                    def _enqueue_fast() -> None:
                        try:
                            write_q.put_nowait(frame)
                        except Exception:
                            asyncio.run_coroutine_threadsafe(
                                self._relay.send_scrcpy_control(self._serial, data),
                                self._loop,
                            )
                    self._loop.call_soon_threadsafe(_enqueue_fast)
                else:
                    # WebSocket path: schedule coroutine via run_coroutine_threadsafe
                    asyncio.run_coroutine_threadsafe(
                        self._relay.send_scrcpy_control(self._serial, data),
                        self._loop,
                    )
            except Exception as exc:
                self._logger.warning("relay control send failed: %s", exc)
