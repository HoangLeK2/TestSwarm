"""Live typing must reach the device in frame order.

Regression for scrambled realtime typing: every input frame used to be handed to
the shared default executor, so a DEL burst and the append that followed it ran
on different threads and could land reversed ("chà" → "àch"), or drop keystrokes
when the u2 HTTP lock granted ownership out of order.
"""
from __future__ import annotations

import asyncio
import time

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from web.ws import WebSocketManager


class _RecordingDevice:
    """Records call order; the first text op is slow so reordering is visible."""

    serial = "SN-TYPING"
    screen_width = 1080
    screen_height = 1920
    state = "READY"
    _relay_id = "relay-test"
    _scenario_active = 0

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._first = True

    # Status plumbing used by WebSocketManager.connect().
    def subscribe_status(self, _q: asyncio.Queue) -> None:
        return

    def unsubscribe_status(self, _q: asyncio.Queue) -> None:
        return

    def status_dict(self) -> dict:
        return {"type": "status", "serial": self.serial, "state": "READY"}

    def get_log_lines(self) -> list[str]:
        return []

    def input_route_hint(self) -> str:
        return "test"

    def _record(self, entry: tuple) -> None:
        if self._first:
            self._first = False
            time.sleep(0.15)
        self.calls.append(entry)

    def key(self, key: str) -> None:
        self._record(("key", key))

    def append_input_text(self, text: str) -> None:
        self._record(("append", text))

    def apply_live_input_text(self, text: str) -> None:
        self._record(("replace", text))

    def clear_live_input(self) -> None:
        self._record(("clear",))


class _FakeManager:
    def __init__(self, devices: list[_RecordingDevice]) -> None:
        self._by_serial = {d.serial: d for d in devices}

    def all_devices(self) -> list[_RecordingDevice]:
        return list(self._by_serial.values())

    def get_device(self, serial: str):
        return self._by_serial.get(serial)


def _drive(device: _RecordingDevice, frames: list[dict]) -> None:
    ws_manager = WebSocketManager(_FakeManager([device]), db_enabled=False, read_only=False)
    app = FastAPI()

    @app.websocket("/ws")
    async def _ws(ws: WebSocket):  # pragma: no cover - exercised via TestClient
        await ws_manager.connect(ws, user_id=None)

    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()  # handshake status
        for frame in frames:
            ws.send_json(frame)
        time.sleep(0.6)  # let the queued input tasks drain


def test_live_typing_frames_execute_in_order() -> None:
    dev = _RecordingDevice()
    _drive(
        dev,
        [
            {"type": "input_text", "serial": dev.serial, "text": "cha", "append": True},
            {"type": "key", "serial": dev.serial, "key": "delete"},
            {"type": "input_text", "serial": dev.serial, "text": "à", "append": True},
        ],
    )

    assert dev.calls == [("append", "cha"), ("key", "delete"), ("append", "à")]


def test_delete_count_presses_once_per_char_in_a_single_task() -> None:
    dev = _RecordingDevice()
    _drive(
        dev,
        [
            {"type": "key", "serial": dev.serial, "key": "delete", "count": 3},
            {"type": "input_text", "serial": dev.serial, "text": "xin", "append": True},
        ],
    )

    assert dev.calls == [
        ("key", "delete"),
        ("key", "delete"),
        ("key", "delete"),
        ("append", "xin"),
    ]


def test_delete_count_is_clamped() -> None:
    dev = _RecordingDevice()
    _drive(dev, [{"type": "key", "serial": dev.serial, "key": "delete", "count": 999}])

    assert len(dev.calls) == 64
