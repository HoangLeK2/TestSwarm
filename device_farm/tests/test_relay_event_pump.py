"""Guard tests for the relay → device-FSM pump.

The pump exists because one DB session per reported serial drained the pool
(pool_size=12, max_overflow=3) the moment agent-boot registered a 40-100 phone
fleet, and every API request then blocked on pool_timeout. These tests pin the
three properties that keep that from coming back: batching, dedupe, and bounded
backpressure.
"""
from __future__ import annotations

import asyncio

import pytest

from runtime.transports.relay_event_pump import RelayEventPump


class _FakeSession:
    """Minimal async-context session that records what it was asked to do."""

    def __init__(self, tracker: "_SessionTracker") -> None:
        self._tracker = tracker
        self.commits = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def commit(self) -> None:
        self.commits += 1
        self._tracker.commits += 1


class _SessionTracker:
    def __init__(self) -> None:
        self.opened = 0
        self.commits = 0
        self.sessions: list[_FakeSession] = []

    def __call__(self) -> _FakeSession:
        self.opened += 1
        session = _FakeSession(self)
        self.sessions.append(session)
        return session


def _pump(tracker, *, online=None, offline=None, **kwargs) -> RelayEventPump:
    async def _noop(serial, *, logical_serial=None, hardware_serial=None, db=None):
        return True

    return RelayEventPump(
        session_factory=tracker,
        apply_online=online or _noop,
        apply_offline=offline or _noop,
        **kwargs,
    )


async def _drain(pump: RelayEventPump, *, timeout: float = 2.0) -> None:
    """Wait until the pump has emptied its queue."""
    deadline = asyncio.get_running_loop().time() + timeout
    while pump.stats()["depth"] > 0 or pump.stats()["batches"] == 0:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"pump did not drain: {pump.stats()}")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_one_session_serves_a_whole_fleet():
    """100 phones registering must cost one connection, not one hundred.

    This is the regression that froze the backend: the old code scheduled a
    coroutine per serial, each opening its own pooled session.
    """
    tracker = _SessionTracker()
    applied: list[str] = []

    async def _online(serial, *, logical_serial=None, hardware_serial=None, db=None):
        applied.append(serial)
        return True

    pump = _pump(tracker, online=_online, batch_max=256, coalesce_ms=20)
    await pump.start()
    try:
        for i in range(100):
            assert pump.submit("online", f"serial-{i}") is True
        await _drain(pump)
    finally:
        await pump.stop()

    assert len(applied) == 100
    assert tracker.opened == 1, f"expected 1 session, got {tracker.opened}"
    assert tracker.commits == 1


@pytest.mark.asyncio
async def test_batch_max_bounds_the_transaction_size():
    tracker = _SessionTracker()
    pump = _pump(tracker, batch_max=10, coalesce_ms=20)
    await pump.start()
    try:
        for i in range(30):
            pump.submit("online", f"serial-{i}")
        await _drain(pump)
    finally:
        await pump.stop()

    # 30 events, at most 10 per transaction — never one session per event.
    assert 3 <= tracker.opened <= 4
    assert pump.stats()["processed"] == 30


@pytest.mark.asyncio
async def test_flapping_serial_only_writes_its_final_state():
    """online→offline inside one window writes offline once, not both."""
    tracker = _SessionTracker()
    calls: list[tuple[str, str]] = []

    async def _online(serial, *, logical_serial=None, hardware_serial=None, db=None):
        calls.append(("online", serial))
        return True

    async def _offline(serial, *, logical_serial=None, hardware_serial=None, db=None):
        calls.append(("offline", serial))
        return True

    pump = _pump(tracker, online=_online, offline=_offline, coalesce_ms=30)
    await pump.start()
    try:
        pump.submit("online", "dev-1")
        pump.submit("offline", "dev-1")
        pump.submit("online", "dev-2")
        await _drain(pump)
    finally:
        await pump.stop()

    assert ("offline", "dev-1") in calls
    assert ("online", "dev-1") not in calls
    assert ("online", "dev-2") in calls


