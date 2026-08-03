from __future__ import annotations

from relay.grpc_client import (
    _GRPC_VIDEO_WRITE_WAIT_WARN_MS,
    _GrpcVideoSendStats,
    agent_message_from_item,
    parse_binary_video_frame,
)
from relay.grpc_gen import relay_pb2
from relay.video_packet import VideoPacket


def test_grpc_adapter_accepts_typed_video_packet() -> None:
    packet = VideoPacket(
        serial="phone-A",
        data=b"\x00\x00\x00\x04test",
        is_config=False,
        is_key=True,
        pts_us=123_456,
        width=720,
        height=1280,
    )
    message = agent_message_from_item(packet, relay_pb2)

    assert message is not None
    assert message.video.serial == "phone-A"
    assert message.video.data == packet.data
    assert message.video.is_key is True
    assert message.video.pts_us == 123_456


def test_typed_video_packet_preserves_legacy_websocket_contract() -> None:
    packet = VideoPacket(
        serial="phone-A",
        data=b"\x00\x00\x00\x04test",
        is_config=True,
        is_key=False,
        pts_us=123_456,
        width=720,
        height=1280,
    )

    parsed = parse_binary_video_frame(packet.to_legacy_bytes())

    assert parsed == (
        "phone-A",
        packet.data,
        True,
        False,
        123_456,
        720,
        1280,
    )


def test_grpc_video_stats_tracks_write_wait_backpressure() -> None:
    stats = _GrpcVideoSendStats()

    stats.record_write_wait(_GRPC_VIDEO_WRITE_WAIT_WARN_MS)

    assert stats.write_wait_samples == 1
    assert stats.write_wait_warn == 1
    assert stats.write_wait_max_ms == _GRPC_VIDEO_WRITE_WAIT_WARN_MS
