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
    assert q.video_stats_snapshot() == {
        "drops": 1,
        "evictions": 0,
        "affected_serials": 1,
    }


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
    assert q.video_stats_snapshot(reset=True) == {
        "drops": 0,
        "evictions": 1,
        "affected_serials": 1,
    }
    assert q.video_stats_snapshot() == {
        "drops": 0,
        "evictions": 0,
        "affected_serials": 0,
    }


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
    assert q.video_stats_snapshot() == {
        "drops": 120,
        "evictions": 0,
        "affected_serials": 120,
    }

    drained = [await q.get() for _ in range(120 * 3)]
    for serial in serials:
        assert f"result:{serial}" in drained
        assert f"frame-1:{serial}" in drained
        assert f"frame-2:{serial}" in drained
