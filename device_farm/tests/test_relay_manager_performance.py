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


@pytest.mark.asyncio
async def test_has_ocr_survives_the_capability_whitelist(monkeypatch):
    """update_capabilities copies an explicit key list — a missed key is silent.

    When has_ocr was dropped here, ocr_supported() returned False for every
    device and every OCR step failed with OCR_AGENT_UNSUPPORTED, with nothing
    logged on either side to say why.
    """
    manager = AdbRelayManager()

    async def fake_sync_caps(serial: str, caps: dict) -> None:
        return None

    monkeypatch.setattr(manager, "_sync_caps_to_redis", fake_sync_caps)
    manager.update_capabilities([{"serial": "dev-1", "has_u2": True, "has_ocr": True}])
    await asyncio.sleep(0)

    assert manager.get_capabilities("dev-1")["has_ocr"] is True

    manager.update_capabilities([{"serial": "dev-2", "has_u2": True}])
    await asyncio.sleep(0)
    assert manager.get_capabilities("dev-2")["has_ocr"] is False


def test_every_agent_reply_type_is_dispatchable():
    """Reply types are matched against a hardcoded set on both transports.

    A type missing from it never resolves its pending future, so the caller
    waits out the whole timeout and reports a relay timeout instead of the
    answer that already arrived.
    """
    from runtime.transports import grpc_relay_server
    from runtime.transports.adb_relay_server import _REQUEST_REPLY_TYPES

    # Both relay servers must consult the same set, not two hand-kept copies.
    assert grpc_relay_server._REQUEST_REPLY_TYPES is _REQUEST_REPLY_TYPES
    assert "ocr_result" in _REQUEST_REPLY_TYPES
