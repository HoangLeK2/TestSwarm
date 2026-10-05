from __future__ import annotations

import asyncio
import time

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.stream_telemetry import stream_telemetry
from tests.perf_assertions import MemoryTracker, assert_p95, perf_budget


def _make_device(serial: str, loop: asyncio.AbstractEventLoop) -> DeviceClient:
    device = DeviceClient(serial=serial, index=0, config=Config())
    device._loop = loop
    device.screen_width = 360
    device.screen_height = 800
    return device


@pytest.mark.asyncio
async def test_backend_h264_fanout_100_phone_single_viewer_budget() -> None:
    """Synthetic 100-phone backend fanout budget.

    The key property: frame fanout must stay non-blocking even when browser
    queues are already full. This models a weak browser/network reader without
    allowing one phone's queue pressure to block other phones.
    """
    stream_telemetry.reset()
    loop = asyncio.get_running_loop()
    devices = [_make_device(f"SN{i:03d}", loop) for i in range(100)]
    queues: list[asyncio.Queue[bytes]] = []
    for device in devices:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        device.subscribe_frames(q)
        queues.append(q)

    frame_payload = b"\x00\x00\x00\x04data"
    samples_ms: list[float] = []
    total_started = time.perf_counter()
    with MemoryTracker() as memory:
        for frame_idx in range(30):
            is_key = frame_idx % 15 == 0
            for device in devices:
                started = time.perf_counter()
                device.on_agent_h264_video(
                    frame_payload,
                    is_key=is_key,
                    pts_us=frame_idx,
                )
                samples_ms.append((time.perf_counter() - started) * 1000.0)
    total_ms = (time.perf_counter() - total_started) * 1000.0

    assert_p95(
        samples_ms,
        perf_budget("STREAM_FANOUT_100_PHONE_P95_MS", 1.0),
        label="100-phone backend h264 fanout per frame",
    )
    assert total_ms <= perf_budget("STREAM_FANOUT_100_PHONE_TOTAL_MS", 500.0)
    assert memory.peak_mb <= perf_budget("STREAM_FANOUT_100_PHONE_PEAK_MB", 4.0)
    assert all(q.qsize() <= q.maxsize for q in queues)

    snapshot = stream_telemetry.snapshot(reset=True)
    assert snapshot["fanout_frames"] == 3000
    assert snapshot["fanout_no_subscriber"] == 0
    assert snapshot["fanout_max_subscribers"] == 1
    assert snapshot["fanout_p95_ms"] <= perf_budget("STREAM_FANOUT_TELEMETRY_P95_MS", 2.0)
