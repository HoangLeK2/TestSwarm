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
_SCRCPY_OP_LOCKS: dict[str, asyncio.Lock] = {}


def _scrcpy_op_lock(serial: str) -> asyncio.Lock:
    lock = _SCRCPY_OP_LOCKS.get(serial)
    if lock is None:
        lock = asyncio.Lock()
        _SCRCPY_OP_LOCKS[serial] = lock
    return lock


def build_scrcpy_router(manager: DeviceManager, *, db_enabled: bool) -> APIRouter:
    router = APIRouter()

    @router.post("/devices/{serial}/scrcpy/attach")
    async def api_scrcpy_attach(serial: str, body: ScrcpyAttachRequest):
        lock = _scrcpy_op_lock(serial)
        if lock.locked():
            return {"ok": True, "serial": serial, "coalesced": True}

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

        async with lock:
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
        lock = _scrcpy_op_lock(serial)
        if lock.locked():
            return {"ok": True, "serial": serial, "coalesced": True}

        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)
        async with lock:
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
    """Resolve scrcpy attach target: relay ADB serial first, then trusted LAN IP from DB/caps."""
    from core.net_utils import is_trusted_device_lan_ip

    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        relay = get_relay_manager()
        if relay is not None:
            resolved = relay.resolve_serial(serial)
            if relay.relay_for_serial(resolved):
                return resolved
            caps = relay.get_capabilities(resolved) or relay.get_capabilities(serial) or {}
            wlan = str(caps.get("wlan_ip") or "").strip()
            if wlan and is_trusted_device_lan_ip(wlan):
                return wlan
    except Exception as exc:
        log.debug("relay scrcpy target lookup skipped for %s: %s", serial, exc)

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
                adb_ip = str(row.adb_ip).strip()
                if is_trusted_device_lan_ip(adb_ip):
                    return adb_ip
                log.info(
                    "Ignoring stale adb_ip=%s for %s (Docker/untrusted); use relay serial",
                    adb_ip,
                    serial,
                )
    except Exception as exc:
        log.warning("Failed to resolve device IP from DB: %s", exc)
    return None
