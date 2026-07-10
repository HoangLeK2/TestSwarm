from __future__ import annotations

import asyncio
import json

import pytest

from runtime.transports.adb_relay_server import (
    AdbRelayManager,
    RelayConnection,
)


@pytest.mark.asyncio
async def test_start_scrcpy_without_profile_uses_fleet_defaults() -> None:
    manager = AdbRelayManager()
    queue: asyncio.Queue[str | bytes] = asyncio.Queue()
    conn = RelayConnection("relay-1", queue)
    conn.serials.add("serial-1")
    manager._relays["relay-1"] = conn
    manager._serial_index["serial-1"] = "relay-1"

    assert await manager.start_scrcpy(
        serial="serial-1",
        max_fps=0,
        max_width=0,
        enable_control=True,
        port=27183,
        bitrate=0,
    )

    payload = json.loads(await queue.get())
    assert payload["type"] == "scrcpy_start"
    assert payload["max_fps"] == 15
    assert payload["max_width"] == 540
    assert payload["bitrate"] == 800_000
