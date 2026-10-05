from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from runtime.transports.adb_relay_server import AdbRelayManager


class _FakeExtraDataConn:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.request_cancelled = False

    async def send_json_request(self, **_kwargs: Any) -> dict[str, Any]:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.request_cancelled = True
            raise
        return {"type": "extra_data_result", "ok": True}

    async def send_json_message(self, msg: dict[str, Any]) -> None:
        self.sent_messages.append(msg)


@pytest.mark.asyncio
async def test_extra_data_sends_agent_cancel_when_cancel_event_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AdbRelayManager()
    conn = _FakeExtraDataConn()
    cancel_event = threading.Event()

    monkeypatch.setattr(manager, "relay_for_serial", lambda _serial: conn)
    monkeypatch.setattr(manager, "resolve_serial", lambda serial: serial)

    async def cancel_soon() -> None:
        await asyncio.sleep(0.01)
        cancel_event.set()

    asyncio.create_task(cancel_soon())

    result = await manager.extra_data(
        serial="10AE7S00HD002JK",
        strategy="comments",
        context={"max_items": 500},
        timeout=5,
        cancel_event=cancel_event,
    )

    assert result == {"ok": False, "error": "cancelled", "cancelled": True}
    assert conn.request_cancelled is True
    assert len(conn.sent_messages) == 1
    cancel_msg = conn.sent_messages[0]
    assert cancel_msg["type"] == "extra_data_cancel"
    assert cancel_msg["id"].startswith("extra-")
    assert cancel_msg["serial"] == "10AE7S00HD002JK"
    assert cancel_msg["strategy"] == "comments"


class _ReplyingConn:
    relay_id = "relay-abc"

    def __init__(self, reply: dict[str, Any]) -> None:
        self._reply = reply

    async def send_json_request(self, **_kwargs: Any) -> dict[str, Any]:
        return self._reply

    async def send_json_message(self, _msg: dict[str, Any]) -> None:
        return None


@pytest.mark.asyncio
async def test_extra_data_stamps_trusted_relay_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persistence authorizes the batch by this relay_id. Without the stamp
    every uplink is rejected as content_uplink_unauthorized."""
    manager = AdbRelayManager()
    # The agent controls the body, so it may claim any identity it likes.
    conn = _ReplyingConn({
        "type": "extra_data_result",
        "ok": True,
        "_trusted_relay_id": "spoofed",
        "_trusted_serial": "spoofed",
    })
    monkeypatch.setattr(manager, "relay_for_serial", lambda _serial: conn)
    monkeypatch.setattr(manager, "resolve_serial", lambda _serial: "RESOLVED")

    result = await manager.extra_data(
        serial="alias",
        strategy="comments",
        context={},
        timeout=5,
    )

    assert result["_trusted_relay_id"] == "relay-abc"
    assert result["_trusted_serial"] == "RESOLVED"


def test_list_devices_returns_plain_list() -> None:
    manager = AdbRelayManager()
    manager._capabilities = {"serial-1": {"model": "Pixel"}}
    monkeypatch_conn = object()
    manager.relay_for_serial = lambda _serial: monkeypatch_conn  # type: ignore[method-assign]

    devices = manager.list_devices()

    assert isinstance(devices, list)
    assert devices[0]["serial"] == "serial-1"
