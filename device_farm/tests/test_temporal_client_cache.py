"""get_temporal_client must reuse one client per event loop.

Before this cache every call opened a fresh gRPC channel, from 19 call sites
including hot API routes: 200 clients cost +200 file descriptors and +14MB RSS.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from core.config import TemporalConfig
from temporal import worker as worker_mod


class _FakeClient:
    def __init__(self, tag: int) -> None:
        self.tag = tag


@pytest.fixture(autouse=True)
def _clear_cache():
    worker_mod._loop_clients.clear()
    worker_mod._loop_client_locks.clear()
    yield
    worker_mod._loop_clients.clear()
    worker_mod._loop_client_locks.clear()


def _cfg(server: str = "localhost:7233", namespace: str = "default") -> TemporalConfig:
    return TemporalConfig(server_url=server, namespace=namespace)


@pytest.mark.asyncio
async def test_same_loop_reuses_one_client():
    calls = 0

    async def _fake_create(cfg):
        nonlocal calls
        calls += 1
        return _FakeClient(calls)

    with patch.object(worker_mod, "_create_client", _fake_create):
        first = await worker_mod.get_temporal_client(_cfg())
        second = await worker_mod.get_temporal_client(_cfg())

    assert first is second
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_callers_do_not_race_a_second_connect():
    calls = 0

    async def _fake_create(cfg):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)  # yield so both callers interleave
        return _FakeClient(calls)

    with patch.object(worker_mod, "_create_client", _fake_create):
        clients = await asyncio.gather(
            *[worker_mod.get_temporal_client(_cfg()) for _ in range(8)]
        )

    assert calls == 1
    assert all(c is clients[0] for c in clients)


@pytest.mark.asyncio
async def test_different_server_or_namespace_gets_its_own_client():
    async def _fake_create(cfg):
        return _FakeClient(hash((cfg.server_url, cfg.namespace)))

    with patch.object(worker_mod, "_create_client", _fake_create):
        a = await worker_mod.get_temporal_client(_cfg())
        b = await worker_mod.get_temporal_client(_cfg(server="other:7233"))
        c = await worker_mod.get_temporal_client(_cfg(namespace="staging"))

    assert a is not b
    assert a is not c


@pytest.mark.asyncio
async def test_dispose_drops_only_this_loop_entries():
    async def _fake_create(cfg):
        return _FakeClient(0)

    other_loop_key = (-1, "localhost:7233", "default")
    worker_mod._loop_clients[other_loop_key] = (lambda: None, _FakeClient(99))

    with patch.object(worker_mod, "_create_client", _fake_create):
        await worker_mod.get_temporal_client(_cfg())
        assert len(worker_mod._loop_clients) == 2
        await worker_mod.dispose_loop_clients()

    assert list(worker_mod._loop_clients) == [other_loop_key]


def test_separate_loops_do_not_share_a_client():
    """A worker thread's loop must not hand its client to another loop.

    CPython reuses id() once the first loop is collected, so this also covers
    the stale-id case the weakref guard exists for: without it the second
    asyncio.run could inherit a client bound to the dead loop.
    """

    async def _fake_create(cfg):
        return _FakeClient(0)

    async def _get():
        return await worker_mod.get_temporal_client(_cfg())

    with patch.object(worker_mod, "_create_client", _fake_create):
        first = asyncio.run(_get())
        second = asyncio.run(_get())

    assert first is not second


@pytest.mark.asyncio
async def test_entry_from_a_dead_loop_is_not_reused():
    """Directly plant a same-key entry whose loop is gone: must be a miss."""
    calls = 0

    async def _fake_create(cfg):
        nonlocal calls
        calls += 1
        return _FakeClient(calls)

    loop = asyncio.get_running_loop()
    stale_key = (id(loop), "localhost:7233", "default")
    worker_mod._loop_clients[stale_key] = (lambda: None, _FakeClient(99))

    with patch.object(worker_mod, "_create_client", _fake_create):
        client = await worker_mod.get_temporal_client(_cfg())

    assert calls == 1
    assert client.tag == 1
