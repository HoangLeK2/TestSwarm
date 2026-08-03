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
import time

import pytest

from relay.runtime import (
    FairSendQueue,
    MultiStreamSendQueue,
    bounded_put,
    bounded_put_nowait,
)
from relay.video_packet import VideoPacket


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


@pytest.mark.asyncio
async def test_reliable_result_is_not_blocked_by_full_video_lane() -> None:
    q = FairSendQueue(per_device_max=1, control_max=4)
    q.put_video_nowait("frame-1", "A")

    # Results and frames from the same phone must not share capacity.
    q.put_nowait_with_serial("result-1", "A")

    # Reliable per-device traffic is drained before lossy video.
    assert await q.get() == "result-1"
    assert await q.get() == "frame-1"


@pytest.mark.asyncio
async def test_drop_serial_clears_reliable_and_video_lanes() -> None:
    q = FairSendQueue(per_device_max=4)
    q.put_nowait_with_serial("result-1", "A")
    q.put_video_nowait("frame-1", "A")
    q.put_video_nowait("frame-2", "A")

    assert q.drop_serial("A") == 3
    assert q.qsize() == 0
    assert "A" not in q.snapshot()
    assert "video:A" not in q.snapshot()


def test_video_lane_has_independent_low_latency_capacity() -> None:
    q = FairSendQueue(per_device_max=16, video_per_device_max=2)
    q.put_video_nowait("frame-1", "A")
    q.put_video_nowait("frame-2", "A")

    with pytest.raises(asyncio.QueueFull):
        q.put_video_nowait("stale-frame", "A")

    # Reliable results keep their larger burst capacity.
    for index in range(16):
        q.put_nowait_with_serial(f"result-{index}", "A")


@pytest.mark.asyncio
async def test_video_drain_skips_known_empty_reliable_lanes() -> None:
    q = FairSendQueue(per_device_max=2, video_per_device_max=2)
    q.put_nowait_with_serial("result", "A")
    assert await q.get() == "result"
    q.put_video_nowait("frame-1", "A")
    assert await q.get() == "frame-1"

    class PoisonEmptyLane:
        def empty(self) -> bool:
            raise AssertionError("empty reliable lanes must not be scanned")

    q._per_dev["A"] = PoisonEmptyLane()
    q.put_video_nowait("frame-2", "A")
    assert await q.get() == "frame-2"


@pytest.mark.asyncio
async def test_video_stats_report_queue_age_on_dequeue() -> None:
    q = FairSendQueue(video_per_device_max=2)
    packet = VideoPacket(
        serial="A",
        data=b"frame",
        is_config=False,
        is_key=True,
        pts_us=1,
        received_ns=time.monotonic_ns() - 50_000_000,
    )
    q.offer_video_nowait(
        packet,
        packet.serial,
        is_config=packet.is_config,
        is_key=packet.is_key,
    )
    await asyncio.sleep(0.05)

    assert await q.get() is packet
    stats = q.video_stats_snapshot()
    assert stats["dequeued"] == 1
    assert stats["queue_age_p95_ms"] >= 40
    assert stats["queue_age_max_ms"] >= 40
    assert stats["handoff_age_p95_ms"] >= 40


@pytest.mark.asyncio
async def test_video_capacity_one_is_raised_to_preserve_config_and_keyframe() -> None:
    q = FairSendQueue(video_per_device_max=1)
    for index in range(2):
        q.offer_video_nowait(
            f"delta-{index}",
            "A",
            is_config=False,
            is_key=False,
        )
    assert q.offer_video_nowait(
        "dropped-delta",
        "A",
        is_config=False,
        is_key=False,
    )
    assert await q.get() == "delta-0"
    assert await q.get() == "delta-1"

    q.offer_video_nowait("config", "A", is_config=True, is_key=False)
    q.offer_video_nowait("key", "A", is_config=False, is_key=True)

    assert await q.get() == "config"
    assert await q.get() == "key"


