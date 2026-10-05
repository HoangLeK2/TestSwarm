from __future__ import annotations

import asyncio
import atexit
import base64
import functools
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.core import DeviceManager

log = logging.getLogger(__name__)


def _screenshot_capture_workers() -> int:
    try:
        return max(
            1,
            min(
                8,
                int(os.environ.get("DEVICE_FARM_SCREENSHOT_CAPTURE_WORKERS", "4")),
            ),
        )
    except Exception:
        return 4


_SCREENSHOT_CAPTURE_POOL = ThreadPoolExecutor(
    max_workers=_screenshot_capture_workers(),
    thread_name_prefix="screenshot-capture",
)
atexit.register(
    _SCREENSHOT_CAPTURE_POOL.shutdown,
    wait=False,
    cancel_futures=True,
)


def _frame_age_ms(device) -> float:
    last_frame_time = float(
        getattr(device, "_last_jpeg_frame_time", 0.0) or 0.0
    )
    if last_frame_time <= 0.0:
        return float("inf")
    return max(0.0, (time.monotonic() - last_frame_time) * 1000.0)


def _store_snapshot_frame(device, frame: bytes) -> None:
    lock = getattr(device, "_latest_jpeg_lock", None)
    if lock is None:
        return
    with lock:
        device._latest_jpeg = frame
        now = time.monotonic()
        device._last_frame_time = now
        device._last_jpeg_frame_time = now


def _resize_snapshot_frame(frame: bytes, max_width: int) -> bytes:
    from PIL import Image
    import io

    with Image.open(io.BytesIO(frame)) as image:
        if image.width <= max_width:
            return frame
        height = max(1, round(image.height * max_width / image.width))
        resized = image.resize((max_width, height), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        resized.save(output, format="JPEG", quality=65)
        return output.getvalue()


def _request_stream_jpeg_frames(device, duration_s: float = 3.0) -> bool:
    request = getattr(device, "request_stream_jpeg_frames", None)
    if request is not None:
        return bool(request(duration_s=duration_s))
    return False


def _screenshot_capture_timeout_s() -> float:
    try:
        return max(
            0.05,
            float(os.environ.get("DEVICE_FARM_SCREENSHOT_CAPTURE_TIMEOUT_S", "2.0")),
        )
    except Exception:
        return 2.0


async def _wait_for_new_jpeg(
    device,
    previous_jpeg_time: float,
    *,
    timeout_s: float = 0.45,
) -> bytes | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        await asyncio.sleep(0.02)
        jpeg_time = float(
            getattr(device, "_last_jpeg_frame_time", 0.0) or 0.0
        )
        if jpeg_time <= previous_jpeg_time:
            continue
        try:
            return device.take_screenshot()
        except Exception:
            return None
    return None


async def _capture_screenshot_bounded(device, serial: str, **kwargs) -> bytes | None:
    loop = asyncio.get_running_loop()
    capture_future = loop.run_in_executor(
        _SCREENSHOT_CAPTURE_POOL,
        functools.partial(device.capture_screenshot, **kwargs),
    )
    timeout_s = _screenshot_capture_timeout_s()
    try:
        return await asyncio.wait_for(capture_future, timeout=timeout_s)
    except asyncio.TimeoutError:
        log.warning(
            "screenshot fresh capture timed out for %s after %.2fs",
            serial,
            timeout_s,
        )
        return None


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
            while True:
                _request_stream_jpeg_frames(
                    device,
                    duration_s=max(3.0, interval * 2),
                )
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
                        frame = await _capture_screenshot_bounded(
                            device,
                            serial,
                            quality=70,
                            max_width=800,
                            allow_ws_u2_fallback=False,
                            skip_cache=fresh,
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
        max_width: int | None = None,
    ):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Not found"}, status_code=404)
        previous_jpeg_time = float(
            getattr(device, "_last_jpeg_frame_time", 0.0) or 0.0
        )
        jpeg_demand_active = _request_stream_jpeg_frames(device)
        frame = None
        try:
            frame = None if fresh else device.take_screenshot()
        except Exception as exc:
            log.debug("screenshot cache read failed for %s: %s", serial, exc)

        stale = fresh or frame is None
        effective_max_age_ms = (
            max_age_ms
            if max_age_ms is not None
            else (3_000 if jpeg_demand_active else None)
        )
        if effective_max_age_ms is not None:
            max_age = max(250, min(int(effective_max_age_ms), 10_000))
            stale = stale or _frame_age_ms(device) >= max_age

        if stale:
            if jpeg_demand_active:
                frame = await _wait_for_new_jpeg(device, previous_jpeg_time)
                stale = frame is None
        if stale:
            fresh_frame = await _capture_screenshot_bounded(
                device,
                serial,
                quality=70,
                max_width=800,
                allow_ws_u2_fallback=False,
                skip_cache=True,
            )
            if fresh_frame:
                frame = fresh_frame
                _store_snapshot_frame(device, fresh_frame)
        if not frame:
            return JSONResponse({"error": "No frame available"}, status_code=503)
        if max_width is not None:
            preview_width = max(160, min(int(max_width), 800))
            loop = asyncio.get_running_loop()
            frame = await loop.run_in_executor(
                None, _resize_snapshot_frame, frame, preview_width
            )
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

        previous_jpeg_time = float(
            getattr(device, "_last_jpeg_frame_time", 0.0) or 0.0
        )
        jpeg_demand_active = _request_stream_jpeg_frames(device)
        frame = device.take_screenshot()
        if jpeg_demand_active and _frame_age_ms(device) >= 3_000:
            frame = await _wait_for_new_jpeg(device, previous_jpeg_time)
        if not frame:
            frame = await _capture_screenshot_bounded(
                device,
                serial,
                allow_ws_u2_fallback=False,
                skip_cache=jpeg_demand_active,
            )
            if frame:
                _store_snapshot_frame(device, frame)
        if not frame:
            return JSONResponse({"error": "No frame available"}, status_code=503)

        return JSONResponse({
            "screenshot": base64.b64encode(frame).decode("ascii"),
            "width": device.screen_width or 0,
            "height": device.screen_height or 0,
        })

    return router
