"""Unit tests for DeviceClient touch fallback flow: U2 → Agent shell → minitouch."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, call, patch

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient, DeviceState


def _make_device(**kwargs) -> DeviceClient:
    cfg = Config()
    d = DeviceClient(serial="test-serial", index=0, config=cfg)
    d._state = DeviceState.READY
    return d


def _make_device_with_u2() -> DeviceClient:
    """Device with U2 properly wired (tunnel ports + channels set)."""
    d = _make_device()
    mock_u2 = MagicMock()
    mock_u2.ping.return_value = True
    d._u2 = mock_u2
    d._tunnel_ports = {"u2": 9008, "stfservice": 9009, "minitouch": 0}
    d._tunnels_ready_channels = {"u2", "stfservice", "minitouch"}
    return d, mock_u2


class TestTapFallbackFlow:
    def test_tap_uses_u2_first(self):
        d, mock_u2 = _make_device_with_u2()
        d.tap(100, 200)
        mock_u2.click.assert_called_once_with(100, 200)

    def test_tap_falls_back_to_agent_shell_when_u2_none(self):
        d = _make_device()
        d._u2 = None
        mock_send = MagicMock()
        d._agent_send = mock_send
        d.tap(100, 200)
        # Should send shell command via agent
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg["type"] == "shell"
        assert "input tap 100 200" in msg["cmd"]

    def test_tap_falls_back_to_minitouch_when_no_agent(self):
        d = _make_device()
        d._u2 = None
        d._agent_send = None
        mock_mt = MagicMock()
        mock_mt.is_connected = True
        d._minitouch = mock_mt
        d.tap(100, 200)
        mock_mt.tap.assert_called_once_with(100, 200)

    def test_tap_logs_warning_when_no_method(self):
        d = _make_device()
        d._u2 = None
        d._agent_send = None
        d._minitouch = None
        # Should not raise, just log
        d.tap(100, 200)


class TestSwipeFallbackFlow:
    def test_swipe_uses_u2_first(self):
        d, mock_u2 = _make_device_with_u2()
        d.swipe(0, 0, 100, 200, duration_ms=300)
        mock_u2.swipe.assert_called_once_with(0, 0, 100, 200, duration=0.3)

    def test_swipe_falls_back_to_agent_shell(self):
        d = _make_device()
        d._u2 = None
        mock_send = MagicMock()
        d._agent_send = mock_send
        d.swipe(10, 20, 30, 40, duration_ms=500)
        msg = mock_send.call_args[0][0]
        assert msg["type"] == "shell"
        assert "input swipe 10 20 30 40 500" in msg["cmd"]

    def test_swipe_falls_back_to_minitouch(self):
        d = _make_device()
        d._u2 = None
        d._agent_send = None
        mock_mt = MagicMock()
        mock_mt.is_connected = True
        d._minitouch = mock_mt
        d.swipe(0, 0, 100, 200, duration_ms=300)
        mock_mt.swipe.assert_called_once()


class TestLongTapFallbackFlow:
    def test_long_tap_uses_u2_first(self):
        d, mock_u2 = _make_device_with_u2()
        d.long_tap(100, 200, duration_ms=1000)
        mock_u2.long_click.assert_called_once_with(100, 200, duration=1.0)

    def test_long_tap_falls_back_to_agent_shell(self):
        d = _make_device()
        d._u2 = None
        mock_send = MagicMock()
        d._agent_send = mock_send
        d.long_tap(100, 200, duration_ms=800)
        msg = mock_send.call_args[0][0]
        assert "input swipe 100 200 100 200 800" in msg["cmd"]


class TestKeyFallbackFlow:
    def test_key_uses_scrcpy_control_first(self):
        d = _make_device()
        mock_ctrl = MagicMock()
        mock_ctrl.is_connected = True
        mock_receiver = MagicMock()
        mock_receiver.control = mock_ctrl
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        d.key("home")
        mock_ctrl.key.assert_called_once_with("home")

    def test_key_falls_back_to_u2(self):
        d = _make_device()
        d._scrcpy_receiver = None
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d.key("home")
        mock_u2.press.assert_called_once_with("home")

    def test_key_falls_back_to_agent_shell(self):
        d = _make_device()
        d._scrcpy_receiver = None
        d._u2 = None
        mock_send = MagicMock()
        d._agent_send = mock_send
        d.key("home")
        msg = mock_send.call_args[0][0]
        assert msg["type"] == "shell"
        assert "KEYCODE_HOME" in msg["cmd"]


class TestInputTextFallbackFlow:
    def test_input_text_uses_scrcpy_control_first(self):
        d = _make_device()
        mock_ctrl = MagicMock()
        mock_ctrl.is_connected = True
        mock_receiver = MagicMock()
        mock_receiver.control = mock_ctrl
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        d.input_text("hello")
        mock_ctrl.input_text.assert_called_once_with("hello")

    def test_input_text_falls_back_to_u2(self):
        d = _make_device()
        d._scrcpy_receiver = None
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d.input_text("hello")
        mock_u2.send_keys.assert_called_once_with("hello")

    def test_input_text_falls_back_to_agent(self):
        d = _make_device()
        d._scrcpy_receiver = None
        d._u2 = None
        mock_send = MagicMock()
        d._agent_send = mock_send
        d.input_text("hello")
        msg = mock_send.call_args[0][0]
        assert msg["type"] == "type"
        assert msg["text"] == "hello"


class TestGetScrcpyControl:
    def test_returns_none_when_no_receiver(self):
        d = _make_device()
        d._scrcpy_receiver = None
        assert d._get_scrcpy_control() is None

    def test_returns_none_when_control_is_none(self):
        d = _make_device()
        mock_receiver = MagicMock()
        mock_receiver.control = None
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        assert d._get_scrcpy_control() is None

    def test_returns_none_when_disconnected(self):
        d = _make_device()
        mock_ctrl = MagicMock()
        mock_ctrl.is_connected = False
        mock_receiver = MagicMock()
        mock_receiver.control = mock_ctrl
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        assert d._get_scrcpy_control() is None

    def test_returns_control_when_connected(self):
        d = _make_device()
        mock_ctrl = MagicMock()
        mock_ctrl.is_connected = True
        mock_receiver = MagicMock()
        mock_receiver.control = mock_ctrl
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        assert d._get_scrcpy_control() is mock_ctrl


class TestCaptureScreenshot:
    def test_returns_cached_when_scrcpy_active(self):
        d = _make_device()
        d._scrcpy_active = True
        d._latest_jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
        result = d.capture_screenshot()
        assert result == b"\xff\xd8\xff\xe0fake-jpeg"

    def test_returns_cached_when_ws_agent_mode(self):
        d = _make_device()
        d.is_adb_mode = False
        d._latest_jpeg = b"cached"
        result = d.capture_screenshot()
        assert result == b"cached"

    def test_returns_none_when_no_cache(self):
        d = _make_device()
        d._scrcpy_active = True
        d._latest_jpeg = None
        result = d.capture_screenshot()
        assert result is None
