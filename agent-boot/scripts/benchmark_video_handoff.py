"""Compare legacy video repack/parse with the typed gRPC handoff."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relay.grpc_client import _parse_binary_frame
from relay.grpc_gen import relay_pb2
from relay.video_packet import VideoPacket


def _message_from_typed(packet: VideoPacket):
    return relay_pb2.AgentMsg(
        video=relay_pb2.VideoFrame(
            serial=packet.serial,
            data=packet.data,
            is_config=packet.is_config,
            is_key=packet.is_key,
            pts_us=packet.pts_us,
            width=packet.width if packet.is_config else 0,
            height=packet.height if packet.is_config else 0,
        )
    )


def _message_from_legacy(packet: VideoPacket):
    parsed = _parse_binary_frame(packet.to_legacy_bytes())
    if parsed is None:
        raise RuntimeError("legacy packet parse failed")
    serial, payload, is_config, is_key, pts_us, width, height = parsed
    return relay_pb2.AgentMsg(
        video=relay_pb2.VideoFrame(
            serial=serial,
            data=payload,
            is_config=is_config,
            is_key=is_key,
            pts_us=pts_us,
            width=width if is_config else 0,
            height=height if is_config else 0,
        )
    )


def _measure(
    build: Callable[[VideoPacket], object],
    packet: VideoPacket,
    iterations: int,
) -> float:
    for _ in range(min(100, iterations)):
        build(packet)
    gc.collect()
    started = time.perf_counter()
    checksum = 0
    for _ in range(iterations):
        message = build(packet)
        checksum += len(message.video.data)
    elapsed = time.perf_counter() - started
    if checksum != iterations * len(packet.data):
        raise RuntimeError("benchmark checksum mismatch")
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5_000)
    parser.add_argument("--payload-bytes", type=int, default=50_000)
    args = parser.parse_args()
    iterations = max(1, args.iterations)
    payload_bytes = max(1, args.payload_bytes)
    packet = VideoPacket(
        serial="benchmark-phone",
        data=b"x" * payload_bytes,
        is_config=False,
        is_key=False,
        pts_us=123_456,
    )

    legacy_s = _measure(_message_from_legacy, packet, iterations)
    typed_s = _measure(_message_from_typed, packet, iterations)
    print(
        json.dumps(
            {
                "iterations": iterations,
                "payload_bytes": payload_bytes,
                "legacy_seconds": round(legacy_s, 6),
                "typed_seconds": round(typed_s, 6),
                "speedup": round(legacy_s / typed_s, 2),
                "legacy_messages_per_second": round(iterations / legacy_s),
                "typed_messages_per_second": round(iterations / typed_s),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
