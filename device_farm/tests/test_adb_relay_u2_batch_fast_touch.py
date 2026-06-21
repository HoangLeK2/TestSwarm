from __future__ import annotations

import asyncio
import json
import threading

import pytest

from runtime.transports.adb_relay_server import AdbRelayManager


class _FakeRelayConn:
    def __init__(self) -> None:
        self.u2_requests: list[tuple[str, str, str, dict, str, float]] = []
        self.json_requests: list[dict] = []
        self.json_messages: list[dict] = []
        self.after_u2_request = None
        self.on_json_request = None

    async def send_u2_request(
        self,
        serial: str,
        method: str,
        path: str,
        body: str = "",
        content_type: str = "application/json",
        timeout: float = 30.0,
    ) -> dict:
        self.u2_requests.append(
            (serial, method, path, json.loads(body), content_type, timeout)
        )
        if self.after_u2_request is not None:
            self.after_u2_request()
        return {
            "ok": True,
            "status": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": len(self.u2_requests), "result": True}),
            "content_type": "application/json",
        }

    async def send_json_request(
        self,
        msg: dict,
        reply_id: str,
        timeout: float = 30.0,
        timeout_grace: float = 10.0,
    ) -> dict:
        self.json_requests.append(msg)
        if self.on_json_request is not None:
            return await self.on_json_request(msg, reply_id, timeout, timeout_grace)
        return {"ok": True, "stopped_at": None, "results": [], "error": None}

    async def send_json_message(self, msg: dict) -> None:
        self.json_messages.append(msg)


def _manager_with_conn(conn: _FakeRelayConn) -> AdbRelayManager:
    manager = AdbRelayManager()
    manager._relays["relay-1"] = conn  # type: ignore[assignment]
    manager._serial_index["serial-1"] = "relay-1"
    return manager


@pytest.mark.asyncio
async def test_u2_batch_coordinate_touch_uses_u2_http_fast_path():
    conn = _FakeRelayConn()
    manager = _manager_with_conn(conn)

    result = await manager.u2_batch(
        "serial-1",
        [{"op": "click", "x": 10, "y": 20}],
        timeout=1.5,
    )

    assert result == {
        "ok": True,
        "stopped_at": None,
        "results": [{"op": "click", "ok": True}],
        "error": None,
    }
    assert conn.json_requests == []
    assert conn.u2_requests == [
        (
            "serial-1",
            "POST",
            "/jsonrpc/0",
            {
                "jsonrpc": "2.0",
                "method": "click",
                "id": 1,
                "params": [10, 20],
            },
            "application/json",
            1.5,
        )
    ]


@pytest.mark.asyncio
async def test_u2_batch_coordinate_touch_stops_between_actions_on_cancel_event():
    conn = _FakeRelayConn()
    cancel_event = threading.Event()
    conn.after_u2_request = cancel_event.set
    manager = _manager_with_conn(conn)

    result = await manager.u2_batch(
        "serial-1",
        [
            {"op": "click", "x": 10, "y": 20},
            {"op": "click", "x": 30, "y": 40},
        ],
        timeout=3.0,
        cancel_event=cancel_event,
    )

    assert len(conn.u2_requests) == 1
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["stopped_at"] == 1
    assert result["results"] == [{"op": "click", "ok": True}]


@pytest.mark.asyncio
async def test_u2_batch_non_touch_action_uses_agent_batch_path():
    conn = _FakeRelayConn()
    manager = _manager_with_conn(conn)

    await manager.u2_batch(
        "serial-1",
        [{"op": "dump_hierarchy", "timeout": 4.0}],
        timeout=4.0,
    )

    assert conn.u2_requests == []
    assert len(conn.json_requests) == 1
    assert conn.json_requests[0]["type"] == "u2_batch"
    assert conn.json_requests[0]["actions"] == [{"op": "dump_hierarchy", "timeout": 4.0}]


@pytest.mark.asyncio
async def test_u2_batch_non_touch_cancel_sends_agent_cancel_message():
    conn = _FakeRelayConn()
    cancel_event = threading.Event()
    started = asyncio.Event()

    async def _blocked_request(*_args):
        started.set()
        await asyncio.sleep(30.0)
        return {"ok": True, "stopped_at": None, "results": [], "error": None}

    conn.on_json_request = _blocked_request
    manager = _manager_with_conn(conn)

    task = asyncio.create_task(
        manager.u2_batch(
            "serial-1",
            [{"op": "dump_hierarchy", "timeout": 4.0}],
            timeout=4.0,
            cancel_event=cancel_event,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    cancel_event.set()
    result = await asyncio.wait_for(task, timeout=1.0)

    assert result["cancelled"] is True
    assert len(conn.json_messages) == 1
    assert conn.json_messages[0]["type"] == "u2_batch_cancel"
    assert conn.json_messages[0]["id"] == conn.json_requests[0]["id"]
