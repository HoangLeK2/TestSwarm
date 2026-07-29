from __future__ import annotations

import pytest

from relay.runtime import FairSendQueue
from relay.scrcpy_relay import _relay_enqueue


@pytest.mark.asyncio
async def test_keyframe_eviction_never_discards_reliable_result() -> None:
    q = FairSendQueue(per_device_max=1)
    q.put_nowait_with_serial("result-1", "A")
    q.put_video_nowait("old-frame", "A")

    _relay_enqueue(
        q,
        b"keyframe",
        is_cfg=False,
        is_key=True,
        serial="A",
    )

    # A full video lane may evict an old frame, but it must never touch the
    # result lane for the same phone.
    assert await q.get() == "result-1"
    assert await q.get() == b"keyframe"


@pytest.mark.asyncio
async def test_p_frame_drop_requests_idr_without_touching_result() -> None:
    q = FairSendQueue(per_device_max=1)
    q.put_nowait_with_serial("result-1", "A")
    q.put_video_nowait("old-frame", "A")
    drops: list[str] = []

    _relay_enqueue(
        q,
        b"p-frame",
        is_cfg=False,
        is_key=False,
        on_p_drop=lambda: drops.append("drop"),
        serial="A",
    )

    assert drops == ["drop"]
    assert await q.get() == "result-1"
    assert await q.get() == "old-frame"
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 1
    assert stats["evictions"] == 0
    assert stats["affected_serials"] == 1
    assert stats["awaiting_keyframe"] == 1


@pytest.mark.asyncio
async def test_delta_frames_stay_suppressed_until_keyframe_after_congestion() -> None:
    q = FairSendQueue(per_device_max=1, video_per_device_max=1)
    q.put_video_nowait(b"old-frame", "A")
    idr_requests: list[str] = []

    _relay_enqueue(
        q,
        b"dropped-frame",
        is_cfg=False,
        is_key=False,
        on_p_drop=lambda: idr_requests.append("request"),
        serial="A",
    )
    assert await q.get() == b"old-frame"

    # The queue has capacity again, but this delta depends on the frame that
    # was dropped. It must not be forwarded and must not trigger another IDR.
    _relay_enqueue(
        q,
        b"undecodable-delta",
        is_cfg=False,
        is_key=False,
        on_p_drop=lambda: idr_requests.append("request"),
        serial="A",
    )
    assert q.qsize() == 0
    assert idr_requests == ["request"]

    _relay_enqueue(
        q,
        b"recovery-keyframe",
        is_cfg=False,
        is_key=True,
        serial="A",
    )
    assert await q.get() == b"recovery-keyframe"

    _relay_enqueue(
        q,
        b"decodable-delta",
        is_cfg=False,
        is_key=False,
        serial="A",
    )
    assert await q.get() == b"decodable-delta"
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 2
    assert stats["suppressed_until_keyframe"] == 1
    assert stats["resyncs"] == 1
    assert stats["awaiting_keyframe"] == 0


@pytest.mark.asyncio
async def test_keyframe_replacement_is_reported_separately_from_drop() -> None:
    q = FairSendQueue(per_device_max=1)
    q.put_video_nowait("old-frame", "A")

    _relay_enqueue(
        q,
        b"keyframe",
        is_cfg=False,
        is_key=True,
        serial="A",
    )

    assert await q.get() == b"keyframe"
    stats = q.video_stats_snapshot(reset=True)
    assert stats["drops"] == 0
    assert stats["evictions"] == 1
    assert stats["affected_serials"] == 1
    reset_stats = q.video_stats_snapshot()
    assert reset_stats["drops"] == 0
    assert reset_stats["evictions"] == 0
    assert reset_stats["affected_serials"] == 0


@pytest.mark.asyncio
async def test_120_live_phones_keep_bounded_independent_backlogs() -> None:
    q = FairSendQueue(per_device_max=1, video_per_device_max=2)
    serials = [f"phone-{index:03d}" for index in range(120)]

    for serial in serials:
        q.put_nowait_with_serial(f"result:{serial}", serial)
        q.put_video_nowait(f"frame-1:{serial}", serial)
        q.put_video_nowait(f"frame-2:{serial}", serial)
        _relay_enqueue(
            q,
            f"stale:{serial}".encode(),
            is_cfg=False,
            is_key=False,
            serial=serial,
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
        _relay_enqueue(
            q,
            f"dropped:{serial}".encode(),
            is_cfg=False,
            is_key=False,
            on_p_drop=lambda serial=serial: idr_requests.append(serial),
            serial=serial,
        )

    for _ in range(120 * 2):
        await q.get()

    for serial in serials:
        for index in range(10):
            _relay_enqueue(
                q,
                f"suppressed-{index}:{serial}".encode(),
                is_cfg=False,
                is_key=False,
                on_p_drop=lambda serial=serial: idr_requests.append(serial),
                serial=serial,
            )
        _relay_enqueue(
            q,
            f"key:{serial}".encode(),
            is_cfg=False,
            is_key=True,
            serial=serial,
        )

    assert q.qsize() == 120
    assert len(idr_requests) == 120
    stats = q.video_stats_snapshot()
    assert stats["drops"] == 120 * 11
    assert stats["suppressed_until_keyframe"] == 120 * 10
    assert stats["resyncs"] == 120
    assert stats["awaiting_keyframe"] == 0
