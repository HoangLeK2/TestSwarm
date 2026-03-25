from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.mount import mount_http_routers
from core.config import Config
from db.database import init_db
from runtime.core import DeviceManager, TaskQueue
from common.session_lock import SessionLockStore
from .ws import WebSocketManager, DeviceAgentSession, get_ws_user_id, heartbeat

log = logging.getLogger(__name__)


class RequestLogMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        client = request.client
        addr = f"{client[0]}:{client[1]}" if client else "?"
        path = request.url.path
        if request.headers.get("upgrade", "").lower() == "websocket":
            log.info("[REQUEST] %s %s (WebSocket) from %s", request.method, path, addr)
        else:
            log.debug("[REQUEST] %s %s from %s", request.method, path, addr)
        return await call_next(request)


def create_app(
    manager: DeviceManager,
    queue: TaskQueue,
    config: Config,
    templates_dir: str,
    static_dir: str,
    front_end_dist: Optional[str] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        loop = asyncio.get_running_loop()
        manager.register_event_loop(loop)
        log.info("Device Farm server started")
        asyncio.create_task(heartbeat(manager))
        if config.database.enabled:
            try:
                await init_db()
                log.info("PostgreSQL connected and tables ready")
            except Exception as exc:  # noqa: BLE001
                log.warning("PostgreSQL init failed (running without DB): %s", exc)
        yield

    app = FastAPI(
        title="Android Device Farm",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.state.session_store = SessionLockStore()

    db_enabled = bool(
        getattr(config, "database", None)
        and getattr(config.database, "enabled", False)
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"https?://.*",
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    app.add_middleware(RequestLogMiddleware)

    templates = Jinja2Templates(directory=templates_dir)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    assets_dir = Path(front_end_dist) / "assets" if front_end_dist else None
    if assets_dir and assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    mount_http_routers(
        app,
        manager,
        queue,
        config,
        templates,
        front_end_dist,
        app.state.session_store,
        db_enabled,
    )

    ws_manager = WebSocketManager(manager, db_enabled=db_enabled)
    agent_session = DeviceAgentSession(manager, ws_manager, config)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        user_id: Optional[str] = None
        if db_enabled:
            user_id = await get_ws_user_id(ws)
        await ws_manager.connect(ws, user_id=user_id)

    @app.websocket("/device-agent")
    async def device_agent_endpoint(ws: WebSocket):
        await agent_session.handle(ws)

    return app
