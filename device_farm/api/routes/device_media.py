from __future__ import annotations

import asyncio
import base64
import functools
import logging
import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.core import DeviceManager

log = logging.getLogger(__name__)


def _frame_age_ms(device) -> float:
    last_frame_time = float(getattr(device, "_last_frame_time", 0.0) or 0.0)
    if last_frame_time <= 0.0:
        return float("inf")
    return max(0.0, (time.monotonic() - last_frame_time) * 1000.0)


def _store_snapshot_frame(device, frame: bytes) -> None:
    lock = getattr(device, "_latest_jpeg_lock", None)
    if lock is None:
        return
    with lock:
        device._latest_jpeg = frame
        device._last_frame_time = time.monotonic()


def build_device_media_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter()
    low_bw_mode = os.environ.get("LOW_BW_MODE", "").lower() in {"1", "true", "yes"}

    @router.get("/api/stream/{serial}")
    async def mjpeg_stream(serial: str, fps: float = 0, fresh: bool = False):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Not found"}, status_code=404)

        async def _gen():
            if fps > 0:
                interval = 1.0 / max(0.1, min(fps, 30))
            else:
                interval = 1.0 if low_bw_mode else 0.033
            loop = asyncio.get_running_loop()
            while True:
                # Normal mode uses cached scrcpy frame (fast path). Stall fallback
                # can opt into fresh screencap at low FPS so the UI has a way out
                # when the H264/cache path is frozen.
                frame = None
                if not fresh:
                    try:
                        frame = device.take_screenshot()
                    except Exception as exc:
                        log.debug("mjpeg stream cache read failed for %s: %s", serial, exc)
                if not frame:
                    try:
                        frame = await loop.run_in_executor(
                            None,
                            functools.partial(
                                device.capture_screenshot,
                                quality=70,
                                max_width=800,
                                allow_ws_u2_fallback=False,
                                skip_cache=fresh,
                            ),
                        )
                    except Exception as exc:
                        log.debug("mjpeg stream capture failed for %s: %s", serial, exc)
                if frame:
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                await asyncio.sleep(interval)

        return StreamingResponse(
            _gen(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @router.get("/api/screenshot/{serial}")
    async def screenshot(
        serial: str,
        fresh: bool = False,
        max_age_ms: int | None = None,
    ):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Not found"}, status_code=404)
        frame = None
        try:
            frame = None if fresh else device.take_screenshot()
        except Exception as exc:
            log.debug("screenshot cache read failed for %s: %s", serial, exc)

        stale = fresh or frame is None
        if max_age_ms is not None:
            max_age = max(250, min(int(max_age_ms), 10_000))
            stale = stale or _frame_age_ms(device) >= max_age

        if stale:
            loop = asyncio.get_running_loop()
            fresh_frame = await loop.run_in_executor(
                None,
                functools.partial(
                    device.capture_screenshot,
                    quality=70,
                    max_width=800,
                    allow_ws_u2_fallback=False,
                    skip_cache=True,
                ),
            )
            if fresh_frame:
                frame = fresh_frame
                _store_snapshot_frame(device, fresh_frame)
        if not frame:
            return JSONResponse({"error": "No frame available"}, status_code=503)
        return StreamingResponse(
            iter([frame]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/screenshot-b64/{serial}")
    async def screenshot_b64(serial: str):
        """Screenshot as base64 JPEG. Cropping is done client-side."""
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Not found"}, status_code=404)

        frame = device.take_screenshot()
        if not frame:
            frame = device.capture_screenshot(allow_ws_u2_fallback=False)
        if not frame:
            return JSONResponse({"error": "No frame available"}, status_code=503)

        return JSONResponse({
            "screenshot": base64.b64encode(frame).decode("ascii"),
            "width": device.screen_width or 0,
            "height": device.screen_height or 0,
        })

    return router
