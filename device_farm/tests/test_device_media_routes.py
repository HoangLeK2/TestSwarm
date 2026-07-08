from __future__ import annotations

import threading
import time

import pytest

from api.routes.device_media import build_device_media_router


class _Manager:
    def __init__(self, device):
        self.device = device

    def get_device(self, serial: str):
        return self.device if serial == "serial-1" else None


class _FlakyStreamDevice:
    screen_width = 1080
    screen_height = 1920

    def __init__(self) -> None:
        self.cache_reads = 0
        self.captures = 0

    def take_screenshot(self):
        self.cache_reads += 1
        raise RuntimeError("cache unavailable")

    def capture_screenshot(self, **_kwargs):
        self.captures += 1
        return b"jpeg-frame"


class _SnapshotDevice:
    def __init__(self, cached: bytes = b"old-frame") -> None:
        self._latest_jpeg = cached
        self._latest_jpeg_lock = threading.Lock()
        self._last_frame_time = time.monotonic()
        self.captures = 0

    def take_screenshot(self):
        with self._latest_jpeg_lock:
            return self._latest_jpeg

    def capture_screenshot(self, **_kwargs):
        self.captures += 1
        return b"fresh-frame"


@pytest.mark.anyio
async def test_mjpeg_stream_survives_transient_frame_source_error():
    router = build_device_media_router(_Manager(_FlakyStreamDevice()))
    route = next(r for r in router.routes if getattr(r, "path", "") == "/stream/{serial}")

    response = await route.endpoint("serial-1", fps=5, fresh=False)
    chunk = await anext(response.body_iterator)

    assert response.status_code == 200
    assert b"Content-Type: image/jpeg" in chunk
    assert b"jpeg-frame" in chunk


@pytest.mark.anyio
async def test_screenshot_uses_cached_frame_when_fresh_enough():
    device = _SnapshotDevice()
    router = build_device_media_router(_Manager(device))
    route = next(r for r in router.routes if getattr(r, "path", "") == "/screenshot/{serial}")

    response = await route.endpoint("serial-1", fresh=False, max_age_ms=5_000)
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert response.status_code == 200
    assert body == b"old-frame"
    assert device.captures == 0


@pytest.mark.anyio
async def test_screenshot_refreshes_stale_cache_once():
    device = _SnapshotDevice()
    device._last_frame_time = time.monotonic() - 10
    router = build_device_media_router(_Manager(device))
    route = next(r for r in router.routes if getattr(r, "path", "") == "/screenshot/{serial}")

    response = await route.endpoint("serial-1", fresh=False, max_age_ms=500)
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert response.status_code == 200
    assert body == b"fresh-frame"
    assert device.captures == 1
    assert device.take_screenshot() == b"fresh-frame"
