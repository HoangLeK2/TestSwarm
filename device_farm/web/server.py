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
    event_recorder=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        loop = asyncio.get_running_loop()
        _app.state.main_loop = loop
        manager.register_event_loop(loop)
        if event_recorder is not None:
            event_recorder.set_event_loop(loop)
            _app.state.event_recorder = event_recorder
        log.info("Device Farm server started")
        asyncio.create_task(heartbeat(manager))
        # Schedule daily event cleanup (keep 30 days)
        if event_recorder is not None:
            async def _event_cleanup_loop() -> None:
                import asyncio as _aio
                while True:
                    await _aio.sleep(86400)  # 24h
                    await event_recorder.cleanup_old_events(keep_days=30)
            asyncio.create_task(_event_cleanup_loop())
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

        # ── ADB relay WebSocket + gRPC server ────────────────────────────────
        relay_manager = None
        if config.relay.enabled:
            try:
                from runtime.transports.adb_relay_server import create_relay_manager, WsRelayAgentSession
                relay_manager = create_relay_manager()
                # WsRelayAgentSession kept as fallback for older agent-boot versions
                _app.state.relay_agent_session = WsRelayAgentSession(
                    relay_manager,
                    api_key=config.relay.api_key or None,
                )
                log.info("ADB relay WebSocket server ready on /relay-agent (main port %d)", config.web.port)

                # ── gRPC relay server (HTTP/2 multiplexing for 100+ phones) ──
                try:
                    from runtime.transports.grpc_relay_server import start_grpc_server
                    grpc_port = getattr(config.relay, "port", 50051)
                    grpc_server = await start_grpc_server(
                        relay_manager,
                        api_key=config.relay.api_key or None,
                        port=grpc_port,
                    )
                    _app.state.grpc_server = grpc_server
                    log.info("gRPC relay server ready on port %d", grpc_port)
                except Exception as grpc_exc:
                    log.warning("gRPC relay server failed to start (WS fallback active): %s", grpc_exc)

                # Auto-attach scrcpy whenever a relay agent reports a new device.
                _relay_mgr_ref = relay_manager
                _manager_ref   = manager
                _config_ref    = config

                def _relay_db_allows_scrcpy(serial_check: str) -> bool:
                    if not _config_ref.database.enabled:
                        return True
                    ml = getattr(_app.state, "main_loop", None)
                    if ml is None:
                        return True
                    from db import crud as _repo
                    from db.database import AsyncSessionLocal

                    async def _q() -> bool:
                        async with AsyncSessionLocal() as db:
                            return await _repo.relay_scrcpy_auto_attach_allowed(db, serial_check)

                    try:
                        # Startup (Temporal, migrations) can stall the event loop; 5s was
                        # too tight and caused spurious timeouts + duplicate attach churn.
                        return asyncio.run_coroutine_threadsafe(_q(), ml).result(timeout=15.0)
                    except TimeoutError as exc:
                        log.warning(
                            "relay_scrcpy DB pref lookup timed out (15s) for %s: %r",
                            serial_check,
                            exc,
                        )
                        return True
                    except Exception as exc:
                        log.warning(
                            "relay_scrcpy DB pref lookup failed for %s: %r",
                            serial_check,
                            exc,
                        )
                        return True

                def _on_relay_device_online(serial: str) -> None:
                    device_ip = serial.rsplit(":", 1)[0] if ":" in serial else serial
                    # Check if a WS-Agent device already exists for this IP.
                    # If so, reattach scrcpy for it (relay reconnect case).
                    ws_device = next(
                        (d for d in _manager_ref.all_devices()
                         if d.serial != serial
                         and (
                             # Cloud/Docker (u2_always_tunnel=True): _u2_host is None,
                             # match by _adb_serial which is set to "device_ip:5555".
                             getattr(d, "_adb_serial", "").startswith(device_ip + ":")
                             # Exact match for USB ADB serials (no colon in serial).
                             or getattr(d, "_adb_serial", "") == serial
                             # Local/LAN fallback: _u2_host == device_ip (legacy).
                             or getattr(d, "_u2_host", None) == device_ip
                         )),
                        None,
                    )
                    # Relay often registers before NAT hello copies hardware serial onto
                    # _adb_serial; tunnel mode leaves _u2_host=None — primary matcher misses.
                    # Scrcpy would then attach only to a relay-slot client (wrong serial);
                    # the dashboard shows the QR/logical device → black video.
                    if ws_device is None:
                        agents = [
                            d for d in _manager_ref.all_devices()
                            if d.serial != serial
                            and getattr(d, "_agent_send", None) is not None
                        ]
                        if len(agents) == 1:
                            ws_device = agents[0]
                            log.info(
                                "relay device online %s — lone WS-Agent match %s "
                                "(pre-NAT _adb_serial / tunnel u2 host)",
                                serial,
                                ws_device.serial,
                            )
                    if ws_device is not None:
                        ws_device.set_event_loop(asyncio.get_event_loop())
                        _st = getattr(_config_ref, "streaming", None)
                        _relay_auto = bool(
                            getattr(_st, "auto_attach_scrcpy_on_relay_online", True)
                        )
                        if _relay_auto and _relay_db_allows_scrcpy(ws_device.serial):
                            import concurrent.futures as _cf2
                            _cf2.ThreadPoolExecutor(max_workers=1).submit(
                                ws_device.attach_scrcpy_stream,
                                serial,
                                None,
                                _config_ref.device.scrcpy_control,
                            )
                            log.info(
                                "relay device online %s — reattaching scrcpy for WS device %s",
                                serial, ws_device.serial,
                            )
                        elif _relay_auto:
                            log.info(
                                "relay device online %s — skip scrcpy reattach "
                                "(relay_scrcpy_enabled=false in DB for %s)",
                                serial,
                                ws_device.serial,
                            )
                        else:
                            log.info(
                                "relay device online %s — skip scrcpy reattach (auto_attach_scrcpy_on_relay_online=false)",
                                serial,
                            )
                        return

                    is_new = _manager_ref.get_device(serial) is None
                    device = _manager_ref.ensure_device(serial)
                    device.set_event_loop(asyncio.get_event_loop())
                    # Set READY immediately — relay reports it as online.
                    # Relay-only devices have no WS-Agent APK to call on_agent_status(),
                    # so without this the device stays DISCONNECTED and frontend shows "Offline".
                    from runtime.core.device_client import DeviceState
                    if device.state in (DeviceState.DISCONNECTED, DeviceState.CONNECTING):
                        device.on_agent_status({"state": "READY"})
                    if is_new:
                        ws_manager.subscribe_device(device)
                        # Bootstrap atx-agent + u2 on first connect so tap/swipe work
                        # without requiring a manual POST /api/devices/adb-register.
                        if _relay_mgr_ref is not None:
                            loop = asyncio.get_event_loop()
                            asyncio.run_coroutine_threadsafe(
                                _relay_mgr_ref.bootstrap(serial), loop
                            )
                            log.info("relay device online → queued bootstrap: %s", serial)
                    _st2 = getattr(_config_ref, "streaming", None)
                    _relay_auto2 = bool(getattr(_st2, "auto_attach_scrcpy_on_relay_online", True))
                    if _relay_auto2 and _relay_db_allows_scrcpy(serial):
                        import concurrent.futures as _cf
                        _cf.ThreadPoolExecutor(max_workers=1).submit(
                            device.attach_scrcpy_stream,
                            serial,
                            None,
                            _config_ref.device.scrcpy_control,
                        )
                        log.info("relay device online → auto-attach scrcpy: %s", serial)
                    elif _relay_auto2:
                        log.info(
                            "relay device online → skip auto-attach scrcpy "
                            "(relay_scrcpy_enabled=false in DB): %s",
                            serial,
                        )
                    else:
                        log.info(
                            "relay device online → skip auto-attach scrcpy (%s, auto_attach_scrcpy_on_relay_online=false)",
                            serial,
                        )

                def _on_relay_capabilities_update(serial: str, caps: dict) -> None:
                    """Propagate relay heartbeat capabilities to DeviceClient metadata."""
                    device = _manager_ref.get_device(serial)
                    if device is None:
                        return
                    device.on_agent_status({
                        "brand":        caps.get("brand", ""),
                        "model":        caps.get("model", ""),
                        "android":      caps.get("android_version", ""),
                        "screen_width": caps.get("screen_width", 0),
                        "screen_height":caps.get("screen_height", 0),
                        "state":        "READY",
                    })

                relay_manager.set_on_device_online(_on_relay_device_online)
                relay_manager.set_on_capabilities_update(_on_relay_capabilities_update)
            except Exception as exc:
                log.warning("ADB relay WebSocket server failed to start: %s", exc)

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
        grpc_server = getattr(_app.state, "grpc_server", None)
        if grpc_server is not None:
            await grpc_server.stop(grace=5)
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
            "devices": len(manager.all_devices()),
            "db": db_enabled,
        }

    @app.get("/api/relay/status")
    async def relay_status():
        """Debug endpoint — shows connected relay agents and their registered serials."""
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            mgr = get_relay_manager()
            if mgr is None:
                return {"relay_enabled": False}
            return {
                "relay_enabled": True,
                "agents": mgr.registered_relays(),
                "devices": mgr.list_devices(),
            }
        except Exception as exc:
            return {"relay_enabled": False, "error": str(exc)}

    templates = Jinja2Templates(directory=templates_dir)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    from services.image_store import init as _init_image_store
    from services import minio_store, capture_store
    _captures_dir = Path("captures")
    _captures_dir.mkdir(exist_ok=True)
    _init_image_store(_captures_dir)
    capture_store.init(_captures_dir)
    minio_store.init(config.object_storage)
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
    if event_recorder is not None:
        ws_manager.bind_event_recorder(event_recorder)
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

    @app.websocket("/relay-agent")
    async def relay_agent_endpoint(ws: WebSocket):
        relay_session = getattr(app.state, "relay_agent_session", None)
        if relay_session is None:
            await ws.close(code=4503, reason="relay not enabled")
            return
        await relay_session.handle(ws)

    return app
