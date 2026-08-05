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
from urllib.parse import urlencode
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


class _RelayBootstrapGate:
    def __init__(
        self,
        *,
        cooldown_s: float | None = None,
        clock=time.monotonic,
    ) -> None:
        self._cooldown_s = (
            float(os.getenv("DEVICE_FARM_RELAY_BOOTSTRAP_COOLDOWN_S", "60"))
            if cooldown_s is None
            else float(cooldown_s)
        )
        self._clock = clock
        self._inflight: set[str] = set()
        self._last_attempt_at: dict[str, float] = {}

    def acquire(
        self,
        serial: str,
        *,
        has_runtime_u2: bool = False,
        caps: dict | None = None,
    ) -> tuple[bool, str]:
        serial = str(serial or "").strip()
        if not serial:
            return False, "empty-serial"
        if has_runtime_u2 or bool((caps or {}).get("has_u2")):
            return False, "u2-ready"
        if serial in self._inflight:
            return False, "in-flight"
        now = self._clock()
        last = self._last_attempt_at.get(serial)
        if last is not None and (now - last) < self._cooldown_s:
            return False, "cooldown"
        self._inflight.add(serial)
        self._last_attempt_at[serial] = now
        return True, "queued"

    def release(self, serial: str) -> None:
        self._inflight.discard(str(serial or "").strip())


def _relay_discovery_bootstrap_decision() -> tuple[bool, str]:
    """Relay discovery never performs heavy bootstrap work.

    Discovery must only publish that a phone exists. Installing STF/u2/atx
    assets is an explicit register/pair/bootstrap action, otherwise 40 newly
    plugged phones can monopolize the shared ADB server before a user chooses
    which phones to use.
    """
    return False, "discovery-gated"


async def _run_relay_bootstrap_bounded(
    relay_manager,
    slots: asyncio.Semaphore,
    serial: str,
    device,
    bind_relay_u2,
) -> bool | None:
    async with slots:
        if relay_manager.relay_for_serial(serial) is None:
            return None
        ok = await relay_manager.bootstrap(serial)
        caps = relay_manager.get_capabilities(serial) or {}
        bind_relay_u2(device, serial, caps=caps)
        return ok


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
from .ws import (
    WebSocketManager,
    DeviceAgentSession,
    authenticate_ws,
    heartbeat,
    _relay_scrcpy_auto_attach_allowed_for_serial,
)
from .ws_lifecycle import DeviceLifecycleWsManager

log = logging.getLogger(__name__)
api_trace_log = importlib.import_module("structlog").get_logger("api_trace")
STREAM_GUARDRAIL_WARN_INTERVAL_S = max(
    1.0,
    float(os.getenv("DEVICE_FARM_STREAM_GUARDRAIL_WARN_INTERVAL_S", "15")),
)
STREAM_GUARDRAIL_WS_WAIT_P95_WARN_MS = max(
    1.0,
    float(os.getenv("DEVICE_FARM_STREAM_GUARDRAIL_WS_WAIT_P95_WARN_MS", "5")),
)
STREAM_GUARDRAIL_WS_DROPS_WARN = max(
    1,
    int(os.getenv("DEVICE_FARM_STREAM_GUARDRAIL_WS_DROPS_WARN", "1")),
)
_last_stream_guardrail_warning_at = 0.0


def _stream_guardrail_status(
    *,
    stream_telemetry: dict,
    websocket_streams: dict,
) -> dict:
    """Summarize stream isolation/backpressure health for operator scans."""
    violations: list[str] = []
    max_streams_per_connection = int(
        websocket_streams.get("max_media_streams_per_connection") or 0
    )
    shared_connections = int(
        websocket_streams.get("shared_media_ws_connections") or 0
    )
    ws_dropped = int(stream_telemetry.get("ws_dropped") or 0)
    ws_wait_p95_ms = float(stream_telemetry.get("ws_send_wait_p95_ms") or 0.0)

    if shared_connections > 0 or max_streams_per_connection > 1:
        violations.append("shared_media_ws")
    if ws_dropped >= STREAM_GUARDRAIL_WS_DROPS_WARN:
        violations.append("ws_drops")
    if ws_wait_p95_ms > STREAM_GUARDRAIL_WS_WAIT_P95_WARN_MS:
        violations.append("ws_send_wait_p95")

    return {
        "ok": not violations,
        "violations": violations,
        "thresholds": {
            "ws_send_wait_p95_warn_ms": STREAM_GUARDRAIL_WS_WAIT_P95_WARN_MS,
            "ws_drops_warn": STREAM_GUARDRAIL_WS_DROPS_WARN,
        },
        "observed": {
            "max_media_streams_per_connection": max_streams_per_connection,
            "shared_media_ws_connections": shared_connections,
            "ws_dropped": ws_dropped,
            "ws_send_wait_p95_ms": ws_wait_p95_ms,
            "top_dropped_serials": websocket_streams.get("top_dropped_serials")
            or [],
        },
    }


