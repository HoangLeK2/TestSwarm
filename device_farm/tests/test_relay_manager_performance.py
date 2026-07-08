from __future__ import annotations

import asyncio

import pytest

from runtime.transports.adb_relay_server import AdbRelayManager


@pytest.mark.asyncio
async def test_update_capabilities_skips_unchanged_heartbeat(monkeypatch):
    manager = AdbRelayManager()
    callback_calls: list[tuple[str, dict]] = []
    redis_syncs: list[tuple[str, dict]] = []

    async def fake_sync_caps(serial: str, caps: dict) -> None:
        redis_syncs.append((serial, dict(caps)))

    monkeypatch.setattr(manager, "_sync_caps_to_redis", fake_sync_caps)
    manager.set_on_capabilities_update(
        lambda serial, caps: callback_calls.append((serial, dict(caps)))
    )

    payload = [{"serial": "dev-1", "has_u2": True, "model": "Pixel"}]
    manager.update_capabilities(payload)
    await asyncio.sleep(0)

    manager.update_capabilities(payload)
    await asyncio.sleep(0)

    assert [serial for serial, _ in callback_calls] == ["dev-1"]
    assert [serial for serial, _ in redis_syncs] == ["dev-1"]

    manager.update_capabilities(
        [{"serial": "dev-1", "has_u2": True, "model": "Pixel 2"}]
    )
    await asyncio.sleep(0)

    assert [serial for serial, _ in callback_calls] == ["dev-1", "dev-1"]
    assert [serial for serial, _ in redis_syncs] == ["dev-1", "dev-1"]
