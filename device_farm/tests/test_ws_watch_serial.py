from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

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
    _q: Optional[asyncio.Queue] = None

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


class _FakeManager:
    def __init__(self, devices: list[_FakeDevice]):
        self._by_serial = {d.serial: d for d in devices}

    def all_devices(self):
        return list(self._by_serial.values())

    def get_device(self, serial: str):
        return self._by_serial.get(serial)


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

