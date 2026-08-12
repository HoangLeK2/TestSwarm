from __future__ import annotations

import argparse
import asyncio
import json
import time
import tracemalloc

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.stream_telemetry import stream_telemetry


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    pos = max(0.0, min(1.0, p)) * (len(vals) - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= len(vals) - 1:
        return vals[-1]
    return vals[idx] + (vals[idx + 1] - vals[idx]) * frac


def _make_device(serial: str, loop: asyncio.AbstractEventLoop) -> DeviceClient:
    device = DeviceClient(serial=serial, index=0, config=Config())
    device._loop = loop
    device.screen_width = 360
    device.screen_height = 800
    return device


async def _run(phone_count: int, frames_per_phone: int, subscribers_per_phone: int) -> dict:
    stream_telemetry.reset()
    loop = asyncio.get_running_loop()
    devices = [_make_device(f"SN{i:04d}", loop) for i in range(phone_count)]
    queues: list[asyncio.Queue[bytes]] = []
    for device in devices:
        for _ in range(subscribers_per_phone):
            q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
            device.subscribe_frames(q)
            queues.append(q)

    payload = b"\x00\x00\x00\x04data"
    samples_ms: list[float] = []
    tracemalloc.start()
    total_started = time.perf_counter()
    for frame_idx in range(frames_per_phone):
        is_key = frame_idx % 15 == 0
        for device in devices:
            started = time.perf_counter()
            device.on_agent_h264_video(payload, is_key=is_key, pts_us=frame_idx)
            samples_ms.append((time.perf_counter() - started) * 1000.0)
    total_ms = (time.perf_counter() - total_started) * 1000.0
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    telemetry = stream_telemetry.snapshot(reset=True)

    return {
        "phones": phone_count,
        "subscribers_per_phone": subscribers_per_phone,
        "frames_per_phone": frames_per_phone,
        "total_frames": len(samples_ms),
        "p50_ms": round(_percentile(samples_ms, 0.50), 4),
        "p95_ms": round(_percentile(samples_ms, 0.95), 4),
        "p99_ms": round(_percentile(samples_ms, 0.99), 4),
        "max_ms": round(max(samples_ms) if samples_ms else 0.0, 4),
        "total_ms": round(total_ms, 3),
        "peak_mb": round(peak / (1024.0 * 1024.0), 4),
        "queue_max": max((q.qsize() for q in queues), default=0),
        "telemetry": telemetry,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark backend H264 fanout path.")
    parser.add_argument("--phones", type=int, default=100)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--subscribers", type=int, default=1)
    args = parser.parse_args()

    result = asyncio.run(_run(args.phones, args.frames, args.subscribers))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
