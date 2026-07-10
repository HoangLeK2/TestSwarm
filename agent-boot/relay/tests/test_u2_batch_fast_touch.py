from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from relay.agent import RelayAgent
from relay.u2_executor import U2Executor


class _FakePool:
    async def run_locked(self, _serial, fn):
        return fn(_FakeDevice())


class _FakeDevice:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def swipe(self, *_args, **_kwargs) -> None:
        raise AssertionError("u2 HTTP swipe batch must not call Python u2 swipe")


@pytest.mark.asyncio
async def test_u2_batch_coordinate_touch_uses_http_fast_path(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._u2_executor = AsyncMock()

    calls: list[tuple[str, str, str, dict, float]] = []

    def _fake_u2_http(serial, method, path, body, content_type, timeout):
        calls.append((serial, method, path, json.loads(body), timeout))
        return {
            "ok": True,
            "status": 200,
            "body": json.dumps({"jsonrpc": "2.0", "id": 1, "result": True}),
            "content_type": "application/json",
        }

    monkeypatch.setattr(agent, "_do_u2_http", _fake_u2_http)

    send_q: asyncio.Queue = asyncio.Queue()
    await agent._handle_u2_batch(
        {
            "id": "batch-1",
            "serial": "10AE7S00HD002JK",
            "actions": [{"op": "click", "x": 100, "y": 200}],
        },
        send_q,
    )

    msg = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert msg["type"] == "u2_batch_result"
    assert msg["id"] == "batch-1"
    assert msg["ok"] is True
    assert msg["results"] == [{"op": "click", "ok": True}]
    assert calls == [
        (
            "10AE7S00HD002JK",
            "POST",
            "/jsonrpc/0",
            {
                "jsonrpc": "2.0",
                "method": "click",
                "id": 1,
                "params": [100, 200],
            },
            1.5,
        )
    ]
    agent._u2_executor.run_batch.assert_not_called()


@pytest.mark.asyncio
async def test_u2_executor_u2_swipe_batch_uses_http_rpc():
    calls: list[tuple[str, dict, float]] = []

    def fake_http_rpc(serial: str, payload: dict, timeout: float):
        calls.append((serial, payload, timeout))
        return True, ""

    executor = U2Executor(
        _FakePool(),
        asyncio.get_running_loop(),
        http_rpc=fake_http_rpc,
    )
    result = await executor.run_batch(
        "10AE7S00HD002JK",
        [
            {
                "op": "u2_swipe_batch",
                "count": 3,
                "fx": 540,
                "fy": 1200,
                "tx": 540,
                "ty": 360,
                "duration": 0.08,
                "pause_s": 0,
            }
        ],
    )

    assert result["ok"] is True
    assert result["results"][0]["op"] == "u2_swipe_batch"
    assert result["results"][0]["ok"] is True
    assert result["results"][0]["value"] == 3
    assert result["results"][0]["duration_ms"] >= 0
    assert result["total_ms"] >= 0
    assert len(calls) == 3
    assert all(call[0] == "10AE7S00HD002JK" for call in calls)
    assert [call[1]["method"] for call in calls] == ["swipe", "swipe", "swipe"]
    assert calls[0][1]["params"] == [540, 1200, 540, 360, 3]
    assert calls[0][2] >= 1.5


@pytest.mark.asyncio
async def test_u2_batch_fast_path_respects_early_exit_false(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._u2_executor = AsyncMock()
    calls = 0

    def _fake_u2_http(serial, method, path, body, content_type, timeout):
        nonlocal calls
        calls += 1
        ok = calls == 2
        return {
            "ok": ok,
            "status": 200 if ok else 500,
            "body": json.dumps({"jsonrpc": "2.0", "id": calls, "result": ok}),
            "content_type": "application/json",
        }

    monkeypatch.setattr(agent, "_do_u2_http", _fake_u2_http)

    send_q: asyncio.Queue = asyncio.Queue()
    await agent._handle_u2_batch(
        {
            "id": "batch-2",
            "serial": "10AE7S00HD002JK",
            "early_exit": False,
            "actions": [
                {"op": "click", "x": 1, "y": 2},
                {"op": "click", "x": 3, "y": 4},
            ],
        },
        send_q,
    )

    msg = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert msg["ok"] is False
    assert msg["stopped_at"] is None
    assert msg["results"] == [
        {"op": "click", "ok": False, "error": "JSON-RPC HTTP 500"},
        {"op": "click", "ok": True},
    ]
    agent._u2_executor.run_batch.assert_not_called()


@pytest.mark.asyncio
async def test_u2_executor_run_batch_stops_before_next_action_when_cancelled():
    cancel_event = asyncio.Event()
    executor = U2Executor(_FakePool(), asyncio.get_running_loop())

    original_op = None
    import relay.u2_executor as u2_executor

    original_op = u2_executor._OP_TABLE["click"]

    def _click_and_cancel(dev, act):
        original_op(dev, act)
        cancel_event.set()

    u2_executor._OP_TABLE["click"] = _click_and_cancel
    try:
        result = await executor.run_batch(
            "10AE7S00HD002JK",
            [
                {"op": "click", "x": 1, "y": 2},
                {"op": "click", "x": 3, "y": 4},
            ],
            cancel_event=cancel_event,
        )
    finally:
        u2_executor._OP_TABLE["click"] = original_op

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["stopped_at"] == 1
    assert result["results"][0]["op"] == "click"
    assert result["results"][0]["ok"] is True
    assert result["results"][0]["duration_ms"] >= 0
    assert result["total_ms"] >= 0
