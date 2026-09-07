"""The busy flag must survive a long run, or the phone drops off the fleet grid.

``/api/devices/live`` reads ``device:{serial}:scenario_active`` from Redis to
learn that a phone driven by a Temporal worker is busy — the in-memory counter
lives in the worker process and the web process never sees it. Two ways that
signal used to go missing mid-run, both of which made a running device vanish
from Giám sát trực tiếp on any transport blip:

1. the key is written once with a 5-minute TTL, and a crawl outlives it;
2. the standalone worker never registers an event loop, so nothing is written
   at all.
"""
from __future__ import annotations

import asyncio
import services
import threading
from types import SimpleNamespace

import pytest

from tasks import scenario_task
from temporal.worker import _ensure_manager_event_loop


class _FakeRedis:
    def __init__(self) -> None:
        self.setex_calls: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.setex_calls.append((key, ttl, value))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


def _install_fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    module = SimpleNamespace(
        enabled=lambda: True,
        client=lambda: fake,
        key=lambda name: f"df:{name}",
    )
    monkeypatch.setitem(__import__("sys").modules, "services.redis_store", module)
    monkeypatch.setattr(services, "redis_store", module, raising=False)
    return fake


def _device_on_loop(loop: asyncio.AbstractEventLoop, *, active: int = 1):
    return SimpleNamespace(serial="ABC123", _scenario_active=active, _loop=loop)


def _run_loop_in_thread() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _stop_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def test_publish_writes_flag_with_refreshable_ttl(monkeypatch):
    fake = _install_fake_redis(monkeypatch)
    loop, thread = _run_loop_in_thread()
    try:
        scenario_task._try_publish_scenario_active_redis(_device_on_loop(loop))
        # run_coroutine_threadsafe is fire-and-forget; let the loop drain.
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=5)
    finally:
        _stop_loop(loop, thread)

    assert fake.setex_calls == [
        ("df:device:ABC123:scenario_active", scenario_task._SCENARIO_ACTIVE_TTL_S, "1")
    ]
    # A refresh that never beats the TTL would expire the flag mid-run.
    assert scenario_task._SCENARIO_ACTIVE_REFRESH_S < scenario_task._SCENARIO_ACTIVE_TTL_S


def test_keepalive_republishes_until_stopped(monkeypatch):
    republished = threading.Event()
    calls: list[object] = []

    def _record(device):
        calls.append(device)
        republished.set()

    monkeypatch.setattr(scenario_task, "_SCENARIO_ACTIVE_REFRESH_S", 0.01)
    monkeypatch.setattr(scenario_task, "_try_publish_scenario_active_redis", _record)

    device = SimpleNamespace(serial="ABC123", _scenario_active=1, _loop=None)
    stop = scenario_task._start_scenario_active_keepalive(device)
    try:
        assert republished.wait(timeout=5), "keepalive never refreshed the flag"
    finally:
        stop.set()

    seen = len(calls)
    threading.Event().wait(0.1)
    assert len(calls) == seen, "keepalive kept running after stop"


def test_keepalive_stops_when_scenario_is_force_cleared(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(scenario_task, "_SCENARIO_ACTIVE_REFRESH_S", 0.01)
    monkeypatch.setattr(
        scenario_task,
        "_try_publish_scenario_active_redis",
        lambda device: calls.append(device),
    )

    # force_clear_scenario_busy() zeroes the counter on interrupt / preview
    # cancel; the keepalive must not resurrect the busy flag afterwards.
    device = SimpleNamespace(serial="ABC123", _scenario_active=0, _loop=None)
    stop = scenario_task._start_scenario_active_keepalive(device)
    try:
        threading.Event().wait(0.1)
    finally:
        stop.set()

    assert calls == []


def test_worker_registers_event_loop_when_registry_has_none():
    registered: list[object] = []
    manager = SimpleNamespace(
        _event_loop=None,
        register_event_loop=lambda loop: registered.append(loop),
    )
    sentinel = object()

    _ensure_manager_event_loop(manager, sentinel)

    assert registered == [sentinel]


def test_worker_does_not_steal_an_already_registered_loop():
    """In-process mode registers the app loop in the web lifespan — keep it."""
    registered: list[object] = []
    app_loop = object()
    manager = SimpleNamespace(
        _event_loop=app_loop,
        register_event_loop=lambda loop: registered.append(loop),
    )

    _ensure_manager_event_loop(manager, object())

    assert registered == []
