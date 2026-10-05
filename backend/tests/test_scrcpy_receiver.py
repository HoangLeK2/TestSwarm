"""Unit tests for ScrcpyReceiver — init, start/stop, control lifecycle."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from runtime.transports.scrcpy_receiver import ScrcpyReceiver


class TestScrcpyReceiverInit:
    def test_default_state(self):
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test:5555",
            adb_path="adb",
            port=27183,
            server_jar="/tmp/scrcpy-server",
        )
        assert r.serial == "test:5555"
        assert r.port == 27183
        assert r.max_fps == 30
        assert r.max_width == 800
        assert r.enable_control is False
        assert r.control is None
        assert r.on_frame is None
        assert r._running is False
        assert r.device_width == 0
        assert r.device_height == 0
        assert r._device_msg_thread is None

    def test_on_frame_param(self):
        cb = MagicMock()
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test",
            adb_path="adb",
            port=27183,
            server_jar="/tmp/s",
            on_frame=cb,
        )
        assert r.on_frame is cb

    def test_enable_control_param(self):
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test",
            adb_path="adb",
            port=27183,
            server_jar="/tmp/s",
            enable_control=True,
        )
        assert r.enable_control is True


class TestScrcpyReceiverStartStop:
    def test_start_sets_running(self):
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test", adb_path="adb", port=27183, server_jar="/tmp/s"
        )
        # Don't actually start the thread — just test the flag
        r._running = False
        r.start_receiver()
        assert r._running is True
        r._running = False  # prevent thread from running

    def test_stop_sets_not_running(self):
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test", adb_path="adb", port=27183, server_jar="/tmp/s"
        )
        r._running = True
        # Mock _server_proc so stop doesn't crash
        r._server_proc = None
        r.stop_receiver()
        assert r._running is False

    def test_stop_disconnects_control(self):
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test", adb_path="adb", port=27183, server_jar="/tmp/s"
        )
        r._running = True
        r._server_proc = None
        mock_ctrl = MagicMock()
        with r._ctrl_lock:
            r.control = mock_ctrl
        r.stop_receiver()
        mock_ctrl.disconnect.assert_called_once()
        assert r.control is None


class TestCtrlLockThreadSafety:
    def test_concurrent_control_access(self):
        """Verify _ctrl_lock prevents race on control attribute."""
        r = ScrcpyReceiver.__new__(ScrcpyReceiver)
        r.__init__(  # type: ignore[misc]
            serial="test", adb_path="adb", port=27183, server_jar="/tmp/s"
        )
        results = []

        def reader():
            for _ in range(100):
                with r._ctrl_lock:
                    ctrl = r.control
                results.append(ctrl)

        def writer():
            mock = MagicMock()
            mock.is_connected = True
            for _ in range(100):
                with r._ctrl_lock:
                    r.control = mock
                with r._ctrl_lock:
                    r.control = None

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        # Should not crash — all reads return either None or a mock
        assert len(results) == 100
        for val in results:
            assert val is None or hasattr(val, "is_connected")
