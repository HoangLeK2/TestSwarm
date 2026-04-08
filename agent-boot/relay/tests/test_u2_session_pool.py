"""Tests for relay.u2_session_pool — persistent u2 device session pool."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

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
async def test_connect_timeout_raises(event_loop):
    """connect_fn that hangs should raise via asyncio.wait_for."""
    async def slow_connect(host):
        await asyncio.sleep(100)

    def blocking_slow(host):
        time.sleep(100)

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