@pytest.mark.asyncio
async def test_full_queue_drops_instead_of_blocking():
    """submit() runs on the API event loop — it must never await or raise."""
    tracker = _SessionTracker()
    release = asyncio.Event()

    async def _slow(serial, *, logical_serial=None, hardware_serial=None, db=None):
        await release.wait()
        return True

    pump = _pump(tracker, online=_slow, queue_max=4, batch_max=1, coalesce_ms=0)
    await pump.start()
    try:
        results = [pump.submit("online", f"serial-{i}") for i in range(50)]
        assert any(r is False for r in results), "expected drops on a full queue"
        stats = pump.stats()
        assert stats["dropped"] > 0
        assert stats["depth"] <= 4
        release.set()
    finally:
        release.set()
        await pump.stop()


@pytest.mark.asyncio
async def test_one_bad_serial_does_not_sink_the_batch():
    """A failing event aborts its transaction; the rest must still be written."""
    tracker = _SessionTracker()
    applied: list[str] = []

    async def _online(serial, *, logical_serial=None, hardware_serial=None, db=None):
        if serial == "bad":
            raise RuntimeError("boom")
        applied.append(serial)
        return True

    pump = _pump(tracker, online=_online, batch_max=64, coalesce_ms=20)
    await pump.start()
    try:
        pump.submit("online", "good-1")
        pump.submit("online", "bad")
        pump.submit("online", "good-2")
        await _drain(pump)
        # Individual retries happen after the batch fails.
        for _ in range(100):
            if pump.stats()["failed"]:
                break
            await asyncio.sleep(0.01)
    finally:
        await pump.stop()

    # good-1 is applied twice: once in the batch that "bad" aborted, once on
    # its individual retry. That replay is required, not wasteful — the failed
    # batch's transaction was discarded, so the first write never landed.
    assert set(applied) == {"good-1", "good-2"}
    stats = pump.stats()
    assert stats["failed"] == 1
    assert stats["retries"] == 3
    assert "boom" in stats["last_error"]


@pytest.mark.asyncio
async def test_stop_drains_queued_events():
    tracker = _SessionTracker()
    applied: list[str] = []

    async def _online(serial, *, logical_serial=None, hardware_serial=None, db=None):
        applied.append(serial)
        return True

    pump = _pump(tracker, online=_online, batch_max=64, coalesce_ms=5)
    await pump.start()
    for i in range(5):
        pump.submit("online", f"serial-{i}")
    await pump.stop()

    assert len(applied) == 5
    assert pump.stats()["depth"] == 0


@pytest.mark.asyncio
async def test_submit_rejects_junk_without_touching_the_queue():
    tracker = _SessionTracker()
    pump = _pump(tracker)
    assert pump.submit("online", "") is False
    assert pump.submit("online", "   ") is False
    assert pump.submit("sideways", "dev-1") is False
    assert pump.stats()["submitted"] == 0
    assert pump.stats()["depth"] == 0


@pytest.mark.asyncio
async def test_metadata_reaches_the_apply_function():
    tracker = _SessionTracker()
    seen: list[dict] = []

    async def _online(serial, *, logical_serial=None, hardware_serial=None, db=None):
        seen.append(
            {
                "serial": serial,
                "logical": logical_serial,
                "hardware": hardware_serial,
                "db_is_session": db is not None,
            }
        )
        return True

    pump = _pump(tracker, online=_online, coalesce_ms=5)
    await pump.start()
    try:
        pump.submit(
            "online", "dev-1", logical_serial="logical-1", hardware_serial="hw-1"
        )
        await _drain(pump)
    finally:
        await pump.stop()

    assert seen == [
        {
            "serial": "dev-1",
            "logical": "logical-1",
            "hardware": "hw-1",
            "db_is_session": True,
        }
    ]
