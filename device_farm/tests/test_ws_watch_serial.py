from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

import web.ws as ws_module
from web.ws import WebSocketManager


def _h264_cfg(serial: str) -> bytes:
    s = serial.encode("utf-8")
    # Minimal 0x10 frame header; payload can be empty for this unit test.
    return bytes([0x10, len(s)]) + s + b"\x00\x01\x00\x01" + b"\x00"


def _h264_key(serial: str) -> bytes:
    s = serial.encode("utf-8")
    # Minimal 0x11 keyframe header; payload can be empty for this unit test.
    # Layout used by DeviceClient.on_agent_h264_video:
    # [0x11][slen][serial][w:2][h:2][is_key:1][pts_hi:4][pts_lo:4][payload...]
    return (
        bytes([0x11, len(s)])
        + s
        + b"\x00\x01\x00\x01"
        + b"\x01"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


@dataclass
class _FakeDevice:
    serial: str
    screen_width: int = 1080
    screen_height: int = 1920
    state: str = "READY"
    _relay_id: str = "relay-test"
    _scenario_active: int = 0
    _q: Optional[asyncio.Queue] = None
    calls: list[tuple] | None = None

    def subscribe_status(self, _ctrl_q: asyncio.Queue) -> None:
        return

    def unsubscribe_status(self, _ctrl_q: asyncio.Queue) -> None:
        return

    def status_dict(self) -> dict:
        return {"type": "status", "serial": self.serial, "state": "READY"}

    def get_log_lines(self) -> list[str]:
        return []

    def get_stream_bootstrap(self, *_args, **_kwargs):
        return None, None

    def subscribe_frames(self, q: asyncio.Queue) -> None:
        self._q = q
        # Provide a config + key immediately so the sender has bytes to forward.
        try:
            q.put_nowait(_h264_cfg(self.serial))
            q.put_nowait(_h264_key(self.serial))
        except Exception:
            pass

    def unsubscribe_frames(self, q: asyncio.Queue) -> None:
        if self._q is q:
            self._q = None

    def tap(self, x: int, y: int) -> None:
        if self.calls is None:
            self.calls = []
        self.calls.append(("tap", x, y))


class _FakeManager:
    def __init__(self, devices: list[_FakeDevice]):
        self._by_serial = {d.serial: d for d in devices}

    def all_devices(self):
        return list(self._by_serial.values())

    def get_device(self, serial: str):
        return self._by_serial.get(serial)


class _PingThenDisconnectWebSocket:
    def __init__(self) -> None:
        self.state = SimpleNamespace()
        self.sent: list[dict] = []
        self._received = False

    async def receive_json(self) -> dict:
        if not self._received:
            self._received = True
            return {"type": "ping"}
        raise WebSocketDisconnect()

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)


class _BootstrapFailOnceWebSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._failed = False

    async def send_bytes(self, data: bytes) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("bootstrap send failed")
        self.sent.append(data)


def test_ws_watch_serial_spawns_sender_and_emits_binary_frames():
    dev = _FakeDevice(serial="SN001")
    mgr = _FakeManager([dev])
    ws_manager = WebSocketManager(mgr, db_enabled=False, read_only=False)

    app = FastAPI()

    @app.websocket("/ws")
    async def _ws(ws: WebSocket):
        await ws_manager.connect(ws, user_id=None)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # Handshake emits status JSON; ignore.
        _ = ws.receive_json()
        ws.send_json({"type": "watch_serial", "serial": "SN001"})

        # After watch, backend should forward binary frames from the device queue.
        buf1 = ws.receive_bytes()
        buf2 = ws.receive_bytes()
        assert buf1[0] in (0x10, 0x11)
        assert buf2[0] in (0x10, 0x11)
        assert buf1 != buf2

        ws.send_json({"type": "unwatch_serial", "serial": "SN001"})


def test_ws_watch_serial_reassert_cancels_pending_unwatch(monkeypatch):
    monkeypatch.setattr(ws_module, "STREAM_WS_UNWATCH_GRACE_MS", 50.0)
    dev = _FakeDevice(serial="SN001")
    mgr = _FakeManager([dev])
    ws_manager = WebSocketManager(mgr, db_enabled=False, read_only=False)

    app = FastAPI()

    @app.websocket("/ws")
    async def _ws(ws: WebSocket):
        await ws_manager.connect(ws, user_id=None)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()
        ws.send_json({"type": "watch_serial", "serial": "SN001"})
        _ = ws.receive_bytes()
        _ = ws.receive_bytes()

        ws.send_json({"type": "unwatch_serial", "serial": "SN001"})
        ws.send_json({"type": "watch_serial", "serial": "SN001"})

        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            if dev._q is None:
                break
            time.sleep(0.02)

        assert dev._q is not None


@pytest.mark.asyncio
async def test_device_sender_keeps_live_subscription_when_bootstrap_send_fails():
    class BootstrapDevice(_FakeDevice):
        def get_stream_bootstrap(self, *_args, **_kwargs):
            return _h264_cfg(self.serial), None

    dev = BootstrapDevice(serial="SN_BOOT")
    ws_manager = WebSocketManager(_FakeManager([dev]), db_enabled=False, read_only=False)
    ws = _BootstrapFailOnceWebSocket()
    task = asyncio.create_task(ws_manager._device_sender(ws, dev, asyncio.Lock()))

    try:
        for _ in range(20):
            if ws.sent:
                break
            await asyncio.sleep(0.05)
        assert ws.sent
        assert ws.sent[0][0] in (0x10, 0x11)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_ws_receiver_pong_uses_connection_send_lock():
    mgr = _FakeManager([])
    ws_manager = WebSocketManager(mgr, db_enabled=False, read_only=False)
    ws = _PingThenDisconnectWebSocket()
    lock = asyncio.Lock()

    await lock.acquire()
    task = asyncio.create_task(ws_manager._receiver(ws, lock))
    await asyncio.sleep(0)

    assert ws.sent == []

    lock.release()
    await task

    assert ws.sent
    assert ws.sent[0]["type"] == "pong"


def test_ws_multi_action_returns_per_device_result_and_scales_ratio():
    dev_a = _FakeDevice(serial="A", screen_width=1000, screen_height=2000)
    dev_b = _FakeDevice(serial="B", screen_width=500, screen_height=1000)
    mgr = _FakeManager([dev_a, dev_b])
    ws_manager = WebSocketManager(mgr, db_enabled=False, read_only=False)

    app = FastAPI()

    @app.websocket("/ws")
    async def _ws(ws: WebSocket):
        await ws_manager.connect(ws, user_id=None)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()
        _ = ws.receive_json()
        ws.send_json(
            {
                "type": "multi_action",
                "request_id": "req-ws",
                "serials": ["A", "B"],
                "action": {"type": "tap_ratio", "rx": 0.25, "ry": 0.5},
            }
        )

        result = ws.receive_json()
        assert result["type"] == "multi_action_result"
        assert result["request_id"] == "req-ws"
        assert result["ok"] is True
        assert dev_a.calls == [("tap", 250, 1000)]
        assert dev_b.calls == [("tap", 125, 500)]
