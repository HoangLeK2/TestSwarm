"""Tests for install_apk scenario step."""
from __future__ import annotations

from unittest.mock import MagicMock

from tasks.scenario.context import ScenarioContext
from tasks.scenario.steps.navigation import handle_install_apk


def _ctx(device: MagicMock | None = None) -> ScenarioContext:
    sc = MagicMock(spec=ScenarioContext)
    sc.serial = "emulator-5554"
    sc.device = device or MagicMock()
    return sc


def test_install_apk_success():
    device = MagicMock()
    sc = _ctx(device)
    result = {"ok": True}
    handle_install_apk(
        sc,
        {"type": "install_apk", "url": "https://cdn.example.com/app.apk", "timeout": 120},
        0,
        result,
    )
    assert result["ok"] is True
    device.install.assert_called_once_with(
        "https://cdn.example.com/app.apk", timeout=120.0, verify_package=None
    )


def test_install_apk_forwards_verify_package():
    device = MagicMock()
    sc = _ctx(device)
    result = {"ok": True}
    handle_install_apk(
        sc,
        {
            "type": "install_apk",
            "url": "https://cdn.example.com/fb.apk",
            "verify_package": "com.facebook.katana",
        },
        0,
        result,
    )
    assert result["ok"] is True
    device.install.assert_called_once_with(
        "https://cdn.example.com/fb.apk",
        timeout=90.0,
        verify_package="com.facebook.katana",
    )


def test_install_apk_empty_url():
    sc = _ctx()
    result = {"ok": True}
    handle_install_apk(sc, {"type": "install_apk", "url": "  "}, 0, result)
    assert result["ok"] is False
    assert "empty url" in result["message"]


def test_install_apk_failure():
    device = MagicMock()
    device.install.side_effect = RuntimeError("HTTP 500")
    sc = _ctx(device)
    result = {"ok": True}
    handle_install_apk(
        sc,
        {"type": "install_apk", "url": "https://cdn.example.com/bad.apk"},
        0,
        result,
    )
    assert result["ok"] is False
    assert "install_apk failed" in result["message"]
