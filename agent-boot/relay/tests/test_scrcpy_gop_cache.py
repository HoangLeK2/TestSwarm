from __future__ import annotations

import asyncio

import pytest

from relay.scrcpy_relay import ScrcpyRelaySession
from relay.video_packet import VideoPacket


class _VideoQueue:
    def __init__(self) -> None:
        self.items: list[VideoPacket] = []

    def offer_video_nowait(
        self,
        item: VideoPacket,
        serial: str,
        *,
        is_config: bool,
        is_key: bool,
        on_drop=None,
    ) -> bool:
        self.items.append(item)
        return False

    def is_video_awaiting_keyframe(self, serial: str) -> bool:
        return False


def _packet(
    label: bytes,
    *,
    is_config: bool = False,
    is_key: bool = False,
) -> VideoPacket:
    return VideoPacket(
        serial="phone-a",
        data=label,
        is_config=is_config,
        is_key=is_key,
        pts_us=len(label),
        width=720 if is_config else 0,
        height=1280 if is_config else 0,
    )


def test_gop_cache_keeps_config_keyframe_and_delta_chain() -> None:
    loop = asyncio.new_event_loop()
    session = ScrcpyRelaySession(
        "phone-a",
        max_fps=12,
        max_width=480,
        enable_control=True,
        port=27183,
        send_queue=asyncio.Queue(),
        loop=loop,
    )
    try:
        session._remember_gop_frame(_packet(b"config", is_config=True))
        session._remember_gop_frame(_packet(b"idr", is_key=True))
        session._remember_gop_frame(_packet(b"p1"))
        session._remember_gop_frame(_packet(b"p2"))

        snapshot = session._cached_gop_snapshot()

        assert [packet.data for packet in snapshot] == [b"config", b"idr", b"p1", b"p2"]
        assert snapshot[0].is_config is True
        assert snapshot[1].is_key is True
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_resume_replays_cached_gop_to_new_queue() -> None:
    loop = asyncio.get_running_loop()
    queue = _VideoQueue()
    session = ScrcpyRelaySession(
        "phone-a",
        max_fps=12,
        max_width=480,
        enable_control=True,
        port=27183,
        send_queue=asyncio.Queue(),
        loop=loop,
    )
    session._remember_gop_frame(_packet(b"config", is_config=True))
    session._remember_gop_frame(_packet(b"idr", is_key=True))
    session._remember_gop_frame(_packet(b"p1"))

    session.pause_forwarding(reason="idle")
    session.resume_forwarding(send_queue=queue, loop=loop, reason="test")
    await asyncio.sleep(0)

    assert [packet.data for packet in queue.items] == [b"config", b"idr", b"p1"]
    assert session.forwarding_enabled is True
    assert session.stats_snapshot(reset=True)["gop_replay_packets"] == 3


def test_start_and_first_frame_latency_metrics_are_windowed() -> None:
    loop = asyncio.new_event_loop()
    session = ScrcpyRelaySession(
        "phone-a",
        max_fps=12,
        max_width=480,
        enable_control=True,
        port=27183,
        send_queue=asyncio.Queue(),
        loop=loop,
    )
    try:
        with session._stats_lock:
            session._stats_start_requested_at = 100.000

        session._record_stream_handshake_latency(
            now=100.050,
            connect_started=100.010,
        )
        session._record_first_frame_latency(
            now=100.090,
            connect_started=100.010,
        )

        stats = session.stats_snapshot(reset=True, now=100.100)

        assert stats["connect_to_handshake_p95_ms"] == 40
        assert stats["connect_to_first_frame_p95_ms"] == 80
        assert stats["start_to_handshake_p95_ms"] == 50
        assert stats["start_to_first_frame_p95_ms"] == 90

        reset_stats = session.stats_snapshot(reset=True, now=100.200)

        assert reset_stats["connect_to_handshake_p95_ms"] == 0
        assert reset_stats["connect_to_first_frame_p95_ms"] == 0
    finally:
        loop.close()
