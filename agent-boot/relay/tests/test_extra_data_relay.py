from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from relay.agent import RelayAgent, _extra_data_reply_messages
from relay.extra_data.collector import _dump_action


class _FakeIngest:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.payloads: list[dict] = []

    async def process_payload(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.result


class _FakeExecutor:
    def __init__(self) -> None:
        self.ops: list[str] = []

    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
        self.ops.extend(str(action.get("op")) for action in actions)
        if actions and actions[0].get("op") == "screenshot":
            return {
                "ok": True,
                "results": [{
                    "op": "screenshot",
                    "ok": True,
                    "value": "shot-b64",
                }],
            }
        return {
            "ok": True,
            "results": [{
                "op": "dump_hierarchy",
                "ok": True,
                "value": '<?xml version="1.0"?><hierarchy><node/></hierarchy>',
            }],
        }

    async def window_size(self, serial: str) -> tuple[int, int]:
        return 1080, 2340

    async def with_session(self, serial: str, coro):
        return await coro()


def test_extra_data_dump_action_forwards_profile_root_in_active() -> None:
    action = _dump_action(
        {
            "hierarchy_root_in_active": True,
            "hierarchy_verify_root_in_active": False,
            "hierarchy_verify_compressed": True,
            "hierarchy_verify_max_depth": 24,
        },
        profile="verify",
    )

    assert action["compressed"] is True
    assert action["root_in_active"] is False
    assert action["max_depth"] == 24


def test_extra_data_persist_batch_is_chunked_and_manifested(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BOOT_CONTENT_UPLINK_CHUNK_BYTES", "16384")
    items = [{"body": "x" * 10_000}, {"body": "y" * 10_000}]
    reply = {
        "type": "extra_data_result",
        "id": "req-1",
        "ok": True,
        "ingest": {
            "persist_batch": {
                "schema_version": 1,
                "kind": "content",
                "items": items,
                "content_hashes": ["h1", "h2"],
            }
        },
    }

    messages = _extra_data_reply_messages(reply)

    assert [message["type"] for message in messages] == [
        "extra_data_result_chunk",
        "extra_data_result_chunk",
        "extra_data_result",
    ]
    assert messages[-1]["ingest"]["persist_batch_manifest"]["chunk_count"] >= 2
    assert "persist_batch" not in messages[-1]["ingest"]


@pytest.mark.asyncio
async def test_handle_extra_data_success() -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key=None,
        relay_id="test-relay",
        relay_mode="grpc",
        extra_ingest=_FakeIngest({
            "ok": True,
            "parsed_count": 2,
            "inserted_count": 1,
            "duplicate_count": 1,
            "diagnostic": {"reason_code": "ok"},
        }),
    )
    agent._u2_executor = _FakeExecutor()
    queue: asyncio.Queue = asyncio.Queue()

    await agent._handle_extra_data({
        "id": "extra-1",
        "serial": "dev1",
        "strategy": "ig_posts",
        "context": {"collection": "ig", "persist": True, "_cancel_event": asyncio.Event()},
    }, queue)

    raw = await asyncio.wait_for(queue.get(), timeout=2.0)
    msg = json.loads(raw)
    assert msg["type"] == "extra_data_result"
    assert msg["ok"] is True
    assert msg["route"] == "relay_u2"
    assert msg["ingest"]["parsed_count"] == 2
    assert len(agent._extra_ingest.payloads) == 1
    assert "screenshot" not in agent._u2_executor.ops
    assert "screenshot_b64" not in agent._extra_ingest.payloads[0].get("evidence", {})
    assert "screenshot_b64" not in msg["ingest"]
    assert "_cancel_event" not in agent._extra_ingest.payloads[0]["context"]


@pytest.mark.asyncio
async def test_handle_extra_data_probe_skips_ingest() -> None:
    ingest = _FakeIngest({"ok": True, "parsed_count": 99})
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key=None,
        relay_id="test-relay",
        relay_mode="grpc",
        extra_ingest=ingest,
    )
    agent._u2_executor = _FakeExecutor()
    queue: asyncio.Queue = asyncio.Queue()

    await agent._handle_extra_data({
        "id": "extra-probe",
        "serial": "dev1",
        "strategy": "fb_comment_filter_next",
        "context": {"comment_filter": "all_comments"},
    }, queue)

    msg = json.loads(await asyncio.wait_for(queue.get(), timeout=2.0))
    assert msg["ok"] is True
    assert "diagnostic" in msg["ingest"]
    assert ingest.payloads == []


@pytest.mark.asyncio
async def test_handle_extra_data_collect_error_includes_open_post_diagnostic() -> None:
    ingest = _FakeIngest({"ok": True, "parsed_count": 99})
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key=None,
        relay_id="test-relay",
        relay_mode="grpc",
        extra_ingest=ingest,
    )
    agent._u2_executor = _FakeExecutor()
    queue: asyncio.Queue = asyncio.Queue()

    async def fake_collect_xml_snapshots(executor, serial, strategy, context):
        context["open_post_detail_diagnostic"] = {
            "reason_code": "post_open_target_not_found",
            "timing": {"total_ms": 42.0, "resolve_ms": 3.0},
        }
        return [], "post_open_required:post_open_target_not_found"

    with patch(
        "relay.extra_data.collector.collect_xml_snapshots",
        new=fake_collect_xml_snapshots,
    ):
        await agent._handle_extra_data({
            "id": "extra-open-post-fail",
            "serial": "dev1",
            "strategy": "fb_posts",
            "context": {"open_post_before_extract": True},
        }, queue)

    msg = json.loads(await asyncio.wait_for(queue.get(), timeout=2.0))
    assert msg["ok"] is False
    assert msg["error"] == "post_open_required:post_open_target_not_found"
    assert msg["diagnostic"]["reason_code"] == "post_open_target_not_found"
    assert msg["diagnostic"]["timing"]["total_ms"] == 42.0
    assert msg["ingest"]["diagnostic"] == msg["diagnostic"]
    assert ingest.payloads == []


@pytest.mark.asyncio
async def test_handle_extra_data_not_configured() -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key=None,
        relay_id="test-relay",
        relay_mode="grpc",
        extra_ingest=None,
    )
    agent._u2_executor = _FakeExecutor()
    queue: asyncio.Queue = asyncio.Queue()

    await agent._handle_extra_data({
        "id": "extra-2",
        "serial": "dev1",
        "strategy": "fb_posts",
        "context": {},
    }, queue)

    msg = json.loads(await queue.get())
    assert msg["ok"] is False
    assert msg["error"] == "extra_data_not_configured"


@pytest.mark.asyncio
async def test_cancel_extra_data_task_by_request_id() -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key=None,
        relay_id="test-relay",
        relay_mode="grpc",
        extra_ingest=_FakeIngest({"ok": True}),
    )
    task = asyncio.create_task(asyncio.sleep(30))
    cancel_event = asyncio.Event()
    agent._extra_data_tasks["extra-cancel"] = task
    agent._extra_data_cancel_events["extra-cancel"] = cancel_event

    assert agent._cancel_extra_data_task("extra-cancel") is True
    await asyncio.sleep(0)

    assert cancel_event.is_set()
    assert task.cancelled()
    assert "extra-cancel" not in agent._extra_data_tasks
    assert "extra-cancel" not in agent._extra_data_cancel_events
