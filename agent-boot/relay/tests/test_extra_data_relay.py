from __future__ import annotations

import asyncio
import json

import pytest

from relay.agent import RelayAgent


class _FakeIngest:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.payloads: list[dict] = []

    async def process_payload(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.result


class _FakeExecutor:
    async def run_batch(self, serial: str, actions: list[dict], early_exit: bool = True) -> dict:
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
        "context": {"collection": "ig", "persist": True},
    }, queue)

    raw = await asyncio.wait_for(queue.get(), timeout=2.0)
    msg = json.loads(raw)
    assert msg["type"] == "extra_data_result"
    assert msg["ok"] is True
    assert msg["route"] == "relay_u2"
    assert msg["ingest"]["parsed_count"] == 2
    assert len(agent._extra_ingest.payloads) == 1


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
