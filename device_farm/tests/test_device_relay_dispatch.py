"""Tests for device relay command dispatch (control plane + video relay fallback)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.routes import devices as devices_routes


@pytest.mark.asyncio
async def test_dispatch_uses_relay_when_control_missing(monkeypatch):
    ctrl = MagicMock()
    ctrl.conn_for_serial.return_value = None

    relay = MagicMock()
    relay.relay_for_serial.return_value = MagicMock()
    relay.bootstrap = AsyncMock(return_value=True)

    async def _resolve(*_args, **_kwargs):
        return "10AE7S00HD002JK"

    monkeypatch.setattr(devices_routes, "_get_ctrl_servicer_optional", lambda: ctrl)
    monkeypatch.setattr(devices_routes, "_get_relay_manager_optional", lambda: relay)
    monkeypatch.setattr(devices_routes, "_resolve_relay_serial", _resolve)

    out = await devices_routes._dispatch_relay_command(
        None, "dev-id", "user-id", None, kind="bootstrap", timeout=180.0
    )

    assert out.ok is True
    relay.bootstrap.assert_awaited_once_with("10AE7S00HD002JK", timeout=180.0)
    ctrl.bootstrap.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_prefers_control_when_available(monkeypatch):
    ctrl = MagicMock()
    ctrl.conn_for_serial.return_value = MagicMock()
    ctrl.bootstrap = AsyncMock(
        return_value={"ok": True, "output": "done", "exit_code": 0, "error": ""}
    )

    relay = MagicMock()
    relay.relay_for_serial.return_value = MagicMock()
    relay.bootstrap = AsyncMock(return_value=True)

    async def _resolve(*_args, **_kwargs):
        return "10AE7S00HD002JK"

    monkeypatch.setattr(devices_routes, "_get_ctrl_servicer_optional", lambda: ctrl)
    monkeypatch.setattr(devices_routes, "_get_relay_manager_optional", lambda: relay)
    monkeypatch.setattr(devices_routes, "_resolve_relay_serial", _resolve)

    out = await devices_routes._dispatch_relay_command(
        None, "dev-id", "user-id", None, kind="bootstrap", timeout=180.0
    )

    assert out.ok is True
    assert out.output == "done"
    ctrl.bootstrap.assert_awaited_once()
    relay.bootstrap.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_relay_serial_raises_when_unreachable(monkeypatch):
    ctrl = MagicMock()
    ctrl.conn_for_serial.return_value = None
    ctrl.find_serial_by_ip.return_value = None

    relay = MagicMock()
    relay.relay_for_serial.return_value = None
    relay.resolve_serial.side_effect = lambda s: s

    device = MagicMock()
    device.user_id = "u1"
    device.serial = "ABC123"
    device.adb_serial = None
    device.adb_ip = None

    monkeypatch.setattr(
        devices_routes.repo, "get_device", AsyncMock(return_value=device)
    )

    with pytest.raises(HTTPException) as exc:
        await devices_routes._resolve_relay_serial(
            MagicMock(), "dev-id", "u1", ctrl, relay, manager=None
        )

    assert exc.value.status_code == 409
