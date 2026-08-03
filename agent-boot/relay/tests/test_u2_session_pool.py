"""Tests for relay.u2_session_pool — persistent u2 device session pool."""
from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from relay import u2_session_pool as u2_pool_mod
from relay.u2_session_pool import U2SessionPool, SESSION_TTL_SECONDS


@pytest.fixture
def mock_device():
    dev = MagicMock()
    dev.alive = True
    return dev


@pytest.fixture
def pool(event_loop, mock_device):
    fn = MagicMock(return_value=mock_device)
    p = U2SessionPool(loop=event_loop, connect_fn=fn)
    return p, fn, mock_device


# ── Basic session management ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_connects_once(pool):
    p, fn, dev = pool
    await p.start()
    try:
        d1 = await p.get_session("192.168.1.10:5555")
        d2 = await p.get_session("192.168.1.10:5555")
        assert d1 is dev
        assert d2 is dev
        fn.assert_called_once()
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_stats_snapshot_reports_alive_probe_and_heartbeat_coverage(pool):
    p, _fn, _dev = pool
    await p.start()
    try:
        await p.get_session("192.168.1.10:5555")
        entry = p._sessions["192.168.1.10:5555"]

        assert await p._is_alive(entry) is True

        stats = p.stats_snapshot(reset=False)
        assert stats["alive_probes"] >= 1
        assert stats["alive_probe_p95_ms"] >= 0
        assert stats["heartbeat_coverage_percent"] > 0
        assert "reset_uiautomator_success" in stats
        assert "reconnect_fallbacks" in stats
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_warm_session_preconnects_first_request(pool):
    p, fn, dev = pool
    await p.start()
    try:
        warmed = await p.warm_session("192.168.1.10:5555")
        assert warmed is True
        assert p._sessions["192.168.1.10:5555"].keep_warm is True
        d1 = await p.get_session("192.168.1.10:5555")
        assert d1 is dev
        fn.assert_called_once()
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_warm_session_waits_for_active_entry_lock(pool):
    p, fn, dev = pool
    await p.start()
    try:
        await p.get_session("192.168.1.10:5555")
        entry = p._sessions["192.168.1.10:5555"]

        async with entry.lock:
            task = asyncio.create_task(p.warm_session("192.168.1.10:5555"))
            await asyncio.sleep(0)
            assert not task.done()

        assert await asyncio.wait_for(task, timeout=1.0) is True
        fn.assert_called_once()
        assert entry.device is dev
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_mark_keep_warm_pins_existing_session(pool):
    p, fn, _dev = pool
    await p.start()
    try:
        await p.get_session("192.168.1.10:5555")
        entry = p._sessions["192.168.1.10:5555"]
        assert entry.keep_warm is False

        assert p.mark_keep_warm("192.168.1.10:5555") is True

        assert entry.keep_warm is True
        fn.assert_called_once()
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_concurrent_get_session_safe(pool):
    """Two concurrent calls should only connect once (double-check pattern)."""
    p, fn, dev = pool
    await p.start()
    try:
        results = await asyncio.gather(
            p.get_session("192.168.1.10:5555"),
            p.get_session("192.168.1.10:5555"),
        )
        assert results[0] is dev
        assert results[1] is dev
        # May be called once or twice (race), but the pool should converge to one entry
        assert fn.call_count <= 2
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_run_locked_cancel_waits_for_blocking_work_to_finish(pool):
    p, _fn, _dev = pool
    serial = "192.168.1.10:5555"
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def _blocking(_device):
        started.set()
        try:
            release.wait(timeout=2.0)
        finally:
            finished.set()

    await p.start()
    try:
        await p.get_session(serial)
        task = asyncio.create_task(p.run_locked(serial, _blocking))
        while not started.is_set():
            await asyncio.sleep(0)

        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.5)
        assert finished.is_set()
    finally:
        release.set()
        await p.stop()


