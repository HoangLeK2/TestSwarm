"""Scrcpy attach/detach — supports WiFi (IP from DB) and USB ADB."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import ScrcpyAttachRequest, ScrcpyDetachRequest
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager

log = logging.getLogger(__name__)
_SCRCPY_OP_LOCKS: dict[str, asyncio.Lock] = {}
_SCRCPY_VIEWERS: dict[str, set[str]] = {}
_SCRCPY_STOP_TASKS: dict[str, asyncio.Task[None]] = {}
_LEGACY_VIEWER_ID = "legacy"
_DEFAULT_DETACH_GRACE_S = 6.0


def _scrcpy_op_lock(serial: str) -> asyncio.Lock:
    lock = _SCRCPY_OP_LOCKS.get(serial)
    if lock is None:
        lock = asyncio.Lock()
        _SCRCPY_OP_LOCKS[serial] = lock
    return lock


def _scrcpy_viewer_id(raw: str | None) -> str:
    viewer_id = (raw or "").strip()
    if not viewer_id:
        return _LEGACY_VIEWER_ID
    return viewer_id[:128]


def _scrcpy_viewer_surface(viewer_id: str) -> str | None:
    if viewer_id == _LEGACY_VIEWER_ID or ":" not in viewer_id:
        return None
    surface = viewer_id.split(":", 1)[0].strip()
    return surface or None


def _replace_stale_surface_viewers(viewers: set[str], viewer_id: str) -> int:
    surface = _scrcpy_viewer_surface(viewer_id)
    if not surface:
        return 0
    before = len(viewers)
    viewers.difference_update(
        existing
        for existing in list(viewers)
        if existing != viewer_id and _scrcpy_viewer_surface(existing) == surface
    )
    return before - len(viewers)


def has_active_scrcpy_viewers(serial: str) -> bool:
    return bool(_SCRCPY_VIEWERS.get(serial))


def build_scrcpy_router(
    manager: DeviceManager,
    *,
    db_enabled: bool,
    scrcpy_detach_grace_s: float = _DEFAULT_DETACH_GRACE_S,
) -> APIRouter:
    router = APIRouter()

    async def _persist_scrcpy_enabled(serial: str, enabled: bool) -> None:
        if not db_enabled:
            return
        try:
            async with AsyncSessionLocal() as db:
                await repo.set_relay_scrcpy_enabled(db, serial, enabled)
        except Exception as exc:
            log.warning("persist relay_scrcpy_enabled=%s for %s: %s", enabled, serial, exc)

    async def _stop_scrcpy_after_grace(serial: str, viewer_id: str) -> None:
        try:
            if scrcpy_detach_grace_s > 0:
                await asyncio.sleep(scrcpy_detach_grace_s)
            lock = _scrcpy_op_lock(serial)
            async with lock:
                if _SCRCPY_VIEWERS.get(serial):
                    return
                if _SCRCPY_STOP_TASKS.get(serial) is not asyncio.current_task():
                    return
                _SCRCPY_STOP_TASKS.pop(serial, None)
                device = manager.get_device(serial)
                if not device:
                    return
                device.detach_scrcpy_stream(reason=f"api_scrcpy_detach:{viewer_id}")
                await _persist_scrcpy_enabled(serial, False)
            log.info(
                "api_scrcpy_detach serial=%s viewer=%s active_viewers=0 stop=True",
                serial,
                viewer_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("delayed scrcpy detach failed for %s viewer=%s: %s", serial, viewer_id, exc)

    @router.post("/devices/{serial}/scrcpy/attach")
    async def api_scrcpy_attach(serial: str, body: ScrcpyAttachRequest):
        lock = _scrcpy_op_lock(serial)

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

        viewer_id = _scrcpy_viewer_id(body.viewer_id)
        async with lock:
            stop_task = _SCRCPY_STOP_TASKS.pop(serial, None)
            if stop_task and not stop_task.done():
                stop_task.cancel()
            viewers = _SCRCPY_VIEWERS.setdefault(serial, set())
            pruned_viewers = _replace_stale_surface_viewers(viewers, viewer_id)
            if pruned_viewers:
                log.info(
                    "api_scrcpy_attach serial=%s viewer=%s pruned_stale_surface_viewers=%d",
                    serial,
                    viewer_id,
                    pruned_viewers,
                )
            scrcpy_active = bool(getattr(device, "_scrcpy_active", False))
            scrcpy_pending = bool(getattr(device, "_scrcpy_pending_registered_ip", None))
            should_start = not scrcpy_active and not scrcpy_pending
            viewers.add(viewer_id)
            attach_status = "active"
            if should_start:
                loop = asyncio.get_running_loop()
                try:
                    raw_status = await loop.run_in_executor(
                        None,
                        device.attach_scrcpy_stream,
                        device_ip,
                        adb_port,
                        body.enable_control,
                    )
                    if raw_status in {"active", "pending", "unavailable"}:
                        attach_status = raw_status
                    else:
                        attach_status = "active"
                except Exception:
                    viewers.discard(viewer_id)
                    if not viewers:
                        _SCRCPY_VIEWERS.pop(serial, None)
                    raise
                if attach_status == "unavailable":
                    viewers.discard(viewer_id)
                    if not viewers:
                        _SCRCPY_VIEWERS.pop(serial, None)
                    return JSONResponse(
                        {
                            "ok": False,
                            "serial": serial,
                            "status": attach_status,
                            "error": "scrcpy relay unavailable",
                            "active_viewers": len(_SCRCPY_VIEWERS.get(serial, set())),
                        },
                        status_code=503,
                    )
                await _persist_scrcpy_enabled(serial, True)
            elif not getattr(device, "_scrcpy_active", False):
                attach_status = "pending"
        log.info(
            "api_scrcpy_attach serial=%s viewer=%s status=%s active_viewers=%d",
            serial,
            viewer_id,
            attach_status,
            len(_SCRCPY_VIEWERS.get(serial, set())),
        )
        return {
            "ok": True,
            "serial": serial,
            "status": attach_status,
            "scrcpy": f"{device_ip}:{adb_port}",
            "control": body.enable_control,
            "active_viewers": len(_SCRCPY_VIEWERS.get(serial, set())),
        }

    @router.post("/devices/{serial}/scrcpy/detach")
    async def api_scrcpy_detach(serial: str, body: ScrcpyDetachRequest | None = None):
        lock = _scrcpy_op_lock(serial)

        device = manager.get_device(serial)
        if not device:
            return JSONResponse({"error": "Device not found"}, status_code=404)
        viewer_id = _scrcpy_viewer_id(body.viewer_id if body else None)
        async with lock:
            viewers = _SCRCPY_VIEWERS.get(serial)
            if viewers is not None:
                viewers.discard(viewer_id)
                if viewers:
                    log.info(
                        "api_scrcpy_detach serial=%s viewer=%s active_viewers=%d stop=False",
                        serial,
                        viewer_id,
                        len(viewers),
                    )
                    return {
                        "ok": True,
                        "serial": serial,
                        "active_viewers": len(viewers),
                    }
                _SCRCPY_VIEWERS.pop(serial, None)

            existing_stop = _SCRCPY_STOP_TASKS.pop(serial, None)
            if existing_stop and not existing_stop.done():
                existing_stop.cancel()
            if scrcpy_detach_grace_s <= 0:
                device.detach_scrcpy_stream(reason=f"api_scrcpy_detach:{viewer_id}")
                await _persist_scrcpy_enabled(serial, False)
            else:
                task = asyncio.create_task(_stop_scrcpy_after_grace(serial, viewer_id))
                _SCRCPY_STOP_TASKS[serial] = task
                log.info(
                    "api_scrcpy_detach serial=%s viewer=%s active_viewers=0 stop_scheduled=%.1fs",
                    serial,
                    viewer_id,
                    scrcpy_detach_grace_s,
                )
                return {
                    "ok": True,
                    "serial": serial,
                    "active_viewers": 0,
                    "stop_scheduled": True,
                }
        log.info(
            "api_scrcpy_detach serial=%s viewer=%s active_viewers=0 stop=True",
            serial,
            viewer_id,
        )
        return {"ok": True, "serial": serial, "active_viewers": 0}

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