@pytest.mark.asyncio
async def test_queue_age_p95_does_not_collapse_to_single_extreme_max() -> None:
    q = FairSendQueue(video_per_device_max=100)
    now_ns = time.monotonic_ns()
    ages_ms = [100] * 94 + [6_000] * 5 + [100_000]
    for index, age_ms in enumerate(ages_ms):
        packet = VideoPacket(
            serial="A",
            data=b"frame",
            is_config=False,
            is_key=True,
            pts_us=index,
        )
        q.offer_video_nowait(
            packet,
            packet.serial,
            is_config=False,
            is_key=True,
        )
        packet.enqueued_ns = now_ns - age_ms * 1_000_000

    for _ in ages_ms:
        await q.get()

    stats = q.video_stats_snapshot()
    assert stats["queue_age_p95_ms"] == 10_000
    assert stats["queue_age_max_ms"] >= 100_000


@pytest.mark.asyncio
async def test_stale_delta_is_dropped_on_dequeue_and_requests_idr() -> None:
    q = FairSendQueue(video_per_device_max=4, video_stale_ms=10)
    idr_requests: list[str] = []
    stale_delta = VideoPacket(
        serial="A",
        data=b"stale-delta",
        is_config=False,
        is_key=False,
        pts_us=1,
    )
    keyframe = VideoPacket(
        serial="A",
        data=b"keyframe",
        is_config=False,
        is_key=True,
        pts_us=2,
    )

    q.offer_video_nowait(
        stale_delta,
        "A",
        is_config=False,
        is_key=False,
        on_drop=lambda: idr_requests.append("A"),
    )
    await asyncio.sleep(0.02)
    q.offer_video_nowait(
        keyframe,
        "A",
        is_config=False,
        is_key=True,
        on_drop=lambda: idr_requests.append("A"),
    )

    assert await q.get() is keyframe
    assert idr_requests == ["A"]
    stats = q.video_stats_snapshot()
    assert stats["stale_drops"] == 1
    assert stats["drops"] == 1
    assert stats["awaiting_keyframe"] == 0


@pytest.mark.asyncio
async def test_multi_stream_queue_keeps_reliable_and_video_physical_lanes_separate() -> None:
    q = MultiStreamSendQueue(
        video_shards=4,
        per_device_max=2,
        video_per_device_max=2,
    )
    q.put_nowait("control")
    q.put_nowait_with_serial("result-A", "A")
    q.offer_video_nowait(
        VideoPacket(
            serial="A",
            data=b"frame-A",
            is_config=False,
            is_key=True,
            pts_us=1,
        ),
        "A",
        is_config=False,
        is_key=True,
    )

    assert await q.get() == "control"
    assert await q.get() == "result-A"

    shard_items = []
    for index in range(q.video_shard_count()):
        shard = q.video_shard_queue(index)
        if shard.qsize():
            shard_items.append(await shard.get())

    assert [item.data for item in shard_items] == [b"frame-A"]
    assert q.qsize() == 0


def test_multi_stream_drop_serial_clears_reliable_and_video_shard() -> None:
    q = MultiStreamSendQueue(
        video_shards=4,
        per_device_max=2,
        video_per_device_max=2,
    )
    q.put_nowait_with_serial("result-A", "A")
    q.offer_video_nowait(
        VideoPacket(
            serial="A",
            data=b"frame-A",
            is_config=False,
            is_key=True,
            pts_us=1,
        ),
        "A",
        is_config=False,
        is_key=True,
    )

    assert q.drop_serial("A") == 2
    assert q.qsize() == 0


@pytest.mark.asyncio
async def test_multi_stream_video_stats_use_max_latency_not_sum() -> None:
    q = MultiStreamSendQueue(
        video_shards=2,
        video_per_device_max=8,
        video_stale_ms=0,
    )
    now_ns = time.monotonic_ns()
    packets = [
        VideoPacket(
            serial="A",
            data=b"frame-A",
            is_config=False,
            is_key=True,
            pts_us=1,
        ),
        VideoPacket(
            serial="B",
            data=b"frame-B",
            is_config=False,
            is_key=True,
            pts_us=2,
        ),
    ]
    for index, packet in enumerate(packets):
        shard = q.video_shard_queue(index)
        shard.offer_video_nowait(
            packet,
            packet.serial,
            is_config=False,
            is_key=True,
        )
        packet.enqueued_ns = now_ns - 100 * 1_000_000

    for shard_index in range(q.video_shard_count()):
        shard = q.video_shard_queue(shard_index)
        while shard.qsize():
            await shard.get()

    stats = q.video_stats_snapshot()
    assert stats["dequeued"] == 2
    assert stats["queue_age_p95_ms"] == 128
