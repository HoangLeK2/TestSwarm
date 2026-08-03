from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

import web.ws as ws_module
from web.ws import WebSocketManager
from runtime.core.device_client import LatestFrameStore
from runtime.stream_telemetry import stream_telemetry


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
        return _h264_cfg(self.serial), _h264_key(self.serial)

    def subscribe_frames(self, q: asyncio.Queue, **_kwargs):
        self._q = q
        return self.get_stream_bootstrap()

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


class _MessagesThenDisconnectWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self.state = SimpleNamespace()
        self._messages = iter(messages)

    async def receive_json(self) -> dict:
        try:
            return next(self._messages)
        except StopIteration:
            raise WebSocketDisconnect() from None


class _BootstrapFailOnceWebSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._failed = False

    async def send_bytes(self, data: bytes) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("bootstrap send failed")
        self.sent.append(data)


class _CollectingWebSocket:
    def __init__(self) -> None:
        self.sent: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)


class _CountingScrcpyControl:
    def __init__(self) -> None:
        self.idr_requests = 0

    def request_idr(self) -> bool:
        self.idr_requests += 1
        return True


class _DisconnectedOnAcceptWebSocket:
    async def accept(self) -> None:
        raise RuntimeError(
            "Expected ASGI message 'websocket.send' or 'websocket.close', "
            "but got 'websocket.accept'"
        )


@pytest.mark.anyio
async def test_ws_connect_ignores_client_disconnect_before_accept() -> None:
    ws_manager = WebSocketManager(
        _FakeManager([]),
        db_enabled=False,
        read_only=False,
    )

    await ws_manager.connect(_DisconnectedOnAcceptWebSocket())

    assert ws_manager._connections == {}


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

        def subscribe_frames(self, q: asyncio.Queue) -> None:
            super().subscribe_frames(q)
            q.put_nowait(_h264_key(self.serial))

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
async def test_device_sender_sends_cached_bootstrap_once_without_forcing_idr():
    class BootstrapDevice(_FakeDevice):
        def get_stream_bootstrap(self, *_args, **_kwargs):
            return _h264_cfg(self.serial), _h264_key(self.serial)

    control = _CountingScrcpyControl()
    dev = BootstrapDevice(serial="SN_BOOT_ONCE")
    dev._scrcpy_receiver = SimpleNamespace(control=control)
    ws_manager = WebSocketManager(_FakeManager([dev]), db_enabled=False, read_only=False)
    ws = _CollectingWebSocket()
    task = asyncio.create_task(ws_manager._device_sender(ws, dev, asyncio.Lock()))

    try:
        for _ in range(20):
            if len(ws.sent) >= 4:
                break
            await asyncio.sleep(0.01)

        assert ws.sent == [
            _h264_cfg(dev.serial),
            _h264_key(dev.serial),
        ]
        assert control.idr_requests == 0
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_device_sender_healthy_stats_are_debug_only(monkeypatch, caplog):
    monkeypatch.setattr(
        ws_module,
        "STREAM_STATS_LOG_INTERVAL_S",
        0.0,
        raising=False,
    )
    dev = _FakeDevice(serial="SN_STATS")
    ws_manager = WebSocketManager(_FakeManager([dev]), db_enabled=False, read_only=False)
    ws = _CollectingWebSocket()

    with caplog.at_level(logging.DEBUG, logger=ws_module.__name__):
        task = asyncio.create_task(
            ws_manager._device_sender(ws, dev, asyncio.Lock())
        )
        try:
            for _ in range(20):
                if dev._q is not None:
                    break
                await asyncio.sleep(0.01)
            assert dev._q is not None
            dev._q.put_nowait(_h264_key(dev.serial))

            for _ in range(20):
                if len(ws.sent) >= 3:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    matching = [
        record
        for record in caplog.records
        if "[WS device sender]" in record.getMessage()
    ]
    assert [record.levelno for record in matching] == [logging.DEBUG]


@pytest.mark.asyncio
async def test_device_sender_records_ws_send_telemetry():
    stream_telemetry.reset()
    dev = _FakeDevice(serial="SN_WS_TELEMETRY")
    ws_manager = WebSocketManager(_FakeManager([dev]), db_enabled=False, read_only=False)
    ws = _CollectingWebSocket()
    task = asyncio.create_task(ws_manager._device_sender(ws, dev, asyncio.Lock()))

    try:
        for _ in range(20):
            if dev._q is not None and len(ws.sent) >= 2:
                break
            await asyncio.sleep(0.01)
        assert dev._q is not None

        dev._q.put_nowait(_h264_key(dev.serial))
        for _ in range(20):
            if len(ws.sent) >= 3:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    snapshot = stream_telemetry.snapshot(reset=True)
    assert snapshot["ws_sent"] >= 1
    assert snapshot["ws_dropped"] == 0
    assert snapshot["ws_send_wait_p95_ms"] >= 0
    assert snapshot["ws_send_p95_ms"] >= 0


