from __future__ import annotations

import asyncio

import pytest

from relay.runtime import FairSendQueue
from relay.scrcpy_relay import enqueue_video_packet
from relay.video_packet import VideoPacket


def _packet(
    serial: str,
    data: bytes,
    *,
    is_config: bool = False,
    is_key: bool = False,
) -> VideoPacket:
    return VideoPacket(
        serial=serial,
        data=data,
        is_config=is_config,
        is_key=is_key,
        pts_us=1,
    )


@pytest.mark.asyncio
async def test_keyframe_eviction_never_discards_reliable_result() -> None:
    q = FairSendQueue(per_device_max=1)
    q.put_nowait_with_serial("result-1", "A")
    q.put_video_nowait(_packet("A", b"old-frame-1"), "A")
    q.put_video_nowait(_packet("A", b"old-frame-2"), "A")

    enqueue_video_packet(
        q,
        _packet("A", b"keyframe", is_key=True),
    )

    # A full video lane may evict an old frame, but it must never touch the
    # result lane for the same phone.
    assert await q.get() == "result-1"
    assert (await q.get()).data == b"old-frame-2"
    assert (await q.get()).data == b"keyframe"


@pytest.mark.asyncio
async def test_p_frame_drop_requests_idr_without_touching_result() -> None:
    q = FairSendQueue(per_device_max=1)
    q.put_nowait_with_serial("result-1", "A")
    q.put_video_nowait(_packet("A", b"old-frame-1"), "A")
    q.put_video_nowait(_packet("A", b"old-frame-2"), "A")
    drops: list[str] = []

    enqueue_video_packet(
        q,
        _packet("A", b"p-frame"),
        on_drop=lambda: drops.append("drop"),
    )

    assert drops == ["drop"]
    assert await q.get() == "result-1"
    assert (await q.get()).data == b"old-frame-1"
    assert (await q.get()).data == b"old-frame-2"
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 1
    assert stats["evictions"] == 0
    assert stats["affected_serials"] == 1
    assert stats["awaiting_keyframe"] == 1


@pytest.mark.asyncio
async def test_delta_frames_stay_suppressed_until_keyframe_after_congestion() -> None:
    q = FairSendQueue(per_device_max=1, video_per_device_max=1)
    q.put_video_nowait(_packet("A", b"old-frame-1"), "A")
    q.put_video_nowait(_packet("A", b"old-frame-2"), "A")
    idr_requests: list[str] = []
    resyncs: list[str] = []

    enqueue_video_packet(
        q,
        _packet("A", b"dropped-frame"),
        on_drop=lambda: idr_requests.append("request"),
    )
    assert (await q.get()).data == b"old-frame-1"
    assert (await q.get()).data == b"old-frame-2"

    # The queue has capacity again, but this delta depends on the frame that
    # was dropped. It must not be forwarded and must not trigger another IDR.
    enqueue_video_packet(
        q,
        _packet("A", b"undecodable-delta"),
        on_drop=lambda: idr_requests.append("request"),
    )
    assert q.qsize() == 0
    assert idr_requests == ["request"]

    enqueue_video_packet(
        q,
        _packet("A", b"recovery-keyframe", is_key=True),
        on_resync=lambda: resyncs.append("resync"),
    )
    assert (await q.get()).data == b"recovery-keyframe"
    assert resyncs == ["resync"]

    enqueue_video_packet(
        q,
        _packet("A", b"decodable-delta"),
    )
    assert (await q.get()).data == b"decodable-delta"
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 2
    assert stats["suppressed_until_keyframe"] == 1
    assert stats["resyncs"] == 1
    assert stats["awaiting_keyframe"] == 0


@pytest.mark.asyncio
async def test_keyframe_replacement_is_reported_separately_from_drop() -> None:
    q = FairSendQueue(per_device_max=1)
    q.put_video_nowait(_packet("A", b"old-frame-1"), "A")
    q.put_video_nowait(_packet("A", b"old-frame-2"), "A")

    enqueue_video_packet(
        q,
        _packet("A", b"keyframe", is_key=True),
    )

    assert (await q.get()).data == b"old-frame-2"
    assert (await q.get()).data == b"keyframe"
    stats = q.video_stats_snapshot(reset=True)
    assert stats["drops"] == 0
    assert stats["evictions"] == 1
    assert stats["affected_serials"] == 1
    reset_stats = q.video_stats_snapshot()
    assert reset_stats["drops"] == 0
    assert reset_stats["evictions"] == 0
    assert reset_stats["affected_serials"] == 0


@pytest.mark.asyncio
async def test_legacy_bounded_queue_notifies_resync_after_key_replacement() -> None:
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(_packet("A", b"old"))
    resyncs: list[str] = []

    enqueue_video_packet(
        queue,
        _packet("A", b"key", is_key=True),
        on_resync=lambda: resyncs.append("A"),
    )

    assert (await queue.get()).data == b"key"
    assert resyncs == ["A"]


@pytest.mark.asyncio
async def test_120_live_phones_keep_bounded_independent_backlogs() -> None:
    q = FairSendQueue(per_device_max=1, video_per_device_max=2)
    serials = [f"phone-{index:03d}" for index in range(120)]

    for serial in serials:
        q.put_nowait_with_serial(f"result:{serial}", serial)
        q.put_video_nowait(f"frame-1:{serial}", serial)
        q.put_video_nowait(f"frame-2:{serial}", serial)
        enqueue_video_packet(
            q,
            _packet(serial, f"stale:{serial}".encode()),
        )

    # Capacity is bounded to one reliable result + two current video packets
    # per phone; the third delta is dropped independently for every phone.
    assert q.qsize() == 120 * 3
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 120
    assert stats["evictions"] == 0
    assert stats["affected_serials"] == 120
    assert stats["awaiting_keyframe"] == 120

    drained = [await q.get() for _ in range(120 * 3)]
    for serial in serials:
        assert f"result:{serial}" in drained
        assert f"frame-1:{serial}" in drained
        assert f"frame-2:{serial}" in drained


@pytest.mark.asyncio
async def test_120_congested_phones_resume_only_from_decodable_keyframes() -> None:
    q = FairSendQueue(per_device_max=1, video_per_device_max=2)
    serials = [f"phone-{index:03d}" for index in range(120)]
    idr_requests: list[str] = []

    for serial in serials:
        q.put_video_nowait(f"frame-1:{serial}", serial)
        q.put_video_nowait(f"frame-2:{serial}", serial)
        enqueue_video_packet(
            q,
            _packet(serial, f"dropped:{serial}".encode()),
            on_drop=lambda serial=serial: idr_requests.append(serial),
        )

    for _ in range(120 * 2):
        await q.get()

    for serial in serials:
        for index in range(10):
            enqueue_video_packet(
                q,
                _packet(serial, f"suppressed-{index}:{serial}".encode()),
                on_drop=lambda serial=serial: idr_requests.append(serial),
            )
        enqueue_video_packet(
            q,
            _packet(serial, f"key:{serial}".encode(), is_key=True),
        )

    assert q.qsize() == 120
    assert len(idr_requests) == 120
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 120 * 11
    assert stats["suppressed_until_keyframe"] == 120 * 10
    assert stats["resyncs"] == 120
    assert stats["awaiting_keyframe"] == 0