def _warn_stream_guardrail_if_needed(
    *,
    stream_guardrail: dict,
    now: float | None = None,
) -> None:
    """Throttle stream guardrail warnings to keep `/api/relay/status` safe."""
    global _last_stream_guardrail_warning_at
    if stream_guardrail.get("ok") is True:
        return
    now = time.monotonic() if now is None else now
    if (now - _last_stream_guardrail_warning_at) < STREAM_GUARDRAIL_WARN_INTERVAL_S:
        return
    _last_stream_guardrail_warning_at = now
    observed = stream_guardrail.get("observed") or {}
    log.warning(
        "stream guardrail violation: violations=%s max_streams_per_connection=%s "
        "shared_connections=%s ws_dropped=%s ws_send_wait_p95_ms=%s "
        "top_dropped_serials=%s",
        stream_guardrail.get("violations") or [],
        observed.get("max_media_streams_per_connection"),
        observed.get("shared_media_ws_connections"),
        observed.get("ws_dropped"),
        observed.get("ws_send_wait_p95_ms"),
        observed.get("top_dropped_serials"),
    )


def _relay_device_ip(serial: str) -> str:
    serial = str(serial or "").strip()
    return serial.rsplit(":", 1)[0] if ":" in serial else serial


def _relay_cap_hardware_serial(caps: dict | None) -> str:
    return str((caps or {}).get("hardware_serial") or "").strip()


def _relay_serial_matches_ws_device(
    device,
    relay_serial: str,
    *,
    caps: dict | None = None,
) -> bool:
    """Return True only for explicit relay-to-logical device matches."""
    if device is None:
        return False
    relay_serial = str(relay_serial or "").strip()
    if not relay_serial or getattr(device, "serial", None) == relay_serial:
        return False

    hardware_serial = _relay_cap_hardware_serial(caps)
    if hardware_serial and getattr(device, "serial", None) == hardware_serial:
        return True

    device_ip = _relay_device_ip(relay_serial)
    adb_serial = str(getattr(device, "_adb_serial", "") or "").strip()
    u2_host = str(getattr(device, "_u2_host", "") or "").strip()
    return bool(
        adb_serial == relay_serial
        or (device_ip and adb_serial.startswith(device_ip + ":"))
        or (device_ip and u2_host == device_ip)
    )


def _relay_capabilities_status_payload(device, caps: dict | None) -> dict:
    """Build metadata from relay heartbeat without reviving watchdog-dead devices."""
    caps = caps or {}
    payload = {
        "brand":         caps.get("brand", ""),
        "model":         caps.get("model", ""),
        "android":       caps.get("android_version", ""),
        "screen_width":  caps.get("screen_width", 0),
        "screen_height": caps.get("screen_height", 0),
    }
    state = getattr(device, "state", None)
    state_value = str(getattr(state, "value", state) or "").upper()
    if state_value in {"DISCONNECTED", "CONNECTING", "ERROR"}:
        payload["state"] = "READY"
    return payload


def _find_ws_device_for_relay_serial(
    devices,
    relay_serial: str,
    *,
    caps: dict | None = None,
):
    """Find the WS logical DeviceClient for a relay serial without guessing."""
    return next(
        (
            device
            for device in devices
            if _relay_serial_matches_ws_device(device, relay_serial, caps=caps)
        ),
        None,
    )


def _relay_has_active_scrcpy_viewers(serial: str) -> bool:
    try:
        from api.routes.device_control.scrcpy import has_active_scrcpy_viewers

        return has_active_scrcpy_viewers(serial)
    except Exception as exc:
        log.debug("scrcpy viewer state unavailable for relay online %s: %s", serial, exc)
        return False


def _relay_should_attach_scrcpy_on_online(device_serial: str, *, auto_attach: bool) -> bool:
    return bool(auto_attach or _relay_has_active_scrcpy_viewers(device_serial))


def _relay_auto_attach_scrcpy_on_relay_online(config_ref) -> bool:
    streaming = getattr(config_ref, "streaming", None)
    return bool(getattr(streaming, "auto_attach_scrcpy_on_relay_online", False))