@pytest.mark.asyncio
async def test_stream_runtime_status_tracks_media_sender_per_connection():
    dev = _FakeDevice(serial="SN_WS_STATUS")
    ws_manager = WebSocketManager(_FakeManager([dev]), db_enabled=False, read_only=False)
    ws = _CollectingWebSocket()
    conn_id = "conn-media-1"
    task = asyncio.create_task(
        ws_manager._device_sender(
            ws,
            dev,
            asyncio.Lock(),
            conn_id=conn_id,
        )
    )
    setattr(task, "_device_serial", dev.serial)
    setattr(task, "_connection_id", conn_id)
    ws_manager._conn_sender_groups[conn_id] = [task]
    ws_manager._conn_sessions[conn_id] = "session-media-1"

    try:
        for _ in range(20):
            if dev._q is not None and len(ws.sent) >= 2:
                break
            await asyncio.sleep(0.01)
        assert dev._q is not None

        status = ws_manager.stream_runtime_status()
        assert status["media_ws_active"] == 1
        assert status["media_streams_active"] == 1
        assert status["max_media_streams_per_connection"] == 1
        assert status["shared_media_ws_connections"] == 0
        assert status["dedicated_media_ws_ok"] is True
        assert status["media_ws_per_connection"] == [
            {
                "conn_id": conn_id,
                "session_id": "session-media-1",
                "stream_count": 1,
                "serials": [dev.serial],
            }
        ]

        dev._q.put_nowait(_h264_key(dev.serial))
        for _ in range(20):
            if len(ws.sent) >= 3:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    stopped_status = ws_manager.stream_runtime_status()
    assert stopped_status["media_ws_active"] == 0
    assert stopped_status["sender_started_total"] == 1
    assert stopped_status["sender_stopped_total"] == 1
    assert stopped_status["sender_sent_total"] >= 1
    assert stopped_status["top_sent_serials"][0] == {
        "serial": dev.serial,
        "count": stopped_status["sender_sent_total"],
    }


@pytest.mark.asyncio
async def test_device_sender_drop_stats_are_warning(monkeypatch, caplog):
    monkeypatch.setattr(
        ws_module,
        "STREAM_STATS_LOG_INTERVAL_S",
        0.0,
        raising=False,
    )
    dev = _FakeDevice(serial="SN_DROP")
    ws_manager = WebSocketManager(_FakeManager([dev]), db_enabled=False, read_only=False)
    ws = _CollectingWebSocket()
    ws_send_lock = asyncio.Lock()

    with caplog.at_level(logging.DEBUG, logger=ws_module.__name__):
        task = asyncio.create_task(
            ws_manager._device_sender(ws, dev, ws_send_lock)
        )
        try:
            for _ in range(20):
                if dev._q is not None and len(ws.sent) >= 2:
                    break
                await asyncio.sleep(0.01)
            assert dev._q is not None
            await ws_send_lock.acquire()
            dev._q.put_nowait(_h264_key(dev.serial))

            for _ in range(20):
                if any(
                    "[WS device sender]" in record.getMessage()
                    for record in caplog.records
                ):
                    break
                await asyncio.sleep(0.01)
        finally:
            if ws_send_lock.locked():
                ws_send_lock.release()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    matching = [
        record
        for record in caplog.records
        if "[WS device sender]" in record.getMessage()
    ]
    assert [record.levelno for record in matching] == [logging.WARNING]


def test_stream_bootstrap_invalidates_key_when_config_generation_changes():
    store = LatestFrameStore()
    store.set_config(b"config-a")
    store.set_frame(b"key-a", is_key=True)
    assert store.get_bootstrap() == (b"config-a", b"key-a")

    store.set_config(b"config-b")

    assert store.get_bootstrap() == (b"config-b", None)


def test_stream_bootstrap_does_not_reuse_key_across_same_config_generation():
    store = LatestFrameStore()
    store.set_config(b"same-config")
    store.set_frame(b"old-session-key", is_key=True)

    store.reset_bootstrap()
    store.set_config(b"same-config")

    assert store.get_bootstrap() == (b"same-config", None)


@pytest.mark.asyncio
async def test_ws_receiver_coalesces_burst_idr_requests_per_device():
    control = _CountingScrcpyControl()
    dev = _FakeDevice(serial="SN_IDR")
    dev._scrcpy_receiver = SimpleNamespace(control=control)
    ws_manager = WebSocketManager(
        _FakeManager([dev]), db_enabled=False, read_only=False
    )
    ws = _MessagesThenDisconnectWebSocket(
        [
            {"type": "request_idr", "serial": dev.serial},
            {"type": "request_idr", "serial": dev.serial},
        ]
    )

    await ws_manager._receiver(ws, asyncio.Lock())
    for _ in range(20):
        if control.idr_requests:
            break
        await asyncio.sleep(0.01)

    assert control.idr_requests == 1


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
