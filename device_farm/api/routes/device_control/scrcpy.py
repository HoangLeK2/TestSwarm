"""Scrcpy attach/detach — supports WiFi (IP from DB) and USB ADB."""

from __future__ import annotations

import asyncio
import logging
import os
from functools import partial

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.schemas.device_control import ScrcpyAttachRequest, ScrcpyDetachRequest
from db import crud as repo
from db.database import AsyncSessionLocal
from runtime.core import DeviceManager

log = logging.getLogger(__name__)
_SCRCPY_OP_LOCKS: dict[str, asyncio.Lock] = {}
_SCRCPY_VIEWERS: dict[str, set[str]] = {}
_SCRCPY_VIEWER_REQUESTS: dict[str, dict[str, ScrcpyAttachRequest]] = {}
_SCRCPY_STOP_TASKS: dict[str, asyncio.Task[None]] = {}
_SCRCPY_STOP_VIEWERS: dict[str, str] = {}
_LEGACY_VIEWER_ID = "legacy"
_DEFAULT_DETACH_GRACE_S = 6.0
_DEFAULT_VIEWER_LEASE_TTL_S = 45.0
_CONTROL_VIEWER_SURFACES = {"device-screen", "control-screen"}
_PREVIEW_VIEWER_SURFACES = {
    "campaign-monitor",
    "follower-preview",
    "snapshot-preview",
}
_BUDGETED_PREVIEW_VIEWER_SURFACES = {"snapshot-preview"}
_PROFILE_KEYS = ("max_fps", "max_width", "bitrate")
_VIEWER_SURFACE_PRIORITY = {
    "snapshot-preview": 10,
    "follower-preview": 20,
    "campaign-monitor": 30,
    "device-screen": 100,
    "control-screen": 100,
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


_SCRCPY_PREVIEW_VIEWER_LIMIT = _env_int("SCRCPY_PREVIEW_VIEWER_LIMIT", 64)


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


def _is_control_viewer(viewer_id: str) -> bool:
    surface = _scrcpy_viewer_surface(viewer_id)
    return surface in _CONTROL_VIEWER_SURFACES


def _is_preview_viewer(viewer_id: str) -> bool:
    surface = _scrcpy_viewer_surface(viewer_id)
    return surface in _PREVIEW_VIEWER_SURFACES


def _viewer_uses_lease(viewer_id: str) -> bool:
    surface = _scrcpy_viewer_surface(viewer_id)
    return surface in _CONTROL_VIEWER_SURFACES | _PREVIEW_VIEWER_SURFACES


def _active_preview_viewer_count() -> int:
    return sum(
        1
        for viewers in _SCRCPY_VIEWERS.values()
        for viewer_id in viewers
        if _scrcpy_viewer_surface(viewer_id) in _BUDGETED_PREVIEW_VIEWER_SURFACES
    )


def _preview_viewer_budget_exhausted(serial: str, viewer_id: str) -> bool:
    if _scrcpy_viewer_surface(viewer_id) not in _BUDGETED_PREVIEW_VIEWER_SURFACES:
        return False
    if _SCRCPY_PREVIEW_VIEWER_LIMIT <= 0:
        return False
    if viewer_id in _SCRCPY_VIEWERS.get(serial, set()):
        return False
    return _active_preview_viewer_count() >= _SCRCPY_PREVIEW_VIEWER_LIMIT


def _positive_profile_value(value: int | None) -> int | None:
    try:
        parsed = int(value or 0)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _requested_scrcpy_profile(
    body: ScrcpyAttachRequest,
) -> tuple[int | None, int | None, int | None]:
    return (
        _positive_profile_value(body.max_fps),
        _positive_profile_value(body.max_width),
        _positive_profile_value(body.bitrate),
    )


def _current_scrcpy_profile(device: object) -> tuple[int | None, int | None, int | None]:
    params = getattr(device, "_scrcpy_params", None)
    if isinstance(params, dict):
        return tuple(
            _positive_profile_value(params.get(key))
            for key in _PROFILE_KEYS
        )  # type: ignore[return-value]
    if isinstance(params, tuple):
        values = list(params[3:6])
        while len(values) < 3:
            values.append(None)
        return tuple(_positive_profile_value(value) for value in values)  # type: ignore[return-value]
    return (None, None, None)


def _has_limited_profile_request(body: ScrcpyAttachRequest) -> bool:
    return any(value is not None for value in _requested_scrcpy_profile(body))


def _has_limited_scrcpy_profile(device: object) -> bool:
    return any(value is not None for value in _current_scrcpy_profile(device))


def _scrcpy_profile_matches_request(device: object, body: ScrcpyAttachRequest) -> bool:
    return _current_scrcpy_profile(device) == _requested_scrcpy_profile(body)


def _scrcpy_request_matches_device(
    device: object, body: ScrcpyAttachRequest
) -> bool:
    params = getattr(device, "_scrcpy_params", None)
    current_control = bool(params[2]) if isinstance(params, tuple) and len(params) >= 3 else True
    return (
        current_control == bool(body.enable_control)
        and _scrcpy_profile_matches_request(device, body)
    )


def _has_control_scrcpy_viewer(viewers: set[str]) -> bool:
    return any(_is_control_viewer(viewer_id) for viewer_id in viewers)


def _sync_viewer_requests(serial: str, viewers: set[str]) -> None:
    requests = _SCRCPY_VIEWER_REQUESTS.get(serial)
    if not requests:
        return
    for existing in list(requests):
        if existing not in viewers:
            requests.pop(existing, None)
    if not requests:
        _SCRCPY_VIEWER_REQUESTS.pop(serial, None)


def _forget_viewer_request(serial: str, viewer_id: str) -> None:
    requests = _SCRCPY_VIEWER_REQUESTS.get(serial)
    if not requests:
        return
    requests.pop(viewer_id, None)
    if not requests:
        _SCRCPY_VIEWER_REQUESTS.pop(serial, None)


def _effective_viewer_request(
    serial: str,
    viewers: set[str],
    *,
    preview_only: bool = False,
) -> ScrcpyAttachRequest | None:
    requests = _SCRCPY_VIEWER_REQUESTS.get(serial, {})
    ranked: list[tuple[int, str, ScrcpyAttachRequest]] = []
    for viewer_id in viewers:
        if preview_only and not _is_preview_viewer(viewer_id):
            continue
        request = requests.get(viewer_id)
        if request is None:
            continue
        surface = _scrcpy_viewer_surface(viewer_id)
        # Unknown/legacy viewers retain control-level precedence for compatibility.
        priority = _VIEWER_SURFACE_PRIORITY.get(surface or "", 100)
        ranked.append((priority, viewer_id, request))
    if not ranked:
        return None

    highest_priority = max(item[0] for item in ranked)
    selected = [item for item in ranked if item[0] == highest_priority]
    _, _, base = max(
        selected,
        key=lambda item: (
            _positive_profile_value(item[2].max_fps) or 0,
            _positive_profile_value(item[2].max_width) or 0,
            _positive_profile_value(item[2].bitrate) or 0,
            item[1],
        ),
    )

    def _max_requested(key: str) -> int | None:
        values = [
            _positive_profile_value(getattr(item[2], key))
            for item in selected
        ]
        present = [value for value in values if value is not None]
        return max(present) if present else None

    return base.model_copy(
        update={
            "enable_control": any(item[2].enable_control for item in selected),
            "max_fps": _max_requested("max_fps"),
            "max_width": _max_requested("max_width"),
            "bitrate": _max_requested("bitrate"),
        }
    )


def has_active_scrcpy_viewers(serial: str) -> bool:
    return bool(_SCRCPY_VIEWERS.get(serial))


def build_scrcpy_router(
    manager: DeviceManager,
    *,
    db_enabled: bool,
    scrcpy_detach_grace_s: float = _DEFAULT_DETACH_GRACE_S,
    scrcpy_viewer_lease_ttl_s: float | None = None,
) -> APIRouter:
    router = APIRouter()
    if scrcpy_viewer_lease_ttl_s is None:
        configured_lease_ttl_s = _env_float(
            "SCRCPY_VIEWER_LEASE_TTL_S",
            _DEFAULT_VIEWER_LEASE_TTL_S,
        )
        viewer_lease_ttl_s = (
            0.0
            if configured_lease_ttl_s <= 0
            else max(_DEFAULT_VIEWER_LEASE_TTL_S, configured_lease_ttl_s)
        )
    else:
        viewer_lease_ttl_s = max(0.0, scrcpy_viewer_lease_ttl_s)
    viewer_lease_deadlines: dict[tuple[str, str], float] = {}
    viewer_lease_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
    profile_reapply_tasks: dict[str, asyncio.Task[None]] = {}

    async def _persist_scrcpy_enabled(serial: str, enabled: bool) -> None:
        if not db_enabled:
            return
        try:
            async with AsyncSessionLocal() as db:
                await repo.set_relay_scrcpy_enabled(db, serial, enabled)
        except Exception as exc:
            log.warning("persist relay_scrcpy_enabled=%s for %s: %s", enabled, serial, exc)

    def _clear_viewer_lease(serial: str, viewer_id: str) -> None:
        key = (serial, viewer_id)
        viewer_lease_deadlines.pop(key, None)
        task = viewer_lease_tasks.pop(key, None)
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def _cancel_profile_reapply(serial: str) -> None:
        task = profile_reapply_tasks.pop(serial, None)
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def _profile_reapply_pending(serial: str) -> bool:
        task = profile_reapply_tasks.get(serial)
        if task is None:
            return False
        if task.done():
            profile_reapply_tasks.pop(serial, None)
            return False
        return True

    def _should_defer_profile_downgrade(
        removed_viewer_id: str,
        viewers: set[str],
    ) -> bool:
        return (
            scrcpy_detach_grace_s > 0
            and _is_control_viewer(removed_viewer_id)
            and bool(viewers)
            and all(_is_preview_viewer(viewer_id) for viewer_id in viewers)
        )

    async def _reapply_effective_viewer_profile(
        serial: str,
        device: object,
        viewers: set[str],
    ) -> bool:
        effective_request = _effective_viewer_request(serial, viewers)
        if (
            effective_request is None
            or _scrcpy_request_matches_device(device, effective_request)
        ):
            return False
        raw_status = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                device.attach_scrcpy_stream,
                effective_request.device_ip,
                effective_request.adb_port,
                effective_request.enable_control,
                max_fps=effective_request.max_fps,
                max_width=effective_request.max_width,
                bitrate=effective_request.bitrate,
            ),
        )
        return raw_status != "unavailable"

    async def _reapply_profile_after_grace(serial: str) -> None:
        try:
            await asyncio.sleep(scrcpy_detach_grace_s)
            lock = _scrcpy_op_lock(serial)
            async with lock:
                if profile_reapply_tasks.get(serial) is not asyncio.current_task():
                    return
                viewers = _SCRCPY_VIEWERS.get(serial)
                if (
                    not viewers
                    or _has_control_scrcpy_viewer(viewers)
                    or not all(_is_preview_viewer(viewer_id) for viewer_id in viewers)
                ):
                    return
                device = manager.get_device(serial)
                if not device:
                    return
                profile_reapplied = await _reapply_effective_viewer_profile(
                    serial,
                    device,
                    viewers,
                )
            log.info(
                "scrcpy profile downgrade serial=%s active_viewers=%d "
                "profile_reapplied=%s",
                serial,
                len(viewers),
                profile_reapplied,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("delayed scrcpy profile downgrade failed for %s: %s", serial, exc)
        finally:
            if profile_reapply_tasks.get(serial) is asyncio.current_task():
                profile_reapply_tasks.pop(serial, None)

    def _schedule_profile_reapply(serial: str) -> None:
        _cancel_profile_reapply(serial)
        profile_reapply_tasks[serial] = asyncio.create_task(
            _reapply_profile_after_grace(serial)
        )

    async def _expire_viewer_lease(serial: str, viewer_id: str) -> None:
        key = (serial, viewer_id)
        try:
            while True:
                deadline = viewer_lease_deadlines.get(key)
                if deadline is None:
                    return
                delay = deadline - asyncio.get_running_loop().time()
                if delay > 0:
                    await asyncio.sleep(delay)
                    continue

                lock = _scrcpy_op_lock(serial)
                async with lock:
                    deadline = viewer_lease_deadlines.get(key)
                    if deadline is None:
                        return
                    if deadline > asyncio.get_running_loop().time():
                        continue

                    viewer_lease_deadlines.pop(key, None)
                    viewers = _SCRCPY_VIEWERS.get(serial)
                    if not viewers or viewer_id not in viewers:
                        return
                    viewers.discard(viewer_id)
                    _forget_viewer_request(serial, viewer_id)
                    if viewers:
                        device = manager.get_device(serial)
                        profile_reapplied = False
                        if device:
                            if _should_defer_profile_downgrade(viewer_id, viewers):
                                _schedule_profile_reapply(serial)
                            else:
                                profile_reapplied = await _reapply_effective_viewer_profile(
                                    serial,
                                    device,
                                    viewers,
                                )
                        log.info(
                            "scrcpy viewer lease expired serial=%s viewer=%s "
                            "active_viewers=%d stop=False profile_reapplied=%s "
                            "profile_reapply_scheduled=%s",
                            serial,
                            viewer_id,
                            len(viewers),
                            profile_reapplied,
                            _profile_reapply_pending(serial),
                        )
                        return

                    _cancel_profile_reapply(serial)
                    _SCRCPY_VIEWERS.pop(serial, None)
                    _SCRCPY_VIEWER_REQUESTS.pop(serial, None)
                    device = manager.get_device(serial)
                    if device:
                        device.detach_scrcpy_stream(
                            reason=f"scrcpy_viewer_lease_expired:{viewer_id}"
                        )
                        await _persist_scrcpy_enabled(serial, False)
                log.info(
                    "scrcpy viewer lease expired serial=%s viewer=%s "
                    "active_viewers=0 stop=True",
                    serial,
                    viewer_id,
                )
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "scrcpy viewer lease expiry failed for %s viewer=%s: %s",
                serial,
                viewer_id,
                exc,
            )
        finally:
            if viewer_lease_tasks.get(key) is asyncio.current_task():
                viewer_lease_tasks.pop(key, None)

    def _refresh_viewer_lease(serial: str, viewer_id: str) -> None:
        if viewer_lease_ttl_s <= 0 or not _viewer_uses_lease(viewer_id):
            return
        key = (serial, viewer_id)
        viewer_lease_deadlines[key] = (
            asyncio.get_running_loop().time() + viewer_lease_ttl_s
        )
        task = viewer_lease_tasks.get(key)
        if task is None or task.done():
            viewer_lease_tasks[key] = asyncio.create_task(
                _expire_viewer_lease(serial, viewer_id)
            )

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
                _SCRCPY_STOP_VIEWERS.pop(serial, None)
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
            viewers = _SCRCPY_VIEWERS.get(serial)
            if viewers is not None:
                if not viewers:
                    _SCRCPY_VIEWERS.pop(serial, None)
                _sync_viewer_requests(serial, viewers)
            if _preview_viewer_budget_exhausted(serial, viewer_id):
                return JSONResponse(
                    {
                        "ok": False,
                        "serial": serial,
                        "status": "preview_budget_exhausted",
                        "error": "scrcpy preview viewer budget exhausted",
                        "active_preview_viewers": _active_preview_viewer_count(),
                        "preview_viewer_limit": _SCRCPY_PREVIEW_VIEWER_LIMIT,
                    },
                    status_code=429,
                )
            stop_task = _SCRCPY_STOP_TASKS.pop(serial, None)
            _SCRCPY_STOP_VIEWERS.pop(serial, None)
            if stop_task and not stop_task.done():
                stop_task.cancel()
            if not _is_preview_viewer(viewer_id):
                _cancel_profile_reapply(serial)
            viewers = _SCRCPY_VIEWERS.setdefault(serial, set())
            scrcpy_active = bool(getattr(device, "_scrcpy_active", False))
            scrcpy_pending = bool(getattr(device, "_scrcpy_pending_registered_ip", None))
            should_start = not scrcpy_active and not scrcpy_pending
            viewers.add(viewer_id)
            viewer_request = body.model_copy(update={"device_ip": device_ip})
            _SCRCPY_VIEWER_REQUESTS.setdefault(serial, {})[viewer_id] = viewer_request
            _refresh_viewer_lease(serial, viewer_id)
            attach_request = _effective_viewer_request(serial, viewers) or viewer_request
            should_reapply_profile = (
                (scrcpy_active or scrcpy_pending)
                and not _scrcpy_request_matches_device(device, attach_request)
                and not _profile_reapply_pending(serial)
            )
            attach_status = "active"
            if should_start or should_reapply_profile:
                loop = asyncio.get_running_loop()
                if (
                    attach_request.max_fps is None
                    and attach_request.max_width is None
                    and attach_request.bitrate is None
                ):
                    attach_call = partial(
                        device.attach_scrcpy_stream,
                        device_ip,
                        attach_request.adb_port,
                        attach_request.enable_control,
                    )
                else:
                    attach_call = partial(
                        device.attach_scrcpy_stream,
                        device_ip,
                        attach_request.adb_port,
                        attach_request.enable_control,
                        max_fps=attach_request.max_fps,
                        max_width=attach_request.max_width,
                        bitrate=attach_request.bitrate,
                    )
                try:
                    raw_status = await loop.run_in_executor(
                        None,
                        attach_call,
                    )
                    if raw_status in {"active", "pending", "unavailable"}:
                        attach_status = raw_status
                    else:
                        attach_status = "active"
                except Exception:
                    viewers.discard(viewer_id)
                    _forget_viewer_request(serial, viewer_id)
                    _clear_viewer_lease(serial, viewer_id)
                    if _should_defer_profile_downgrade(viewer_id, viewers):
                        _schedule_profile_reapply(serial)
                    if not viewers:
                        _SCRCPY_VIEWERS.pop(serial, None)
                    raise
                if attach_status == "unavailable":
                    viewers.discard(viewer_id)
                    _forget_viewer_request(serial, viewer_id)
                    _clear_viewer_lease(serial, viewer_id)
                    if _should_defer_profile_downgrade(viewer_id, viewers):
                        _schedule_profile_reapply(serial)
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

    @router.post("/devices/{serial}/scrcpy/heartbeat")
    async def api_scrcpy_heartbeat(serial: str, body: ScrcpyDetachRequest):
        viewer_id = _scrcpy_viewer_id(body.viewer_id)
        if not _viewer_uses_lease(viewer_id):
            return JSONResponse(
                {"error": "viewer_id must identify a leased scrcpy viewer"},
                status_code=400,
            )
        if manager.get_device(serial) is None:
            return JSONResponse({"error": "Device not found"}, status_code=404)

        lock = _scrcpy_op_lock(serial)
        async with lock:
            viewers = _SCRCPY_VIEWERS.get(serial)
            if not viewers or viewer_id not in viewers:
                return JSONResponse(
                    {"error": "scrcpy viewer not found"},
                    status_code=404,
                )
            _refresh_viewer_lease(serial, viewer_id)
            active_viewers = len(viewers)
        return {
            "ok": True,
            "serial": serial,
            "active_viewers": active_viewers,
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
                _forget_viewer_request(serial, viewer_id)
                _clear_viewer_lease(serial, viewer_id)
                if viewers:
                    profile_reapply_scheduled = _should_defer_profile_downgrade(
                        viewer_id,
                        viewers,
                    )
                    if profile_reapply_scheduled:
                        _schedule_profile_reapply(serial)
                        profile_reapplied = False
                    else:
                        profile_reapplied = await _reapply_effective_viewer_profile(
                            serial,
                            device,
                            viewers,
                        )
                    log.info(
                        "api_scrcpy_detach serial=%s viewer=%s active_viewers=%d "
                        "stop=False profile_reapplied=%s profile_reapply_scheduled=%s",
                        serial,
                        viewer_id,
                        len(viewers),
                        profile_reapplied,
                        profile_reapply_scheduled,
                    )
                    return {
                        "ok": True,
                        "serial": serial,
                        "active_viewers": len(viewers),
                        "profile_reapplied": profile_reapplied,
                        "profile_reapply_scheduled": profile_reapply_scheduled,
                    }
                _cancel_profile_reapply(serial)
                _SCRCPY_VIEWERS.pop(serial, None)
                _SCRCPY_VIEWER_REQUESTS.pop(serial, None)

            existing_stop = _SCRCPY_STOP_TASKS.pop(serial, None)
            _SCRCPY_STOP_VIEWERS.pop(serial, None)
            if existing_stop and not existing_stop.done():
                existing_stop.cancel()
            if scrcpy_detach_grace_s <= 0 or _is_preview_viewer(viewer_id):
                device.detach_scrcpy_stream(reason=f"api_scrcpy_detach:{viewer_id}")
                await _persist_scrcpy_enabled(serial, False)
            else:
                task = asyncio.create_task(_stop_scrcpy_after_grace(serial, viewer_id))
                _SCRCPY_STOP_TASKS[serial] = task
                _SCRCPY_STOP_VIEWERS[serial] = viewer_id
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
