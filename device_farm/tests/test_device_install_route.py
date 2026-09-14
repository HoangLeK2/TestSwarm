"""install() must let the agent host download the APK, not the phone.

atx-agent's /install hands the URL to the device, which answers
"http download error" whenever it has no route to the APK host.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient


def _device(relay_result: dict | None) -> DeviceClient:
    d = DeviceClient(serial="test-serial", index=0, config=Config())
    d._relay_batch_available = MagicMock(return_value=relay_result is not None)
    d._run_relay_coro = MagicMock(return_value=relay_result or {})
    return d


def test_install_prefers_relay_and_skips_atx_agent():
    d = _device({"ok": True, "results": [{"op": "install_apk", "ok": True}]})
    d._u2 = MagicMock()

    d.install("https://cdn.example/fb.apk", timeout=300.0, verify_package="com.facebook.katana")

    d._u2.install.assert_not_called()
    assert d._run_relay_coro.call_args.kwargs["timeout"] == 300.0


def test_install_falls_back_to_atx_agent_when_no_relay():
    d = _device(None)
    d._u2 = MagicMock()

    d.install("https://cdn.example/fb.apk", timeout=120.0)

    d._u2.install.assert_called_once_with(
        "https://cdn.example/fb.apk", timeout=120.0, verify_package=None
    )


def test_install_reports_both_routes_when_both_fail():
    d = _device({"ok": False, "error": "adb install failed"})
    d._u2 = MagicMock()
    d._u2.install.side_effect = RuntimeError("install task 1 failed: http download error")

    with pytest.raises(RuntimeError) as exc:
        d.install("https://cdn.example/fb.apk")

    assert "adb install failed" in str(exc.value)
    assert "http download error" in str(exc.value)


def test_install_reports_relay_error_when_no_atx_agent():
    d = _device({"ok": False, "error": "no relay for serial"})
    d._u2 = None

    with pytest.raises(RuntimeError, match="no relay for serial"):
        d.install("https://cdn.example/fb.apk")
