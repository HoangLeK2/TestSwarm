from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import MagicMock

import pytest

from relay.agent import RelayAgent


@pytest.fixture(autouse=True)
async def cleanup_a11y_worker_tasks():
    yield
    current = asyncio.current_task()
    tasks = [
        task for task in asyncio.all_tasks()
        if task is not current and task.get_name().startswith("a11y-")
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_a11y_queue_overflow_rejects(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._a11y_max_queue = 1

    async def _noop_worker(*args, **kwargs):
        await asyncio.sleep(3600)

    # Keep queue items enqueued so overflow is deterministic.
    monkeypatch.setattr(agent, "_a11y_worker", _noop_worker)

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    base = {
        "type": "a11y_action",
        "serial": "s1",
        "session_id": "sess-1",
        "mode": "mutate",
        "action": "tap",
        "payload": {"x": 1, "y": 2},
    }

    await agent._handle_a11y_action({**base, "id": "r1", "seq": 1, "ts": 1}, send_q, loop)
    ack1 = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack1["type"] == "a11y_ack"
    assert ack1["accepted"] is True

    await agent._handle_a11y_action({**base, "id": "r2", "seq": 2, "ts": 2}, send_q, loop)
    ack2 = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack2["type"] == "a11y_ack"
    assert ack2["accepted"] is False
    assert ack2["error"] == "queue_overflow"


@pytest.mark.asyncio
async def test_a11y_stale_seq_rejected(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )

    async def _noop_worker(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(agent, "_a11y_worker", _noop_worker)

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    base = {
        "type": "a11y_action",
        "serial": "s1",
        "session_id": "sess-1",
        "mode": "mutate",
        "action": "tap",
        "payload": {"x": 1, "y": 2},
    }

    # Prime state: last_seq already advanced.
    agent._a11y_state["s1"] = {
        "session_id": "sess-1",
        "last_seq": 10,
        "queued_seqs": set(),
        "mut_q": asyncio.Queue(maxsize=10),
        "qry_q": asyncio.Queue(maxsize=10),
        "mut_worker": None,
        "qry_worker": None,
    }

    await agent._handle_a11y_action({**base, "id": "r-stale", "seq": 9, "ts": 9}, send_q, loop)
    ack = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack["type"] == "a11y_ack"
    assert ack["accepted"] is False
    assert ack["error"] == "stale_seq"


@pytest.mark.asyncio
async def test_a11y_session_switch_resets_seq(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )

    async def _noop_worker(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(agent, "_a11y_worker", _noop_worker)

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    agent._a11y_state["s1"] = {
        "session_id": "old-session",
        "last_seq": 42,
        "queued_seqs": {43},
        "mut_q": asyncio.Queue(maxsize=10),
        "qry_q": asyncio.Queue(maxsize=10),
        "mut_worker": None,
        "qry_worker": None,
    }

    await agent._handle_a11y_action(
        {
            "type": "a11y_action",
            "serial": "s1",
            "session_id": "new-session",
            "mode": "mutate",
            "action": "tap",
            "payload": {"x": 1, "y": 2},
            "id": "r-new",
            "seq": 1,
            "ts": 1,
        },
        send_q,
        loop,
    )

    ack = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack["type"] == "a11y_ack"
    assert ack["accepted"] is True
    assert agent._a11y_state["s1"]["session_id"] == "new-session"
    assert agent._a11y_state["s1"]["queued_seqs"] == {1}


@pytest.mark.asyncio
async def test_a11y_query_stale_seq_returns_result(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )

    async def _noop_worker(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(agent, "_a11y_worker", _noop_worker)

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    agent._a11y_state["s1"] = {
        "session_id": "sess-1",
        "last_seq": 10,
        "queued_seqs": set(),
        "mut_q": asyncio.Queue(maxsize=10),
        "qry_q": asyncio.Queue(maxsize=10),
        "mut_worker": None,
        "qry_worker": None,
    }

    await agent._handle_a11y_action(
        {
            "type": "a11y_action",
            "serial": "s1",
            "session_id": "sess-1",
            "mode": "query",
            "action": "dump_hierarchy",
            "payload": {},
            "id": "r-stale-query",
            "seq": 9,
            "ts": 9,
        },
        send_q,
        loop,
    )

    result = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert result["type"] == "a11y_result"
    assert result["ok"] is False
    assert result["error"] == "stale_seq"


@pytest.mark.asyncio
async def test_a11y_duplicate_seq_rejected(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )

    async def _noop_worker(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(agent, "_a11y_worker", _noop_worker)

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    agent._a11y_state["s1"] = {
        "session_id": "sess-1",
        "last_seq": 10,
        "queued_seqs": set(),
        "mut_q": asyncio.Queue(maxsize=10),
        "qry_q": asyncio.Queue(maxsize=10),
        "mut_worker": None,
        "qry_worker": None,
    }

    await agent._handle_a11y_action(
        {
            "type": "a11y_action",
            "serial": "s1",
            "session_id": "sess-1",
            "mode": "mutate",
            "action": "tap",
            "payload": {"x": 1, "y": 2},
            "id": "r-dup",
            "seq": 10,
            "ts": 10,
        },
        send_q,
        loop,
    )
    ack = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack["type"] == "a11y_ack"
    assert ack["accepted"] is False
    assert ack["error"] == "stale_seq"


@pytest.mark.asyncio
async def test_a11y_query_does_not_emit_ack(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )

    monkeypatch.setattr(
        agent,
        "_execute_a11y_action",
        lambda item: {
            "type": "a11y_result",
            "id": item["id"],
            "serial": item["serial"],
            "seq": item["seq"],
            "ok": True,
            "error": "",
            "data": {"xml": "<hierarchy />"},
        },
    )

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    await agent._handle_a11y_action(
        {
            "type": "a11y_action",
            "serial": "s1",
            "session_id": "sess-1",
            "mode": "query",
            "action": "dump_hierarchy",
            "payload": {},
            "id": "r-query",
            "seq": 1,
            "ts": 1,
        },
        send_q,
        loop,
    )
    msg = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert msg["type"] == "a11y_result"
    assert msg["id"] == "r-query"


@pytest.mark.asyncio
async def test_a11y_worker_marks_mutating_action_ui_generation(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._u2_executor = MagicMock()
    monkeypatch.setattr(
        agent,
        "_execute_a11y_action",
        lambda item: {
            "type": "a11y_result",
            "id": item["id"],
            "serial": item["serial"],
            "seq": item["seq"],
            "ok": True,
            "error": "",
            "data": {},
        },
    )
    q: asyncio.Queue = asyncio.Queue()
    await q.put({
        "id": "a11y-mutation",
        "serial": "s1",
        "seq": 1,
        "session_id": "sess-1",
        "mode": "mutate",
        "action": "tap",
        "payload": {"x": 1, "y": 2},
    })
    await q.put(None)
    agent._a11y_state["s1"] = {
        "session_id": "sess-1",
        "last_seq": 0,
        "queued_seqs": {1},
    }

    await agent._a11y_worker(
        "s1",
        q,
        asyncio.Queue(),
        asyncio.get_running_loop(),
        query_lane=False,
    )

    agent._u2_executor.begin_ui_mutation.assert_called_once_with("s1")
    agent._u2_executor.end_ui_mutation.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_a11y_cancel_keeps_mutation_in_flight_until_thread_finishes(
    monkeypatch,
):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._u2_executor = MagicMock()
    started = threading.Event()
    release = threading.Event()

    def _blocking_action(item):
        started.set()
        release.wait(timeout=2.0)
        return {
            "type": "a11y_result",
            "id": item["id"],
            "serial": item["serial"],
            "seq": item["seq"],
            "ok": True,
            "error": "",
            "data": {},
        }

    monkeypatch.setattr(agent, "_execute_a11y_action", _blocking_action)
    q: asyncio.Queue = asyncio.Queue()
    await q.put({
        "id": "a11y-cancelled",
        "serial": "s1",
        "seq": 1,
        "session_id": "sess-1",
        "mode": "mutate",
        "action": "tap",
        "payload": {"x": 1, "y": 2},
    })
    agent._a11y_state["s1"] = {
        "session_id": "sess-1",
        "last_seq": 0,
        "queued_seqs": {1},
    }
    task = asyncio.create_task(
        agent._a11y_worker(
            "s1",
            q,
            asyncio.Queue(),
            asyncio.get_running_loop(),
            query_lane=False,
        )
    )
    while not started.is_set():
        await asyncio.sleep(0)

    task.cancel()
    await asyncio.sleep(0.01)
    agent._u2_executor.end_ui_mutation.assert_not_called()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)
    agent._u2_executor.end_ui_mutation.assert_called_once_with("s1")


def test_a11y_dump_hierarchy_retries_empty_stub(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    calls = []
    responses = [
        {"ok": True, "status": 200, "body": "<hierarchy />", "content_type": "text/xml"},
        {"ok": True, "status": 200, "body": "<hierarchy><node /></hierarchy>", "content_type": "text/xml"},
    ]

    def _fake_u2_http(serial, method, path, body, content_type, timeout):
        calls.append((serial, method, path, timeout))
        return responses.pop(0)

    monkeypatch.setattr(agent, "_do_u2_http", _fake_u2_http)

    ok, err, data = agent._execute_dump_hierarchy(
        "s1",
        {"timeout": 2.0, "attempts": 2},
    )

    assert ok is True
    assert err == ""
    assert data["attempts"] == 2
    assert data["xml"].startswith("<hierarchy")
    assert len(calls) == 2
    assert calls[0][2] == "/dump/hierarchy"
    assert 1.0 <= calls[0][3] <= 2.0


def test_a11y_dump_hierarchy_rejects_non_xml(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )

    def _fake_u2_http(serial, method, path, body, content_type, timeout):
        return {"ok": True, "status": 200, "body": "not xml", "content_type": "text/plain"}

    monkeypatch.setattr(agent, "_do_u2_http", _fake_u2_http)

    ok, err, data = agent._execute_dump_hierarchy(
        "s1",
        {"timeout": 1.0, "attempts": 1},
    )

    assert ok is False
    assert "not xml" in err
    assert data["xml"] == ""


@pytest.mark.asyncio
async def test_a11y_inflight_duplicate_seq_rejected(monkeypatch):
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="r1",
        relay_mode="grpc",
    )
    agent._a11y_max_queue = 8

    async def _noop_worker(*args, **kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(agent, "_a11y_worker", _noop_worker)

    send_q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    base = {
        "type": "a11y_action",
        "serial": "s1",
        "session_id": "sess-1",
        "mode": "mutate",
        "action": "tap",
        "payload": {"x": 1, "y": 2},
        "seq": 7,
        "ts": 1,
    }

    await agent._handle_a11y_action({**base, "id": "r-first"}, send_q, loop)
    ack1 = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack1["accepted"] is True

    await agent._handle_a11y_action({**base, "id": "r-dup"}, send_q, loop)
    ack2 = json.loads(await asyncio.wait_for(send_q.get(), timeout=0.5))
    assert ack2["accepted"] is False
    assert ack2["error"] == "stale_seq"
