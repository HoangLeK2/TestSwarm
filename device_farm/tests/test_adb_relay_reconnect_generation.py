from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from runtime.transports.adb_relay_server import AdbRelayManager, RelayConnection


@pytest.mark.asyncio
async def test_stale_stream_cleanup_does_not_unregister_newer_connection() -> None:
    manager = AdbRelayManager()
    manager._sync_relay_to_redis = AsyncMock()
    manager._remove_relay_from_redis = AsyncMock()

    old_conn = RelayConnection("relay-1", asyncio.Queue())
    old_conn.serials = {"serial-1"}
    new_conn = RelayConnection("relay-1", asyncio.Queue())
    new_conn.serials = {"serial-1"}

    await manager.register(old_conn)
    await manager.register(new_conn)
    await manager.unregister(
        "relay-1",
        "old gRPC stream disconnected",
        expected_conn=old_conn,
    )

    assert manager.relay_for_serial("serial-1") is new_conn
    manager._remove_relay_from_redis.assert_not_awaited()


def test_stale_stream_cleanup_does_not_remove_newer_grpc_control_queue() -> None:
    manager = AdbRelayManager()
    old_queue: asyncio.Queue = asyncio.Queue()
    new_queue: asyncio.Queue = asyncio.Queue()

    manager.register_grpc_agent("agent-1", old_queue)
    manager.register_grpc_agent("agent-1", new_queue)
    manager.unregister_grpc_agent("agent-1", expected_queue=old_queue)

    assert manager._grpc_agents["agent-1"] is new_queue
    assert new_queue.empty()
