"""Tap, swipe, key, text, scroll, open URL."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import (
    InputTextRequest,
    KeyRequest,
    LongTapRequest,
    OpenUrlRequest,
    ScrollRequest,
    SwipeRequest,
    TapRequest,
)
from runtime.core import DeviceManager


def build_gestures_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter()

    @router.post("/tap/{serial}")
    async def api_tap(serial: str, body: TapRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.tap, body.x, body.y)
        return {"ok": True}

    @router.post("/swipe/{serial}")
    async def api_swipe(serial: str, body: SwipeRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, device.swipe, body.x1, body.y1, body.x2, body.y2, body.ms
        )
        return {"ok": True}

    @router.post("/key/{serial}")
    async def api_key(serial: str, body: KeyRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.key, body.key)
        return {"ok": True}

    @router.post("/open_url/{serial}")
    async def api_open_url(serial: str, body: OpenUrlRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: device.open_url(body.url, body.package))
        return {"ok": True}

    @router.post("/devices/{serial}/input_text")
    async def api_input_text(serial: str, body: InputTextRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.input_text, body.text)
        return {"ok": True}

    @router.post("/devices/{serial}/long_tap")
    async def api_long_tap(serial: str, body: LongTapRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.long_tap, body.x, body.y, body.duration_ms)
        return {"ok": True}

    @router.post("/devices/{serial}/scroll")
    async def api_scroll(serial: str, body: ScrollRequest):
        if body.direction not in ("up", "down", "left", "right"):
            return JSONResponse({"error": "direction must be up|down|left|right"}, status_code=400)
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.scroll, body.direction, body.distance)
        return {"ok": True}

    return router
