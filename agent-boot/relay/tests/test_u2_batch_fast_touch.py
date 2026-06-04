from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from relay.agent import RelayAgent


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
