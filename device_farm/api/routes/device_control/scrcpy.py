"""Scrcpy attach/detach."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import ScrcpyAttachRequest
from runtime.core import DeviceManager


def build_scrcpy_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter()

    @router.post("/devices/{serial}/scrcpy/attach")
    async def api_scrcpy_attach(serial: str, body: ScrcpyAttachRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, device.attach_scrcpy_stream, body.device_ip, body.adb_port
        )
        return {"ok": True, "serial": serial, "scrcpy": f"{body.device_ip}:{body.adb_port}"}

    @router.post("/devices/{serial}/scrcpy/detach")
    async def api_scrcpy_detach(serial: str):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)
        device.detach_scrcpy_stream()
        return {"ok": True, "serial": serial}

    return router
