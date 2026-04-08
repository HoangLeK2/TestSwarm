"""Tap, swipe, key, text, scroll, open URL."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import (
    ClipboardSetRequest,
    DragRequest,
    DoubleTapRequest,
    InputTextRequest,
    KeyRequest,
    LaunchAppRequest,
    LongTapRequest,
    OpenUrlRequest,
    PinchRequest,
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

    @router.post("/launch_app/{serial}")
    async def api_launch_app(serial: str, body: LaunchAppRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.launch_app, body.package)
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

    @router.post("/devices/{serial}/double_tap")
    async def api_double_tap(serial: str, body: DoubleTapRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.double_tap, body.x, body.y)
        return {"ok": True}

    @router.post("/devices/{serial}/pinch")
    async def api_pinch(serial: str, body: PinchRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: device.pinch(body.cx, body.cy, body.scale, body.duration_ms)
        )
        return {"ok": True}

    @router.post("/devices/{serial}/drag")
    async def api_drag(serial: str, body: DragRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda: device.drag(body.x1, body.y1, body.x2, body.y2, body.duration_ms)
        )
        return {"ok": True}

    @router.post("/devices/{serial}/clipboard")
    async def api_set_clipboard(serial: str, body: ClipboardSetRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, device.set_clipboard, body.text)
        return {"ok": True}

    @router.get("/devices/{serial}/clipboard")
    async def api_get_clipboard(serial: str):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, device.get_clipboard)
        return {"text": text}

    return router
