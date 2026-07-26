"""
relay/agent.py — RelayAgent: WebSocket bidi stream + command dispatch.

1 WebSocket connection per agent.
Reconnect: jittered exponential backoff 0.5s → 60s.

Protocol:
  Text frames  → JSON control messages (register, heartbeat, result, ack, command, ...)
  Binary frames → scrcpy video (0x53 tag) or scrcpy control (0x43 tag)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
import struct
import threading
import uuid
import time
from typing import Any, Optional

from relay.adb           import (
    _list_serials, _adb_connect, _adb_shell,
    _restart_u2, _restart_atx, _probe_capabilities,
    _resolve_device_lan_ip, _run,
    _screencap, _bootstrap_device,
    lock_portrait_rotation,
    lock_rotation_after_shell_enabled,
    reconcile_usb_preferred_for_duplicate_devices,
)
from relay.mdns          import start_mdns_discovery
from relay.device_state  import DeviceRegistry, DeviceState
from relay.device_watcher import AdbDeviceWatcher
from relay.session_manager import ScrcpySessionManager
from relay.supervisor     import RelaySupervisor
from relay.u2_session_pool import U2SessionPool
from relay.runtime         import (
    SEND_CONTROL_MAX,
    SEND_PER_DEVICE_MAX,
    FairSendQueue,
    LoopWatchdog,
    RuntimeStats,
    TaskRegistry,
    adb_executor,
    bounded_put,
    bounded_put_nowait,
    cpu_executor,
    dumps,
    dumps_maybe_offload,
    extra_data_sem,
    generic_executor,
    init_executors,
    init_semaphores,
    register_stats_source,
    shutdown_executors,
    u2_batch_sem,
    u2_executor_pool,
    u2_flow_sem,
)

logger = logging.getLogger("relay.agent")


async def _await_executor_completion(future: asyncio.Future[Any]) -> Any:
    """Keep mutation guards active until blocking work really stops."""
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(future)
            break
        except asyncio.CancelledError:
            if future.cancelled():
                raise
            cancelled = True
        except Exception:
            if cancelled:
                raise asyncio.CancelledError
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result


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


SEMAPHORE_WAIT_WARN_MS = _env_float("RELAY_SEMAPHORE_WAIT_WARN_MS", 250.0)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _atx_forward_host() -> str:
    """Host for adb-forwarded atx-agent ports.

    With Docker using a remote host ADB server, `adb forward tcp:N tcp:7912`
    binds on the host machine, not inside the container.
    """
    override = os.getenv("ATX_FORWARD_HOST", "").strip()
    if override:
        return override
    sock = os.getenv("ADB_SERVER_SOCKET", "").strip()
    if sock.startswith("tcp:"):
        rest = sock[4:]
        if ":" in rest:
            host = rest.rsplit(":", 1)[0].strip()
            if host:
                return host
    adb_host = os.getenv("ADB_HOST", "").strip()
    if adb_host and adb_host not in ("127.0.0.1", "localhost"):
        return adb_host
    return "127.0.0.1"


def _looks_like_hierarchy_xml(body: str) -> bool:
    s = (body or "").strip()
    if not s or "<hierarchy" not in s:
        return False
    return not (
        s == "<hierarchy />"
        or s == '<?xml version="1.0" encoding="UTF-8"?><hierarchy />'
        or s.endswith("<hierarchy />")
    )


SCRCPY_RESTART_WINDOW_SECONDS = 120.0
SCRCPY_RESTART_MAX_ATTEMPTS = 5
SCRCPY_RESTART_MAX_BACKOFF_SECONDS = 15.0
SCRCPY_STABLE_RESET_SECONDS = 30.0
RELAY_SEND_QUEUE_MAX = max(4, _env_int("RELAY_SEND_QUEUE_MAX", 12))
SCRCPY_DEFAULT_MAX_FPS = max(1, _env_int("SCRCPY_DEFAULT_MAX_FPS", 12))
SCRCPY_DEFAULT_MAX_WIDTH = max(160, _env_int("SCRCPY_DEFAULT_MAX_WIDTH", 480))
SCRCPY_DEFAULT_BITRATE = max(80_000, _env_int("SCRCPY_DEFAULT_BITRATE", 600_000))

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT_BOOT_ROOT = os.path.dirname(_HERE)
_STATE_DIR = os.getenv("AGENT_BOOT_STATE_DIR", _AGENT_BOOT_ROOT).strip() or _AGENT_BOOT_ROOT
_RELAY_ID_FILE = os.path.join(_STATE_DIR, ".relay_id")

# CMD_TYPE constants — must match adb_relay_server.py
CMD_SHELL           = 0
CMD_RESTART_U2      = 1
CMD_ADB_CONNECT     = 2
CMD_RESTART_ATX     = 3
CMD_BOOTSTRAP       = 4  # push binaries + install APKs + start atx-agent + u2
CMD_SCREENCAP       = 5  # adb exec-out screencap -p → base64 PNG
CMD_PROBE_CAPS      = 6  # _probe_capabilities() → JSON dict in output
CMD_RESTART_SCRCPY  = 7  # stop + resume scrcpy session for a device


def _auto_bootstrap_enabled() -> bool:
    return os.getenv("AGENT_BOOT_AUTO_BOOTSTRAP", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def load_or_create_relay_id() -> str:
    """Stable relay identity across restarts (persisted under AGENT_BOOT_STATE_DIR)."""
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
    except OSError:
        pass
    if os.path.exists(_RELAY_ID_FILE):
        rid = open(_RELAY_ID_FILE).read().strip()
        if rid:
            return rid
    rid = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    with open(_RELAY_ID_FILE, "w") as f:
        f.write(rid)
    return rid


async def _cancel_and_await(*tasks: asyncio.Task | None) -> None:
    """Cancel tasks and await completion so Queue.get() waiters are not leaked."""
    pending = [t for t in tasks if t is not None and not t.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


class RelayAgent:
    """
    Connects outbound to device_farm server, executes ADB commands received from the server.

    Supports two transport modes:
      - "grpc"  : gRPC bidirectional stream (HTTP/2 multiplexing, recommended for ≥5 phones)
      - "ws"    : WebSocket (legacy fallback, default when RELAY_MODE not set)

    Device changes are detected in real-time by AdbDeviceWatcher (<100ms latency).
    Scrcpy sessions are managed by ScrcpySessionManager (TTL + zombie cleanup).
    """

    def __init__(
        self,
        server_url: str,
        api_key: Optional[str],
        relay_id: str,
        relay_mode: str = "ws",
        enrollment_token: Optional[str] = None,
        grpc_tls: bool = False,
        grpc_root_cert_file: str = "",
        extra_ingest: Any = None,
    ) -> None:
        self._api_key   = api_key
        self._relay_id  = relay_id
        self._relay_mode = relay_mode.lower().strip()
        self._enrollment_token = (enrollment_token or "").strip()

        if self._relay_mode == "grpc":
            # Accept "host:port" or "grpc://host:port" → strip scheme
            addr = server_url
            grpc_scheme_tls = addr.startswith(("grpcs://", "https://"))
            for prefix in ("grpcs://", "grpc://", "ws://", "wss://", "http://", "https://"):
                if addr.startswith(prefix):
                    addr = addr[len(prefix):]
                    break
            # Strip any path (e.g. "/relay-agent")
            addr = addr.split("/")[0]
            # If no port given, use default gRPC relay port
            if ":" not in addr:
                addr = f"{addr}:50051"
            self._grpc_addr  = addr
            self._server_url = addr  # for logging
            tls_env = os.getenv("RELAY_GRPC_TLS", "").strip().lower() in ("1", "true", "yes", "on")
            self._grpc_tls_enabled = bool(grpc_tls or grpc_scheme_tls or tls_env)
            self._grpc_root_cert_file = (
                grpc_root_cert_file
                or os.getenv("RELAY_GRPC_ROOT_CERT_FILE", "").strip()
            )
            if self._grpc_tls_enabled and not self._grpc_root_cert_file:
                bundled_root_cert = "/app/certs/grpc-relay-ca.pem"
                if os.path.isfile(bundled_root_cert):
                    self._grpc_root_cert_file = bundled_root_cert
        else:
            # WS mode: normalise URL
            if not server_url.startswith("ws://") and not server_url.startswith("wss://"):
                server_url = f"ws://{server_url}/relay-agent"
            self._server_url = server_url
            self._grpc_addr  = ""
            self._grpc_tls_enabled = False
            self._grpc_root_cert_file = ""

        self._registry   = DeviceRegistry()
        self._scrcpy_mgr = ScrcpySessionManager(on_session_stopped=self._on_session_stopped)
        self._supervisor = RelaySupervisor(self)
        self._scrcpy_desired: dict[str, dict[str, Any]] = {}
        self._active_send_queue: Optional[FairSendQueue] = None
        self._active_loop: Optional[asyncio.AbstractEventLoop] = None
        # Viewer-gated default: do not auto-start scrcpy for every online device.
        self._scrcpy_auto_resume_enabled = os.getenv("SCRCPY_AUTO_RESUME", "false").lower() in ("1", "true", "yes", "on")

        self._u2_batch_enabled = os.getenv("U2_BATCH_ENABLED", "true").lower() in ("1", "true")
        self._u2_pool: Optional[U2SessionPool] = None
        self._u2_executor: Optional[Any] = None
        self._u2_warm_inflight: set[str] = set()
        self._u2_warm_tasks: dict[str, asyncio.Task] = {}
        self._u2_warm_fail_count: dict[str, int] = {}
        self._u2_warm_retry_after: dict[str, float] = {}
        self._u2_warm_retry_base_s = _env_float("U2_WARM_RETRY_BASE_S", 5.0)
        self._u2_warm_retry_max_s = _env_float("U2_WARM_RETRY_MAX_S", 60.0)
        self._u2_warm_on_heartbeat = _env_bool("AGENT_BOOT_U2_WARM_ON_HEARTBEAT", False)
        self._extra_ingest = extra_ingest
        # A11y control-plane workers
        self._a11y_max_queue = int(os.getenv("A11Y_MAX_QUEUE_PER_DEVICE", "100"))
        self._a11y_state: dict[str, dict[str, Any]] = {}
        # TCP serial -> USB serial we kept; suppress auto-reconnect / farm adb connect
        # while that USB is still online (avoids disconnect ↔ reconnect loop).
        self._tcp_suppressed_for_usb: dict[str, str] = {}
        # Farm may still send scrcpy/control with TCP serial — map to real ADB serial.
        self._scrcpy_logical_to_adb: dict[str, str] = {}
        # USB serial → LAN IP for atx-agent HTTP (u2 proxy); filled from TCP suppress map or adb probe.
        self._atx_lan_host_cache: dict[str, str] = {}
        # USB serial -> (host, forwarded port) when phone WLAN is unreachable.
        self._atx_forward_cache: dict[str, tuple[str, int]] = {}
        self._atx_forward_lock = threading.Lock()
        self._bootstrap_inflight: set[str] = set()

        # Runtime: bounded executors + task registry + watchdog.
        # `_stream_tasks` is replaced per transport connect; this initial
        # registry exists so `_handle_*` paths can spawn tasks before the
        # first stream is established (e.g. during the brief startup window).
        self._stream_tasks: TaskRegistry = TaskRegistry()
        self._extra_data_tasks: dict[str, asyncio.Task] = {}
        self._extra_data_cancel_events: dict[str, asyncio.Event] = {}
        self._u2_batch_tasks: dict[str, asyncio.Task] = {}
        self._u2_batch_cancel_events: dict[str, asyncio.Event] = {}
        self._command_max_queue = max(8, _env_int("COMMAND_MAX_QUEUE_PER_DEVICE", 128))
        self._command_state: dict[str, dict[str, Any]] = {}
        self._loop_watchdog: Optional[LoopWatchdog] = None
        self._runtime_stats: Optional[RuntimeStats] = None

        # Heartbeat coalescing — rebuilding the caps_list dict on every
        # device event burns CPU when 20-40 phones flap together (cradle
        # power blip, USB controller reset). Cache the rendered JSON keyed
        # on (serials_signature, caps_version). Bumping `caps_version` on
        # capability change invalidates the cache.
        self._hb_cache_key: Optional[tuple] = None
        self._hb_cache_payload: Optional[str] = None
        self._hb_caps_version: int = 0
        self._capability_probe_inflight: set[str] = set()
        self._capability_probe_tasks: set[asyncio.Task] = set()

    def _ensure_default_scrcpy_desired(self) -> None:
        """
        Normalize desired scrcpy sessions for currently online devices.

        Do not seed new desired sessions here. Scrcpy is viewer-gated:
        only an explicit scrcpy_start from the farm/backend should set
        desired=True. Connection and device-online recovery paths may then
        resume those explicit sessions, but must not start scrcpy for every
        online phone in the background.
        """
        base_port = 27183
        used_ports: set[int] = set()

        def _next_free_port() -> int:
            p = base_port
            while p in used_ports:
                p += 1
            used_ports.add(p)
            return p

        # Normalize online devices first: avoid duplicate local forward ports
        # (two scrcpy sessions sharing one local tcp port causes EOF/reset loops).
        for serial in self._registry.online_serials:
            state = self._scrcpy_desired.get(serial)
            if not state:
                continue
            cfg = state.get("cfg") or {}
            try:
                port = int(cfg.get("port", 0) or 0)
            except Exception:
                port = 0
            if port <= 0 or port in used_ports:
                cfg["port"] = _next_free_port()
            else:
                used_ports.add(port)
            state["cfg"] = cfg

    async def run(self) -> None:
        zc = start_mdns_discovery()

        # Bounded executor pools + global semaphores. Must be created before
        # any coroutine offloads blocking work (scrcpy_mgr.start does).
        init_executors()
        init_semaphores()

        # Loop watchdog + runtime stats — long-running observability so
        # multi-day stability regressions are visible in the log instead of
        # only appearing as "agent died after 2h" tickets.
        self._loop_watchdog = LoopWatchdog()
        self._loop_watchdog.start()
        self._runtime_stats = RuntimeStats(
            watchdog=self._loop_watchdog,
            task_registry=self._stream_tasks,
        )
        self._runtime_stats.start()
        register_stats_source(
            "scrcpy",
            lambda: {"sessions": self._scrcpy_mgr.count},
        )
        register_stats_source(
            "devices",
            lambda: {"online": len(self._registry.online_serials)},
        )
        register_stats_source(
            "a11y",
            lambda: {"serials": len(self._a11y_state)},
        )
   
        def _send_queue_stats() -> dict[str, int]:
            q = self._active_send_queue
            if q is None:
                return {}
            try:
                snap = q.snapshot()
            except Exception:
                return {"qsize": q.qsize()}
            ctrl = snap.pop("_control", 0)
            return {
                "qsize": sum(snap.values()) + ctrl,
                "lanes": len(snap),
                "ctrl": ctrl,
                "max_lane": max(snap.values(), default=0),
            }
        register_stats_source("send_q", _send_queue_stats)

        await self._scrcpy_mgr.start()
        await self._supervisor.start()

        if self._u2_batch_enabled:
            loop = asyncio.get_running_loop()
            self._u2_pool = U2SessionPool(loop=loop)
            await self._u2_pool.start()
            from relay.u2_executor import U2Executor
            self._u2_executor = U2Executor(
                pool=self._u2_pool,
                loop=loop,
                http_dump=self._dump_hierarchy_http_sync,
                http_rpc=self._u2_jsonrpc_sync,
            )
            register_stats_source(
                "u2pool",
                lambda: {"sessions": len(self._u2_pool._sessions)} if self._u2_pool else {},
            )
            logger.info("u2 batch/flow enabled (U2_BATCH_ENABLED=true)")

        # HTTP keep-alive pool stats — visible warm-pool size matters when
        # debugging "u2 HTTP suddenly slow" reports.
        try:
            from relay.http_pool import default_pool as _http_default_pool
            register_stats_source(
                "http",
                lambda: {"hosts": len(_http_default_pool()._hosts)},
            )
        except Exception:
            pass

        # Multi-day GC tuning: freeze long-lived objects (modules, the agent
        # instance, the scrcpy/u2 managers) so future GC runs only scan the
        # smaller request-scoped heap. Without this, every gen-2 sweep walks
        # ~all reachable objects — cost grows with uptime.
        try:
            import gc
            # One full collection to compact, then freeze the survivors.
            gc.collect()
            gc.freeze()
            logger.info("runtime: gc.freeze() applied (frozen=%d)", gc.get_freeze_count())
        except Exception:
            pass

        attempt    = 0
        base_delay = 0.5

        # Brief initial delay so device_farm server has time to start
        await asyncio.sleep(3.0)

        try:
            while True:
                try:
                    if self._relay_mode == "grpc":
                        await self._connect_and_stream_grpc()
                    else:
                        await self._connect_and_stream()
                    # Clean exit (server closed stream) — reset backoff but
                    # still wait 1s before reconnecting to avoid tight loops
                    # when the server repeatedly closes streams immediately.
                    attempt = 0
                    await asyncio.sleep(1.0)
                except Exception as exc:
                    attempt += 1
                    delay = min(base_delay * (2 ** attempt), 8.0)
                    delay += delay * 0.2 * random.random()
                    logger.warning(
                        "%s stream failed (attempt %d): %s — retry in %.1fs",
                        self._relay_mode.upper(), attempt, exc, delay,
                    )
                    await asyncio.sleep(delay)
        finally:
            await self._supervisor.stop()
            await _cancel_and_await(*list(self._u2_warm_tasks.values()))
            self._u2_warm_tasks.clear()
            self._u2_warm_inflight.clear()
            self._u2_warm_fail_count.clear()
            self._u2_warm_retry_after.clear()
            if self._u2_pool:
                await self._u2_pool.stop()
            await self._scrcpy_mgr.stop()
            await self._stream_tasks.cancel_all(timeout=3.0)
            if self._loop_watchdog:
                await self._loop_watchdog.stop()
            if self._runtime_stats:
                await self._runtime_stats.stop()
            shutdown_executors(wait=False)
            if zc:
                zc.close()

    async def _connect_and_stream(self) -> None:
        import websockets  # type: ignore

        headers: dict = {}
        if self._api_key:
            headers["x-relay-api-key"] = self._api_key
        if self._enrollment_token:
            headers["x-relay-enrollment-token"] = self._enrollment_token

        # send_queue: str for JSON text frames, bytes for binary frames.
        # FairSendQueue replaces a single shallow asyncio.Queue: one lane per
        # device + a high-priority control lane. A phone whose scrcpy stream
        # is stuck on IDR retries no longer blocks every other device's u2
        # results, and heartbeats are never starved by a backlogged frame
        # queue. scrcpy_relay.py drops deltas on overflow and requests IDR.
        send_queue = FairSendQueue(
            per_device_max=SEND_PER_DEVICE_MAX,
            control_max=SEND_CONTROL_MAX,
        )
        loop = asyncio.get_running_loop()
        self._active_send_queue = send_queue
        self._active_loop = loop

        async with websockets.connect(
            self._server_url,
            additional_headers=headers,
            ping_interval=30,
            ping_timeout=10,
            max_size=16 * 1024 * 1024,  # 16 MB — large scrcpy frames
        ) as ws:
            logger.info("WS connected → %s (relay_id=%s)", self._server_url, self._relay_id)

            # ── Register ──────────────────────────────────────────────────────
            serials = self._registry.online_serials or _list_serials()
            await ws.send(dumps({
                "type":     "register",
                "relay_id": self._relay_id,
                "serials":  serials,
                "version":  "2.0.0",
            }))
            logger.info("register sent: relay_id=%s serials=%s", self._relay_id, serials)
            await self._send_heartbeat(send_queue)
            if self._scrcpy_auto_resume_enabled:
                self._ensure_default_scrcpy_desired()
                await self._resume_desired_scrcpy_sessions(send_queue, loop, source="ws-connected")

            # ── Device watcher + heartbeat ────────────────────────────────────
            watcher = AdbDeviceWatcher(
                on_device_event=lambda s, st: self._on_device_event(s, st, send_queue),
            )
            watcher_task = asyncio.create_task(watcher.run(), name="device-watcher")
            hb_task = asyncio.create_task(
                self._periodic_heartbeat(send_queue), name="relay-heartbeat"
            )

            # ── Sender task: drain send_queue → WS ───────────────────────────
            async def _sender() -> None:
                try:
                    while True:
                        item = await send_queue.get()
                        if item is None:
                            return
                        if isinstance(item, bytes):
                            await ws.send(item)
                        else:
                            await ws.send(item)
                except Exception as exc:
                    logger.debug("WS sender exited: %s", exc)

            sender_task = asyncio.create_task(_sender(), name="ws-sender")

            try:
                async for raw_msg in ws:
                    if isinstance(raw_msg, bytes):
                        await self._handle_binary(raw_msg, send_queue)
                    else:
                        try:
                            msg = json.loads(raw_msg)
                        except Exception:
                            continue
                        await self._handle_server_msg(msg, send_queue, loop)
            finally:
                await send_queue.put(None)
                await _cancel_and_await(watcher_task, hb_task, sender_task)
                await self._shutdown_stream_helpers()
                if self._active_send_queue is send_queue:
                    self._active_send_queue = None
                    self._active_loop = None
                # Keep scrcpy sessions alive across transport reconnects.
                # Transient WS/gRPC reconnects are common on unstable networks; stopping
                # all sessions here causes 2-5s black/freeze gaps on every reconnect.
                # Sessions are explicitly cleaned up on scrcpy_stop or full agent shutdown.

    async def _connect_and_stream_grpc(self) -> None:
        """gRPC mode: bidirectional stream with HTTP/2 multiplexing."""
        from relay.grpc_client import GrpcRelayClient, create_grpc_channel
        from relay.control_client import AgentControlClient

        # FairSendQueue: same per-device fairness story as the WS path. The
        # gRPC frame generator consumes via `await send_queue.get()`, which
        # transparently interleaves frames + JSON results from the right lane.
        send_queue = FairSendQueue(
            per_device_max=SEND_PER_DEVICE_MAX,
            control_max=SEND_CONTROL_MAX,
        )
        loop = asyncio.get_running_loop()
        self._active_send_queue = send_queue
        self._active_loop = loop

        logger.info("gRPC connecting → %s (relay_id=%s)", self._grpc_addr, self._relay_id)

        # Keep the high-volume video stream and the control stream on separate
        # channels. In practice, reconnect/cancel churn on one grpc.aio stream
        # can poison pending sends on another stream when both share a channel,
        # surfacing as INTERNAL "Failed execute_batch" on the agent.
        async with create_grpc_channel(
            self._grpc_addr,
            tls_enabled=self._grpc_tls_enabled,
            root_cert_file=self._grpc_root_cert_file,
        ) as stream_channel, create_grpc_channel(
            self._grpc_addr,
            tls_enabled=self._grpc_tls_enabled,
            root_cert_file=self._grpc_root_cert_file,
        ) as control_channel:
            client = GrpcRelayClient(
                server_addr=self._grpc_addr,
                api_key=self._api_key,
                agent_id=self._relay_id,
                send_queue=send_queue,
                loop=loop,
                channel=stream_channel,
                tls_enabled=self._grpc_tls_enabled,
                root_cert_file=self._grpc_root_cert_file,
            )

            # Channel 2: control plane (register/heartbeat/commands) — runs
            # independently; a 180s bootstrap never blocks video frames.
            ctrl_client = AgentControlClient(control_channel, self._api_key, self)
            ctrl_task = asyncio.create_task(ctrl_client.run(), name="grpc-ctrl-client")

            # ── Register on Channel 1 (video stream) for backward compat ──────
            # Channel 2 also sends register; server uses whichever arrives first.
            serials = self._registry.online_serials or _list_serials()
            register_msg = dumps({
                "type":     "register",
                "relay_id": self._relay_id,
                "serials":  serials,
                "version":  "2.0.0",
            })
            await send_queue.put(register_msg)
            await self._send_heartbeat(send_queue)
            if self._scrcpy_auto_resume_enabled:
                self._ensure_default_scrcpy_desired()
                await self._resume_desired_scrcpy_sessions(send_queue, loop, source="grpc-connected")

            # ── Device watcher + heartbeat ────────────────────────────────────
            watcher = AdbDeviceWatcher(
                on_device_event=lambda s, st: self._on_device_event(s, st, send_queue),
            )
            watcher_task = asyncio.create_task(watcher.run(), name="device-watcher-grpc")
            hb_task = asyncio.create_task(
                self._periodic_heartbeat(send_queue), name="relay-heartbeat-grpc"
            )

            # ── ControlMsg consumer: routes server msgs to sessions ───────────
            async def _consume_ctrl() -> None:
                while True:
                    ctrl_msg = await client.ctrl_q.get()
                    if ctrl_msg is None:
                        return
                    if ctrl_msg.is_json:
                        try:
                            msg = json.loads(ctrl_msg.data.decode("utf-8", errors="replace"))
                            await self._handle_server_msg(msg, send_queue, loop)
                        except Exception as exc:
                            logger.debug("gRPC JSON msg error: %s", exc)
                    else:
                        # Binary scrcpy control → route to session
                        self._scrcpy_mgr.send_control(
                            self._scrcpy_device_serial(ctrl_msg.serial),
                            ctrl_msg.data,
                        )

            consume_task = asyncio.create_task(_consume_ctrl(), name="grpc-ctrl-consumer")

            try:
                await client._stream_once(stream_channel)
            finally:
                client.stop()
                ctrl_client.stop()
                await send_queue.put(None)
                await _cancel_and_await(
                    watcher_task,
                    hb_task,
                    consume_task,
                    ctrl_task,
                )
                await self._shutdown_stream_helpers()
                if self._active_send_queue is send_queue:
                    self._active_send_queue = None
                    self._active_loop = None
                # Keep scrcpy sessions alive across transport reconnects.
                # Transient WS/gRPC reconnects are common on unstable networks; stopping
                # all sessions here causes 2-5s black/freeze gaps on every reconnect.
                # Sessions are explicitly cleaned up on scrcpy_stop or full agent shutdown.

    async def _handle_binary(self, data: bytes, send_queue: asyncio.Queue) -> None:
        """Handle binary frame from server (currently: scrcpy control 0x43)."""
        if len(data) < 2:
            return
        tag = data[0]
        if tag == 0x43:
            # Scrcpy control: [0x43][slen][serial][ctrl_data]
            slen = data[1]
            if len(data) < 2 + slen:
                return
            serial = data[2:2 + slen].decode("utf-8", errors="replace")
            ctrl_data = data[2 + slen:]
            self._scrcpy_mgr.send_control(
                self._scrcpy_device_serial(serial),
                ctrl_data,
            )

    # ── Device event handling ─────────────────────────────────────────────────

    def _clear_tcp_suppress_for_usb_anchor(self, usb_serial: str) -> None:
        to_pop = [
            t for t, u in self._tcp_suppressed_for_usb.items() if u == usb_serial
        ]
        for t in to_pop:
            self._tcp_suppressed_for_usb.pop(t, None)
            self._scrcpy_logical_to_adb.pop(t, None)
            logger.debug(
                "USB anchor %s not device — cleared TCP suppress %s",
                usb_serial,
                t,
            )

    def _adb_serial_prefer_usb_over_tcp(self, serial: str) -> str:
        """When TCP was dropped for USB duplicate, farm may still use the IP:port serial."""
        if not serial or ":" not in serial:
            return serial
        usb = self._tcp_suppressed_for_usb.get(serial)
        if not usb:
            return serial
        uctx = self._registry.get(usb)
        if uctx and uctx.is_available:
            return usb
        return serial

    def _scrcpy_device_serial(self, server_serial: str) -> str:
        """ADB serial to use for scrcpy session / control (after USB-preference remap)."""
        if not server_serial:
            return server_serial
        mapped = self._scrcpy_logical_to_adb.get(server_serial)
        if mapped:
            return mapped
        return self._adb_serial_prefer_usb_over_tcp(server_serial)

    async def _auto_bootstrap_online_device(self, serial: str) -> None:
        if not _auto_bootstrap_enabled():
            return
        if serial in self._bootstrap_inflight:
            return
        self._bootstrap_inflight.add(serial)
        try:
            loop = asyncio.get_running_loop()
            logger.info("[%s] auto-bootstrap starting (AGENT_BOOT_AUTO_BOOTSTRAP)", serial)
            output, rc = await loop.run_in_executor(
                adb_executor(),
                _bootstrap_device,
                serial,
                180,
            )
            if rc == 0:
                logger.info("[%s] auto-bootstrap ok: %s", serial, output[:500])
                self._schedule_u2_warm(serial, reason="auto-bootstrap")
            else:
                logger.warning("[%s] auto-bootstrap failed (rc=%s): %s", serial, rc, output[:500])
        except Exception as exc:
            logger.warning("[%s] auto-bootstrap error: %s", serial, exc)
        finally:
            self._bootstrap_inflight.discard(serial)

    def _clear_u2_warm_backoff(self, serial: str) -> None:
        self._u2_warm_fail_count.pop(serial, None)
        self._u2_warm_retry_after.pop(serial, None)

    def _record_u2_warm_failed(self, serial: str, *, reason: str) -> None:
        count = self._u2_warm_fail_count.get(serial, 0) + 1
        self._u2_warm_fail_count[serial] = count
        delay = min(self._u2_warm_retry_max_s, self._u2_warm_retry_base_s * (2 ** (count - 1)))
        delay *= 1.0 + 0.2 * random.random()
        self._u2_warm_retry_after[serial] = asyncio.get_running_loop().time() + delay
        logger.debug(
            "[%s] u2 warm session retry delayed %.1fs after failure #%d (%s)",
            serial,
            delay,
            count,
            reason,
        )

    def _schedule_u2_warm(self, serial: str, *, reason: str) -> None:
        if not self._u2_pool or not serial:
            return
        mark_keep_warm = getattr(self._u2_pool, "mark_keep_warm", None)
        if callable(mark_keep_warm) and mark_keep_warm(serial, True):
            self._clear_u2_warm_backoff(serial)
            return
        has_session = getattr(self._u2_pool, "has_session", None)
        if callable(has_session) and has_session(serial):
            self._clear_u2_warm_backoff(serial)
            return
        ctx = self._registry.get(serial)
        if ctx and ctx.state != DeviceState.ONLINE:
            return
        if serial in self._u2_warm_inflight:
            return
        retry_after = self._u2_warm_retry_after.get(serial, 0.0)
        if retry_after > asyncio.get_running_loop().time():
            return
        self._u2_warm_inflight.add(serial)
        task = asyncio.create_task(
            self._warm_u2_session(serial, reason=reason),
            name=f"u2-warm-{serial}",
        )
        self._u2_warm_tasks[serial] = task

        def _done(done: asyncio.Task, *, s: str = serial) -> None:
            self._u2_warm_inflight.discard(s)
            if self._u2_warm_tasks.get(s) is done:
                self._u2_warm_tasks.pop(s, None)

        task.add_done_callback(_done)

    async def _warm_u2_session(self, serial: str, *, reason: str) -> None:
        try:
            ctx = self._registry.get(serial)
            if ctx and ctx.state != DeviceState.ONLINE:
                return
            warm = getattr(self._u2_pool, "warm_session", None)
            if not callable(warm):
                return
            ok = await warm(serial, keep_warm=True)
            ctx = self._registry.get(serial)
            if ctx and ctx.state != DeviceState.ONLINE:
                evict = getattr(self._u2_pool, "evict", None)
                if callable(evict):
                    await evict(serial)
                return
            if ok:
                self._clear_u2_warm_backoff(serial)
                logger.info("[%s] u2 warm session ready (%s)", serial, reason)
            else:
                self._record_u2_warm_failed(serial, reason=reason)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_u2_warm_failed(serial, reason=reason)
            logger.debug("[%s] u2 warm session failed (%s): %s", serial, reason, exc)
        finally:
            self._u2_warm_inflight.discard(serial)
            task = asyncio.current_task()
            if task is not None and self._u2_warm_tasks.get(serial) is task:
                self._u2_warm_tasks.pop(serial, None)

    async def _on_device_event(
        self, serial: str, adb_state: str, send_queue: asyncio.Queue
    ) -> None:
        ctx, changed = self._registry.on_adb_event(serial, adb_state)
        if not changed:
            return

        logger.info("device %s → %s (retries=%d)", serial, ctx.state.value, ctx.retry_count)

        # USB disappeared — allow WiFi/TCP to be used again
        if ":" not in serial and adb_state != "device":
            self._clear_tcp_suppress_for_usb_anchor(serial)
            self._atx_lan_host_cache.pop(serial, None)

        if adb_state != "device" and self._u2_pool:
            asyncio.create_task(self._u2_pool.evict(serial))

        if ctx.state == DeviceState.OFFLINE:
            # Device-offline cascade: tear down every relay component owned for
            # this serial so we don't waste retry budget hammering a dead device.
            # scrcpy_mgr.stop_all_for_serial emits reason="device_offline" which
            # _on_session_stopped treats as non-abnormal (no auto-resume until
            # the device comes back ONLINE).
            asyncio.create_task(
                self._scrcpy_mgr.stop_all_for_serial(serial, reason="device_offline")
            )
            self._cleanup_serial_state(serial)

        if ctx.state == DeviceState.ONLINE:
            self._schedule_u2_warm(serial, reason="device-online")
            if _auto_bootstrap_enabled():
                asyncio.create_task(
                    self._auto_bootstrap_online_device(serial),
                    name=f"auto-bootstrap-{serial}",
                )
            loop = asyncio.get_running_loop()
            self._schedule_capability_probe([serial], send_queue, loop)
            if self._scrcpy_auto_resume_enabled:
                self._ensure_default_scrcpy_desired()
                await self._resume_desired_scrcpy_sessions(send_queue, loop, source="device-online")

        if ctx.state == DeviceState.RECONNECTING and ":" in serial:
            usb_anchor = self._tcp_suppressed_for_usb.get(serial)
            skip = False
            if usb_anchor:
                usb_ctx = self._registry.get(usb_anchor)
                if usb_ctx and usb_ctx.is_available:
                    skip = True
                    logger.debug(
                        "skip auto-reconnect %s (USB preferred: %s)",
                        serial,
                        usb_anchor,
                    )
                else:
                    self._tcp_suppressed_for_usb.pop(serial, None)
            if not skip:
                loop = asyncio.get_running_loop()
                output, rc = await loop.run_in_executor(adb_executor(), _adb_connect, serial)
                if rc == 0:
                    logger.info("auto-reconnected %s — %s", serial, output)
                else:
                    logger.debug("reconnect failed %s — %s", serial, output)

        await self._send_heartbeat(send_queue)

    async def _periodic_heartbeat(self, send_queue: asyncio.Queue) -> None:
        """Keepalive heartbeat every 30s."""
        while True:
            await asyncio.sleep(30)
            await self._send_heartbeat(send_queue)

    async def _refresh_devices_after_adb_connect(
        self,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        requested_serial: str,
    ) -> None:
        """Publish a fresh serial list immediately after a successful adb connect."""
        try:
            serials = await loop.run_in_executor(adb_executor(), _list_serials)
        except Exception as exc:
            logger.debug(
                "post-adb-connect device refresh failed serial=%s: %s",
                requested_serial,
                exc,
            )
            return
        if not serials:
            logger.debug(
                "post-adb-connect device refresh found no serials requested=%s",
                requested_serial,
            )
            return

        changed = self._seed_registry_from_adb_serials(
            serials,
            source="post-adb-connect refresh",
            requested_serial=requested_serial,
        )

        # Force a heartbeat even if the serial set matches the cached key:
        # pending scrcpy on the server may be waiting for this immediate publish.
        self._hb_cache_key = None
        await self._send_heartbeat(send_queue)

        if changed and self._scrcpy_auto_resume_enabled:
            self._ensure_default_scrcpy_desired()
            await self._resume_desired_scrcpy_sessions(
                send_queue,
                loop,
                source="post-adb-connect-refresh",
            )

    def _seed_registry_from_adb_serials(
        self,
        serials: list[str],
        *,
        source: str,
        requested_serial: str = "",
    ) -> bool:
        changed = False
        for serial in serials:
            ctx, state_changed = self._registry.on_adb_event(serial, "device")
            changed = changed or state_changed
            if requested_serial:
                logger.info(
                    "%s: %s -> %s requested=%s",
                    source,
                    serial,
                    ctx.state.value,
                    requested_serial,
                )
            else:
                logger.info("%s: %s -> %s", source, serial, ctx.state.value)
        return changed

    async def _ensure_capabilities_for_serials(
        self, serials: list[str], loop: asyncio.AbstractEventLoop
    ) -> None:
        """Probe capabilities for ONLINE serials missing cached caps."""
        for serial in serials:
            ctx = self._registry.get(serial)
            if not ctx or ctx.state != DeviceState.ONLINE or ctx.capabilities:
                continue
            caps = await loop.run_in_executor(adb_executor(), _probe_capabilities, serial)
            self._registry.set_capabilities(serial, caps)
            self._hb_caps_version += 1
            wlan_ip = str((caps or {}).get("wlan_ip") or "").strip()
            if wlan_ip and ":" not in serial:
                self._atx_lan_host_cache[serial] = wlan_ip
            logger.info(
                "capabilities probed %s: wlan_ip=%s",
                serial,
                wlan_ip or "unset",
            )
            if bool((caps or {}).get("u2", False)):
                self._schedule_u2_warm(serial, reason="capability-probe")

    def _missing_capability_serials(self, serials: list[str]) -> list[str]:
        missing: list[str] = []
        for serial in serials:
            ctx = self._registry.get(serial)
            if (
                ctx
                and ctx.state == DeviceState.ONLINE
                and not ctx.capabilities
                and serial not in self._capability_probe_inflight
            ):
                missing.append(serial)
        return missing

    def _send_queue_is_current(self, send_queue: asyncio.Queue) -> bool:
        return self._active_send_queue is None or self._active_send_queue is send_queue

    def _schedule_capability_probe(
        self,
        serials: list[str],
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        missing = self._missing_capability_serials(serials)
        if not missing:
            return
        for serial in missing:
            self._capability_probe_inflight.add(serial)
        task = asyncio.create_task(
            self._probe_capabilities_then_publish(missing, send_queue, loop),
            name=f"capabilities-probe-{','.join(missing[:3])}",
        )
        self._capability_probe_tasks.add(task)
        task.add_done_callback(self._capability_probe_tasks.discard)

    async def _apply_usb_preference_reconcile(
        self,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        pairs = await loop.run_in_executor(
            adb_executor(),
            reconcile_usb_preferred_for_duplicate_devices,
            self._registry,
        )
        for tcp_s, usb_s in pairs or []:
            self._tcp_suppressed_for_usb[tcp_s] = usb_s
            if ":" in tcp_s:
                self._atx_lan_host_cache[usb_s] = tcp_s.rsplit(":", 1)[0]
        for tcp_s, _usb_s in pairs or []:
            await self._scrcpy_mgr.stop_session(tcp_s, reason="manual_stop")
            tcp_state = self._scrcpy_desired.pop(tcp_s, None)
            if tcp_state is not None:
                restart_task = tcp_state.get("restart_task")
                if restart_task and not restart_task.done():
                    restart_task.cancel()
                logger.info(
                    "scrcpy: dropped duplicate TCP desired state %s (USB anchor %s)",
                    tcp_s,
                    _usb_s,
                )
            self._scrcpy_logical_to_adb.pop(tcp_s, None)

    async def _probe_capabilities_then_publish(
        self,
        serials: list[str],
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        try:
            await self._ensure_capabilities_for_serials(serials, loop)
            await self._apply_usb_preference_reconcile(send_queue, loop)
            if self._send_queue_is_current(send_queue):
                await self._send_heartbeat(send_queue, schedule_capability_probe=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("capability probe background failed serials=%s: %s", serials, exc)
        finally:
            for serial in serials:
                self._capability_probe_inflight.discard(serial)

    def _cancel_capability_probe_tasks(self) -> None:
        for task in list(self._capability_probe_tasks):
            task.cancel()
        self._capability_probe_tasks.clear()
        self._capability_probe_inflight.clear()

    async def _shutdown_stream_helpers(self) -> None:
        """Cancel and await per-stream helper tasks blocked on queue I/O."""
        workers: list[asyncio.Task] = []

        for state in self._command_state.values():
            worker = state.get("worker")
            if worker is not None and not worker.done():
                workers.append(worker)
        self._command_state.clear()

        for state in self._scrcpy_desired.values():
            task = state.get("restart_task")
            if task is not None and not task.done():
                workers.append(task)
            state["restart_task"] = None

        for task in list(self._capability_probe_tasks):
            if not task.done():
                workers.append(task)
        self._capability_probe_tasks.clear()
        self._capability_probe_inflight.clear()

        await _cancel_and_await(*workers)

    async def _send_heartbeat(
        self,
        send_queue: asyncio.Queue,
        *,
        schedule_capability_probe: bool = True,
    ) -> None:
        serials = self._registry.online_serials
        loop = asyncio.get_running_loop()
        if not serials:
            try:
                snapshot = await loop.run_in_executor(adb_executor(), _list_serials)
            except Exception as exc:
                logger.debug("heartbeat adb snapshot failed: %s", exc)
                snapshot = []
            if snapshot:
                self._seed_registry_from_adb_serials(
                    snapshot,
                    source="heartbeat adb snapshot",
                )
                serials = self._registry.online_serials
        if self._u2_warm_on_heartbeat:
            for serial in serials:
                ctx = self._registry.get(serial)
                if ctx and bool((ctx.capabilities or {}).get("u2", False)):
                    self._schedule_u2_warm(serial, reason="heartbeat")
        if schedule_capability_probe:
            self._schedule_capability_probe(serials, send_queue, loop)

        key = (tuple(serials), self._hb_caps_version)
        if key == self._hb_cache_key and self._hb_cache_payload is not None:
            bounded_put_nowait(send_queue, self._hb_cache_payload, label="heartbeat")
            return

        caps_list = []
        for s in serials:
            ctx = self._registry.get(s)
            if ctx and ctx.capabilities:
                c = ctx.capabilities
                caps_list.append({
                    "serial":          s,
                    "android_version": c.get("android_version", ""),
                    "sdk":             c.get("sdk", ""),
                    "brand":           c.get("brand", ""),
                    "model":           c.get("model", ""),
                    "device_name":     c.get("device_name", ""),
                    "marketing_name":  c.get("marketing_name", ""),
                    "display_name":    c.get("display_name", ""),
                    "wlan_ip":         c.get("wlan_ip", ""),
                    "wlan_cidr":       c.get("wlan_cidr", ""),
                    "abi":             c.get("abi", ""),
                    "screen_width":    c.get("screen_width", 0),
                    "screen_height":   c.get("screen_height", 0),
                    "ram_gb":          c.get("ram_gb", 0),
                    "has_u2":          bool(c.get("u2", False)),
                    "has_stf":         bool(c.get("stf", False)),
                    "tags":            list(c.get("tags", [])),
                })

        payload = dumps({
            "type":         "heartbeat",
            "serials":      serials,
            "capabilities": caps_list,
        })
        self._hb_cache_key = key
        self._hb_cache_payload = payload
        # Heartbeat is control-plane: untagged so it never sits behind a
        # device's video backlog (FairSendQueue gives control absolute prio).
        bounded_put_nowait(send_queue, payload, label="heartbeat")

    # ── Server message handling ───────────────────────────────────────────────

    async def _handle_server_msg(
        self, msg: dict, send_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
    ) -> None:
        mtype = msg.get("type", "")

        if mtype == "ack":
            logger.info("registered: %s", msg.get("message"))

        elif mtype == "command":
            await self._enqueue_command(msg, send_queue, loop)

        elif mtype == "scrcpy_start":
            req = str(msg.get("serial", "") or "")
            adb_s = self._adb_serial_prefer_usb_over_tcp(req)
            if adb_s != req:
                self._scrcpy_logical_to_adb[req] = adb_s
                logger.info("scrcpy_start remap %s -> %s (USB preferred)", req, adb_s)
            state = self._scrcpy_desired.get(req) or {}
            restart_task = state.get("restart_task")
            if restart_task and not restart_task.done():
                restart_task.cancel()
            state.update({
                "desired": True,
                "manual_stop": False,
                "last_stop_reason": "",
                "cfg": {
                    "max_fps": int(msg.get("max_fps") or SCRCPY_DEFAULT_MAX_FPS),
                    "max_width": int(msg.get("max_width") or SCRCPY_DEFAULT_MAX_WIDTH),
                    "enable_control": bool(msg.get("control", True)),
                    "port": int(msg.get("port") or 27183),
                    "bitrate": int(msg.get("bitrate") or SCRCPY_DEFAULT_BITRATE),
                    "low_latency": bool(msg.get("low_latency", False)),
                },
                "adb_serial": adb_s,
                "retry_count": 0,
                "retry_window_start": 0.0,
                "restart_task": None,
                "last_started_at": 0.0,
            })
            self._scrcpy_desired[req] = state
            await self._start_desired_scrcpy(req, send_queue, loop)

        elif mtype == "scrcpy_stop":
            req = str(msg.get("serial", "") or "")
            adb_s = self._scrcpy_logical_to_adb.pop(req, req)
            state = self._scrcpy_desired.get(req) or {}
            restart_task = state.get("restart_task")
            if restart_task and not restart_task.done():
                restart_task.cancel()
            state.update({
                "desired": False,
                "manual_stop": True,
                "last_stop_reason": "manual_stop",
                "restart_task": None,
            })
            self._scrcpy_desired[req] = state
            await self._scrcpy_mgr.stop_session(adb_s, reason="manual_stop")
            if adb_s != req:
                await self._scrcpy_mgr.stop_session(req, reason="manual_stop")

        elif mtype == "u2_request":
            self._stream_tasks.add(
                self._handle_u2_request(msg, send_queue),
                name="u2-request",
            )

        elif mtype == "u2_batch":
            req_id = str(msg.get("id", "") or "")
            if req_id:
                msg = dict(msg)
                cancel_event = asyncio.Event()
                msg["_cancel_event"] = cancel_event
                self._u2_batch_cancel_events[req_id] = cancel_event
            task = self._stream_tasks.add(
                self._guarded(
                    u2_batch_sem(),
                    self._handle_u2_batch(msg, send_queue),
                    label="u2_batch",
                ),
                name="u2-batch",
            )
            if req_id:
                self._u2_batch_tasks[req_id] = task
                task.add_done_callback(
                    lambda _task, _req_id=req_id: (
                        self._u2_batch_tasks.pop(_req_id, None),
                        self._u2_batch_cancel_events.pop(_req_id, None),
                    )
                )

        elif mtype == "u2_batch_cancel":
            self._cancel_u2_batch(str(msg.get("id", "") or ""))

        elif mtype == "u2_flow":
            self._stream_tasks.add(
                self._guarded(
                    u2_flow_sem(),
                    self._handle_u2_flow(msg, send_queue),
                    label="u2_flow",
                ),
                name="u2-flow",
            )

        elif mtype == "extra_data":
            req_id = str(msg.get("id", "") or "")
            if req_id:
                context = msg.get("context") if isinstance(msg.get("context"), dict) else {}
                context = dict(context)
                cancel_event = asyncio.Event()
                context["_cancel_event"] = cancel_event
                msg = dict(msg)
                msg["context"] = context
                self._extra_data_cancel_events[req_id] = cancel_event
            task = self._stream_tasks.add(
                self._guarded(
                    extra_data_sem(),
                    self._handle_extra_data(msg, send_queue),
                    label="extra_data",
                ),
                name="extra-data",
            )
            if req_id:
                self._extra_data_tasks[req_id] = task
                task.add_done_callback(
                    lambda _task, _req_id=req_id: (
                        self._extra_data_tasks.pop(_req_id, None),
                        self._extra_data_cancel_events.pop(_req_id, None),
                    )
                )

        elif mtype == "extra_data_cancel":
            self._cancel_extra_data_task(str(msg.get("id", "") or ""))

        elif mtype == "a11y_action":
            await self._handle_a11y_action(msg, send_queue, loop)

        elif mtype == "ping":
            pass  # WebSocket ping/pong handles keepalive at transport layer

    async def _handle_a11y_action(
        self, msg: dict, send_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
    ) -> None:
        """
        Handle a11y_action control-plane message from farm.
        - Mutating actions: immediate a11y_ack then async result (best-effort)
        - Query actions: execute on query lane and return a11y_result
        """
        serial = str(msg.get("serial", "") or "")
        req_id = str(msg.get("id", "") or "")
        action = str(msg.get("action", "") or "")
        mode = str(msg.get("mode", "mutate") or "mutate")
        payload = msg.get("payload") or {}
        seq = int(msg.get("seq", 0) or 0)
        session_id = str(msg.get("session_id", "") or "")
        ts = int(msg.get("ts", int(time.time() * 1000)) or int(time.time() * 1000))
        if not serial or not req_id or not action:
            return

        supported_actions = {"tap", "swipe", "drag", "long_tap", "double_tap", "key", "type", "dump_hierarchy"}
        if action not in supported_actions:
            if mode == "query":
                await bounded_put(send_queue, dumps({
                    "type": "a11y_result",
                    "id": req_id,
                    "serial": serial,
                    "seq": seq,
                    "ok": False,
                    "error": f"unsupported_action:{action}",
                    "data": {},
                }), serial=serial, label="a11y_result")
            else:
                await bounded_put(send_queue, dumps({
                    "type": "a11y_ack",
                    "id": req_id,
                    "serial": serial,
                    "seq": seq,
                    "accepted": False,
                    "queue_pos": -1,
                    "error": f"unsupported_action:{action}",
                }), serial=serial, label="a11y_ack")
            return

        def _new_state(active_session_id: str) -> dict[str, Any]:
            return {
                "session_id": active_session_id,
                "last_seq": 0,
                "queued_seqs": set(),
                "mut_q": asyncio.Queue(maxsize=self._a11y_max_queue),
                "qry_q": asyncio.Queue(maxsize=max(8, self._a11y_max_queue // 8)),
                "mut_worker": None,
                "qry_worker": None,
            }

        async def _reject(error: str, queue_pos: int = -1) -> None:
            if mode == "query":
                await bounded_put(send_queue, dumps({
                    "type": "a11y_result",
                    "id": req_id,
                    "serial": serial,
                    "seq": seq,
                    "ok": False,
                    "error": error,
                    "data": {},
                }), serial=serial, label="a11y_result")
                return
            await bounded_put(send_queue, dumps({
                "type": "a11y_ack",
                "id": req_id,
                "serial": serial,
                "seq": seq,
                "accepted": False,
                "queue_pos": queue_pos,
                "error": error,
            }), serial=serial, label="a11y_ack")

        state = self._a11y_state.get(serial)
        if state is None:
            state = _new_state(session_id)
            self._a11y_state[serial] = state

        # Farm/device-client restarts create a new session_id and reset their
        # local seq counter. Treat ordering as session-scoped; otherwise a
        # long-running agent rejects every new farm request as stale_seq.
        if session_id and state.get("session_id") and state.get("session_id") != session_id:
            for key in ("mut_worker", "qry_worker"):
                worker = state.get(key)
                if worker is not None and not worker.done():
                    worker.cancel()
            state = _new_state(session_id)
            self._a11y_state[serial] = state
        elif session_id and not state.get("session_id"):
            state["session_id"] = session_id

        if not state.get("mut_worker") or state["mut_worker"].done():
            state["mut_worker"] = asyncio.create_task(
                self._a11y_worker(serial, state["mut_q"], send_queue, loop, query_lane=False),
                name=f"a11y-mut-{serial}",
            )
        if not state.get("qry_worker") or state["qry_worker"].done():
            state["qry_worker"] = asyncio.create_task(
                self._a11y_worker(serial, state["qry_q"], send_queue, loop, query_lane=True),
                name=f"a11y-qry-{serial}",
            )

        # At-most-once / in-order guard on enqueue.
        if seq > 0 and (
            seq <= int(state.get("last_seq", 0) or 0)
            or seq in state.get("queued_seqs", set())
        ):
            await _reject("stale_seq")
            return

        q = state["qry_q"] if mode == "query" else state["mut_q"]
        item = {
            "id": req_id,
            "serial": serial,
            "seq": seq,
            "ts": ts,
            "action": action,
            "payload": payload,
            "session_id": session_id,
            "mode": mode,
            "enqueued_at": time.time(),
        }
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            await _reject("queue_overflow", queue_pos=q.qsize())
            return
        if seq > 0:
            state.setdefault("queued_seqs", set()).add(seq)

        # Query mode returns only a11y_result to avoid ack/result race on same id.
        if mode != "query":
            await bounded_put(send_queue, dumps({
                "type": "a11y_ack",
                "id": req_id,
                "serial": serial,
                "seq": seq,
                "accepted": True,
                "queue_pos": q.qsize() - 1,
            }), serial=serial, label="a11y_ack")

    async def _a11y_worker(
        self,
        serial: str,
        q: asyncio.Queue,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        query_lane: bool,
    ) -> None:
        while True:
            item = await q.get()
            if item is None:
                return
            state = self._a11y_state.get(serial)
            if state is None:
                continue
            # Drop stale session items
            sess = str(item.get("session_id") or "")
            if sess and sess != str(state.get("session_id") or ""):
                continue
            seq = int(item.get("seq", 0) or 0)
            if seq > 0 and seq <= int(state.get("last_seq", 0) or 0):
                state.get("queued_seqs", set()).discard(seq)
                continue

            ui_executor = self._u2_executor
            mutates_ui = (
                ui_executor is not None
                and item.get("action") != "dump_hierarchy"
            )
            if mutates_ui:
                ui_executor.begin_ui_mutation(serial)
            try:
                future = loop.run_in_executor(
                    adb_executor(),
                    self._execute_a11y_action,
                    item,
                )
                res = await _await_executor_completion(future)
            finally:
                if mutates_ui:
                    ui_executor.end_ui_mutation(serial)
            if seq > 0:
                state.get("queued_seqs", set()).discard(seq)
                state["last_seq"] = max(int(state.get("last_seq", 0) or 0), seq)

            # Mutating lane: best-effort emit result for observability (caller shouldn't block on it)
            # Query lane: caller expects a11y_result.
            if item.get("mode") != "query":
                res["id"] = f"{res.get('id', '')}:result"
            await bounded_put(
                send_queue, dumps(res), serial=serial, label="a11y_result"
            )

    def _execute_a11y_action(self, item: dict) -> dict:
        serial = str(item.get("serial", "") or "")
        req_id = str(item.get("id", "") or "")
        action = str(item.get("action", "") or "")
        payload = item.get("payload") or {}
        seq = int(item.get("seq", 0) or 0)
        try:
            if action == "tap":
                x = int(payload.get("x", 0)); y = int(payload.get("y", 0))
                out, rc = _adb_shell(serial, f"input tap {x} {y}", timeout=5)
                ok = rc == 0
                err = "" if ok else out
                data = {}
            elif action in ("swipe", "drag"):
                x1 = int(payload.get("x1", 0)); y1 = int(payload.get("y1", 0))
                x2 = int(payload.get("x2", 0)); y2 = int(payload.get("y2", 0))
                ms = int(payload.get("ms", 300))
                out, rc = _adb_shell(serial, f"input swipe {x1} {y1} {x2} {y2} {ms}", timeout=8)
                ok = rc == 0
                err = "" if ok else out
                data = {}
            elif action == "long_tap":
                x = int(payload.get("x", 0)); y = int(payload.get("y", 0)); ms = int(payload.get("ms", 800))
                out, rc = _adb_shell(serial, f"input swipe {x} {y} {x} {y} {ms}", timeout=8)
                ok = rc == 0
                err = "" if ok else out
                data = {}
            elif action == "double_tap":
                x = int(payload.get("x", 0)); y = int(payload.get("y", 0))
                out1, rc1 = _adb_shell(serial, f"input tap {x} {y}", timeout=5)
                if rc1 == 0:
                    time.sleep(0.1)
                    out2, rc2 = _adb_shell(serial, f"input tap {x} {y}", timeout=5)
                    ok = rc2 == 0
                    err = "" if ok else out2
                else:
                    ok = False
                    err = out1
                data = {}
            elif action == "key":
                key = str(payload.get("key", "") or "").lower()
                key_map = {"home": "3", "back": "4", "recent": "187", "app_switch": "187", "enter": "66", "paste": "279", "delete": "67", "del": "67"}
                code = key_map.get(key, key)
                out, rc = _adb_shell(serial, f"input keyevent {code}", timeout=5)
                ok = rc == 0
                err = "" if ok else out
                data = {}
            elif action == "type":
                text = str(payload.get("text", "") or "")
                safe = text.replace(" ", "%s")
                out, rc = _adb_shell(serial, f'input text "{safe}"', timeout=8)
                ok = rc == 0
                err = "" if ok else out
                data = {}
            elif action == "dump_hierarchy":
                ok, err, data = self._execute_dump_hierarchy(serial, payload)
            else:
                ok = False
                err = f"unsupported_action:{action}"
                data = {}
            return {
                "type": "a11y_result",
                "id": req_id,
                "serial": serial,
                "seq": seq,
                "ok": bool(ok),
                "error": err,
                "data": data,
            }
        except Exception as exc:
            return {
                "type": "a11y_result",
                "id": req_id,
                "serial": serial,
                "seq": seq,
                "ok": False,
                "error": str(exc),
                "data": {},
            }

    def _dump_hierarchy_http_sync(
        self,
        serial: str,
        timeout: float,
        compressed: bool = False,
    ) -> str:
        """Fast path: atx-agent GET /dump/hierarchy (~4–5s on device). Empty → caller falls back to u2."""
        path = "/dump/hierarchy"
        if compressed:
            path = f"{path}?compressed=1"
        r = self._do_u2_http(
            serial,
            "GET",
            path,
            "",
            "application/json",
            max(1.0, min(float(timeout), 15.0)),
        )
        body = str(r.get("body") or "")
        if r.get("ok") and _looks_like_hierarchy_xml(body):
            return body
        if body and not r.get("ok"):
            logger.debug(
                "atx-http dump failed serial=%s status=%s: %s",
                serial,
                r.get("status"),
                body[:120],
            )
        return ""

    def _execute_dump_hierarchy(self, serial: str, payload: dict) -> tuple[bool, str, dict]:
        """
        Query lane only: use atx-agent dumpHierarchy endpoint.

        The caller owns the overall deadline; keep retries opportunistic so a
        fast empty/500 response can recover, but a slow dump does not exceed the
        relay timeout by much.
        """
        try:
            total_timeout = float(
                payload.get("timeout")
                or payload.get("timeout_s")
                or _env_float("A11Y_DUMP_TIMEOUT", 4.0)
            )
        except Exception:
            total_timeout = _env_float("A11Y_DUMP_TIMEOUT", 4.0)
        total_timeout = max(1.0, min(total_timeout, 15.0))

        try:
            attempts = int(payload.get("attempts") or _env_int("A11Y_DUMP_ATTEMPTS", 2))
        except Exception:
            attempts = 2
        attempts = max(1, min(attempts, 3))

        deadline = time.monotonic() + total_timeout
        last_err = ""
        last_status = 0
        last_ct = ""

        for attempt in range(attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0.2:
                break
            req_timeout = max(1.0, min(total_timeout, remaining))
            r = self._do_u2_http(
                serial,
                "GET",
                "/dump/hierarchy",
                "",
                "application/json",
                req_timeout,
            )
            last_status = int(r.get("status", 0) or 0)
            last_ct = str(r.get("content_type", "") or "")
            body = str(r.get("body", "") or "")
            if bool(r.get("ok")) and _looks_like_hierarchy_xml(body):
                return True, "", {
                    "xml": body,
                    "content_type": last_ct,
                    "status": last_status,
                    "attempts": attempt + 1,
                }
            last_err = body or str(r.get("error", "") or "")
            if attempt < attempts - 1 and (deadline - time.monotonic()) > 0.5:
                time.sleep(0.2)

        err = last_err or f"dump_hierarchy timeout after {total_timeout:.1f}s"
        return False, err, {
            "xml": "",
            "content_type": last_ct,
            "status": last_status,
            "attempts": attempts,
        }

    async def _handle_u2_request(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Proxy an HTTP request to atx-agent (port 7912) on behalf of device_farm."""
        msg_id       = msg.get("msg_id", "")
        serial       = msg.get("serial", "")
        method       = msg.get("method", "GET").upper()
        path         = msg.get("path", "/")
        body         = msg.get("body", "")
        content_type = msg.get("content_type", "")
        timeout      = max(1.0, float(msg.get("timeout", 30)))

        ui_executor = self._u2_executor
        mutates_ui = (
            ui_executor is not None
            and method == "POST"
            and str(path).startswith("/jsonrpc/")
        )
        if mutates_ui:
            ui_executor.begin_ui_mutation(str(serial))

        loop   = asyncio.get_running_loop()
        try:
            future = loop.run_in_executor(
                u2_executor_pool(),
                self._do_u2_http,
                serial,
                method,
                path,
                body,
                content_type,
                timeout,
            )
            result = await _await_executor_completion(future)
        finally:
            if mutates_ui:
                ui_executor.end_ui_mutation(str(serial))
        result["type"]   = "u2_result"
        result["msg_id"] = msg_id
        # Bounded put: control results are important, but we MUST NOT block
        # forever waiting for a stuck transport — that's what froze the agent
        # after a few hours. `bounded_put` drops with a counter on timeout.
        await bounded_put(
            send_queue, dumps(result), serial=serial, label="u2_result"
        )

    def _atx_http_host(self, serial: str) -> str:
        """Host for http://HOST:7912 — must be an IPv4, not a USB ADB serial string."""
        if not serial:
            return ""
        if ":" in serial:
            return serial.rsplit(":", 1)[0]
        for tcp_s, usb_s in self._tcp_suppressed_for_usb.items():
            if usb_s == serial and ":" in tcp_s:
                return tcp_s.rsplit(":", 1)[0]
        cached = self._atx_lan_host_cache.get(serial)
        if cached:
            return cached
        ip = _resolve_device_lan_ip(serial)
        if ip:
            self._atx_lan_host_cache[serial] = ip
            logger.debug("u2 atx host: %s → %s (LAN probe)", serial, ip)
            return ip
        logger.warning(
            "u2 atx host: cannot resolve LAN IP for USB serial %r — u2 HTTP will fail",
            serial,
        )
        return serial

    def _cached_atx_forward_endpoint(self, serial: str) -> tuple[str, int] | None:
        if not serial or ":" in serial:
            return None
        with self._atx_forward_lock:
            return self._atx_forward_cache.get(serial)

    def _clear_atx_forward(self, serial: str) -> None:
        if not serial:
            return
        with self._atx_forward_lock:
            endpoint = self._atx_forward_cache.pop(serial, None)
        if endpoint is None:
            return
        host, port = endpoint
        try:
            from relay.http_pool import default_pool
            default_pool().drop_host(host, port)
        except Exception:
            pass
        _run("forward", "--remove", f"tcp:{port}", serial=serial, timeout=5)

    def _ensure_atx_forward_endpoint(self, serial: str) -> tuple[str, int] | None:
        """Forward host tcp:N to device tcp:7912 for USB devices.

        This is the path for Docker/Windows setups where USB ADB works but the
        host cannot route to the phone's WLAN IP.
        """
        if not serial or ":" in serial:
            return None
        with self._atx_forward_lock:
            cached = self._atx_forward_cache.get(serial)
            if cached is not None:
                return cached
            out, rc = _run("forward", "tcp:0", "tcp:7912", serial=serial, timeout=10)
            if rc != 0:
                logger.warning(
                    "u2 atx adb-forward failed serial=%s: %s",
                    serial,
                    (out or "").strip()[:200],
                )
                return None
            port = 0
            for token in (out or "").replace("\r", " ").split():
                if token.isdigit():
                    port = int(token)
                    break
            if port <= 0:
                logger.warning(
                    "u2 atx adb-forward returned no port serial=%s output=%r",
                    serial,
                    (out or "").strip()[:200],
                )
                return None
            endpoint = (_atx_forward_host(), port)
            self._atx_forward_cache[serial] = endpoint
            logger.info(
                "u2 atx adb-forward active serial=%s endpoint=%s:%s -> tcp:7912",
                serial,
                endpoint[0],
                endpoint[1],
            )
            return endpoint

    def _u2_http_request(
        self,
        host: str,
        port: int,
        method: str,
        path: str,
        body: str,
        content_type: str,
        timeout: float,
    ) -> dict:
        from relay.http_pool import default_pool

        headers: dict[str, str] = {}
        data: bytes | None = None
        if body:
            data = body.encode("utf-8") if isinstance(body, str) else body
            headers["Content-Type"] = content_type or "application/json"

        status, resp_headers, resp_body = default_pool().request(
            host,
            port,
            method,
            path,
            body=data,
            headers=headers,
            timeout=timeout,
        )
        ok = 200 <= status < 400
        return {
            "ok": ok,
            "status": status,
            "body": resp_body.decode("utf-8", errors="replace"),
            "content_type": resp_headers.get("Content-Type", ""),
        }

    def _do_u2_http(
        self,
        serial: str,
        method: str,
        path: str,
        body: str,
        content_type: str,
        timeout: float,
    ) -> dict:
        """Blocking: call atx-agent at device_ip:7912 and return a result dict.

        Uses a per-process HTTP/1.1 keep-alive pool to avoid the per-call TCP
        handshake. atx-agent supports keep-alive, so a warm pool turns each
        call into a single request/response round trip — ~30-100ms saved
        per call on WiFi-attached phones.
        """
        forward_endpoint = self._cached_atx_forward_endpoint(serial)
        host, port = forward_endpoint or (self._atx_http_host(serial), 7912)

        try:
            return self._u2_http_request(host, port, method, path, body, content_type, timeout)
        except Exception as exc:
            if forward_endpoint is not None:
                self._clear_atx_forward(serial)
            endpoint = self._ensure_atx_forward_endpoint(serial)
            if endpoint is not None:
                fwd_host, fwd_port = endpoint
                try:
                    return self._u2_http_request(
                        fwd_host,
                        fwd_port,
                        method,
                        path,
                        body,
                        content_type,
                        timeout,
                    )
                except Exception as fwd_exc:
                    self._clear_atx_forward(serial)
                    logger.debug(
                        "u2 HTTP adb-forward error %s http://%s:%s%s: %s",
                        method,
                        fwd_host,
                        fwd_port,
                        path,
                        fwd_exc,
                    )
                    exc = RuntimeError(f"{exc}; adb-forward: {fwd_exc}")
            logger.debug("u2 HTTP error %s http://%s:%s%s: %s", method, host, port, path, exc)
            return {
                "ok":           False,
                "status":       0,
                "body":         str(exc),
                "content_type": "",
            }

    def _u2_jsonrpc_sync(
        self,
        serial: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> tuple[bool, str]:
        res = self._do_u2_http(
            serial,
            "POST",
            "/jsonrpc/0",
            json.dumps(payload),
            "application/json",
            timeout,
        )
        return self._parse_u2_touch_rpc_result(res)

    async def _handle_u2_batch(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Execute a batch of primitive u2 actions and return aggregated results."""
        serial = str(msg.get("serial", "") or "")
        actions = msg.get("actions") or []
        cancel_event = msg.get("_cancel_event")
        if not isinstance(cancel_event, asyncio.Event):
            cancel_event = None
        started = time.perf_counter()
        ui_executor = self._u2_executor
        fast_touch_candidate = bool(
            ui_executor is not None
            and isinstance(actions, list)
            and actions
            and all(
                isinstance(action, dict)
                and action.get("op") in {"click", "swipe", "long_click"}
                for action in actions
            )
        )
        if fast_touch_candidate:
            ui_executor.begin_ui_mutation(serial)
        try:
            result = await self._try_u2_batch_touch_fast_path(
                serial=serial,
                actions=actions,
                early_exit=bool(msg.get("early_exit", True)),
                cancel_event=cancel_event,
            )
        finally:
            if fast_touch_candidate:
                ui_executor.end_ui_mutation(serial)
        if result is not None:
            pass
        elif self._u2_executor is None:
            result = {"ok": False, "stopped_at": 0, "results": [],
                      "error": "u2 batch not enabled"}
        else:
            result = await self._u2_executor.run_batch(
                serial=serial,
                actions=actions,
                early_exit=bool(msg.get("early_exit", True)),
                cancel_event=cancel_event,
            )
        result.setdefault("total_ms", round((time.perf_counter() - started) * 1000, 1))
        result["type"] = "u2_batch_result"
        result["id"] = msg.get("id", "")
        # dump_hierarchy / screenshot ops can produce MB-sized values; offload
        # large dumps to keep the event loop responsive. With orjson the
        # offloaded calls actually run in parallel because the GIL is released.
        payload = await dumps_maybe_offload(result)
        await bounded_put(
            send_queue, payload, serial=serial, label="u2_batch_result"
        )

    async def _try_u2_batch_touch_fast_path(
        self,
        *,
        serial: str,
        actions: list[dict],
        early_exit: bool,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> Optional[dict]:
        """Low-latency u2_batch path for coordinate touch only.

        Selector, dump, app, and file operations stay on U2Executor because they
        need the richer uiautomator2 Python surface. Plain coordinate touch can
        use the same atx-agent JSON-RPC HTTP path as u2_proxy, avoiding the
        batch session pool, per-serial lock, and alive-check overhead.
        """
        if not actions:
            return None
        prepared: list[tuple[str, dict, float]] = []
        for act in actions:
            rpc = self._u2_touch_rpc_payload(act, len(prepared) + 1)
            if rpc is None:
                return None
            method, payload, timeout = rpc
            prepared.append((method, payload, timeout))

        loop = asyncio.get_running_loop()

        def _run() -> dict:
            results: list[dict] = []
            stopped_at: Optional[int] = None
            for idx, (op, payload, timeout) in enumerate(prepared):
                if cancel_event is not None and cancel_event.is_set():
                    return {
                        "ok": False,
                        "stopped_at": idx,
                        "results": results,
                        "error": "cancelled",
                        "cancelled": True,
                    }
                try:
                    res = self._do_u2_http(
                        serial,
                        "POST",
                        "/jsonrpc/0",
                        json.dumps(payload),
                        "application/json",
                        timeout,
                    )
                    ok, error = self._parse_u2_touch_rpc_result(res)
                except Exception as exc:
                    ok, error = False, str(exc)
                entry: dict[str, Any] = {"op": op, "ok": ok}
                if error:
                    entry["error"] = error
                results.append(entry)
                if not ok and early_exit:
                    stopped_at = idx
                    break
                if cancel_event is not None and cancel_event.is_set() and idx + 1 < len(prepared):
                    return {
                        "ok": False,
                        "stopped_at": idx + 1,
                        "results": results,
                        "error": "cancelled",
                        "cancelled": True,
                    }
            all_ok = all(bool(item.get("ok")) for item in results) and len(results) == len(prepared)
            return {
                "ok": all_ok,
                "stopped_at": stopped_at,
                "results": results,
                "error": None if all_ok else (results[-1].get("error") if results else "touch_failed"),
            }

        future = loop.run_in_executor(u2_executor_pool(), _run)
        return await _await_executor_completion(future)

    def _u2_touch_rpc_payload(self, act: dict, req_id: int) -> Optional[tuple[str, dict, float]]:
        op = str(act.get("op", "") or "")
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
        }
        timeout = 1.5
        if op == "click":
            payload["method"] = "click"
            payload["params"] = [int(act["x"]), int(act["y"])]
        elif op == "swipe":
            duration = max(0.0, float(act.get("duration", 0.5)))
            steps = max(1, int(duration * 40))
            payload["method"] = "swipe"
            payload["params"] = [
                int(act["fx"]), int(act["fy"]),
                int(act["tx"]), int(act["ty"]),
                steps,
            ]
            timeout = max(1.5, duration + 0.8)
        elif op == "long_click":
            duration = max(0.1, float(act.get("duration", 0.5)))
            payload["method"] = "longClick"
            payload["params"] = [int(act["x"]), int(act["y"])]
            timeout = max(1.5, duration + 0.8)
        else:
            return None
        return op, payload, timeout

    @staticmethod
    def _parse_u2_touch_rpc_result(res: dict) -> tuple[bool, str]:
        if not bool(res.get("ok")):
            status = int(res.get("status", 0) or 0)
            if status:
                return False, f"JSON-RPC HTTP {status}"
            return False, str(res.get("body") or "JSON-RPC request failed")
        raw = str(res.get("body") or "")
        if not raw.strip():
            return False, "JSON-RPC empty response"
        try:
            data = json.loads(raw)
        except Exception:
            return False, f"JSON-RPC invalid response: {raw[:120]!r}"
        if "error" in data:
            return False, f"JSON-RPC error: {data['error']}"
        return True, ""

    async def _handle_u2_flow(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Execute a named high-level u2 flow and return result."""
        serial = str(msg.get("serial", "") or "")
        if self._u2_executor is None:
            result: dict = {"ok": False, "value": None, "error": "u2 batch not enabled"}
        else:
            result = await self._u2_executor.execute_flow(
                serial=serial,
                flow=msg.get("flow", ""),
                params=msg.get("params") or {},
            )
        result["type"] = "u2_flow_result"
        result["id"] = msg.get("id", "")
        result["flow"] = msg.get("flow", "")
        payload = await dumps_maybe_offload(result)
        await bounded_put(
            send_queue, payload, serial=serial, label="u2_flow_result"
        )

    async def _handle_extra_data(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """PA B: u2 dump + in-process ingest; reply extra_data_result."""
        loop = asyncio.get_running_loop()
        req_id = str(msg.get("id", "") or "")
        serial = str(msg.get("serial", "") or "")
        strategy = str(msg.get("strategy", "fb_posts") or "fb_posts")
        context = msg.get("context") if isinstance(msg.get("context"), dict) else {}
        reply: dict[str, Any] = {
            "type": "extra_data_result",
            "id": req_id,
            "ok": False,
            "route": "relay_u2",
            "error": "",
        }
        if not serial:
            reply["error"] = "serial_required"
            await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
            return
        if self._u2_executor is None:
            reply["error"] = "u2_batch_not_enabled"
            await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
            return
        if self._extra_ingest is None:
            reply["error"] = "extra_data_not_configured"
            await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
            return

        from relay.extra_data.collector import (
            build_ingest_payload,
            collect_fb_comment_filter_apply,
            collect_fb_comment_target_with_tap,
            collect_xml_snapshots,
            strip_private_context,
        )
        from relay.extra_data.ingest import _parse_items

        expand_on = bool(context.get("expand_see_more"))
        logger.info(
            "extra_data start serial=%s strategy=%s expand_see_more=%s",
            serial,
            strategy,
            expand_on,
        )

        def _attach_collect_error_diagnostic() -> None:
            diagnostic = context.get("open_post_detail_diagnostic")
            if not isinstance(diagnostic, dict):
                return
            reply["diagnostic"] = diagnostic
            reply["ingest"] = {"ok": False, "diagnostic": diagnostic}

        try:
            if strategy == "fb_comment_filter_apply":
                report, collect_err = await collect_fb_comment_filter_apply(
                    self._u2_executor,
                    serial,
                    context,
                )
                if collect_err:
                    reply["error"] = collect_err
                else:
                    reply["ok"] = True
                    reply["ingest"] = {"ok": True, "diagnostic": report}
                await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
                return

            if strategy == "fb_comment_target_tap":
                snapshots, collect_err, agent_tapped, diagnostic = (
                    await collect_fb_comment_target_with_tap(
                        self._u2_executor,
                        serial,
                        context,
                    )
                )
                if collect_err:
                    reply["error"] = collect_err
                    await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
                    return
                reply["ok"] = True
                reply["ingest"] = {"ok": True, "diagnostic": diagnostic}
                if agent_tapped:
                    reply["agent_tapped"] = True
                await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
                return

            if strategy in {"fb_comment_target", "fb_comment_filter_next"}:
                snapshots, collect_err = await collect_xml_snapshots(
                    self._u2_executor,
                    serial,
                    strategy,
                    context,
                )
                if collect_err:
                    reply["error"] = collect_err
                    await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
                    return
                primary = snapshots[0] if snapshots else ""
                parse_strategy = (
                    "fb_comment_target"
                    if strategy == "fb_comment_target"
                    else strategy
                )
                # lxml parsing for ~MB hierarchies is pure-CPU; keep it off
                # the event loop so heartbeats / gRPC sends are not delayed.
                _, diagnostic = await loop.run_in_executor(
                    cpu_executor(), _parse_items, parse_strategy, primary, strip_private_context(context),
                )
                reply["ok"] = True
                reply["ingest"] = {"ok": True, "diagnostic": diagnostic}
                await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
                return

            snapshots, collect_err = await collect_xml_snapshots(
                self._u2_executor,
                serial,
                strategy,
                context,
            )
            if collect_err:
                reply["error"] = collect_err
                _attach_collect_error_diagnostic()
                await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")
                return

            from relay.extra_data.collector import (
                _capture_screenshot_b64,
                should_capture_screenshot,
            )

            evidence: dict[str, Any] = {}
            if snapshots:
                evidence["hierarchy_xml"] = snapshots[-1]
            screenshot_b64 = str(context.pop("_ingest_screenshot_b64", "") or "").strip()
            if not screenshot_b64 and should_capture_screenshot(context):
                screenshot_b64 = await _capture_screenshot_b64(self._u2_executor, serial) or ""
            if screenshot_b64:
                evidence["screenshot_b64"] = screenshot_b64

            ingest_context = strip_private_context(context)
            payload = build_ingest_payload(
                serial=serial,
                strategy=strategy,
                context=ingest_context,
                snapshots=snapshots,
                request_id=req_id,
            )
            if evidence:
                payload["evidence"] = evidence
            ingest = await self._extra_ingest.process_payload(payload)
            ingest_diag = ingest.get("diagnostic") if isinstance(ingest.get("diagnostic"), dict) else {}
            logger.info(
                "extra_data ingest done serial=%s strategy=%s ok=%s parsed=%s inserted=%s duplicate=%s "
                "post_stats_found=%s post_stats_persisted=%s parent_stats_skip=%s "
                "comments_returned=%s snapshots=%s xml_bytes=%s elapsed_ms=%s",
                serial,
                strategy,
                bool(ingest.get("ok")),
                ingest.get("parsed_count"),
                ingest.get("inserted_count"),
                ingest.get("duplicate_count"),
                ingest_diag.get("post_stats_found"),
                ingest_diag.get("post_stats_persisted"),
                ingest_diag.get("parent_stats_update_skipped_reason"),
                ingest_diag.get("comments_returned"),
                ingest.get("snapshot_count"),
                ingest.get("xml_bytes"),
                ingest.get("elapsed_ms"),
            )
            if ingest.get("ok"):
                reply["ok"] = True
                reply_ingest = dict(ingest)
                reply_ingest.pop("evidence_pending", None)
                if screenshot_b64:
                    reply_ingest["screenshot_b64"] = screenshot_b64
                if not bool(ingest_context.get("return_items")):
                    reply_ingest.pop("items", None)
                reply["ingest"] = reply_ingest
            else:
                reply["error"] = str(ingest.get("error") or "ingest_failed")
                reply["ingest"] = ingest
        except Exception as exc:
            logger.warning("extra_data failed serial=%s strategy=%s: %s", serial, strategy, exc)
            reply["error"] = str(exc)
        await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")

    def _cancel_extra_data_task(self, req_id: str) -> bool:
        if not req_id:
            return False
        event = self._extra_data_cancel_events.pop(req_id, None)
        if event is not None:
            event.set()
        task = self._extra_data_tasks.pop(req_id, None)
        if task is None or task.done():
            return event is not None
        task.cancel()
        logger.info("extra_data cancelled request_id=%s", req_id)
        return True

    def _cancel_u2_batch(self, req_id: str) -> bool:
        if not req_id:
            return False
        event = self._u2_batch_cancel_events.get(req_id)
        if event is not None:
            event.set()
        task = self._u2_batch_tasks.get(req_id)
        if task is None or task.done():
            return event is not None
        logger.info("u2_batch cancel requested request_id=%s", req_id)
        return True

    async def _enqueue_command(
        self, msg: dict, send_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
    ) -> None:
        cmd_serial = str(msg.get("serial", "") or "")
        serial_key = cmd_serial or "-"
        state = self._command_state.get(serial_key)
        if state is None:
            state = {
                "q": asyncio.Queue(maxsize=self._command_max_queue),
                "worker": None,
            }
            self._command_state[serial_key] = state
        worker = state.get("worker")
        if worker is None or worker.done():
            state["worker"] = asyncio.create_task(
                self._command_worker(state["q"], send_queue, loop),
                name=f"cmd-worker-{serial_key}",
            )
        try:
            state["q"].put_nowait(msg)
        except asyncio.QueueFull:
            result = dumps({
                "type": "result",
                "msg_id": str(msg.get("msg_id", "") or ""),
                "ok": False,
                "exit_code": -1,
                "output": "",
                "error": f"command queue full: serial={serial_key}",
            })
            bounded_put_nowait(send_queue, result, serial=cmd_serial, label="cmd_result")

    async def _command_worker(
        self,
        q: asyncio.Queue,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        while True:
            msg = await q.get()
            if msg is None:
                return
            cmd_serial = str(msg.get("serial", "") or "")
            cmd_type = int(msg.get("cmd_type", CMD_SHELL))
            result = await loop.run_in_executor(
                adb_executor(),
                self._execute_command,
                msg.get("msg_id", ""),
                cmd_serial,
                msg.get("cmd", ""),
                int(msg.get("timeout", 30)),
                cmd_type,
            )
            bounded_put_nowait(send_queue, result, serial=cmd_serial, label="cmd_result")
            if cmd_type == CMD_ADB_CONNECT:
                try:
                    parsed = json.loads(result)
                except Exception:
                    parsed = {}
                if parsed.get("ok"):
                    await self._refresh_devices_after_adb_connect(
                        send_queue,
                        loop,
                        cmd_serial,
                    )

    def _cancel_command_workers(self, serial: str | None = None) -> None:
        if serial is not None:
            serial_key = serial or "-"
            state = self._command_state.pop(serial_key, None)
            if not state:
                return
            worker = state.get("worker")
            if worker is not None and not worker.done():
                worker.cancel()
            return
        for state in self._command_state.values():
            worker = state.get("worker")
            if worker is not None and not worker.done():
                worker.cancel()
        self._command_state.clear()

    def _execute_command(
        self,
        msg_id: str,
        serial: str,
        cmd: str,
        timeout: int,
        cmd_type: int,
    ) -> str:
        """Run ADB command and return JSON result string."""
        if cmd_type != CMD_ADB_CONNECT:
            ctx = self._registry.get(serial)
            if ctx is None or not ctx.is_available:
                state_str = ctx.state.value if ctx else "unknown"
                return dumps({
                    "type":      "result",
                    "msg_id":    msg_id,
                    "ok":        False,
                    "exit_code": -1,
                    "output":    "",
                    "error":     f"serial {serial!r} not available (state={state_str})",
                })

        try:
            if cmd_type == CMD_ADB_CONNECT:
                anchor = self._tcp_suppressed_for_usb.get(serial)
                if anchor:
                    usb_ctx = self._registry.get(anchor)
                    if usb_ctx and usb_ctx.is_available:
                        return dumps({
                            "type":      "result",
                            "msg_id":    msg_id,
                            "ok":        True,
                            "exit_code": 0,
                            "output":    (
                                f"skipped adb connect {serial!r} "
                                f"(USB preferred: {anchor})"
                            ),
                            "error":     "",
                        })
                    self._tcp_suppressed_for_usb.pop(serial, None)
                output, rc = _adb_connect(serial, timeout=timeout)
            elif cmd_type == CMD_RESTART_U2:
                output, rc = _restart_u2(serial, timeout=timeout)
            elif cmd_type == CMD_RESTART_ATX:
                output, rc = _restart_atx(serial, timeout=timeout)
            elif cmd_type == CMD_BOOTSTRAP:
                output, rc = _bootstrap_device(serial, timeout=max(timeout, 180))
            elif cmd_type == CMD_SCREENCAP:
                output, rc = _screencap(serial, timeout=timeout)
            elif cmd_type == CMD_PROBE_CAPS:
                caps = _probe_capabilities(serial)
                output, rc = dumps(caps), 0
            elif cmd_type == CMD_RESTART_SCRCPY:
                output, rc = self._restart_scrcpy_sync(serial, timeout)
            else:
                output, rc = _adb_shell(serial, cmd, timeout=timeout)
                if lock_rotation_after_shell_enabled():
                    lock_portrait_rotation(serial)

            return dumps({
                "type":      "result",
                "msg_id":    msg_id,
                "ok":        rc == 0,
                "exit_code": rc,
                "output":    output,
                "error":     "" if rc == 0 else output,
            })
        except Exception as exc:
            return dumps({
                "type":      "result",
                "msg_id":    msg_id,
                "ok":        False,
                "exit_code": -1,
                "output":    "",
                "error":     str(exc),
            })

    def _on_session_stopped(self, adb_serial: str, reason: str) -> None:
        # NOTE: "device_offline" is deliberately NOT in this set. When a device
        # disappears we already teardown scrcpy via stop_all_for_serial; the
        # ONLINE transition's _resume_desired_scrcpy_sessions path brings it
        # back up. Restarting from the stop callback would race the reconnect.
        abnormal_reasons = {"zombie_thread", "runtime_error", "startup_failure"}
        logical = self._logical_serial_for_adb(adb_serial)
        state = self._scrcpy_desired.get(logical)
        if not state:
            return
        state["last_stop_reason"] = reason
        if not state.get("desired", False):
            logger.info("auto-resume skipped %s: desired=false reason=%s", logical, reason)
            return
        if state.get("manual_stop", False):
            logger.info("auto-resume skipped %s: manual_stop=true reason=%s", logical, reason)
            return
        if reason not in abnormal_reasons:
            logger.info("auto-resume skipped %s: non-abnormal reason=%s", logical, reason)
            return
        if not self._scrcpy_auto_resume_enabled:
            logger.info("auto-resume disabled, skip %s (reason=%s)", logical, reason)
            return
        logger.info("auto-resume flagged %s: reason=%s", logical, reason)
        if self._active_send_queue is None or self._active_loop is None:
            return

        queue = self._active_send_queue
        loop = self._active_loop

        def _schedule_resume() -> None:
            asyncio.create_task(
                self._resume_desired_scrcpy_sessions(
                    queue,
                    loop,
                    source="session-stopped",
                )
            )

        loop.call_soon_threadsafe(_schedule_resume)

    def _restart_scrcpy_sync(self, serial: str, timeout: int) -> tuple[str, int]:
        """Stop + resume scrcpy for serial. Called from thread pool (_execute_command)."""
        loop  = self._active_loop
        queue = self._active_send_queue
        if loop is None or queue is None:
            return "no active transport", -1

        adb_serial = self._scrcpy_device_serial(serial)
        logical    = self._logical_serial_for_adb(adb_serial)

        async def _do_restart():
            await self._scrcpy_mgr.stop_session(adb_serial, reason="manual_restart")
            state = self._scrcpy_desired.get(logical) or self._scrcpy_desired.get(serial)
            if state:
                state["desired"]     = True
                state["manual_stop"] = False
                state["last_stop_reason"] = ""
            await self._start_desired_scrcpy(logical, queue, loop)

        fut = asyncio.run_coroutine_threadsafe(_do_restart(), loop)
        try:
            fut.result(timeout=float(timeout))
            return "scrcpy restarted", 0
        except Exception as exc:
            return str(exc), -1

    def _logical_serial_for_adb(self, adb_serial: str) -> str:
        for logical, mapped in self._scrcpy_logical_to_adb.items():
            if mapped == adb_serial:
                return logical
        return adb_serial

    async def _start_desired_scrcpy(
        self,
        logical_serial: str,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
    ) -> bool:
        state = self._scrcpy_desired.get(logical_serial)
        if not state or not state.get("desired"):
            return False

        cfg = state.get("cfg") or {}
        adb_serial = self._adb_serial_prefer_usb_over_tcp(logical_serial)
        state["adb_serial"] = adb_serial
        if adb_serial != logical_serial:
            self._scrcpy_logical_to_adb[logical_serial] = adb_serial

        await self._scrcpy_mgr.start_session(
            serial=adb_serial,
            max_fps=int(cfg.get("max_fps") or SCRCPY_DEFAULT_MAX_FPS),
            max_width=int(cfg.get("max_width") or SCRCPY_DEFAULT_MAX_WIDTH),
            enable_control=bool(cfg.get("enable_control", True)),
            port=int(cfg.get("port", 27183)),
            send_queue=send_queue,
            loop=loop,
            bitrate=int(cfg.get("bitrate") or SCRCPY_DEFAULT_BITRATE),
            low_latency=bool(cfg.get("low_latency", False)),
        )
        started = self._scrcpy_mgr.get(adb_serial) is not None
        if started:
            now = time.monotonic()
            last_started = float(state.get("last_started_at", 0.0) or 0.0)
            if now - last_started > SCRCPY_STABLE_RESET_SECONDS:
                state["retry_count"] = 0
                state["retry_window_start"] = 0.0
            state["last_started_at"] = now
            state["manual_stop"] = False
            state["last_stop_reason"] = ""
        return started

    async def _resume_desired_scrcpy_sessions(
        self,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        source: str,
    ) -> None:
        # The reason filter only applies to the session-stopped callback path,
        # where we must avoid double-restarting after a clean/manual stop. All
        # other sources (device-online, ws-connected, grpc-connected, supervisor)
        # are recovery triggers — they must resume regardless of last reason
        # (including "device_offline", "cleanup_idle", "manual_stop" from pair
        # switchover, etc.), otherwise the stream will never come back after a
        # phone WiFi drop / reconnect cycle.
        abnormal_reasons = {"zombie_thread", "runtime_error", "startup_failure"}
        only_abnormal = source == "session-stopped"
        for logical, state in list(self._scrcpy_desired.items()):
            if logical in self._tcp_suppressed_for_usb:
                continue
            if not state.get("desired", False):
                continue
            if state.get("manual_stop", False):
                continue
            if only_abnormal and state.get("last_stop_reason") not in abnormal_reasons:
                continue
            restart_task = state.get("restart_task")
            if restart_task and not restart_task.done():
                continue
            # Recovery trigger: reset retry budget so the device gets a fresh
            # attempt window after a genuine availability change.
            if not only_abnormal:
                state["retry_count"] = 0
                state["retry_window_start"] = 0.0
            task = asyncio.create_task(
                self._restart_with_backoff(logical, send_queue, loop, source=source),
                name=f"scrcpy-restart-{logical}",
            )
            state["restart_task"] = task

    async def _restart_with_backoff(
        self,
        logical_serial: str,
        _send_queue: asyncio.Queue,
        _loop: asyncio.AbstractEventLoop,
        source: str,
    ) -> None:
        state = self._scrcpy_desired.get(logical_serial)
        if not state:
            return

        now = time.monotonic()
        window_start = float(state.get("retry_window_start", 0.0) or 0.0)
        retry_count = int(state.get("retry_count", 0) or 0)
        if window_start <= 0 or (now - window_start) > SCRCPY_RESTART_WINDOW_SECONDS:
            window_start = now
            retry_count = 0

        if retry_count >= SCRCPY_RESTART_MAX_ATTEMPTS:
            logger.warning(
                "auto-resume skipped %s: retry budget exceeded (%d/%d in %.0fs)",
                logical_serial,
                retry_count,
                SCRCPY_RESTART_MAX_ATTEMPTS,
                SCRCPY_RESTART_WINDOW_SECONDS,
            )
            state["restart_task"] = None
            state["retry_count"] = retry_count
            state["retry_window_start"] = window_start
            return

        delay = min(2 ** retry_count, SCRCPY_RESTART_MAX_BACKOFF_SECONDS)
        logger.info(
            "auto-resume scheduled %s in %.1fs (attempt=%d source=%s)",
            logical_serial,
            delay,
            retry_count + 1,
            source,
        )
        await asyncio.sleep(delay)

        state = self._scrcpy_desired.get(logical_serial)
        if not state:
            return
        if not state.get("desired") or state.get("manual_stop"):
            state["restart_task"] = None
            return

        adb_serial = self._adb_serial_prefer_usb_over_tcp(logical_serial)
        ctx = self._registry.get(adb_serial)
        if not ctx or not ctx.is_available:
            logger.info("auto-resume deferred %s: device not online (%s)", logical_serial, adb_serial)
            state["restart_task"] = None
            return

        queue = self._active_send_queue
        loop = self._active_loop
        if queue is None or loop is None:
            logger.info("auto-resume deferred %s: transport not connected", logical_serial)
            state["restart_task"] = None
            return

        state["retry_window_start"] = window_start
        state["retry_count"] = retry_count + 1
        started = await self._start_desired_scrcpy(logical_serial, queue, loop)
        state["restart_task"] = None
        if started:
            logger.info("auto-resume success %s", logical_serial)
            state["retry_count"] = 0
            state["retry_window_start"] = 0.0
            state["last_stop_reason"] = ""
        else:
            logger.warning("auto-resume failed to start %s", logical_serial)

    def _cancel_scrcpy_restart_tasks(self) -> None:
        for state in self._scrcpy_desired.values():
            task = state.get("restart_task")
            if task and not task.done():
                task.cancel()
            state["restart_task"] = None

    def _cleanup_serial_state(self, serial: str) -> None:
        """
        Scrub all per-serial state on device OFFLINE so a relay running for
        days does not slowly leak workers / queues / locks / breakers.

        Idempotent: safe to call multiple times for the same serial. Does NOT
        evict the u2 pool or stop scrcpy (those are owned by the callers).
        """
        # a11y workers: cancel mut/qry tasks, drop queues + dedup sets.
        state = self._a11y_state.pop(serial, None)
        if state is not None:
            for key in ("mut_worker", "qry_worker"):
                worker = state.get(key)
                if worker is not None and not worker.done():
                    worker.cancel()

        # Per-serial collect lock (extra_data) — keep map small across cycles.
        try:
            from relay.extra_data.collector import release_collect_lock
            release_collect_lock(serial)
        except Exception:
            pass

        warm_task = self._u2_warm_tasks.pop(serial, None)
        if warm_task is not None and not warm_task.done():
            warm_task.cancel()
        self._u2_warm_inflight.discard(serial)
        self._clear_u2_warm_backoff(serial)

        # Supervisor circuit breaker — let a re-plugged device start fresh.
        breakers = getattr(self._supervisor, "_breakers", None)
        if isinstance(breakers, dict):
            breakers.pop(serial, None)

        # Cancel any pending scrcpy restart task for this serial.
        self._cancel_command_workers(serial)
        sd_state = self._scrcpy_desired.get(serial)
        if sd_state is not None:
            task = sd_state.get("restart_task")
            if task and not task.done():
                task.cancel()
            sd_state["restart_task"] = None

        # ATX cache + logical serial map can grow with phone churn.
        host = self._atx_lan_host_cache.pop(serial, None)
        self._clear_atx_forward(serial)
        mapped_keys = [k for k, v in self._scrcpy_logical_to_adb.items() if v == serial]
        for k in mapped_keys:
            self._scrcpy_logical_to_adb.pop(k, None)

        # Close pooled HTTP/1.1 keep-alive sockets for the offline device's
        # atx-agent host; reused sockets to a powered-off phone would block
        # the next caller for the full request timeout.
        try:
            from relay.http_pool import default_pool
            if host:
                default_pool().drop_host(host, 7912)
            if ":" in serial:
                default_pool().drop_host(serial.rsplit(":", 1)[0], 7912)
        except Exception:
            pass

        # Drop the offline device's lane from the FairSendQueue so we don't
        # carry stale frames / results across an unplug+replug cycle, and so
        # the round-robin cursor stops visiting an empty lane every iteration.
        send_q = self._active_send_queue
        if send_q is not None:
            try:
                dropped = send_q.drop_serial(serial)
                if dropped:
                    logger.info(
                        "send_queue: dropped %d queued items for offline serial %s",
                        dropped, serial,
                    )
            except Exception:
                pass

    async def _guarded(self, sem: asyncio.Semaphore, coro, *, label: str = "work") -> Any:
        """
        Run `coro` while holding a global semaphore so total concurrency for
        this class of work (extra_data / u2_batch / u2_flow) is bounded
        regardless of how many phones the farm fans out to.

        Without this, a burst of 50 farm requests can spawn 50 parallel u2
        dump tasks, each grabbing a thread from the u2 pool — the loop then
        starves heartbeats and gRPC sends, which looks like a hang.
        """
        started = time.perf_counter()
        await sem.acquire()
        wait_ms = (time.perf_counter() - started) * 1000
        if wait_ms >= SEMAPHORE_WAIT_WARN_MS:
            logger.info(
                "%s semaphore wait %.1fms available=%s",
                label,
                wait_ms,
                getattr(sem, "_value", "?"),
            )
        try:
            return await coro
        finally:
            sem.release()
