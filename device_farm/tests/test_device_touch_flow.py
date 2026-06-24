"""Unit tests for DeviceClient touch fallback flow: U2 → Agent shell."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
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
    d._tunnel_ports = {"u2": 9008, "stfservice": 9009}
    d._tunnels_ready_channels = {"u2", "stfservice"}
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

    def test_tap_uses_relay_u2_batch_before_shell_when_local_u2_none(self):
        d = _make_device()
        d._u2 = None
        d._loop = object()
        d._adb_serial = "172.16.0.83:5555"
        d._agent_send = MagicMock()

        class _Relay:
            def relay_for_serial(self, serial):
                return object() if serial == "172.16.0.83:5555" else None

            def resolve_serial(self, serial):
                return "172.16.0.83:5555"

            async def u2_batch(self, serial, actions, timeout=30.0):
                self.serial = serial
                self.actions = actions
                self.timeout = timeout
                return {"ok": True, "results": [{"op": "click", "ok": True}]}

        relay = _Relay()

        def run_now(coro, _loop):
            result = {}

            async def _run():
                result["value"] = await coro

            import asyncio

            asyncio.run(_run())
            return SimpleNamespace(result=lambda timeout=None: result["value"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            d.tap(100, 200)

        assert relay.serial == "172.16.0.83:5555"
        assert relay.actions == [{"op": "click", "x": 100, "y": 200}]
        assert relay.timeout <= 2.0
        d._agent_send.assert_not_called()

    def test_tap_prefers_legacy_relay_proxy_before_relay_u2_batch(self):
        d = _make_device()
        d._loop = object()
        d._adb_serial = "172.16.0.83:5555"
        d._agent_send = MagicMock()
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d._u2_last_ok_at = time.monotonic()
        d.ensure_u2_healthy = MagicMock(return_value=True)

        class _Relay:
            def relay_for_serial(self, serial):
                return object() if serial == "172.16.0.83:5555" else None

            def resolve_serial(self, serial):
                return "172.16.0.83:5555"

            async def u2_batch(self, serial, actions, timeout=30.0):
                self.actions = actions
                return {"ok": True, "results": [{"op": "click", "ok": True}]}

        relay = _Relay()
        relay.actions = None

        def run_now(coro, _loop):
            result = {}

            async def _run():
                result["value"] = await coro

            import asyncio

            asyncio.run(_run())
            return SimpleNamespace(result=lambda timeout=None: result["value"])

        with patch.object(d, "_u2_session_uses_relay", return_value=True), \
                patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            d.tap(100, 200)

        mock_u2.click.assert_called_once_with(100, 200)
        assert relay.actions is None
        d._agent_send.assert_not_called()

    def test_tap_skips_stale_u2_proxy_probe_when_relay_u2_batch_available(self):
        d = _make_device()
        d._loop = object()
        d._adb_serial = "172.16.0.83:5555"
        d._agent_send = MagicMock()
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d._u2_last_ok_at = 0.0
        d.ensure_u2_healthy = MagicMock(return_value=False)

        class _Relay:
            def relay_for_serial(self, serial):
                return object() if serial == "172.16.0.83:5555" else None

            def resolve_serial(self, serial):
                return "172.16.0.83:5555"

            async def u2_batch(self, serial, actions, timeout=30.0):
                self.actions = actions
                return {"ok": True, "results": [{"op": "click", "ok": True}]}

        relay = _Relay()

        def run_now(coro, _loop):
            result = {}

            async def _run():
                result["value"] = await coro

            import asyncio

            asyncio.run(_run())
            return SimpleNamespace(result=lambda timeout=None: result["value"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            d.tap(100, 200)

        d.ensure_u2_healthy.assert_not_called()
        mock_u2.click.assert_not_called()
        assert relay.actions == [{"op": "click", "x": 100, "y": 200}]
        d._agent_send.assert_not_called()

    def test_tap_logs_warning_when_no_u2_no_scrcpy_no_agent(self):
        """No touch path; tap logs a warning and returns without crash."""
        d = _make_device()
        d._u2 = None
        d._agent_send = None
        d.tap(100, 200)  # must not raise

    def test_tap_logs_warning_when_no_method(self):
        d = _make_device()
        d._u2 = None
        d._agent_send = None
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

    def test_swipe_uses_relay_u2_batch_before_shell_when_local_u2_none(self):
        d = _make_device()
        d._u2 = None
        d._loop = object()
        d._adb_serial = "172.16.0.83:5555"
        d._agent_send = MagicMock()

        class _Relay:
            def relay_for_serial(self, serial):
                return object() if serial == "172.16.0.83:5555" else None

            def resolve_serial(self, serial):
                return "172.16.0.83:5555"

            async def u2_batch(self, serial, actions, timeout=30.0):
                self.actions = actions
                return {"ok": True, "results": [{"op": "swipe", "ok": True}]}

        relay = _Relay()

        def run_now(coro, _loop):
            result = {}

            async def _run():
                result["value"] = await coro

            import asyncio

            asyncio.run(_run())
            return SimpleNamespace(result=lambda timeout=None: result["value"])

        with patch("runtime.transports.adb_relay_server.get_relay_manager", return_value=relay), \
                patch("runtime.core.device_client.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            d.swipe(10, 20, 30, 40, duration_ms=500)

        assert relay.actions == [{
            "op": "swipe",
            "fx": 10,
            "fy": 20,
            "tx": 30,
            "ty": 40,
            "duration": 0.5,
        }]
        d._agent_send.assert_not_called()

    def test_swipe_logs_warning_when_no_u2_no_scrcpy_no_agent(self):
        """No touch path; swipe logs a warning and returns without crash."""
        d = _make_device()
        d._u2 = None
        d._agent_send = None
        d.swipe(0, 0, 100, 200, duration_ms=300)  # must not raise


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
    def test_nav_key_does_not_use_scrcpy_control(self):
        d = _make_device()
        mock_ctrl = MagicMock()
        mock_ctrl.is_connected = True
        mock_receiver = MagicMock()
        mock_receiver.control = mock_ctrl
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        d.key("home")
        mock_ctrl.key.assert_not_called()

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
        assert msg["type"] == "key"
        assert msg["key"] == "home"


class TestInputTextFallbackFlow:
    def test_input_text_does_not_use_scrcpy_control(self):
        d = _make_device()
        mock_ctrl = MagicMock()
        mock_ctrl.is_connected = True
        mock_receiver = MagicMock()
        mock_receiver.control = mock_ctrl
        mock_receiver._ctrl_lock = threading.Lock()
        d._scrcpy_receiver = mock_receiver
        d.input_text("hello")
        mock_ctrl.input_text.assert_not_called()

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

    def test_sync_input_text_uses_adb_keyboard_replace(self):
        d = _make_device()
        d._scrcpy_receiver = None
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d.sync_input_text("việt")
        mock_u2.adb_keyboard_replace_text.assert_called_once_with("việt")

    def test_sync_input_text_clear_uses_adb_keyboard(self):
        d = _make_device()
        d._scrcpy_receiver = None
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d.clear_live_input()
        mock_u2.adb_keyboard_clear_text.assert_called_once()

    def test_append_input_text_uses_ime_append(self):
        d = _make_device()
        d._scrcpy_receiver = None
        mock_u2 = MagicMock()
        d._u2 = mock_u2
        d.append_input_text("x")
        mock_u2.send_keys_append.assert_called_once_with("x")


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

    def test_skip_cache_does_not_return_stale_scrcpy_frame(self):
        d = _make_device()
        d._scrcpy_active = True
        d._latest_jpeg = b"\xff\xd8\xff\xe0stale-jpeg"
        result = d.capture_screenshot(skip_cache=True)
        assert result is None

    def test_returns_cached_when_ws_agent_mode(self):
        d = _make_device()
        d._latest_jpeg = b"cached"
        result = d.capture_screenshot()
        assert result == b"cached"

    def test_returns_none_when_no_cache(self):
        d = _make_device()
        d._scrcpy_active = True
        d._latest_jpeg = None
        result = d.capture_screenshot()
        assert result is None