def _mark_relay_scrcpy_offline(device, relay_serial: str) -> bool:
    marker = getattr(device, "mark_scrcpy_relay_offline", None)
    if marker is None:
        return False
    try:
        return bool(marker(relay_serial))
    except Exception as exc:
        log.warning("relay device offline %s - failed to mark scrcpy inactive: %s", relay_serial, exc)
        return False


class RequestLogMiddleware(BaseHTTPMiddleware):

    _SENSITIVE_QUERY_KEYS = frozenset(
        {
            "access_token",
            "api_key",
            "device_control_key",
            "key",
            "pair",
            "password",
            "refresh_token",
            "secret",
            "token",
        }
    )

    @classmethod
    def _safe_query(cls, request: Request) -> str:
        pairs = [
            (
                key,
                "<REDACTED>"
                if key.strip().lower().replace("-", "_") in cls._SENSITIVE_QUERY_KEYS
                else value,
            )
            for key, value in request.query_params.multi_items()
        ]
        return urlencode(pairs)

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
            query=self._safe_query(request),
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
            from runtime.db_health import DbHealthMonitor, db_ping_loop

            db_health = DbHealthMonitor()
            _app.state.db_health = db_health

            try:
                await init_db()
                log.info("PostgreSQL connected and tables ready")
                db_health.mark_connected()
                try:
                    from db.database import AsyncSessionLocal
                    from services.account_state import refresh_account_state_gauges
                    from services.content.registry import init_registry

                    async with AsyncSessionLocal() as _gauge_db:
                        await refresh_account_state_gauges(_gauge_db)
                        await init_registry(_gauge_db)
                except Exception as gauge_exc:
                    log.debug("account_state gauge / content registry init skipped: %s", gauge_exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("PostgreSQL init failed; entering DB safe mode")
                db_health.mark_disconnected()
                import db.database as _db_mod

                _db_mod.schema_init_ok = False
                log.warning(
                    "Continuing startup in DB safe mode — CRUD routes return SERVICE_DEGRADED"
                )

            async def _account_maintenance_loop() -> None:
                import asyncio as _aio
                from services.account_manager import (
                    check_and_reset_cooldowns,
                    reset_daily_usage,
                )
                from services.account_state.temporal_schedule import (
                    COOLDOWN_TICK_INTERVAL_SECONDS,
                )

                tick = 0
                while True:
                    await _aio.sleep(COOLDOWN_TICK_INTERVAL_SECONDS)
                    tick += 1
                    try:
                        await check_and_reset_cooldowns()
                    except Exception as exc:
                        log.warning("account cooldown reset failed: %s", exc)
                    # 288 × 5 min ≈ 24 h — midnight-style daily usage reset
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

            async def _execution_event_outbox_loop() -> None:
                from services.execution.outbox_poller import execution_event_outbox_loop

                await execution_event_outbox_loop()

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "execution-event-outbox",
                _execution_event_outbox_loop,
            )

            async def _preview_artifact_purge_loop() -> None:
                from services.execution.preview_purge import preview_artifact_purge_loop

                await preview_artifact_purge_loop()

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "preview-artifact-purge",
                _preview_artifact_purge_loop,
            )

            async def _artifact_retention_loop() -> None:
                from services.content.extraction.retention import artifact_retention_loop

                await artifact_retention_loop()

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "artifact-retention",
                _artifact_retention_loop,
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
            db_health = _app.state.db_health

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

            # Phase 1/2 — only when migrations succeeded (schema matches ORM).
            from db.database import schema_init_ok as _schema_init_ok

            if _schema_init_ok is True:
                # Crash recovery: mark executions stuck in 'running' as failed + DLQ.
                try:
                    from services.crash_recovery import recover_stuck_executions

                    await recover_stuck_executions(stale_after_minutes=5)
                except Exception as rec_exc:
                    log.warning("crash recovery failed (non-fatal): %s", rec_exc)

                # Relay agent reconciliation: mark stale 'online' rows offline.
                try:
                    from db.database import AsyncSessionLocal as _AslRec
                    from sqlalchemy import text as _text

                    async with _AslRec() as _db:
                        await _db.execute(
                            _text(
                                "UPDATE relay_agents SET status='offline', "
                                "disconnected_at=NOW(), serials='[]'::json "
                                "WHERE status='online'"
                            )
                        )
                        await _db.commit()
                except Exception as _rec_exc:
                    log.warning("relay agent reconciliation failed (non-fatal): %s", _rec_exc)
            else:
                log.debug(
                    "skipping crash recovery and relay reconciliation "
                    "(schema_init_ok=%s)",
                    _schema_init_ok,
                )

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

            lifecycle.register_task(
                LifecyclePhase.BACKGROUND,
                "device-auto-release",
                lambda: __import__(
                    "services.device_state.auto_release_worker",
                    fromlist=["auto_release_loop"],
                ).auto_release_loop(),
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
        # Device registry is live-only: populated when agent-boot relay or WS
        # agent connects. Do not hydrate from Redis — stale entries would register
        # devices that are no longer online.

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
                _app.state.temporal_client = temporal_client
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
                _control_callbacks = None
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

                        _control_callbacks = (
                            _on_ctrl_register,
                            _on_ctrl_heartbeat,
                            _on_ctrl_offline,
                        )
                        _ctrl_svc = get_control_servicer()
                        if _ctrl_svc is not None:
                            _ctrl_svc.set_persistence_callbacks(*_control_callbacks)
                            log.info("AgentControlServicer persistence callbacks wired")
                    except Exception as _cb_exc:
                        log.warning("Could not wire control servicer callbacks: %s", _cb_exc)

                # Auto-attach scrcpy whenever a relay agent reports a new device.
                _relay_mgr_ref = relay_manager
                _manager_ref   = manager
                _config_ref    = config
                _relay_bootstrap_gate = _RelayBootstrapGate()
                try:
                    _relay_bootstrap_limit = int(
                        os.getenv("DEVICE_FARM_RELAY_BOOTSTRAP_CONCURRENCY", "4")
                    )
                except Exception:
                    _relay_bootstrap_limit = 4
                _relay_bootstrap_slots = asyncio.Semaphore(
                    max(1, min(16, _relay_bootstrap_limit))
                )

                async def _relay_db_allows_scrcpy(serial_check: str) -> bool:
                    return await _relay_scrcpy_auto_attach_allowed_for_serial(
                        serial_check,
                        db_enabled=bool(_config_ref.database.enabled),
                    )

                def _schedule_relay_fsm(coro) -> None:
                    ml = getattr(_app.state, "main_loop", None)
                    if ml is None:
                        log.debug("relay FSM schedule skipped: main_loop unset")
                        try:
                            coro.close()
                        except Exception:
                            pass
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
                        try:
                            coro.close()
                        except Exception:
                            pass

                async def _attach_relay_scrcpy_if_allowed(
                    *,
                    device,
                    relay_serial: str,
                    db_serial: str,
                    auto_attach: bool,
                    log_label: str,
                ) -> None:
                    if _relay_mgr_ref and _relay_mgr_ref.relay_for_serial(relay_serial) is None:
                        log.info(
                            "%s %s — skip scrcpy attach: relay disconnected",
                            log_label,
                            relay_serial,
                        )
                        return
                    if not await _relay_db_allows_scrcpy(db_serial):
                        log.info(
                            "%s %s — skip scrcpy attach (not registered/allowed for %s)",
                            log_label,
                            relay_serial,
                            db_serial,
                        )
                        return
                    _RELAY_ATTACH_POOL.submit(
                        device.attach_scrcpy_stream,
                        relay_serial,
                        None,
                        _config_ref.device.scrcpy_control,
                    )
                    log.info(
                        "%s %s — attach scrcpy (%s)",
                        log_label,
                        relay_serial,
                        "auto_attach" if auto_attach else "active_viewer",
                    )

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

                def _relay_host_hint(serial: str, caps: dict | None = None) -> str | None:
                    """WLAN IP from capabilities, else IP portion of relay ADB serial."""
                    wlan = str((caps or {}).get("wlan_ip") or "").strip()
                    if wlan and not wlan.startswith("127."):
                        return wlan
                    if ":" in serial:
                        ip = serial.rsplit(":", 1)[0].strip()
                        if ip and not ip.startswith("127."):
                            return ip
                    return None

                def _find_device_for_relay_serial(serial: str, *, caps: dict | None = None):
                    """Resolve DeviceClient for a relay ADB serial (WS logical or relay slot)."""
                    ws_device = _find_ws_device_for_relay_serial(
                        _manager_ref.all_devices(),
                        serial,
                        caps=caps,
                    )
                    if ws_device is not None:
                        return ws_device
                    return _manager_ref.get_device(serial)

                def _bind_relay_u2(device, serial: str, *, caps: dict | None = None) -> None:
                    if device is None:
                        return
                    host = _relay_host_hint(serial, caps)
                    try:
                        device.bind_relay_u2(serial, host=host)
                    except Exception as exc:
                        log.debug("relay u2 bind failed serial=%s: %s", serial, exc)

                def _mark_relay_runtime_ready(device) -> None:
                    if device is None:
                        return
                    from runtime.core.device_client import DeviceState

                    if device.state in (
                        DeviceState.DISCONNECTED,
                        DeviceState.CONNECTING,
                        DeviceState.ERROR,
                    ):
                        device.on_agent_status({"state": "READY"})

                async def _bootstrap_relay_device(serial: str, device) -> None:
                    """Bootstrap atx+u2 on agent-boot, then (re)bind cloud u2 session."""
                    if _relay_mgr_ref is None or device is None:
                        return
                    try:
                        ok = await _run_relay_bootstrap_bounded(
                            _relay_mgr_ref,
                            _relay_bootstrap_slots,
                            serial,
                            device,
                            _bind_relay_u2,
                        )
                        if ok is None:
                            log.info(
                                "relay bootstrap skipped for %s: relay disconnected",
                                serial,
                            )
                            return
                        log.info(
                            "relay bootstrap %s for %s",
                            "ok" if ok else "failed",
                            serial,
                        )
                    except Exception as exc:
                        log.warning("relay bootstrap error serial=%s: %s", serial, exc)
                    finally:
                        _relay_bootstrap_gate.release(serial)

                def _schedule_relay_bootstrap(serial: str, device, *, is_new: bool) -> None:
                    if _relay_mgr_ref is None or device is None:
                        return
                    allowed, discovery_reason = _relay_discovery_bootstrap_decision()
                    if not allowed:
                        log.info(
                            "relay bootstrap skipped serial=%s reason=%s",
                            serial,
                            discovery_reason,
                        )
                        return
                    caps = _relay_mgr_ref.get_capabilities(serial) or {}
                    queued, reason = _relay_bootstrap_gate.acquire(
                        serial,
                        has_runtime_u2=getattr(device, "u2", None) is not None,
                        caps=caps,
                    )
                    if not queued:
                        log.info(
                            "relay bootstrap skipped serial=%s reason=%s",
                            serial,
                            reason,
                        )
                        return
                    if is_new:
                        log.info("relay device online → queued bootstrap: %s", serial)
                    else:
                        log.info("relay reconnect → queued bootstrap: %s", serial)
                    _schedule_relay_fsm(_bootstrap_relay_device(serial, device))

                def _on_relay_device_online(serial: str) -> None:
                    _emit_relay_fsm_online(serial)
                    caps = (_relay_mgr_ref.get_capabilities(serial) or {}) if _relay_mgr_ref else {}
                    # Check if a WS-Agent device already exists for this IP.
                    # If so, reattach scrcpy for it (relay reconnect case).
                    ws_device = _find_ws_device_for_relay_serial(
                        _manager_ref.all_devices(),
                        serial,
                        caps=caps,
                    )
                    if ws_device is not None:
                        current_adb_serial = str(getattr(ws_device, "_adb_serial", "") or "")
                        # Sticky mapping: if a logical device already has an explicit
                        # relay identity, do not thrash scrcpy attach between serials.
                        # Keep the selected relay serial unless this is the first bind.
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
                        _relay_auto = _relay_auto_attach_scrcpy_on_relay_online(
                            _config_ref
                        )
                        _should_attach = _relay_should_attach_scrcpy_on_online(
                            ws_device.serial,
                            auto_attach=_relay_auto,
                        )
                        if _should_attach:
                            _schedule_relay_fsm(
                                _attach_relay_scrcpy_if_allowed(
                                    device=ws_device,
                                    relay_serial=serial,
                                    db_serial=ws_device.serial,
                                    auto_attach=_relay_auto,
                                    log_label=(
                                        "relay device online reattach for WS device "
                                        f"{ws_device.serial}"
                                    ),
                                )
                            )
                        else:
                            log.info(
                                "relay device online %s — skip scrcpy reattach (auto_attach_scrcpy_on_relay_online=false)",
                                serial,
                            )
                        _mark_relay_runtime_ready(ws_device)
                        _bind_relay_u2(ws_device, serial, caps=caps)
                        _schedule_relay_bootstrap(serial, ws_device, is_new=False)
                        return

                    is_new = _manager_ref.get_device(serial) is None
                    device = _manager_ref.register_relay_device(serial)
                    device.set_event_loop(asyncio.get_event_loop())
                    # Set READY immediately — relay reports it as online.
                    # Relay-only devices have no WS-Agent APK to call on_agent_status(),
                    # so without this the device stays DISCONNECTED and frontend shows "Offline".
                    _mark_relay_runtime_ready(device)
                    _bind_relay_u2(device, serial, caps=caps)
                    _schedule_relay_bootstrap(serial, device, is_new=is_new)
                    if is_new:
                        ws_manager.subscribe_device(device)
                    _relay_auto2 = _relay_auto_attach_scrcpy_on_relay_online(
                        _config_ref
                    )
                    _should_attach2 = _relay_should_attach_scrcpy_on_online(
                        serial,
                        auto_attach=_relay_auto2,
                    )
                    if _should_attach2:
                        _schedule_relay_fsm(
                            _attach_relay_scrcpy_if_allowed(
                                device=device,
                                relay_serial=serial,
                                db_serial=serial,
                                auto_attach=_relay_auto2,
                                log_label="relay device online",
                            )
                        )
                    else:
                        log.info(
                            "relay device online → skip auto-attach scrcpy (%s, auto_attach_scrcpy_on_relay_online=false)",
                            serial,
                        )

                def _on_relay_device_offline(serial: str) -> None:
                    _emit_relay_fsm_offline(serial)
                    device = _find_device_for_relay_serial(serial)
                    if device is not None and _mark_relay_scrcpy_offline(device, serial):
                        log.info("relay device offline %s — scrcpy marked inactive", serial)

                def _on_relay_capabilities_update(serial: str, caps: dict) -> None:
                    """Propagate relay heartbeat capabilities to DeviceClient metadata."""
                    # Keep DB FSM in sync while relay transport is live. USB devices
                    # use the same serial for relay + hardware_serial, so we must not
                    # gate this on NAT-style aliases (previously stuck RECONNECTING).
                    hw = str(caps.get("hardware_serial") or "").strip() or None
                    _emit_relay_fsm_online(serial, hardware_serial=hw)

                    device = _find_device_for_relay_serial(serial, caps=caps)
                    if device is None:
                        return
                    device.on_agent_status(
                        _relay_capabilities_status_payload(device, caps)
                    )
                    host = _relay_host_hint(serial, caps)
                    if device.u2 is None and (caps.get("has_u2") or host):
                        _bind_relay_u2(device, serial, caps=caps)
                    elif host and str(getattr(device, "_u2_host", "") or "") != host:
                        _bind_relay_u2(device, serial, caps=caps)

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
                        control_callbacks=_control_callbacks,
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
    app.state.config = config
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

    # Outermost: ensure CORS headers on early rejects (503 safe mode, etc.).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False if cors_allow_all else bool(cors_allowed_origins),
    )
    app.include_router(
        build_safe_mode_router(
            read_only=safe_mode.read_only,
            stream_hierarchy=safe_mode.stream_hierarchy,
        ),
        prefix="/api",
    )

    from web.metrics_endpoint import build_metrics_router

    app.include_router(build_metrics_router())

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
            from runtime.stream_telemetry import stream_telemetry

            stream_stats = stream_telemetry.snapshot(reset=False)
            websocket_streams = ws_manager.stream_runtime_status()
            stream_guardrail = _stream_guardrail_status(
                stream_telemetry=stream_stats,
                websocket_streams=websocket_streams,
            )
            _warn_stream_guardrail_if_needed(stream_guardrail=stream_guardrail)
            return {
                "relay_enabled": True,
                "agents": mgr.registered_relays(),
                "devices": mgr.list_devices(),
                "stream_telemetry": stream_stats,
                "websocket_streams": websocket_streams,
                "stream_guardrail": stream_guardrail,
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
        media_stream_enabled=not bool(config.streaming.webrtc_enabled),
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
            effective_org_id = ctx.org_id
            try:
                from services.security_audit import emit_security_event
                from db.database import AsyncSessionLocal
                from api.deps import resolve_effective_org_id_for_user_id

                async with AsyncSessionLocal() as db:
                    header_org = await resolve_effective_org_id_for_user_id(
                        ws, db, user_id
                    )
                    if header_org:
                        effective_org_id = header_org
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
        else:
            effective_org_id = None
        await ws_manager.connect(
            ws,
            user_id=user_id,
            org_id=effective_org_id,
            session_id=session_id,
        )

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
