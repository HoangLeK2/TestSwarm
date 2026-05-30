from __future__ import annotations

import asyncio
import atexit
import logging
import importlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import uuid4

# Shared, bounded executor for relay "attach scrcpy" events. Previous code
# did `ThreadPoolExecutor(max_workers=1).submit(...)` on every relay event —
# each instance leaks one idle worker thread until gc runs executor.shutdown
# via atexit, and on a busy farm this piles up fast. A single pool keeps the
# fire-and-forget semantics without creating a new executor per event.
_RELAY_ATTACH_POOL = ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="relay-scrcpy-attach"
)
atexit.register(lambda: _RELAY_ATTACH_POOL.shutdown(wait=False))

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from api.mount import mount_http_routers
from api.deps import AdminUser
from core.config import Config
from db.database import init_db
from runtime.core import DeviceManager, TaskQueue
from runtime.lifecycle import LifecycleManager, LifecyclePhase
from common.session_lock import SessionLockStore
from .ws import WebSocketManager, DeviceAgentSession, authenticate_ws, heartbeat
from .ws_lifecycle import DeviceLifecycleWsManager

log = logging.getLogger(__name__)
api_trace_log = importlib.import_module("structlog").get_logger("api_trace")


class RequestLogMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        client = request.client
        addr = f"{client[0]}:{client[1]}" if client else "?"
        path = request.url.path
        if request.headers.get("upgrade", "").lower() == "websocket":
            log.info("[REQUEST] %s %s (WebSocket) from %s", request.method, path, addr)
            return await call_next(request)

        request_id = request.headers.get("x-request-id") or f"req-{uuid4().hex[:10]}"
        request.state.request_id = request_id
        started = time.perf_counter()
        api_trace_log.info(
            "http_request_start",
            request_id=request_id,
            method=request.method,
            path=path,
            client=addr,
            query=str(request.url.query or ""),
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            api_trace_log.exception(
                "http_request_error",
                request_id=request_id,
                method=request.method,
                path=path,
                client=addr,
                duration_ms=round(elapsed_ms, 1),
                error=str(exc),
            )
            log.exception(
                "[REQUEST] %s %s from %s -> 500 in %.1fms",
                request.method,
                path,
                addr,
                elapsed_ms,
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response.headers["X-Request-ID"] = request_id
        api_trace_log.info(
            "http_request_end",
            request_id=request_id,
            method=request.method,
            path=path,
            client=addr,
            status_code=response.status_code,
            duration_ms=round(elapsed_ms, 1),
        )
        # Keep static/assets less noisy; log API-ish paths prominently.
        if (
            path.startswith("/api/")
            or path.startswith("/devices/")
            or path.startswith("/campaigns/")
            or path.startswith("/executions/")
            or path.startswith("/workflows/")
            or path.startswith("/tasks")
            or path.startswith("/fleet/")
            or path.startswith("/sessions/")
            or path.startswith("/events")
            or path.startswith("/stf/")
            or path.startswith("/connect/")
        ):
            log.info(
                "[REQUEST][%s] %s %s from %s -> %s in %.1fms",
                request_id,
                request.method,
                path,
                addr,
                response.status_code,
                elapsed_ms,
            )
        else:
            log.debug(
                "[REQUEST][%s] %s %s from %s -> %s in %.1fms",
                request_id,
                request.method,
                path,
                addr,
                response.status_code,
                elapsed_ms,
            )
        return response


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
        notification_service = getattr(_app.state, "notification_service", None)
        if notification_service is not None:
            try:
                notification_service.set_event_loop(loop)
            except Exception:
                pass
        activity_logger = getattr(_app.state, "activity_logger", None)
        if activity_logger is not None:
            try:
                activity_logger.set_event_loop(loop)
            except Exception:
                pass
        log.info("Device Farm server started")

        try:
            from auth.secret_versioning import reload_jwt_secrets

            reload_jwt_secrets()
        except Exception as exc:
            log.warning("JWT secret store init skipped: %s", exc)

        # Single lifecycle owner for this app run.
        # subprocess, or async-closeable resource registers here so shutdown
        # tears them down in reverse-phase order with per-entry timeout.
        lifecycle = LifecycleManager()
        _app.state.lifecycle = lifecycle

        lifecycle.register_task(
            LifecyclePhase.BACKGROUND, "heartbeat", lambda: heartbeat(manager),
        )

        if config.database.enabled:

            async def _account_maintenance_loop() -> None:
                import asyncio as _aio
                from services.account_manager import (
                    check_and_reset_cooldowns,
                    reset_daily_usage,
                )

                tick = 0
                while True:
                    await _aio.sleep(60)
                    tick += 1
                    try:
                        await check_and_reset_cooldowns()
                    except Exception as exc:
                        log.warning("account cooldown reset failed: %s", exc)
                    if tick % 288 == 0:
                        try:
                            await reset_daily_usage()
                        except Exception as exc:
                            log.warning("account daily usage reset failed: %s", exc)

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "account-maintenance",
                _account_maintenance_loop,
            )

            async def _dlq_maintenance_loop() -> None:
                from services.dlq_periodic import dlq_stale_offline_maintenance_loop

                await dlq_stale_offline_maintenance_loop(manager=manager)

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "dlq-maintenance",
                _dlq_maintenance_loop,
            )

        # ── Prometheus metrics collector (tạm tắt) ──
        # async def _metrics_collector() -> None:
        #     from web.metrics import (
        #         devices_online, devices_by_state, relay_agents_connected,
        #         relay_devices_total, task_queue_depth,
        #     )
        #     from runtime.core.device_client import DeviceState
        #     while True:
        #         try:
        #             all_devs = manager.all_devices()
        #             devices_online.set(len(all_devs))
        #             state_counts: dict[str, int] = {}
        #             for d in all_devs:
        #                 s = d.state.name if isinstance(d.state, DeviceState) else str(d.state)
        #                 state_counts[s] = state_counts.get(s, 0) + 1
        #             for state_name, count in state_counts.items():
        #                 devices_by_state.labels(state=state_name).set(count)
        #             task_queue_depth.set(queue.size() if hasattr(queue, "size") else len(queue))
        #             try:
        #                 from runtime.transports.adb_relay_server import get_relay_manager
        #                 rmgr = get_relay_manager()
        #                 if rmgr is not None:
        #                     relay_agents_connected.set(len(rmgr.registered_relays()))
        #                     relay_devices_total.set(len(rmgr.list_devices()))
        #                 else:
        #                     relay_agents_connected.set(0)
        #                     relay_devices_total.set(0)
        #             except Exception:
        #                 pass
        #         except Exception:
        #             pass
        #         await asyncio.sleep(15)
        # asyncio.create_task(_metrics_collector())
        # Schedule daily event cleanup (keep 30 days)
        if event_recorder is not None:
            async def _event_cleanup_loop() -> None:
                import asyncio as _aio
                while True:
                    await _aio.sleep(86400)  # 24h
                    await event_recorder.cleanup_old_events(keep_days=30)
            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "event-cleanup-loop",
                _event_cleanup_loop,
            )
        if config.database.enabled:
            from runtime.db_health import DbHealthMonitor, db_ping_loop

            db_health = DbHealthMonitor()
            _app.state.db_health = db_health

            async def _session_idle_loop() -> None:
                import asyncio as _aio
                from auth.session_service import revoke_idle_sessions
                from db.database import AsyncSessionLocal

                while True:
                    await _aio.sleep(86400)
                    try:
                        async with AsyncSessionLocal() as db:
                            revoked = await revoke_idle_sessions(db)
                            await db.commit()
                            if revoked:
                                from auth.ws_session_registry import get_ws_session_registry

                                await get_ws_session_registry().close_sessions(revoked, code=4408)
                    except Exception as exc:
                        log.warning("session idle maintenance failed: %s", exc)

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "session-idle-maintenance",
                _session_idle_loop,
            )
            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "db-health-ping",
                lambda: db_ping_loop(db_health),
            )

            try:
                await init_db()
                log.info("PostgreSQL connected and tables ready")
                db_health.mark_connected()
                try:
                    from db.database import AsyncSessionLocal
                    from services.account_state import refresh_account_state_gauges

                    async with AsyncSessionLocal() as _gauge_db:
                        await refresh_account_state_gauges(_gauge_db)
                except Exception as gauge_exc:
                    log.debug("account_state gauge init skipped: %s", gauge_exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("PostgreSQL init failed; entering DB safe mode")
                db_health.mark_disconnected()
                log.warning(
                    "Continuing startup in DB safe mode — CRUD routes return SERVICE_DEGRADED"
                )

            # Phase 1 — crash recovery: mark executions stuck in 'running' (from a
            # crashed previous session) as failed + DLQ them so operators can retry.
            try:
                from services.crash_recovery import recover_stuck_executions
                await recover_stuck_executions(stale_after_minutes=5)
            except Exception as rec_exc:
                log.warning("crash recovery failed (non-fatal): %s", rec_exc)

            # Phase 2 — relay agent reconciliation: previous crash may have left
            # relay_agents rows with status='online'. Mark them offline so the UI
            # shows accurate state until agents reconnect.
            try:
                from db.database import AsyncSessionLocal as _AslRec
                from sqlalchemy import text as _text
                async with _AslRec() as _db:
                    await _db.execute(_text(
                        "UPDATE relay_agents SET status='offline', disconnected_at=NOW(), serials='[]'::json "
                        "WHERE status='online'"
                    ))
                    await _db.commit()
            except Exception as _rec_exc:
                log.warning("relay agent reconciliation failed (non-fatal): %s", _rec_exc)

            try:
                from services.device_state import start_agent_state_consumer

                start_agent_state_consumer()
            except Exception as fsm_exc:
                log.warning("device FSM consumer start failed (non-fatal): %s", fsm_exc)

            try:
                from services.device_state.ws_publisher import publisher as lifecycle_publisher

                lifecycle_publisher.set_event_loop(loop)
                lifecycle_publisher.start()
                _app.state.lifecycle_publisher = lifecycle_publisher
                lifecycle.register_sync_resource(
                    LifecyclePhase.EGRESS,
                    "lifecycle-publisher",
                    lifecycle_publisher.stop,
                )
            except Exception as pub_exc:
                log.warning("device lifecycle WS publisher start failed (non-fatal): %s", pub_exc)

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "device-fsm-reconcile",
                lambda: __import__(
                    "services.device_state.reconcile",
                    fromlist=["device_fsm_reconcile_loop"],
                ).device_fsm_reconcile_loop(),
            )

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "device-dead-detection",
                lambda: __import__(
                    "services.device_state.dead_detector",
                    fromlist=["dead_detection_loop"],
                ).dead_detection_loop(),
            )

        # ── Redis shared state ──
        from services import redis_store
        await redis_store.init(config.redis)
        lifecycle.register_resource(
            LifecyclePhase.INFRA, "redis_store", redis_store.close,
        )

        # Dispose the main event loop's SQLAlchemy engine on shutdown so
        # asyncpg's pool closes deterministically before uvicorn exits.
        from db.database import dispose_loop_engine
        lifecycle.register_resource(
            LifecyclePhase.INFRA, "db_loop_engine", dispose_loop_engine,
        )
        if redis_store.enabled():
            import json as _json
            try:
                _redis_devs = await redis_store.client().hgetall(redis_store.key("devices"))
                for _serial in _redis_devs:
                    manager.ensure_device(_serial)
                if _redis_devs:
                    log.info("Restored %d device(s) from Redis", len(_redis_devs))
            except Exception as _exc:
                log.warning("Redis device restore failed: %s", _exc)

        # ── Start lifecycle components attached by main.py ──
        watchdog = getattr(_app.state, "watchdog", None)
        dispatcher = getattr(_app.state, "dispatcher", None)

        if watchdog is not None:
            watchdog.start_watchdog()
            log.info("Watchdog started")
            lifecycle.register_sync_resource(
                LifecyclePhase.CONTROL, "watchdog", watchdog.stop_watchdog,
            )
        if dispatcher is not None:
            dispatcher.start_dispatcher()
            log.info("Dispatcher started")
            lifecycle.register_sync_resource(
                LifecyclePhase.CONTROL, "dispatcher", dispatcher.stop_dispatcher,
            )

        # ── Scheduler setup (DF-008) ──────────────────────────────────────
        temporal_client = None
        temporal_threads: list = []
        if config.temporal.enabled:
            try:
                from temporal.worker import start_temporal_worker, get_temporal_client
                temporal_client = await get_temporal_client(config.temporal)
                temporal_threads = start_temporal_worker(manager, config.temporal, queue=queue)
                try:
                    from services.account_state import ensure_account_cooldown_schedule

                    await ensure_account_cooldown_schedule(
                        temporal_client,
                        task_queue=config.temporal.task_queue,
                    )
                except Exception as sched_exc:
                    log.warning(
                        "Account cooldown Temporal schedule registration failed: %s",
                        sched_exc,
                    )
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
            lifecycle.register_resource(
                LifecyclePhase.CONTROL, "scheduler_engine", scheduler_engine.stop,
            )

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

                # gRPC relay starts after FSM/relay callbacks are wired (see below).

                # ── Persistence callbacks for AgentControlServicer ─────────────
                if config.database.enabled:
                    try:
                        from runtime.transports.agent_control_servicer import get_control_servicer
                        from db import crud as _ctrl_repo
                        from db.database import AsyncSessionLocal as _AslCtrl
                        from tenancy.context import tenant_context

                        def _relay_ownership_required() -> bool:
                            raw = os.getenv("RELAY_AGENT_OWNERSHIP_REQUIRED", "").strip().lower()
                            if raw:
                                return raw in {"1", "true", "yes", "on"}
                            return True

                        async def _on_ctrl_register(payload: dict) -> bool:
                            async with _AslCtrl() as _db:
                                try:
                                    org_id: str | None = None
                                    enrollment_token = str(payload.pop("enrollment_token", "") or "").strip()
                                    if not enrollment_token:
                                        if _relay_ownership_required():
                                            log.warning(
                                                "relay register rejected: missing enrollment token relay_id=%s",
                                                payload.get("relay_id", ""),
                                            )
                                            return False
                                        org_id = await _ctrl_repo.lookup_relay_agent_org_id(
                                            _db, str(payload.get("relay_id", ""))
                                        )
                                        if not org_id:
                                            log.warning(
                                                "relay register rejected: no org for relay_id=%s "
                                                "(enrollment token required for new relays)",
                                                payload.get("relay_id", ""),
                                            )
                                            return False
                                    else:
                                        identity = await _ctrl_repo.lookup_relay_token_enrollment(
                                            _db, enrollment_token
                                        )
                                        if identity is None:
                                            log.warning(
                                                "relay register rejected: invalid enrollment token relay_id=%s",
                                                payload.get("relay_id", ""),
                                            )
                                            return False
                                        org_id, user_id, token_id = identity
                                        payload["user_id"] = user_id
                                        payload["enrollment_token_id"] = token_id

                                    with tenant_context(org_id):
                                        if enrollment_token:
                                            await _ctrl_repo.resolve_relay_agent_token(
                                                _db, enrollment_token
                                            )
                                        await _ctrl_repo.upsert_relay_agent(
                                            _db, org_id=org_id, **payload
                                        )
                                        await _db.commit()
                                    return True
                                except Exception as _exc:
                                    await _db.rollback()
                                    log.warning("relay upsert failed: %s", _exc)
                                    return False

                        async def _on_ctrl_heartbeat(payload: dict) -> None:
                            relay_id = str(payload.get("relay_id", ""))
                            async with _AslCtrl() as _db:
                                try:
                                    org_id = await _ctrl_repo.lookup_relay_agent_org_id(_db, relay_id)
                                    if not org_id:
                                        return
                                    with tenant_context(org_id):
                                        await _ctrl_repo.update_relay_heartbeat(_db, **payload)
                                        await _db.commit()
                                except Exception as _exc:
                                    await _db.rollback()
                                    log.debug("relay heartbeat update failed: %s", _exc)

                        async def _on_ctrl_offline(relay_id: str) -> None:
                            async with _AslCtrl() as _db:
                                try:
                                    org_id = await _ctrl_repo.lookup_relay_agent_org_id(_db, relay_id)
                                    if not org_id:
                                        return
                                    with tenant_context(org_id):
                                        await _ctrl_repo.mark_relay_offline(_db, relay_id)
                                        await _db.commit()
                                except Exception as _exc:
                                    await _db.rollback()
                                    log.warning("relay offline mark failed: %s", _exc)

                        _ctrl_svc = get_control_servicer()
                        if _ctrl_svc is not None:
                            _ctrl_svc.set_persistence_callbacks(
                                _on_ctrl_register, _on_ctrl_heartbeat, _on_ctrl_offline
                            )
                            log.info("AgentControlServicer persistence callbacks wired")
                    except Exception as _cb_exc:
                        log.warning("Could not wire control servicer callbacks: %s", _cb_exc)

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
                        running = asyncio.get_running_loop()
                    except RuntimeError:
                        running = None
                    if running is ml:
                        
                        log.debug(
                            "relay_scrcpy DB pref: skip blocking lookup (same event loop); "
                            "default allow serial=%s",
                            serial_check,
                        )
                        return True
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

                def _schedule_relay_fsm(coro) -> None:
                    ml = getattr(_app.state, "main_loop", None)
                    if ml is None:
                        log.debug("relay FSM schedule skipped: main_loop unset")
                        return
                    try:
                        running = asyncio.get_running_loop()
                    except RuntimeError:
                        running = None
                    try:
                        if running is ml:
                            asyncio.create_task(coro)
                        else:
                            asyncio.run_coroutine_threadsafe(coro, ml)
                    except Exception as exc:
                        log.warning("relay FSM schedule failed: %s", exc)

                async def _run_relay_fsm_online(
                    relay_serial: str,
                    *,
                    logical_serial: str | None = None,
                    hardware_serial: str | None = None,
                ) -> None:
                    from services.device_state.relay_bridge import apply_relay_online

                    try:
                        await apply_relay_online(
                            relay_serial,
                            logical_serial=logical_serial,
                            hardware_serial=hardware_serial,
                        )
                    except Exception as exc:
                        log.warning(
                            "relay FSM online failed serial=%s: %s",
                            relay_serial,
                            exc,
                        )

                async def _run_relay_fsm_offline(
                    relay_serial: str,
                    *,
                    logical_serial: str | None = None,
                    hardware_serial: str | None = None,
                ) -> None:
                    from services.device_state.relay_bridge import apply_relay_offline

                    try:
                        await apply_relay_offline(
                            relay_serial,
                            logical_serial=logical_serial,
                            hardware_serial=hardware_serial,
                        )
                    except Exception as exc:
                        log.warning(
                            "relay FSM offline failed serial=%s: %s",
                            relay_serial,
                            exc,
                        )

                def _emit_relay_fsm_online(
                    relay_serial: str,
                    *,
                    logical_serial: str | None = None,
                    hardware_serial: str | None = None,
                ) -> None:
                    _schedule_relay_fsm(
                        _run_relay_fsm_online(
                            relay_serial,
                            logical_serial=logical_serial,
                            hardware_serial=hardware_serial,
                        )
                    )

                def _emit_relay_fsm_offline(
                    relay_serial: str,
                    *,
                    logical_serial: str | None = None,
                    hardware_serial: str | None = None,
                ) -> None:
                    _schedule_relay_fsm(
                        _run_relay_fsm_offline(
                            relay_serial,
                            logical_serial=logical_serial,
                            hardware_serial=hardware_serial,
                        )
                    )

                def _on_relay_device_online(serial: str) -> None:
                    _emit_relay_fsm_online(serial)
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
                        current_adb_serial = str(getattr(ws_device, "_adb_serial", "") or "")
                        # Sticky mapping: when one WS device is "lone match" for multiple
                        # relay serials (e.g. dual devices .83/.86), do not thrash scrcpy
                        # attach between serials. Keep whichever relay serial is already
                        # selected on the device unless this is the first bind.
                        if current_adb_serial and current_adb_serial != serial:
                            log.info(
                                "relay device online %s — skip reattach for WS device %s "
                                "(sticky _adb_serial=%s)",
                                serial,
                                ws_device.serial,
                                current_adb_serial,
                            )
                            return
                        if not current_adb_serial:
                            try:
                                ws_device._adb_serial = serial
                            except Exception:
                                pass
                        ws_device.set_event_loop(asyncio.get_event_loop())
                        _st = getattr(_config_ref, "streaming", None)
                        _relay_auto = bool(
                            getattr(_st, "auto_attach_scrcpy_on_relay_online", True)
                        )
                        if _relay_auto and _relay_db_allows_scrcpy(ws_device.serial):
                            _RELAY_ATTACH_POOL.submit(
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
                        _RELAY_ATTACH_POOL.submit(
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

                def _on_relay_device_offline(serial: str) -> None:
                    _emit_relay_fsm_offline(serial)

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
                    hw = str(caps.get("hardware_serial") or "").strip()
                    if hw and (":" in serial or serial != hw):
                        _emit_relay_fsm_online(serial, hardware_serial=hw)

                relay_manager.set_on_device_online(_on_relay_device_online)
                relay_manager.set_on_device_offline(_on_relay_device_offline)
                relay_manager.set_on_capabilities_update(_on_relay_capabilities_update)

                # ── gRPC relay server (after callbacks — avoids missed register events) ──
                try:
                    from runtime.transports.grpc_relay_server import start_grpc_server
                    grpc_port = getattr(config.relay, "port", 50051)
                    grpc_server = await start_grpc_server(
                        relay_manager,
                        api_key=config.relay.api_key or None,
                        port=grpc_port,
                        tls_cert_file=getattr(config.relay, "tls_cert_file", ""),
                        tls_key_file=getattr(config.relay, "tls_key_file", ""),
                        allow_insecure=bool(getattr(config.relay, "allow_insecure_grpc", True)),
                    )
                    _app.state.grpc_server = grpc_server
                    log.info("gRPC relay server ready on port %d", grpc_port)

                    async def _stop_grpc() -> None:
                        try:
                            await grpc_server.stop(grace=5)
                        except Exception as exc:
                            log.warning("gRPC relay stop error: %s", exc)

                    lifecycle.register_resource(
                        LifecyclePhase.TRANSPORT, "grpc_relay", _stop_grpc,
                    )
                except Exception as grpc_exc:
                    log.warning("gRPC relay server failed to start (WS fallback active): %s", grpc_exc)

                async def _bootstrap_relay_fsm_states() -> None:
                    await asyncio.sleep(3.0)
                    from services.device_state.relay_bridge import apply_relay_online

                    for serial in relay_manager.list_online_serials():
                        caps = relay_manager.get_capabilities(serial) or {}
                        hw = str(caps.get("hardware_serial") or "").strip() or None
                        try:
                            await apply_relay_online(serial, hardware_serial=hw)
                        except Exception as exc:
                            log.warning(
                                "relay FSM bootstrap failed serial=%s: %s",
                                serial,
                                exc,
                            )

                _schedule_relay_fsm(_bootstrap_relay_fsm_states())
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

        # Register ngrok teardown late so it runs in EGRESS (fired first).
        if ngrok_tunnel is not None:
            def _kill_ngrok() -> None:
                try:
                    import pyngrok
                    pyngrok.ngrok.disconnect(ngrok_tunnel.public_url)
                    pyngrok.ngrok.kill()
                except Exception:
                    pass
            lifecycle.register_sync_resource(
                LifecyclePhase.EGRESS, "ngrok_tunnel", _kill_ngrok,
            )

        await lifecycle.shutdown()
        try:
            manager.teardown_all()
        except Exception as exc:
            log.warning("manager.teardown_all error: %s", exc)
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

    cors_allow_all = bool(getattr(config.web, "cors_allow_all", False))
    cors_allowed_origins = (
        ["*"]
        if cors_allow_all
        else [origin.strip() for origin in (config.web.cors_allowed_origins or []) if origin.strip()]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False if cors_allow_all else bool(cors_allowed_origins),
    )
    if db_enabled:
        from services.user_action_audit import UserActionAuditMiddleware
        from web.db_safe_mode import DbSafeModeMiddleware

        app.add_middleware(DbSafeModeMiddleware)
        app.add_middleware(UserActionAuditMiddleware)
    app.add_middleware(RequestLogMiddleware)

    # Observe-only / low-bandwidth gates. Toggled via config.safe_mode or
    # env (FARM_READ_ONLY, FARM_STREAM_HIERARCHY).
    from web.safe_mode import SafeModeMiddleware, build_safe_mode_router
    safe_mode = config.safe_mode
    if safe_mode.read_only or not safe_mode.stream_hierarchy:
        app.add_middleware(
            SafeModeMiddleware,
            read_only=safe_mode.read_only,
            stream_hierarchy=safe_mode.stream_hierarchy,
        )
        log.info(
            "safe_mode active: read_only=%s stream_hierarchy=%s",
            safe_mode.read_only, safe_mode.stream_hierarchy,
        )
    app.include_router(
        build_safe_mode_router(
            read_only=safe_mode.read_only,
            stream_hierarchy=safe_mode.stream_hierarchy,
        ),
        prefix="/api",
    )

    # ── Prometheus instrumentation (tạm tắt) ──
    # from prometheus_fastapi_instrumentator import Instrumentator
    # Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    # ── Health endpoints ──
    @app.get("/health")
    async def root_health():
        return {"status": "alive", "ts": int(time.time())}

    @app.get("/health/ready")
    async def root_readiness():
        monitor = getattr(app.state, "db_health", None)
        if monitor is not None and getattr(monitor, "safe_mode", False):
            from fastapi.responses import JSONResponse

            return JSONResponse({"status": "degraded"}, status_code=503)
        if db_enabled:
            try:
                from sqlalchemy import text as sa_text
                from db.database import AsyncSessionLocal

                async with AsyncSessionLocal() as session:
                    await session.execute(sa_text("SELECT 1"))
            except Exception:
                from fastapi.responses import JSONResponse

                return JSONResponse({"status": "degraded"}, status_code=503)
        return {"status": "ready"}

    @app.get("/api/server/status")
    async def api_server_status():
        monitor = getattr(app.state, "db_health", None)
        if monitor is None:
            return {
                "safe_mode": False,
                "db_connected": bool(db_enabled),
                "version": "1.0.0",
                "started_at": time.time(),
            }
        return monitor.status_payload()

    @app.get("/api/server/version")
    async def api_server_version():
        commit = (os.environ.get("GIT_COMMIT") or os.environ.get("BUILD_COMMIT") or "").strip()
        if not commit:
            try:
                import subprocess

                commit = (
                    subprocess.check_output(
                        ["git", "rev-parse", "--short", "HEAD"],
                        cwd=str(Path(__file__).resolve().parents[1]),
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip()
                )
            except Exception:
                commit = "unknown"
        build_time = (os.environ.get("BUILD_TIME") or "").strip() or None
        return {
            "version": "1.0.0",
            "commit": commit,
            "build_time": build_time,
        }

    @app.get("/api/live")
    async def liveness():
        return {"status": "ok"}

    @app.get("/api/ready")
    async def readiness():
        checks: dict = {"status": "ok", "devices": len(manager.all_devices())}
        if db_enabled:
            try:
                from sqlalchemy import text as sa_text
                from db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    await session.execute(sa_text("SELECT 1"))
                checks["db"] = "ok"
            except Exception:
                checks["db"] = "fail"
                checks["status"] = "degraded"
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            rmgr = get_relay_manager()
            checks["relay_agents"] = len(rmgr.registered_relays()) if rmgr else 0
        except Exception:
            checks["relay_agents"] = 0
        return checks

    @app.get("/api/health")
    async def health():
        return {"status": "alive", "ts": int(time.time())}

    @app.get("/api/relay/status")
    async def relay_status(_: AdminUser):
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
    # _screenshots_dir = Path("screenshots")
    # _screenshots_dir.mkdir(exist_ok=True)
    # app.mount("/screenshots", StaticFiles(directory=str(_screenshots_dir)), name="screenshots")

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

    ws_manager = WebSocketManager(
        manager,
        db_enabled=db_enabled,
        read_only=config.safe_mode.read_only,
    )
    app.state.ws_manager = ws_manager
    lifecycle_ws_manager = DeviceLifecycleWsManager()
    app.state.lifecycle_ws_manager = lifecycle_ws_manager
    if db_enabled:
        try:
            from services.device_state.ws_publisher import publisher as lifecycle_publisher

            lifecycle_ws_manager.bind_publisher(lifecycle_publisher)
        except Exception as exc:
            log.warning("lifecycle WS publisher bind failed: %s", exc)
    if event_recorder is not None:
        ws_manager.bind_event_recorder(event_recorder)
    if db_enabled:
        try:
            from services.notification_service import NotificationService
            from services.activity_logger import ActivityLogger

            notification_service = NotificationService(ws_manager)
            if event_recorder is not None:
                notification_service.bind_device_events(event_recorder)
            app.state.notification_service = notification_service

            activity_logger = ActivityLogger()
            if event_recorder is not None:
                activity_logger.bind_device_events(event_recorder)
            app.state.activity_logger = activity_logger
        except Exception as exc:
            log.warning("notification/activity service failed to initialize: %s", exc)
    agent_session = DeviceAgentSession(manager, ws_manager, config)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        user_id: Optional[str] = None
        session_id: Optional[str] = None
        if db_enabled:
            ctx = await authenticate_ws(ws)
            if ctx is None:
                from services.security_audit import emit_security_event
                from db.database import AsyncSessionLocal

                try:
                    async with AsyncSessionLocal() as db:
                        await emit_security_event(
                            db,
                            action="ws.auth.rejected",
                            ip_address=ws.client.host if ws.client else None,
                            user_agent=ws.headers.get("user-agent"),
                        )
                        await db.commit()
                except Exception:
                    pass
                await ws.close(code=4401)
                return
            user_id = ctx.user_id
            session_id = ctx.session_id
            try:
                from services.security_audit import emit_security_event
                from db.database import AsyncSessionLocal

                async with AsyncSessionLocal() as db:
                    await emit_security_event(
                        db,
                        action="ws.connected",
                        user_id=user_id,
                        entity_type="session",
                        entity_id=session_id,
                        ip_address=ws.client.host if ws.client else None,
                        user_agent=ws.headers.get("user-agent"),
                    )
                    await db.commit()
            except Exception:
                pass
        await ws_manager.connect(ws, user_id=user_id, session_id=session_id)

    @app.websocket("/ws/lifecycle")
    async def lifecycle_websocket_endpoint(ws: WebSocket):
        if not db_enabled:
            await ws.close(code=4503, reason="lifecycle stream requires database mode")
            return
        await lifecycle_ws_manager.connect(ws)

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
