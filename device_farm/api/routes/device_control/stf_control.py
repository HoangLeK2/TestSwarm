"""STFService device control routes: clipboard, wifi, bluetooth, ringer, keyguard, etc."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from runtime.core import DeviceManager


class SetClipboardRequest(BaseModel):
    text: str

class SetEnabledRequest(BaseModel):
    enabled: bool

class SetRingerModeRequest(BaseModel):
    mode: str  # silent, vibrate, normal


def _get_device(manager: DeviceManager, serial: str):
    device = manager.get_device(serial)
    if not device:
        return None, JSONResponse({"error": f"Device {serial} not found"}, status_code=404)
    return device, None


def build_stf_control_router(manager: DeviceManager) -> APIRouter:
    router = APIRouter(prefix="/stf", tags=["stf-control"])

    @router.get("/status/{serial}")
    async def stf_status(serial: str):
        """Get STFService connection status and all event state."""
        device, err = _get_device(manager, serial)
        if err:
            return err
        svc = device._stf_service
        if not svc or not svc.connected:
            return JSONResponse({"error": "STFService not connected"}, status_code=503)
        bat = svc.get_battery_info()
        conn = svc.get_connectivity()
        phone = svc.get_phone_state()
        return {
            "connected": True,
            "battery": {
                "level": bat.level, "status": bat.status, "health": bat.health,
                "source": bat.source, "temp": bat.temp, "voltage": bat.voltage,
            },
            "rotation": svc.get_rotation(),
            "connectivity": {
                "connected": conn.connected, "type": conn.type,
                "subtype": conn.subtype, "roaming": conn.roaming,
            },
            "airplane_mode": svc.get_airplane_mode(),
            "phone_state": {
                "state": phone.state, "operator": phone.operator,
            },
        }

    @router.get("/clipboard/{serial}")
    async def stf_get_clipboard(serial: str):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, device.stf_get_clipboard)
        if text is None:
            return JSONResponse({"error": "STFService not connected"}, status_code=503)
        return {"text": text}

    @router.post("/clipboard/{serial}")
    async def stf_set_clipboard(serial: str, body: SetClipboardRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_clipboard, body.text)
        return {"ok": ok}

    @router.post("/wifi/{serial}")
    async def stf_set_wifi(serial: str, body: SetEnabledRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_wifi, body.enabled)
        return {"ok": ok}

    @router.post("/bluetooth/{serial}")
    async def stf_set_bluetooth(serial: str, body: SetEnabledRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_bluetooth, body.enabled)
        return {"ok": ok}

    @router.post("/keyguard/{serial}")
    async def stf_set_keyguard(serial: str, body: SetEnabledRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_keyguard, body.enabled)
        return {"ok": ok}

    @router.post("/wakelock/{serial}")
    async def stf_set_wake_lock(serial: str, body: SetEnabledRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_wake_lock, body.enabled)
        return {"ok": ok}

    @router.post("/ringer/{serial}")
    async def stf_set_ringer(serial: str, body: SetRingerModeRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_ringer_mode, body.mode)
        return {"ok": ok}

    @router.post("/mute/{serial}")
    async def stf_set_mute(serial: str, body: SetEnabledRequest):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_set_master_mute, body.enabled)
        return {"ok": ok}

    @router.post("/identify/{serial}")
    async def stf_identify(serial: str):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, device.stf_identify)
        return {"ok": ok}

    @router.get("/display/{serial}")
    async def stf_get_display(serial: str):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(None, device.stf_get_display)
        if info is None:
            return JSONResponse({"error": "STFService not connected"}, status_code=503)
        return info

    @router.get("/properties/{serial}")
    async def stf_get_properties(serial: str):
        device, err = _get_device(manager, serial)
        if err:
            return err
        loop = asyncio.get_running_loop()
        props = await loop.run_in_executor(None, device.stf_get_properties)
        if props is None:
            return JSONResponse({"error": "STFService not connected"}, status_code=503)
        return props

    return router
