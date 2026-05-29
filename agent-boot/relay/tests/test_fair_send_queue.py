"""
Tests for relay.runtime.FairSendQueue + serial-aware bounded_put helpers.

Critical invariants we lock in here:

- Control plane (untagged) has absolute priority over per-device lanes.
- Per-device lanes are drained round-robin, regardless of insertion order.
- One device filling its lane does not block other devices' producers.
- drop_serial removes the lane and discards backlog without touching others.
- bounded_put / bounded_put_nowait forward `serial` to the FairSendQueue.
"""
from __future__ import annotations

import asyncio

import pytest

from relay.runtime import (
    FairSendQueue,
    bounded_put,
    bounded_put_nowait,
)


@pytest.mark.asyncio
async def test_control_lane_priority() -> None:
    q = FairSendQueue(per_device_max=4, control_max=4)

    # Fill device lanes first; then put a single control item.
    q.put_nowait_with_serial("dev-a-1", "A")
    q.put_nowait_with_serial("dev-a-2", "A")
    q.put_nowait_with_serial("dev-b-1", "B")
    q.put_nowait("control-1")  # untagged → control lane

    # First out must be the control plane item.
    first = await q.get()
    assert first == "control-1"


@pytest.mark.asyncio
async def test_round_robin_across_devices() -> None:
    q = FairSendQueue(per_device_max=8, control_max=8)
    q.put_nowait_with_serial("a1", "A")
    q.put_nowait_with_serial("a2", "A")
    q.put_nowait_with_serial("a3", "A")
    q.put_nowait_with_serial("b1", "B")
    q.put_nowait_with_serial("c1", "C")

    out = []
    for _ in range(5):
        out.append(await q.get())

    # First pass through RR should pick one from each device that has data.
    # Without RR, A would have drained first; with RR, B and C show up
    # before all of A.
    first_three = out[:3]
    assert set(first_three) == {"a1", "b1", "c1"}, first_three
    # Remaining two are the leftovers from A.
    assert set(out[3:]) == {"a2", "a3"}


@pytest.mark.asyncio
async def test_one_device_full_does_not_block_another() -> None:
    q = FairSendQueue(per_device_max=2, control_max=4)

    # Fill A's lane to capacity.
    q.put_nowait_with_serial(1, "A")
    q.put_nowait_with_serial(2, "A")

    # A's third put should overflow synchronously.
    with pytest.raises(asyncio.QueueFull):
        q.put_nowait_with_serial(3, "A")

    # B's lane is independent — must succeed without delay.
    q.put_nowait_with_serial("b1", "B")
    # Drain control + RR: B's item should reach us even though A is full.
    seen = []
    for _ in range(3):
        seen.append(await q.get())
    assert "b1" in seen


@pytest.mark.asyncio
async def test_async_get_blocks_until_put() -> None:
    q = FairSendQueue()

    async def slow_producer() -> None:
        await asyncio.sleep(0.05)
        q.put_nowait_with_serial("late", "X")

    asyncio.create_task(slow_producer())
    # `get` must wait for the producer; this would hang forever if the
    # wakeup race weren't handled.
    item = await asyncio.wait_for(q.get(), timeout=2.0)
    assert item == "late"


@pytest.mark.asyncio
async def test_drop_serial_clears_lane_and_returns_count() -> None:
    q = FairSendQueue(per_device_max=8)
    for i in range(3):
        q.put_nowait_with_serial(i, "A")
    q.put_nowait_with_serial("b1", "B")

    dropped = q.drop_serial("A")
    assert dropped == 3

    # B's lane is intact.
    item = await q.get()
    assert item == "b1"

    # Re-adding to a dropped serial creates a fresh lane.
    q.put_nowait_with_serial("a-new", "A")
    assert await q.get() == "a-new"


@pytest.mark.asyncio
async def test_bounded_put_forwards_serial() -> None:
    q = FairSendQueue(per_device_max=4)
    ok = await bounded_put(q, "x", serial="phoneZ", label="test")
    assert ok is True
    snap = q.snapshot()
    assert snap.get("phoneZ") == 1
    assert snap.get("_control", 0) == 0


@pytest.mark.asyncio
async def test_bounded_put_nowait_forwards_serial() -> None:
    q = FairSendQueue(per_device_max=4)
    ok = bounded_put_nowait(q, "y", serial="phoneZ", label="test")
    assert ok is True
    assert q.snapshot().get("phoneZ") == 1


@pytest.mark.asyncio
async def test_bounded_put_compatible_with_plain_queue() -> None:
    # Legacy callers should keep working — serial kwarg silently ignored.
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    ok = await bounded_put(q, "z", serial="anything", label="legacy")
    assert ok is True
    assert q.qsize() == 1
    assert await q.get() == "z"


@pytest.mark.asyncio
async def test_qsize_aggregates_all_lanes() -> None:
    q = FairSendQueue(per_device_max=8, control_max=8)
    q.put_nowait("c1")
    q.put_nowait_with_serial("a1", "A")
    q.put_nowait_with_serial("a2", "A")
    q.put_nowait_with_serial("b1", "B")
    assert q.qsize() == 4
