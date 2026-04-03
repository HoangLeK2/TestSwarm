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

        # ── Start lifecycle components attached by main.py ──
        watchdog = getattr(_app.state, "watchdog", None)
        dispatcher = getattr(_app.state, "dispatcher", None)

        if watchdog is not None:
            watchdog.start_watchdog()
            log.info("Watchdog started")
        if dispatcher is not None:
            dispatcher.start_dispatcher()
            log.info("Dispatcher started")

        # ── Scheduler setup (DF-008) ──────────────────────────────────────
        temporal_client = None
        temporal_threads: list = []
        if config.temporal.enabled:
            try:
                from temporal.worker import start_temporal_worker, get_temporal_client
                temporal_client = await get_temporal_client(config.temporal)
                temporal_threads = start_temporal_worker(manager, config.temporal, queue=queue)
            except Exception as exc:
                log.warning("Temporal worker failed to start: %s — campaign execution will be unavailable", exc)
        else:
            log.warning("Temporal disabled — campaign execution endpoints will return 503")

        from services.scheduler import SchedulerService, SchedulerEngine
        scheduler = SchedulerService(
            temporal_client=temporal_client,
            manager=manager,
            queue=queue,
            temporal_config=config.temporal if config.temporal.enabled else None,
        )
        _app.state.scheduler = scheduler

        scheduler_engine = None
        if not config.temporal.enabled and config.database.enabled:
            scheduler_engine = SchedulerEngine(queue=queue, manager=manager)
            scheduler_engine.start()
            log.info("SchedulerEngine (fallback) started")

        ngrok_tunnel = None
        from core.env import ngrok_enabled, ngrok_authtoken
        if ngrok_enabled():
            try:
                import pyngrok
                auth = ngrok_authtoken()
                if auth:
                    pyngrok.set_auth_token(auth)
                ngrok_tunnel = pyngrok.ngrok.connect(addr=str(config.web.port), bind_tls=True)
                log.info("ngrok tunnel: %s", ngrok_tunnel.public_url)
            except Exception as e:
                err = str(e).lower()
                log.warning("ngrok failed: %s", e)
                if "bandwidth" in err:
                    log.warning(
                        "ngrok free tier bandwidth limit. Options: 1) Lower scrcpy_bitrate. "
                        "2) Upgrade at dashboard.ngrok.com. "
                        "3) cloudflared tunnel --url http://localhost:%s",
                        config.web.port,
                    )

        log.info("Dashboard: http://%s:%s", config.web.host, config.web.port)

        yield

        # ── Shutdown ──
        log.info("Shutting down…")
        if scheduler_engine is not None:
            await scheduler_engine.stop()
        if ngrok_tunnel is not None:
            try:
                import pyngrok
                pyngrok.ngrok.disconnect(ngrok_tunnel.public_url)
                pyngrok.ngrok.kill()
            except Exception:
                pass
        if watchdog is not None:
            watchdog.stop_watchdog()
        if dispatcher is not None:
            dispatcher.stop_dispatcher()
        manager.teardown_all()
        log.info("Shutdown complete.")

    app = FastAPI(
        title="Android Device Farm",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.state.queue = queue
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

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "devices": len(manager.devices),
            "db": db_enabled,
        }

    templates = Jinja2Templates(directory=templates_dir)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    from services.image_store import init as _init_image_store
    _captures_dir = Path("captures")
    _captures_dir.mkdir(exist_ok=True)
    _init_image_store(_captures_dir)
    app.mount("/captures", StaticFiles(directory=str(_captures_dir)), name="captures")

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
