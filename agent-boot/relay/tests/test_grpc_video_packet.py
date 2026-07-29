from __future__ import annotations

import asyncio

import pytest

from relay.grpc_client import GrpcRelayClient, _parse_binary_frame
from relay.grpc_gen import relay_pb2
from relay.runtime import FairSendQueue
from relay.video_packet import VideoPacket


@pytest.mark.asyncio
async def test_grpc_generator_accepts_typed_video_without_legacy_repack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = FairSendQueue(video_per_device_max=2)
    packet = VideoPacket(
        serial="phone-A",
        data=b"\x00\x00\x00\x04test",
        is_config=False,
        is_key=True,
        pts_us=123_456,
        width=720,
        height=1280,
    )
    queue.put_video_nowait(packet, packet.serial)

    def fail_legacy_parse(_data: bytes):
        raise AssertionError("typed gRPC video must not parse a legacy binary envelope")

    monkeypatch.setattr("relay.grpc_client._parse_binary_frame", fail_legacy_parse)
    client = GrpcRelayClient(
        server_addr="unused",
        api_key=None,
        agent_id="agent-A",
        send_queue=queue,
        loop=asyncio.get_running_loop(),
    )
    client._running = True

    message = await anext(client._frame_generator(relay_pb2))

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

    parsed = _parse_binary_frame(packet.to_legacy_bytes())

    assert parsed == (
        "phone-A",
        packet.data,
        True,
        False,
        123_456,
        720,
        1280,
    )
