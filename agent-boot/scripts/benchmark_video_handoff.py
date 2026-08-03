"""Compare legacy video repack/parse with the typed gRPC handoff."""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relay.grpc_client import agent_message_from_item, parse_binary_video_frame
from relay.grpc_gen import relay_pb2
from relay.runtime import FairSendQueue
from relay.scrcpy_relay import (
    enqueue_video_packet,
    prepare_video_packet,
)
from relay.video_packet import VideoPacket


def _message_from_typed(packet: VideoPacket):
    message = agent_message_from_item(packet, relay_pb2)
    if message is None:
        raise RuntimeError("typed packet adaptation failed")
    return message


def _message_from_legacy(packet: VideoPacket):
    parsed = parse_binary_video_frame(packet.to_legacy_bytes())
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


async def _measure_synthetic_fleet(
    *,
    phones: int,
    frames_per_phone: int,
    payload_bytes: int,
    consumer_delay_ms: float,
    producer_fps: float,
    gop_seconds: float,
) -> dict[str, int | float | str]:
    """Exercise production conversion, callbacks, lanes, and protobuf encoding."""
    loop = asyncio.get_running_loop()
    queue = FairSendQueue(per_device_max=1, video_per_device_max=2)
    producers_done = asyncio.Event()
    remaining = phones
    max_qsize = 0
    payload = b"x" * payload_bytes
    recovery = {
        f"phone-{index:03d}": threading.Event()
        for index in range(phones)
    }
    producer_suppressed = 0
    scheduled = 0
    protobuf_bytes = 0
    counter_lock = threading.Lock()

    def enqueue(packet: VideoPacket) -> None:
        nonlocal max_qsize
        enqueue_video_packet(
            queue,
            packet,
            recovery[packet.serial].set,
            recovery[packet.serial].clear,
        )
        max_qsize = max(max_qsize, queue.qsize())

    def producer_done() -> None:
        nonlocal remaining
        remaining -= 1
        if remaining == 0:
            producers_done.set()

    def produce(serial: str) -> None:
        nonlocal producer_suppressed, scheduled
        frame_interval_s = 1 / producer_fps if producer_fps > 0 else 0.0
        cadence_fps = producer_fps if producer_fps > 0 else 30.0
        gop_frames = max(1, round(cadence_fps * gop_seconds))
        for index in range(frames_per_phone):
            frame_started = time.perf_counter()
            is_config = index == 0
            nal_type = (
                0x65
                if not is_config and (index - 1) % gop_frames == 0
                else 0x61
            )
            annexb = b"\x00\x00\x00\x01" + bytes([nal_type]) + payload
            received_ns = time.monotonic_ns()
            packet = prepare_video_packet(
                serial=serial,
                annexb=annexb,
                is_config=is_config,
                pts_us=index,
                received_ns=received_ns,
                suppress_deltas=recovery[serial].is_set(),
            )
            if packet is None:
                with counter_lock:
                    producer_suppressed += 1
                if frame_interval_s:
                    time.sleep(
                        max(
                            0.0,
                            frame_interval_s
                            - (time.perf_counter() - frame_started),
                        )
                    )
                continue
            loop.call_soon_threadsafe(enqueue, packet)
            with counter_lock:
                scheduled += 1
            if frame_interval_s:
                time.sleep(
                    max(
                        0.0,
                        frame_interval_s
                        - (time.perf_counter() - frame_started),
                    )
                )
        loop.call_soon_threadsafe(producer_done)

    threads = [
        threading.Thread(
            target=produce,
            args=(f"phone-{index:03d}",),
            daemon=True,
        )
        for index in range(phones)
    ]
    started = time.perf_counter()
    for thread in threads:
        thread.start()

    drained = 0
    delay_s = max(0.0, consumer_delay_ms / 1_000)
    while not producers_done.is_set() or queue.qsize() > 0:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1)
        except TimeoutError:
            continue
        message = agent_message_from_item(item, relay_pb2)
        if message is None:
            raise RuntimeError("synthetic packet adaptation failed")
        protobuf_bytes += len(message.SerializeToString())
        drained += 1
        if delay_s:
            await asyncio.sleep(delay_s)

    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    stats = queue.video_stats_snapshot()
    generated = phones * frames_per_phone
    return {
        "kind": "synthetic_fleet_handoff",
        "phones": phones,
        "frames_per_phone": frames_per_phone,
        "generated": generated,
        "scheduled": scheduled,
        "producer_suppressed": producer_suppressed,
        "protobuf_bytes": protobuf_bytes,
        "drained": drained,
        "seconds": round(elapsed, 6),
        "generated_per_second": round(generated / elapsed),
        "scheduled_per_second": round(scheduled / elapsed),
        "max_qsize": max_qsize,
        "queue_age_p95_ms": stats["queue_age_p95_ms"],
        "handoff_age_p95_ms": stats["handoff_age_p95_ms"],
        "drops": stats["drops"],
        "suppressed_until_keyframe": stats["suppressed_until_keyframe"],
        "resyncs": stats["resyncs"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5_000)
    parser.add_argument("--payload-bytes", type=int, default=50_000)
    parser.add_argument("--phones", type=int, default=0)
    parser.add_argument("--frames-per-phone", type=int, default=120)
    parser.add_argument("--consumer-delay-ms", type=float, default=0.0)
    parser.add_argument("--producer-fps", type=float, default=0.0)
    parser.add_argument("--gop-seconds", type=float, default=1.0)
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
    result: dict[str, object] = {
        "kind": "serialization_microbenchmark",
        "iterations": iterations,
        "payload_bytes": payload_bytes,
        "legacy_seconds": round(legacy_s, 6),
        "typed_seconds": round(typed_s, 6),
        "speedup": round(legacy_s / typed_s, 2),
        "legacy_messages_per_second": round(iterations / legacy_s),
        "typed_messages_per_second": round(iterations / typed_s),
    }
    if args.phones > 0:
        result["fleet"] = asyncio.run(
            _measure_synthetic_fleet(
                phones=args.phones,
                frames_per_phone=max(2, args.frames_per_phone),
                payload_bytes=payload_bytes,
                consumer_delay_ms=args.consumer_delay_ms,
                producer_fps=max(0.0, args.producer_fps),
                gop_seconds=max(0.1, args.gop_seconds),
            )
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
