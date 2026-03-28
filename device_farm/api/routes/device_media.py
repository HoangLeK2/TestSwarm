from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.core import DeviceManager


def build_device_media_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter()
    low_bw_mode = os.environ.get("LOW_BW_MODE", "").lower() in {"1", "true", "yes"}

    @router.get("/stream/{serial}")
    async def mjpeg_stream(serial: str, fps: float = 0):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Not found"}, status_code=404)

        async def _gen():
            if fps > 0:
                interval = 1.0 / max(0.1, min(fps, 30))
            else:
                interval = 1.0 if low_bw_mode else 0.033
            while True:
                frame = device.take_screenshot()
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

    @router.get("/screenshot/{serial}")
    async def screenshot(serial: str, fresh: bool = False):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if fresh:
            # Trigger on-demand capture (u2 → adb screencap → cache fallback)
            frame = device.capture_screenshot()
        else:
            frame = device.take_screenshot()
        if not frame:
            return JSONResponse({"error": "No frame available"}, status_code=503)
        return StreamingResponse(
            iter([frame]),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    return router
