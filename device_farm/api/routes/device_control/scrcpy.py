"""Scrcpy attach/detach — supports WiFi (IP from DB) and USB ADB."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import ScrcpyAttachRequest
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager

log = logging.getLogger(__name__)


def build_scrcpy_router(manager: DeviceManager, *, db_enabled: bool) -> APIRouter:
    router = APIRouter()

    @router.post("/devices/{serial}/scrcpy/attach")
    async def api_scrcpy_attach(serial: str, body: ScrcpyAttachRequest):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        device_ip = body.device_ip
        adb_port = body.adb_port

        if not device_ip:
            device_ip = await _resolve_device_ip(serial)
            if not device_ip:
                return JSONResponse(
                    {"error": "device_ip not provided and not found in DB. "
                     "Device must connect via QR scan or provide IP explicitly."},
                    status_code=400,
                )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, device.attach_scrcpy_stream, device_ip, adb_port, body.enable_control
        )
        if db_enabled:
            try:
                async with AsyncSessionLocal() as db:
                    await repo.set_relay_scrcpy_enabled(db, serial, True)
            except Exception as exc:
                log.warning("persist relay_scrcpy_enabled=True for %s: %s", serial, exc)
        return {
            "ok": True,
            "serial": serial,
            "scrcpy": f"{device_ip}:{adb_port}",
            "control": body.enable_control,
        }

    @router.post("/devices/{serial}/scrcpy/detach")
    async def api_scrcpy_detach(serial: str):
        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)
        device.detach_scrcpy_stream()
        if db_enabled:
            try:
                async with AsyncSessionLocal() as db:
                    await repo.set_relay_scrcpy_enabled(db, serial, False)
            except Exception as exc:
                log.warning("persist relay_scrcpy_enabled=False for %s: %s", serial, exc)
        return {"ok": True, "serial": serial}

    return router


async def _resolve_device_ip(serial: str) -> str | None:
    """Look up device IP from database (saved when agent connected via WS or ADB register)."""
    try:
        from db.database import AsyncSessionLocal
        from db.models.device import Device
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Device.adb_ip, Device.adb_port)
                .where(Device.serial == serial)
            )
            row = result.first()
            if row and row.adb_ip:
                return row.adb_ip
    except Exception as exc:
        log.warning("Failed to resolve device IP from DB: %s", exc)
    return None
