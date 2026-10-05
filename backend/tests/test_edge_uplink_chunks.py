from __future__ import annotations

import asyncio
import base64
import json

import pytest

from runtime.transports.adb_relay_server import RelayConnection


@pytest.mark.asyncio
async def test_relay_connection_reassembles_extra_data_chunks() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    connection = RelayConnection("relay-1", queue)
    task = asyncio.create_task(
        connection.send_json_request(
            {"type": "extra_data", "id": "req-1"},
            "req-1",
            timeout=1,
            timeout_grace=0,
        )
    )
    await queue.get()

    encoded = json.dumps(
        {
            "schema_version": 1,
            "kind": "content",
            "items": [{"body": "a"}, {"body": "b"}],
            "content_hashes": ["h1", "h2"],
        }
    ).encode()
    split = len(encoded) // 2
    connection.add_extra_data_chunk(
        "req-1",
        {"id": "req-1", "index": 1, "total": 2, "data_b64": base64.b64encode(encoded[split:]).decode()},
    )
    connection.add_extra_data_chunk(
        "req-1",
        {"id": "req-1", "index": 0, "total": 2, "data_b64": base64.b64encode(encoded[:split]).decode()},
    )
    connection.resolve_extra_data(
        "req-1",
        {
            "type": "extra_data_result",
            "id": "req-1",
            "ok": True,
            "ingest": {
                "persist_batch_manifest": {
                    "schema_version": 1,
                    "kind": "content",
                    "chunk_count": 2,
                }
            },
        },
    )

    result = await task
    assert result["ingest"]["persist_batch"]["items"] == [{"body": "a"}, {"body": "b"}]
    assert result["ingest"]["persist_batch"]["content_hashes"] == ["h1", "h2"]


@pytest.mark.asyncio
async def test_relay_connection_rejects_incomplete_extra_data_chunks() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    connection = RelayConnection("relay-1", queue)
    task = asyncio.create_task(
        connection.send_json_request(
            {"type": "extra_data", "id": "req-2"},
            "req-2",
            timeout=1,
            timeout_grace=0,
        )
    )
    await queue.get()
    connection.resolve_extra_data(
        "req-2",
        {
            "type": "extra_data_result",
            "id": "req-2",
            "ok": True,
            "ingest": {
                "persist_batch_manifest": {
                    "schema_version": 1,
                    "kind": "content",
                    "chunk_count": 1,
                }
            },
        },
    )

    result = await task
    assert result == {"ok": False, "error": "missing content uplink chunks"}
