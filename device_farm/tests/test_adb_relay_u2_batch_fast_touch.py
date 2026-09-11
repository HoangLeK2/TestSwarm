from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import AsyncMock

import pytest

from runtime.transports.adb_relay_server import AdbRelayManager, CMD_REVERSE_TCP


class _FakeRelayConn:
    def __init__(self) -> None:
        self.relay_id = "relay-1"
        self.serials = {"serial-1"}
        self.u2_requests: list[tuple[str, str, str, dict, str, float]] = []
        self.u2_request_options: list[tuple[str | int | None, int | float | None]] = []
        self.json_requests: list[dict] = []
        self.json_messages: list[dict] = []
        self.commands: list[tuple[str, str, float, int]] = []
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
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        parsed_body = json.loads(body) if body else {}
        self.u2_requests.append(
            (serial, method, path, parsed_body, content_type, timeout)
        )
        self.u2_request_options.append((priority, deadline_ms))
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

    async def send_command(
        self,
        serial: str,
        cmd: str,
        timeout: float,
        cmd_type: int = 0,
    ) -> dict:
        self.commands.append((serial, cmd, timeout, cmd_type))
        return {"ok": True, "exit_code": 0, "output": "8081\n", "error": ""}


def _manager_with_conn(conn: _FakeRelayConn) -> AdbRelayManager:
    manager = AdbRelayManager()
    manager._relays["relay-1"] = conn  # type: ignore[assignment]
    manager._serial_index["serial-1"] = "relay-1"
    return manager


@pytest.mark.asyncio
async def test_reverse_tcp_sends_dedicated_relay_command():
    conn = _FakeRelayConn()
    manager = _manager_with_conn(conn)

    result = await manager.reverse_tcp("serial-1", 8081, 8081, timeout=10.0)

    assert result["ok"] is True
    assert len(conn.commands) == 1
    serial, cmd, timeout, cmd_type = conn.commands[0]
    assert serial == "serial-1"
    assert json.loads(cmd) == {"remote_port": 8081, "local_port": 8081}
    assert timeout == 10.0
    assert cmd_type == CMD_REVERSE_TCP


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
async def test_u2_http_forwards_priority_and_deadline_to_agent_request():
    conn = _FakeRelayConn()
    manager = _manager_with_conn(conn)

    result = await manager.u2_http(
        "serial-1",
        "GET",
        "/dump/hierarchy?compressed=1",
        timeout=1.5,
        priority="visible",
        deadline_ms=1500,
    )

    assert result["ok"] is True
    assert conn.u2_requests == [
        (
            "serial-1",
            "GET",
            "/dump/hierarchy?compressed=1",
            {},
            "application/json",
            1.5,
        )
    ]
    assert conn.u2_request_options == [("visible", 1500)]


@pytest.mark.asyncio
async def test_u2_batch_waits_for_a_transient_relay_reconnect_before_sending():
    manager = AdbRelayManager()
    manager._sync_relay_to_redis = AsyncMock()
    conn = _FakeRelayConn()

    batch_task = asyncio.create_task(
        manager.u2_batch(
            "serial-1",
            [{"op": "click", "x": 10, "y": 20}],
            timeout=1.5,
        )
    )
    await asyncio.sleep(0)

    assert not batch_task.done()
    await manager.register(conn)  # type: ignore[arg-type]

    result = await asyncio.wait_for(batch_task, timeout=0.5)
    assert result["ok"] is True
    assert len(conn.u2_requests) == 1


@pytest.mark.asyncio
async def test_u2_flow_waits_for_a_transient_relay_reconnect_before_sending():
    manager = AdbRelayManager()
    manager._sync_relay_to_redis = AsyncMock()
    conn = _FakeRelayConn()

    flow_task = asyncio.create_task(
        manager.u2_flow(
            "serial-1",
            "swipe_until_found",
            {"selector": {"text": "OK"}},
            timeout=1.5,
        )
    )
    await asyncio.sleep(0)

    assert not flow_task.done()
    await manager.register(conn)  # type: ignore[arg-type]

    result = await asyncio.wait_for(flow_task, timeout=0.5)
    assert result["ok"] is True
    assert len(conn.json_requests) == 1
    assert conn.json_requests[0]["type"] == "u2_flow"


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
        priority="visible",
        deadline_ms=120,
    )

    assert conn.u2_requests == []
    assert len(conn.json_requests) == 1
    assert conn.json_requests[0]["type"] == "u2_batch"
    assert conn.json_requests[0]["actions"] == [{"op": "dump_hierarchy", "timeout": 4.0}]
    assert conn.json_requests[0]["priority"] == "visible"
    assert conn.json_requests[0]["deadline_ms"] == 120


@pytest.mark.asyncio
async def test_u2_flow_forwards_priority_and_deadline_to_agent():
    conn = _FakeRelayConn()
    manager = _manager_with_conn(conn)

    await manager.u2_flow(
        "serial-1",
        "swipe_until_found",
        {"selector": {"text": "OK"}},
        timeout=4.0,
        priority="visible",
        deadline_ms=150,
    )

    assert conn.u2_requests == []
    assert len(conn.json_requests) == 1
    assert conn.json_requests[0]["type"] == "u2_flow"
    assert conn.json_requests[0]["flow"] == "swipe_until_found"
    assert conn.json_requests[0]["params"] == {"selector": {"text": "OK"}}
    assert conn.json_requests[0]["priority"] == "visible"
    assert conn.json_requests[0]["deadline_ms"] == 150


@pytest.mark.asyncio
async def test_u2_flow_cancel_sends_agent_cancel_message():
    conn = _FakeRelayConn()
    cancel_event = threading.Event()
    started = asyncio.Event()

    async def _blocked_request(*_args):
        started.set()
        await asyncio.sleep(30.0)
        return {"type": "u2_flow_result", "ok": True, "value": {}, "error": None}

    conn.on_json_request = _blocked_request
    manager = _manager_with_conn(conn)

    task = asyncio.create_task(
        manager.u2_flow(
            "serial-1",
            "social_scan_posts_interact",
            {"keywords": ["AI"], "max_scrolls": 30},
            timeout=4.0,
            cancel_event=cancel_event,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)
    cancel_event.set()
    result = await asyncio.wait_for(task, timeout=1.0)

    assert result == {"ok": False, "error": "cancelled", "cancelled": True}
    assert len(conn.json_messages) == 1
    cancel_msg = conn.json_messages[0]
    assert cancel_msg["type"] == "u2_flow_cancel"
    assert cancel_msg["id"] == conn.json_requests[0]["id"]
    assert cancel_msg["serial"] == "serial-1"
    assert cancel_msg["flow"] == "social_scan_posts_interact"


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
