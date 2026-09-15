"""Redis clients must not be shared across event loops.

Activities run on their own `asyncio.run()` loop (db.database.run_activity_coro).
A client shared with the API loop raises "got Future attached to a different loop",
and every caller swallows that — the rate limiter silently stops limiting.
"""
from __future__ import annotations

import asyncio

import pytest

from services import redis_store


class _FakeClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_redis(monkeypatch):
    import weakref

    monkeypatch.setattr(redis_store, "_new_client", _FakeClient)
    monkeypatch.setattr(redis_store, "_url", "redis://test/0")
    monkeypatch.setattr(redis_store, "_clients", weakref.WeakKeyDictionary())
    monkeypatch.setattr(redis_store, "_no_loop_client", None)
    yield
    redis_store._clients.clear()


def test_each_event_loop_gets_its_own_client(fake_redis):
    async def grab():
        return redis_store.client()

    # No dispose in between on purpose: a loop that ends without cleanup must not
    # leave a client behind for whichever loop lands on its recycled address.
    first = asyncio.run(grab())
    second = asyncio.run(grab())

    assert first is not None and second is not None
    assert first is not second, "activity loops must not share the API loop's client"


def test_same_loop_reuses_one_client(fake_redis):
    async def grab_twice():
        return redis_store.client(), redis_store.client()

    a, b = asyncio.run(grab_twice())
    assert a is b


def test_dispose_releases_only_this_loop(fake_redis):
    async def grab_and_dispose():
        created = redis_store.client()
        await redis_store.dispose_loop_client()
        return created

    created = asyncio.run(grab_and_dispose())
    assert created.closed is True
    assert redis_store._clients == {}


def test_client_is_none_when_redis_unconfigured(monkeypatch):
    monkeypatch.setattr(redis_store, "_url", None)
    monkeypatch.setattr(redis_store, "_clients", {})
    assert redis_store.enabled() is False
    assert asyncio.run(_call_client()) is None


async def _call_client():
    return redis_store.client()
