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
import uuid
import time
from typing import Any, Optional

from relay.adb           import (
    _list_serials, _adb_connect, _adb_shell,
    _restart_u2, _restart_atx, _probe_capabilities,
    _resolve_device_lan_ip,
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

_HERE = os.path.dirname(os.path.abspath(__file__))
_RELAY_ID_FILE = os.path.join(os.path.dirname(_HERE), ".relay_id")

# CMD_TYPE constants — must match adb_relay_server.py
CMD_SHELL           = 0
CMD_RESTART_U2      = 1
CMD_ADB_CONNECT     = 2
CMD_RESTART_ATX     = 3
CMD_BOOTSTRAP       = 4  # push binaries + install APKs + start atx-agent + u2
CMD_SCREENCAP       = 5  # adb exec-out screencap -p → base64 PNG
CMD_PROBE_CAPS      = 6  # _probe_capabilities() → JSON dict in output
CMD_RESTART_SCRCPY  = 7  # stop + resume scrcpy session for a device


def _load_or_create_relay_id() -> str:
    if os.path.exists(_RELAY_ID_FILE):
        rid = open(_RELAY_ID_FILE).read().strip()
        if rid:
            return rid
    rid = f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    with open(_RELAY_ID_FILE, "w") as f:
        f.write(rid)
    return rid


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
            if self._grpc_root_cert_file:
                self._grpc_tls_enabled = True
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

        # Runtime: bounded executors + task registry + watchdog.
        # `_stream_tasks` is replaced per transport connect; this initial
        # registry exists so `_handle_*` paths can spawn tasks before the
        # first stream is established (e.g. during the brief startup window).
        self._stream_tasks: TaskRegistry = TaskRegistry()
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

    def _ensure_default_scrcpy_desired(self) -> None:
        """
        Ensure every currently online device has a desired scrcpy state.
        This enables "auto open screen" even on fresh startup before any
        explicit scrcpy_start command has ever been received.
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

        for serial in self._registry.online_serials:
            if serial in self._tcp_suppressed_for_usb:
                continue
            state = self._scrcpy_desired.get(serial)
            if state:
                continue
            self._scrcpy_desired[serial] = {
                "desired": True,
                "manual_stop": False,
                "last_stop_reason": "",
                "cfg": {
                    "max_fps": 30,
                    "max_width": 800,
                    "enable_control": True,
                    "port": _next_free_port(),
                    "bitrate": 2_000_000,
                    "low_latency": False,
                },
                "adb_serial": serial,
                "retry_count": 0,
                "retry_window_start": 0.0,
                "restart_task": None,
                "last_started_at": 0.0,
            }

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
                watcher_task.cancel()
                hb_task.cancel()
                sender_task.cancel()
                await send_queue.put(None)
                self._cancel_scrcpy_restart_tasks()
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

        # Shared channel — HTTP/2 multiplexes video stream + control stream
        # over a single TCP connection; the two streams are fully independent.
        async with create_grpc_channel(
            self._grpc_addr,
            tls_enabled=self._grpc_tls_enabled,
            root_cert_file=self._grpc_root_cert_file,
        ) as channel:
            client = GrpcRelayClient(
                server_addr=self._grpc_addr,
                api_key=self._api_key,
                agent_id=self._relay_id,
                send_queue=send_queue,
                loop=loop,
                channel=channel,
                tls_enabled=self._grpc_tls_enabled,
                root_cert_file=self._grpc_root_cert_file,
            )

            # Channel 2: control plane (register/heartbeat/commands) — runs
            # independently; a 180s bootstrap never blocks video frames.
            ctrl_client = AgentControlClient(channel, self._api_key, self)
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
                await client._stream_once(channel)
            finally:
                client.stop()
                ctrl_client.stop()
                watcher_task.cancel()
                hb_task.cancel()
                consume_task.cancel()
                ctrl_task.cancel()
                await send_queue.put(None)
                self._cancel_scrcpy_restart_tasks()
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

        if ctx.state == DeviceState.OFFLINE:
            # Device-offline cascade: tear down every relay component owned for
            # this serial so we don't waste retry budget hammering a dead device.
            # scrcpy_mgr.stop_all_for_serial emits reason="device_offline" which
            # _on_session_stopped treats as non-abnormal (no auto-resume until
            # the device comes back ONLINE).
            if self._u2_pool:
                asyncio.create_task(self._u2_pool.evict(serial))
            asyncio.create_task(
                self._scrcpy_mgr.stop_all_for_serial(serial, reason="device_offline")
            )
            self._cleanup_serial_state(serial)

        if ctx.state == DeviceState.ONLINE:
            loop = asyncio.get_running_loop()
            await self._ensure_capabilities_for_serials([serial], loop)
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

    async def _ensure_capabilities_for_serials(
        self, serials: list[str], loop: asyncio.AbstractEventLoop
    ) -> None:
        """Probe capabilities for ONLINE serials missing cached caps (before heartbeat)."""
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
                "capabilities (pre-heartbeat) %s: wlan_ip=%s",
                serial,
                wlan_ip or "unset",
            )

    async def _send_heartbeat(self, send_queue: asyncio.Queue) -> None:
        serials = self._registry.online_serials
        loop = asyncio.get_running_loop()
        await self._ensure_capabilities_for_serials(serials, loop)

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
            cmd_serial = str(msg.get("serial", "") or "")
            result = await loop.run_in_executor(
                adb_executor(),
                self._execute_command,
                msg.get("msg_id", ""),
                cmd_serial,
                msg.get("cmd", ""),
                int(msg.get("timeout", 30)),
                int(msg.get("cmd_type", CMD_SHELL)),
            )
            bounded_put_nowait(send_queue, result, serial=cmd_serial, label="cmd_result")

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
                    "max_fps": int(msg.get("max_fps") or 30),
                    "max_width": int(msg.get("max_width") or 800),
                    "enable_control": bool(msg.get("control", True)),
                    "port": int(msg.get("port") or 27183),
                    "bitrate": int(msg.get("bitrate") or 2_000_000),
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
            self._stream_tasks.add(
                self._guarded(u2_batch_sem(), self._handle_u2_batch(msg, send_queue)),
                name="u2-batch",
            )

        elif mtype == "u2_flow":
            self._stream_tasks.add(
                self._guarded(u2_flow_sem(), self._handle_u2_flow(msg, send_queue)),
                name="u2-flow",
            )

        elif mtype == "extra_data":
            self._stream_tasks.add(
                self._guarded(extra_data_sem(), self._handle_extra_data(msg, send_queue)),
                name="extra-data",
            )

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

            res = await loop.run_in_executor(adb_executor(), self._execute_a11y_action, item)
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
                key_map = {"home": "3", "back": "4", "recent": "187", "app_switch": "187", "enter": "66"}
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

        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            u2_executor_pool(), self._do_u2_http, serial, method, path, body, content_type, timeout
        )
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
        from relay.http_pool import default_pool

        host = self._atx_http_host(serial)

        headers: dict[str, str] = {}
        data: bytes | None = None
        if body:
            data = body.encode("utf-8") if isinstance(body, str) else body
            headers["Content-Type"] = content_type or "application/json"

        try:
            status, resp_headers, resp_body = default_pool().request(
                host, 7912, method, path,
                body=data, headers=headers, timeout=timeout,
            )
            ok = 200 <= status < 400
            return {
                "ok":           ok,
                "status":       status,
                "body":         resp_body.decode("utf-8", errors="replace"),
                "content_type": resp_headers.get("Content-Type", ""),
            }
        except Exception as exc:
            logger.debug("u2 HTTP error %s http://%s:7912%s: %s", method, host, path, exc)
            return {
                "ok":           False,
                "status":       0,
                "body":         str(exc),
                "content_type": "",
            }

    async def _handle_u2_batch(self, msg: dict, send_queue: asyncio.Queue) -> None:
        """Execute a batch of primitive u2 actions and return aggregated results."""
        serial = str(msg.get("serial", "") or "")
        if self._u2_executor is None:
            result = {"ok": False, "stopped_at": 0, "results": [],
                      "error": "u2 batch not enabled"}
        else:
            result = await self._u2_executor.run_batch(
                serial=serial,
                actions=msg.get("actions") or [],
                early_exit=bool(msg.get("early_exit", True)),
            )
        result["type"] = "u2_batch_result"
        result["id"] = msg.get("id", "")
        # dump_hierarchy / screenshot ops can produce MB-sized values; offload
        # large dumps to keep the event loop responsive. With orjson the
        # offloaded calls actually run in parallel because the GIL is released.
        payload = await dumps_maybe_offload(result)
        await bounded_put(
            send_queue, payload, serial=serial, label="u2_batch_result"
        )

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
        )
        from relay.extra_data.ingest import _parse_items

        expand_on = bool(context.get("expand_see_more"))
        logger.info(
            "extra_data start serial=%s strategy=%s expand_see_more=%s",
            serial,
            strategy,
            expand_on,
        )
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
                    cpu_executor(), _parse_items, parse_strategy, primary, context,
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

            payload = build_ingest_payload(
                serial=serial,
                strategy=strategy,
                context=context,
                snapshots=snapshots,
                request_id=req_id,
            )
            if evidence:
                payload["evidence"] = evidence
            ingest = await self._extra_ingest.process_payload(payload)
            if ingest.get("ok"):
                reply["ok"] = True
                reply_ingest = dict(ingest)
                reply_ingest.pop("evidence_pending", None)
                if screenshot_b64:
                    reply_ingest["screenshot_b64"] = screenshot_b64
                if not bool(context.get("return_items")):
                    reply_ingest.pop("items", None)
                reply["ingest"] = reply_ingest
            else:
                reply["error"] = str(ingest.get("error") or "ingest_failed")
                reply["ingest"] = ingest
        except Exception as exc:
            logger.warning("extra_data failed serial=%s strategy=%s: %s", serial, strategy, exc)
            reply["error"] = str(exc)
        await bounded_put(send_queue, await dumps_maybe_offload(reply), serial=serial, label="extra_data_result")

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

        await self._scrcpy_mgr.stop_session(adb_serial, reason="manual_stop")
        await self._scrcpy_mgr.start_session(
            serial=adb_serial,
            max_fps=int(cfg.get("max_fps", 30)),
            max_width=int(cfg.get("max_width", 800)),
            enable_control=bool(cfg.get("enable_control", True)),
            port=int(cfg.get("port", 27183)),
            send_queue=send_queue,
            loop=loop,
            bitrate=int(cfg.get("bitrate", 2_000_000)),
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

        # Supervisor circuit breaker — let a re-plugged device start fresh.
        breakers = getattr(self._supervisor, "_breakers", None)
        if isinstance(breakers, dict):
            breakers.pop(serial, None)

        # Cancel any pending scrcpy restart task for this serial.
        sd_state = self._scrcpy_desired.get(serial)
        if sd_state is not None:
            task = sd_state.get("restart_task")
            if task and not task.done():
                task.cancel()
            sd_state["restart_task"] = None

        # ATX cache + logical serial map can grow with phone churn.
        host = self._atx_lan_host_cache.pop(serial, None)
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

    async def _guarded(self, sem: asyncio.Semaphore, coro) -> Any:
        """
        Run `coro` while holding a global semaphore so total concurrency for
        this class of work (extra_data / u2_batch / u2_flow) is bounded
        regardless of how many phones the farm fans out to.

        Without this, a burst of 50 farm requests can spawn 50 parallel u2
        dump tasks, each grabbing a thread from the u2 pool — the loop then
        starves heartbeats and gRPC sends, which looks like a hang.
        """
        async with sem:
            return await coro
