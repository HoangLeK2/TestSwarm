from __future__ import annotations

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


@pytest.mark.anyio
async def test_mjpeg_stream_survives_transient_frame_source_error():
    router = build_device_media_router(_Manager(_FlakyStreamDevice()))
    route = next(r for r in router.routes if getattr(r, "path", "") == "/stream/{serial}")

    response = await route.endpoint("serial-1", fps=5, fresh=False)
    chunk = await anext(response.body_iterator)

    assert response.status_code == 200
    assert b"Content-Type: image/jpeg" in chunk
    assert b"jpeg-frame" in chunk
