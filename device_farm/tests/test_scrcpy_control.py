"""Unit tests for ScrcpyControl binary protocol and touch/key/text/scroll methods."""
from __future__ import annotations

import socket
import struct
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from runtime.transports.scrcpy_control import (
    ACTION_DOWN,
    ACTION_MOVE,
    ACTION_UP,
    KEYCODES,
    KEY_ACTION_DOWN,
    KEY_ACTION_UP,
    MSG_INJECT_KEYCODE,
    MSG_INJECT_SCROLL,
    MSG_INJECT_TEXT,
    MSG_INJECT_TOUCH,
    POINTER_ID_GENERIC_FINGER,
    PRESSURE_MAX,
    PRESSURE_NONE,
    ScrcpyControl,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeSocket:
    """Collects bytes sent via sendall() for assertion."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def sendall(self, data: bytes) -> None:
        if self.closed:
            raise OSError("socket closed")
        self.data.extend(data)

    def close(self) -> None:
        self.closed = True


def _make_ctrl(w: int = 1080, h: int = 1920) -> tuple[ScrcpyControl, FakeSocket]:
    sock = FakeSocket()
    ctrl = ScrcpyControl(sock, screen_width=w, screen_height=h, serial="test")  # type: ignore[arg-type]
    return ctrl, sock


# ── Binary Protocol Tests ────────────────────────────────────────────────────


class TestInjectTouch:
    def test_touch_message_is_32_bytes(self):
        ctrl, sock = _make_ctrl()
        ctrl._inject_touch(ACTION_DOWN, 100, 200, PRESSURE_MAX)
        assert len(sock.data) == 32

    def test_touch_fields(self):
        ctrl, sock = _make_ctrl(1080, 1920)
        ctrl._inject_touch(ACTION_DOWN, 540, 960, PRESSURE_MAX)
        msg = bytes(sock.data)
        (
            msg_type, action, pointer_id,
            x, y, sw, sh, pressure, ab, btns,
        ) = struct.unpack(">BBQiiHHHII", msg)
        assert msg_type == MSG_INJECT_TOUCH
        assert action == ACTION_DOWN
        assert pointer_id == POINTER_ID_GENERIC_FINGER
        assert x == 540
        assert y == 960
        assert sw == 1080
        assert sh == 1920
        assert pressure == PRESSURE_MAX
        assert ab == 0
        assert btns == 0

    def test_touch_up_zero_pressure(self):
        ctrl, sock = _make_ctrl()
        ctrl._inject_touch(ACTION_UP, 100, 200, PRESSURE_NONE)
        msg = bytes(sock.data)
        _, action, _, _, _, _, _, pressure, _, _ = struct.unpack(">BBQiiHHHII", msg)
        assert action == ACTION_UP
        assert pressure == PRESSURE_NONE


class TestInjectKeycode:
    def test_keycode_message_is_14_bytes(self):
        ctrl, sock = _make_ctrl()
        ctrl._inject_keycode(KEY_ACTION_DOWN, 4)
        assert len(sock.data) == 14

    def test_keycode_fields(self):
        ctrl, sock = _make_ctrl()
        ctrl._inject_keycode(KEY_ACTION_DOWN, 66, repeat=1, metastate=2)
        msg = bytes(sock.data)
        msg_type, action, keycode, repeat, meta = struct.unpack(">BBIII", msg)
        assert msg_type == MSG_INJECT_KEYCODE
        assert action == KEY_ACTION_DOWN
        assert keycode == 66
        assert repeat == 1
        assert meta == 2


class TestInjectText:
    def test_text_message(self):
        ctrl, sock = _make_ctrl()
        ctrl.input_text("hello")
        msg = bytes(sock.data)
        msg_type, length = struct.unpack(">BI", msg[:5])
        text = msg[5:].decode("utf-8")
        assert msg_type == MSG_INJECT_TEXT
        assert length == 5
        assert text == "hello"

    def test_text_utf8(self):
        ctrl, sock = _make_ctrl()
        ctrl.input_text("xin chào")
        msg = bytes(sock.data)
        _, length = struct.unpack(">BI", msg[:5])
        text = msg[5:].decode("utf-8")
        assert text == "xin chào"
        assert length == len("xin chào".encode("utf-8"))


class TestInjectScroll:
    def test_scroll_message_is_25_bytes(self):
        ctrl, sock = _make_ctrl()
        ctrl.scroll(540, 960, hscroll=0, vscroll=-1)
        assert len(sock.data) == 25

    def test_scroll_fields(self):
        ctrl, sock = _make_ctrl(1080, 1920)
        ctrl.scroll(540, 960, hscroll=0, vscroll=-1)
        msg = bytes(sock.data)
        msg_type, x, y, sw, sh, hs, vs, btns = struct.unpack(">BiiHHiiI", msg)
        assert msg_type == MSG_INJECT_SCROLL
        assert x == 540
        assert y == 960
        assert sw == 1080
        assert sh == 1920
        assert hs == 0
        assert vs == -1
        assert btns == 0


# ── High-Level API Tests ─────────────────────────────────────────────────────


class TestTap:
    def test_tap_sends_down_then_up(self):
        ctrl, sock = _make_ctrl()
        ctrl.tap(100, 200)
        # 2 touch messages = 64 bytes
        assert len(sock.data) == 64
        msg1 = struct.unpack(">BBQiiHHHII", bytes(sock.data[:32]))
        msg2 = struct.unpack(">BBQiiHHHII", bytes(sock.data[32:]))
        assert msg1[1] == ACTION_DOWN
        assert msg2[1] == ACTION_UP

    def test_tap_coordinates(self):
        ctrl, sock = _make_ctrl()
        ctrl.tap(333, 777)
        msg1 = struct.unpack(">BBQiiHHHII", bytes(sock.data[:32]))
        assert msg1[3] == 333  # x
        assert msg1[4] == 777  # y


class TestSwipe:
    def test_swipe_sends_down_moves_up(self):
        ctrl, sock = _make_ctrl()
        ctrl.swipe(0, 0, 100, 100, duration_ms=10, steps=2)
        # 1 DOWN + 2 MOVE + 1 UP = 4 messages = 128 bytes
        assert len(sock.data) == 128
        msgs = [
            struct.unpack(">BBQiiHHHII", bytes(sock.data[i * 32 : (i + 1) * 32]))
            for i in range(4)
        ]
        assert msgs[0][1] == ACTION_DOWN
        assert msgs[1][1] == ACTION_MOVE
        assert msgs[2][1] == ACTION_MOVE
        assert msgs[3][1] == ACTION_UP

    def test_swipe_interpolation(self):
        ctrl, sock = _make_ctrl()
        ctrl.swipe(0, 0, 100, 200, duration_ms=10, steps=2)
        msgs = [
            struct.unpack(">BBQiiHHHII", bytes(sock.data[i * 32 : (i + 1) * 32]))
            for i in range(4)
        ]
        # MOVE 1: 50% → (50, 100)
        assert msgs[1][3] == 50
        assert msgs[1][4] == 100
        # MOVE 2: 100% → (100, 200)
        assert msgs[2][3] == 100
        assert msgs[2][4] == 200

    def test_swipe_stops_early_if_disconnected(self):
        ctrl, sock = _make_ctrl()
        ctrl._connected = False
        ctrl.swipe(0, 0, 100, 100, duration_ms=100, steps=10)
        # DOWN is sent (before loop), then loop sees _connected=False and returns
        # Actually _send checks _connected first, so nothing is sent
        assert len(sock.data) == 0


class TestKey:
    def test_key_by_name(self):
        ctrl, sock = _make_ctrl()
        ctrl.key("home")
        # 2 keycode messages (DOWN + UP) = 28 bytes
        assert len(sock.data) == 28
        msg1 = struct.unpack(">BBIII", bytes(sock.data[:14]))
        msg2 = struct.unpack(">BBIII", bytes(sock.data[14:]))
        assert msg1[2] == KEYCODES["home"]  # keycode = 3
        assert msg1[1] == KEY_ACTION_DOWN
        assert msg2[1] == KEY_ACTION_UP

    def test_key_by_numeric_string(self):
        ctrl, sock = _make_ctrl()
        ctrl.key("66")
        msg1 = struct.unpack(">BBIII", bytes(sock.data[:14]))
        assert msg1[2] == 66

    def test_key_case_insensitive(self):
        ctrl, sock = _make_ctrl()
        ctrl.key("HOME")
        msg1 = struct.unpack(">BBIII", bytes(sock.data[:14]))
        assert msg1[2] == 3

    def test_key_keycode_prefix(self):
        ctrl, sock = _make_ctrl()
        ctrl.key("KEYCODE_66")
        msg1 = struct.unpack(">BBIII", bytes(sock.data[:14]))
        assert msg1[2] == 66

    def test_key_unknown_logs_warning(self):
        ctrl, sock = _make_ctrl()
        ctrl.key("nonexistent_key")
        assert len(sock.data) == 0  # nothing sent

    def test_all_named_keys_are_valid(self):
        """Every key in KEYCODES dict should produce valid messages."""
        for name, expected_code in KEYCODES.items():
            ctrl, sock = _make_ctrl()
            ctrl.key(name)
            assert len(sock.data) == 28, f"Key '{name}' should produce DOWN+UP"
            msg1 = struct.unpack(">BBIII", bytes(sock.data[:14]))
            assert msg1[2] == expected_code, f"Key '{name}' wrong keycode"


# ── Connection / Disconnect Tests ────────────────────────────────────────────


class TestConnection:
    def test_send_skipped_when_disconnected(self):
        ctrl, sock = _make_ctrl()
        ctrl.disconnect()
        ctrl.tap(100, 200)
        assert len(sock.data) == 0

    def test_disconnect_closes_socket(self):
        ctrl, sock = _make_ctrl()
        ctrl.disconnect()
        assert sock.closed
        assert not ctrl.is_connected

    def test_send_failure_sets_disconnected(self):
        ctrl, sock = _make_ctrl()
        sock.close()  # force sendall to raise
        ctrl._send(b"\x00")
        assert not ctrl.is_connected

    def test_double_disconnect_is_safe(self):
        ctrl, sock = _make_ctrl()
        ctrl.disconnect()
        ctrl.disconnect()  # should not raise


class TestScreenDimensions:
    def test_touch_uses_current_screen_dims(self):
        ctrl, sock = _make_ctrl(1080, 2316)
        ctrl.screen_width = 720
        ctrl.screen_height = 1280
        ctrl._inject_touch(ACTION_DOWN, 0, 0, PRESSURE_MAX)
        msg = struct.unpack(">BBQiiHHHII", bytes(sock.data))
        assert msg[5] == 720
        assert msg[6] == 1280
