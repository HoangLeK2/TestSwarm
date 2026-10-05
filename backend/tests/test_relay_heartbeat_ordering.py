"""Guard: a heartbeat must apply capabilities before it applies serials.

`update_serials` fires the device-online callback, and that callback binds u2
using `wlan_ip` from capabilities. When serials were applied first, the callback
always ran against an empty capability map and had to wait for data that could
only be written after it returned — a deadlock-by-polling that cost 2s of frozen
event loop per phone (see test_relay_callback_blocking_guard.py).

Both transports carry the same heartbeat and both must order it the same way, so
each one is pinned here. A transport that regresses only shows up in production,
on a real fleet, as an unexplained startup freeze.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from runtime.transports.grpc_relay_server import RelayServicer

_CAPS = [{"serial": "dev-1", "wlan_ip": "192.168.1.50", "has_u2": True}]


class _OrderRecordingManager:
    """Records what the online callback could see at the moment it fired."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.caps: dict[str, dict] = {}
        self.caps_visible_at_online: list[dict] = []

    # ── surface used by the transports ──
    def register_grpc_agent(self, agent_id, ctrl_q) -> None:
        pass

    def unregister_grpc_agent(self, agent_id, *, expected_queue=None) -> None:
        pass

    async def register(self, conn) -> None:
        self.calls.append("register")

    async def unregister(self, relay_id, _error="", *, expected_conn=None) -> None:
        pass

    def update_capabilities(self, caps_list) -> None:
        self.calls.append("capabilities")
        for cap in caps_list:
            self.caps[cap["serial"]] = cap

    async def update_serials(self, relay_id, serials) -> None:
        self.calls.append("serials")
        # This is where the real manager fires on_device_online.
        for serial in sorted(serials):
            self.caps_visible_at_online.append(dict(self.caps.get(serial, {})))


def _heartbeat() -> dict:
    return {
        "type": "heartbeat",
        "serials": ["dev-1"],
        "capabilities": _CAPS,
    }


@pytest.mark.asyncio
async def test_grpc_heartbeat_applies_capabilities_first():
    manager = _OrderRecordingManager()
    servicer = RelayServicer(manager, api_key=None)

    conn = object()  # _handle_json only checks it is not None
    await servicer._handle_json(_heartbeat(), "agent-1", asyncio.Queue(), "relay-1", conn)

    assert manager.calls == ["capabilities", "serials"]
    assert manager.caps_visible_at_online == [_CAPS[0]], (
        "the device-online callback ran before capabilities were stored — it "
        "cannot resolve wlan_ip and will stall waiting for it"
    )


@pytest.mark.asyncio
async def test_ws_heartbeat_applies_capabilities_first(monkeypatch):
    """Same ordering on the WebSocket relay transport."""
    from runtime.transports import adb_relay_server

    manager = _OrderRecordingManager()
    session = adb_relay_server.WsRelayAgentSession(manager, api_key=None)

    # Drive just the heartbeat branch of the message loop through a fake socket.
    frames = [
        json.dumps({"type": "register", "relay_id": "relay-1", "serials": []}),
        json.dumps(_heartbeat()),
    ]

    class _FakeWs:
        def __init__(self) -> None:
            self.sent: list = []
            self.headers = {}

        async def accept(self, *_a, **_k) -> None:
            pass

        async def send_text(self, data) -> None:
            self.sent.append(data)

        async def send_bytes(self, data) -> None:
            self.sent.append(data)

        async def close(self, *_a, **_k) -> None:
            pass

        async def receive(self):
            if frames:
                return {"type": "websocket.receive", "text": frames.pop(0)}
            raise RuntimeError("client disconnected")

    await session.handle(_FakeWs())

    assert "capabilities" in manager.calls and "serials" in manager.calls
    assert manager.calls.index("capabilities") < manager.calls.index("serials")
    assert manager.caps_visible_at_online == [_CAPS[0]]
