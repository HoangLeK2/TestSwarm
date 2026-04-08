"""
Automation/control routes, mounted at `/api` (paths are suffix-only: `/tap/{serial}`, …).
"""

from __future__ import annotations

from fastapi import APIRouter

from common.session_lock import SessionLockStore
from core.config import Config
from runtime.core import DeviceManager, TaskQueue

from .campaign_fleet import build_campaign_fleet_router
from .connect import build_connect_router
from .device_ui import build_device_ui_router
from .gestures import build_gestures_router
from .scenarios import build_scenarios_router
from .scrcpy import build_scrcpy_router
from .sessions import build_sessions_router
from .stf_control import build_stf_control_router
from .tasks_queue import build_tasks_queue_router


def build_device_control_router(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
    session_store: SessionLockStore,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["device-control"])
    router.include_router(build_connect_router(manager, config))
    router.include_router(build_scrcpy_router(manager))
    router.include_router(build_sessions_router(manager, config, session_store))
    router.include_router(build_gestures_router(manager))
    router.include_router(build_device_ui_router(manager))
    router.include_router(build_tasks_queue_router(manager, queue))
    router.include_router(build_scenarios_router(manager, config, session_store))
    router.include_router(build_campaign_fleet_router(manager, queue, config))
    router.include_router(build_stf_control_router(manager))
    return router
