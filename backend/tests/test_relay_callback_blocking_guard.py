"""Guard: relay device callbacks must not block the API event loop.

Background — the bug this file exists to prevent from returning.

`update_serials` fires the device-online callback synchronously, on the same
event loop that serves the whole HTTP API (the gRPC relay server is started with
`grpc.aio` inside the FastAPI lifespan). `bind_relay_u2` used to poll for
`wlan_ip` there with `for _ in range(8): time.sleep(0.25)`. That poll waited on
capabilities which `update_capabilities()` only writes *after* `update_serials()`
returns — on the loop the sleep was holding. So it always burned the full 2s,
once per phone, serialized. An agent-boot reporting 40-100 phones froze the
backend for 80-200 seconds and nothing in the logs said why.

Two properties are pinned here:
  1. the online callback path stays off the clock (measured as loop lag)
  2. capabilities are visible to the online callback, so nothing needs to wait
"""
from __future__ import annotations

import asyncio
import time

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.transports.adb_relay_server import AdbRelayManager, RelayConnection


def _conn(relay_id: str, serials: set[str]) -> RelayConnection:
    conn = RelayConnection(relay_id, asyncio.Queue())
    conn.serials = set(serials)
    return conn


class _LoopLagProbe:
    """Measure the worst gap between consecutive event-loop ticks."""

    def __init__(self) -> None:
        self.max_lag_ms = 0.0
        self._task: asyncio.Task | None = None
        self._stop = False

    async def _run(self) -> None:
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(0)
            now = time.perf_counter()
            self.max_lag_ms = max(self.max_lag_ms, (now - last) * 1000.0)
            last = now

    async def __aenter__(self) -> "_LoopLagProbe":
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *_exc) -> bool:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return False


@pytest.mark.asyncio
async def test_registering_a_fleet_does_not_stall_the_event_loop(monkeypatch):
    """100 serials arriving at once must not park the loop.

    Budget is deliberately generous (500ms for the whole fleet). The bug this
    catches cost 2000ms *per device*, so any regression of that shape blows
    through by two orders of magnitude.
    """
    manager = AdbRelayManager()

    async def _fake_sync(_conn) -> None:
        return None

    monkeypatch.setattr(manager, "_sync_relay_to_redis", _fake_sync)

    seen: list[str] = []
    manager.set_on_device_online(seen.append)

    serials = {f"serial-{i}" for i in range(100)}
    await manager.register(_conn("relay-1", set()))

    async with _LoopLagProbe() as probe:
        await manager.update_serials("relay-1", serials)

    assert len(seen) == 100
    assert probe.max_lag_ms < 500, (
        f"relay online callbacks stalled the event loop for {probe.max_lag_ms:.0f}ms — "
        "something on the callback path is blocking (sleep, sync I/O, sync DB)"
    )


@pytest.mark.asyncio
async def test_online_callback_is_not_run_while_holding_the_manager_lock(monkeypatch):
    """A callback must be able to use the manager it was called from.

    Holding `_lock` across N user callbacks also queues every relay command
    (scrcpy attach, shell, admission) behind the whole batch.
    """
    manager = AdbRelayManager()

    async def _fake_sync(_conn) -> None:
        return None

    monkeypatch.setattr(manager, "_sync_relay_to_redis", _fake_sync)
    await manager.register(_conn("relay-1", set()))

    lock_free: list[bool] = []
    manager.set_on_device_online(lambda _s: lock_free.append(not manager._lock.locked()))

    await manager.update_serials("relay-1", {"serial-a", "serial-b"})

    assert lock_free == [True, True]


@pytest.mark.asyncio
async def test_slow_callback_is_reported_with_its_serial(monkeypatch, caplog):
    """A blocking callback must name itself in the logs, not just hang."""
    import logging

    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.RELAY_CALLBACK_WARN_MS", 5
    )
    manager = AdbRelayManager()

    async def _fake_sync(_conn) -> None:
        return None

    monkeypatch.setattr(manager, "_sync_relay_to_redis", _fake_sync)
    await manager.register(_conn("relay-1", set()))
    manager.set_on_device_online(lambda _s: time.sleep(0.05))

    with caplog.at_level(logging.WARNING, logger="runtime.transports.adb_relay_server"):
        await manager.update_serials("relay-1", {"slow-serial"})

    messages = [rec.getMessage() for rec in caplog.records]
    assert any("relay callback slow" in m for m in messages), messages
    assert any("slow-serial" in m for m in messages), messages


class _RelayWithoutCaps:
    """A relay that knows the serial but has no capabilities for it yet.

    Exactly the state at heartbeat time for a freshly discovered phone, and the
    state the removed poll loop sat spinning on.
    """

    def resolve_serial(self, serial: str) -> str:
        return serial

    def relay_for_serial(self, serial: str) -> object:
        return object()

    def get_capabilities(self, serial: str) -> dict:
        return {}


def test_bind_relay_u2_returns_immediately_without_capabilities(monkeypatch):
    """bind_relay_u2 must not wait for wlan_ip on the caller's thread.

    A USB serial carries no IP, so with empty capabilities there is nothing to
    resolve. The old code spent 8 x 250ms discovering that — on the API event
    loop, once per phone. Deliberately does NOT stub time.sleep: the wall clock
    is the assertion.
    """
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: _RelayWithoutCaps(),
    )
    # The background waiter is allowed to be slow — it is off the event loop.
    monkeypatch.setattr(
        DeviceClient, "_relay_u2_bind_wait_connect", lambda self, serial: None
    )

    device = DeviceClient(serial="R58M1234USB", index=0, config=Config())

    started = time.perf_counter()
    assert device.bind_relay_u2("R58M1234USB") is True
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assert elapsed_ms < 250, (
        f"bind_relay_u2 blocked for {elapsed_ms:.0f}ms with no capabilities — "
        "it is polling on the event loop again"
    )


def test_bind_relay_u2_keeps_one_waiter_per_device(monkeypatch):
    """Repeat binds must not stack waiter threads.

    _on_relay_capabilities_update re-binds on every capability change while u2
    is None, so an unreachable phone would otherwise accumulate one 15-second
    waiter per heartbeat.
    """
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: _RelayWithoutCaps(),
    )
    started: list[str] = []
    release = __import__("threading").Event()

    def _blocking_waiter(self, serial: str) -> None:
        started.append(serial)
        release.wait(timeout=5)
        self._relay_u2_bind_inflight.release()

    monkeypatch.setattr(DeviceClient, "_relay_u2_bind_wait_connect", _blocking_waiter)

    device = DeviceClient(serial="R58M1234USB", index=0, config=Config())
    try:
        for _ in range(10):
            device.bind_relay_u2("R58M1234USB")
        # Give the first waiter a moment to actually start.
        for _ in range(50):
            if started:
                break
            time.sleep(0.01)
        assert started == ["R58M1234USB"], f"stacked {len(started)} waiters"
    finally:
        release.set()


@pytest.mark.asyncio
async def test_callback_exception_does_not_break_the_batch(monkeypatch):
    """One raising callback must not stop the remaining serials registering."""
    manager = AdbRelayManager()

    async def _fake_sync(_conn) -> None:
        return None

    monkeypatch.setattr(manager, "_sync_relay_to_redis", _fake_sync)
    await manager.register(_conn("relay-1", set()))

    seen: list[str] = []

    def _cb(serial: str) -> None:
        if serial == "boom":
            raise RuntimeError("callback blew up")
        seen.append(serial)

    manager.set_on_device_online(_cb)
    await manager.update_serials("relay-1", {"a", "boom", "b"})

    assert sorted(seen) == ["a", "b"]
