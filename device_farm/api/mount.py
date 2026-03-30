from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from api.crud import api_router
from api.routes.dashboard_page import build_dashboard_router
from api.routes.device_control import build_device_control_router
from api.routes.device_media import build_device_media_router
from api.routes.extraction import build_extraction_router
from api.routes.public import build_public_router
from common.session_lock import SessionLockStore
from core.config import Config
from runtime.core import DeviceManager, TaskQueue


def mount_http_routers(
    app: FastAPI,
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
    templates: Jinja2Templates,
    front_end_dist: Optional[str],
    session_store: SessionLockStore,
    db_enabled: bool,
) -> None:
    app.include_router(build_public_router(manager, queue, config, db_enabled))

    if config.database.enabled:
        app.include_router(api_router, prefix="/api")

    app.include_router(build_dashboard_router(manager, config, templates, front_end_dist))
    app.include_router(
        build_device_control_router(manager, queue, config, session_store)
    )
    app.include_router(build_device_media_router(manager))
    app.include_router(build_extraction_router(manager))