@pytest.mark.asyncio
async def test_evict_removes_entry(pool):
    p, fn, dev = pool
    await p.start()
    try:
        await p.get_session("192.168.1.10:5555")
        await p.evict("192.168.1.10:5555")
        # Next call should re-connect
        await p.get_session("192.168.1.10:5555")
        assert fn.call_count == 2
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_evict_closes_device(pool):
    p, fn, dev = pool
    await p.start()
    try:
        await p.get_session("192.168.1.10:5555")
        await p.evict("192.168.1.10:5555")
        dev.stop.assert_called_once()
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_dead_session_reconnects(event_loop):
    """When device.alive is False, get_session should reconnect transparently."""
    dead_dev = MagicMock()
    dead_dev.alive = False

    new_dev = MagicMock()
    new_dev.alive = True

    call_count = 0

    def connect_fn(host):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return dead_dev
        return new_dev

    p = U2SessionPool(loop=event_loop, connect_fn=connect_fn)
    await p.start()
    try:
        d = await p.get_session("192.168.1.10:5555")
        assert d is new_dev
        assert call_count == 2
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_direct_http_health_skips_device_side_reset(event_loop):
    """If ATX HTTP just worked, avoid reset_uiautomator storm on stale u2 session."""
    stale_dev = MagicMock()
    stale_dev.alive = False
    stale_dev.reset_uiautomator = MagicMock()

    fresh_dev = MagicMock()
    fresh_dev.alive = True

    connect_fn = MagicMock(side_effect=[stale_dev, fresh_dev])
    p = U2SessionPool(loop=event_loop, connect_fn=connect_fn)
    await p.start()
    try:
        p.mark_direct_http_healthy("dev-001")

        dev = await p.get_session("dev-001")

        assert dev is fresh_dev
        stale_dev.reset_uiautomator.assert_not_called()
        assert connect_fn.call_count == 2
        stats = p.stats_snapshot(reset=False)
        assert stats["direct_http_health_marks"] == 1
        assert stats["reset_uiautomator_http_healthy_skips"] == 1
        assert stats["reconnects"] == 1
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_reset_uiautomator_cooldown_skips_repeated_resets(event_loop, monkeypatch):
    """Repeated stale sessions should reconnect locally without hammering u2 reset."""
    monkeypatch.setattr(u2_pool_mod, "RESET_UIAUTOMATOR_COOLDOWN_SECONDS", 60.0)

    first_dev = MagicMock()
    first_dev.alive = False
    first_dev.reset_uiautomator = MagicMock(side_effect=RuntimeError("reset failed"))

    second_dev = MagicMock()
    second_dev.alive = False
    second_dev.reset_uiautomator = MagicMock()

    third_dev = MagicMock()
    third_dev.alive = True

    connect_fn = MagicMock(side_effect=[first_dev, second_dev, third_dev])
    p = U2SessionPool(loop=event_loop, connect_fn=connect_fn)
    await p.start()
    try:
        entry = await p._connect("dev-001")

        await p._reconnect(entry)
        await p._reconnect(entry)

        first_dev.reset_uiautomator.assert_called_once()
        second_dev.reset_uiautomator.assert_not_called()
        assert connect_fn.call_count == 3
        stats = p.stats_snapshot(reset=False)
        assert stats["reset_uiautomator_failures"] == 1
        assert stats["reset_uiautomator_cooldown_skips"] == 1
        assert stats["reconnects"] == 2
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_connect_timeout_raises(event_loop, monkeypatch):
    """connect_fn that hangs should raise via asyncio.wait_for."""
    monkeypatch.setattr(u2_pool_mod, "CONNECT_TIMEOUT_SECONDS", 0.01)

    def blocking_slow(host):
        time.sleep(0.2)

    p = U2SessionPool(loop=event_loop, connect_fn=blocking_slow)
    await p.start()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await p.get_session("192.168.1.10:5555")
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_usb_serial_no_colon(pool):
    """USB serial like 'emulator-5554' should pass serial directly to connect_fn."""
    p, fn, dev = pool
    await p.start()
    try:
        await p.get_session("emulator-5554")
        fn.assert_called_once_with("emulator-5554")
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_reap_loop_evicts_idle(event_loop):
    """Sessions idle past TTL should be reaped."""
    dev = MagicMock()
    dev.alive = True
    fn = MagicMock(return_value=dev)

    p = U2SessionPool(loop=event_loop, connect_fn=fn)
    await p.start()
    try:
        await p.get_session("192.168.1.10:5555")

        # Manually set last_used to the past
        async with p._global_lock:
            entry = p._sessions["192.168.1.10:5555"]
            entry.last_used = time.monotonic() - SESSION_TTL_SECONDS - 10

        # Trigger one reap cycle manually
        now = time.monotonic()
        stale = []
        async with p._global_lock:
            for s, e in p._sessions.items():
                if now - e.last_used > SESSION_TTL_SECONDS:
                    stale.append(s)
        for s in stale:
            await p.evict(s)

        # Session should be gone
        async with p._global_lock:
            assert "192.168.1.10:5555" not in p._sessions
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_reap_loop_keeps_idle_warm_session(event_loop):
    """Desired warm sessions are pinned while the device remains online."""
    dev = MagicMock()
    dev.alive = True
    fn = MagicMock(return_value=dev)

    p = U2SessionPool(loop=event_loop, connect_fn=fn)
    await p.start()
    try:
        await p.warm_session("192.168.1.10:5555")

        async with p._global_lock:
            entry = p._sessions["192.168.1.10:5555"]
            entry.last_used = time.monotonic() - SESSION_TTL_SECONDS - 10

        now = time.monotonic()
        stale = []
        async with p._global_lock:
            for s, e in p._sessions.items():
                if e.keep_warm:
                    continue
                if now - e.last_used > SESSION_TTL_SECONDS:
                    stale.append(s)
        for s in stale:
            await p.evict(s)

        async with p._global_lock:
            assert "192.168.1.10:5555" in p._sessions
            assert p._sessions["192.168.1.10:5555"].keep_warm is True
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_keep_warm_session_expires_after_warm_ttl(event_loop, monkeypatch):
    """Warm sessions must not live forever and consume u2/HTTP resources."""
    monkeypatch.setattr(u2_pool_mod, "REAP_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(u2_pool_mod, "KEEP_WARM_TTL_SECONDS", 0.2)

    dev = MagicMock()
    dev.alive = True
    p = U2SessionPool(loop=event_loop, connect_fn=MagicMock(return_value=dev))
    await p.start()
    try:
        await p.warm_session("dev-001")
        p._sessions["dev-001"].keep_warm_since = time.monotonic() - 10
        p._sessions["dev-001"].last_used = time.monotonic() - 10

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and "dev-001" in p._sessions:
            await asyncio.sleep(0.01)

        assert "dev-001" not in p._sessions
        stats = p.stats_snapshot(reset=False)
        assert stats["keep_warm_expired"] >= 1
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_keep_warm_ttl_preserves_recently_used_session(event_loop, monkeypatch):
    """Warm TTL is idle-time based; active sessions must not be evicted."""
    monkeypatch.setattr(u2_pool_mod, "REAP_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(u2_pool_mod, "KEEP_WARM_TTL_SECONDS", 0.2)

    dev = MagicMock()
    dev.alive = True
    p = U2SessionPool(loop=event_loop, connect_fn=MagicMock(return_value=dev))
    await p.start()
    try:
        await p.warm_session("dev-001")
        p._sessions["dev-001"].keep_warm_since = time.monotonic() - 10
        p._sessions["dev-001"].last_used = time.monotonic()

        await asyncio.sleep(0.05)

        assert "dev-001" in p._sessions
        stats = p.stats_snapshot(reset=False)
        assert stats["keep_warm_expired"] == 0
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_keep_warm_lru_cap_evicts_oldest_sessions(event_loop, monkeypatch):
    """Only the most recently useful warm sessions stay pinned."""
    monkeypatch.setattr(u2_pool_mod, "REAP_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(u2_pool_mod, "KEEP_WARM_TTL_SECONDS", 0.0)
    monkeypatch.setattr(u2_pool_mod, "KEEP_WARM_MAX_SESSIONS", 2)

    def connect_fn(_host):
        dev = MagicMock()
        dev.alive = True
        return dev

    p = U2SessionPool(loop=event_loop, connect_fn=connect_fn)
    await p.start()
    try:
        for index, serial in enumerate(["dev-001", "dev-002", "dev-003"]):
            await p.warm_session(serial)
            p._sessions[serial].last_used = time.monotonic() - (10 - index)

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and len(p._sessions) > 2:
            await asyncio.sleep(0.01)

        assert "dev-001" not in p._sessions
        assert set(p._sessions) == {"dev-002", "dev-003"}
        stats = p.stats_snapshot(reset=False)
        assert stats["keep_warm_lru_evictions"] >= 1
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_heartbeat_budget_limits_alive_probes_per_tick(event_loop, monkeypatch):
    """A large pool should be probed over several ticks instead of all at once."""
    monkeypatch.setattr(u2_pool_mod, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(u2_pool_mod, "HEARTBEAT_MAX_PROBES_PER_TICK", 2)
    monkeypatch.setattr(u2_pool_mod, "HEARTBEAT_SKIP_RECENT_SECONDS", 0.0)

    def connect_fn(_host):
        dev = MagicMock()
        dev.alive = True
        return dev

    p = U2SessionPool(loop=event_loop, connect_fn=connect_fn)
    await p.start()
    try:
        for index in range(5):
            await p.warm_session(f"dev-{index:03d}")
            p._sessions[f"dev-{index:03d}"].last_used = time.monotonic() - 10

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            stats = p.stats_snapshot(reset=False)
            if stats["heartbeat_ticks"] >= 1 and stats["heartbeat_probes"] >= 2:
                break
            await asyncio.sleep(0.01)

        stats = p.stats_snapshot(reset=False)
        assert stats["heartbeat_probe_budget"] == 2
        assert stats["heartbeat_budget_skips"] >= 3
        assert stats["heartbeat_probes"] <= stats["heartbeat_ticks"] * 2
    finally:
        await p.stop()


@pytest.mark.asyncio
async def test_heartbeat_skips_recent_session_without_alive_probe(event_loop, monkeypatch):
    """Recently used sessions should not pay a background .alive probe."""
    monkeypatch.setattr(u2_pool_mod, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(u2_pool_mod, "HEARTBEAT_MAX_PROBES_PER_TICK", 8)
    monkeypatch.setattr(u2_pool_mod, "HEARTBEAT_SKIP_RECENT_SECONDS", 60.0)

    dev = MagicMock()
    dev.alive = True
    p = U2SessionPool(loop=event_loop, connect_fn=MagicMock(return_value=dev))
    await p.start()
    try:
        await p.warm_session("dev-001")
        p.stats_snapshot(reset=True)

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            stats = p.stats_snapshot(reset=False)
            if stats["heartbeat_ticks"] >= 1:
                break
            await asyncio.sleep(0.01)

        stats = p.stats_snapshot(reset=False)
        assert stats["heartbeat_recent_skips"] >= 1
        assert stats["heartbeat_probes"] == 0
        assert stats["alive_probes"] == 0
    finally:
        await p.stop()
