"""
device_client.py — DeviceClient: per-device abstraction.

Supports two connection modes:

MODE A — WebSocket Agent (existing):
  Android Agent APK  ←→  WebSocket  ←→  Server
  Screen  : MediaProjection → H.264/JPEG → WS → server
  Touch   : U2JsonRpcClient via TcpWsTunnel (9008), or WS tap/swipe/key fallback to agent
  Events  : STFServiceClient via TcpWsTunnel

MODE B — Relay (agent-boot):
  agent-boot connects outbound via gRPC/WebSocket and proxies all ADB ops.
  Screen: scrcpy via relay. Touch: u2 via relay HTTP proxy (port 7912).
  No direct ADB from farm — everything through AdbRelayManager.

Touch: uiautomator2 (U2) over WS tunnel, or agent shell / scrcpy control. No a11y.
State: DISCONNECTED → CONNECTING → READY → BUSY → ERROR → DEAD
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import hashlib
import json
import logging
import os
import shlex
import socket
import subprocess
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import re
import xml.etree.ElementTree as ET
from runtime.xml_utils import parse_xml, trim_hierarchy_xml as _trim_xml, XML_PARSE_ERRORS

from core.config import Config
from runtime.stream_telemetry import stream_telemetry
from runtime.transports.scrcpy_control import ScrcpyControl
from runtime.transports.scrcpy_receiver import ScrcpyReceiver
from runtime.transports.stf_client import (
    STFServiceClient, ConnectivityInfo, PhoneStateInfo, BatteryInfo,
)

from runtime.transports.u2_jsonrpc import U2JsonRpcClient
from runtime.transports.ws_tunnel import TunnelSet


class DeviceState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING   = "CONNECTING"
    READY        = "READY"
    BUSY         = "BUSY"
    ERROR        = "ERROR"
    DEAD         = "DEAD"


LOW_BW_MODE = os.environ.get("LOW_BW_MODE", "").lower() in {"1", "true", "yes"}
LOW_BW_FRAME_SKIP = max(1, int(os.environ.get("LOW_BW_FRAME_SKIP", "10")))
U2_FORCE_RELAY = os.environ.get("U2_FORCE_RELAY", "").lower() in {"1", "true", "yes"}
SCRCPY_AUTO_STOP_IDLE_S = max(0.0, float(os.environ.get("SCRCPY_AUTO_STOP_IDLE_S", "30")))
SCRCPY_STOP_GRACE_S = max(0.0, float(os.environ.get("SCRCPY_STOP_GRACE_S", "12")))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class LatestFrameStore:
    """Latest-frame snapshot store with version/event signaling.

    Writers may come from non-async threads. We protect snapshot updates with a
    thread lock and signal async subscribers via loop.call_soon_threadsafe(event.set).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Optional[bytes] = None
        self._version: int = 0
        self._ts_monotonic: float = 0.0
        self._is_key: bool = False
        self._last_config: Optional[bytes] = None
        self._last_keyframe: Optional[bytes] = None
        self._last_keyframe_ts: float = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._event: Optional[asyncio.Event] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._loop is loop and self._event is not None:
            return
        self._loop = loop
        self._event = asyncio.Event()

    def set_frame(self, frame: Union[bytes, bytearray, memoryview], *, is_key: bool = False) -> None:
        if not isinstance(frame, bytes):
            frame = bytes(frame)
        now = time.monotonic()
        with self._lock:
            self._version += 1
            self._frame = frame
            self._ts_monotonic = now
            self._is_key = is_key
            if is_key:
                self._last_keyframe = frame
                self._last_keyframe_ts = now
        self._notify_update()

    def set_config(self, cfg_frame: Union[bytes, bytearray, memoryview]) -> None:
        if not isinstance(cfg_frame, bytes):
            cfg_frame = bytes(cfg_frame)
        with self._lock:
            changed = self._last_config != cfg_frame
            self._last_config = cfg_frame
            if changed:
                self._last_keyframe = None
                self._last_keyframe_ts = 0.0

    def reset_bootstrap(self) -> None:
        """Start a new encoder generation without reusing prior config/key frames."""
        with self._lock:
            self._last_config = None
            self._last_keyframe = None
            self._last_keyframe_ts = 0.0

    def get_snapshot(self) -> tuple[Optional[bytes], int, float, bool]:
        with self._lock:
            return self._frame, self._version, self._ts_monotonic, self._is_key

    async def wait_for_update(self, last_version: int) -> None:
        while True:
            with self._lock:
                if self._version != last_version:
                    return
                event = self._event
            if event is None:
                await asyncio.sleep(0.01)
                continue
            await event.wait()
            event.clear()

    def get_bootstrap(self, *, max_key_age_s: float = 2.0) -> tuple[Optional[bytes], Optional[bytes]]:
        with self._lock:
            cfg = self._last_config
            key = self._last_keyframe
            key_ts = self._last_keyframe_ts
        if key is not None and max_key_age_s > 0 and (time.monotonic() - key_ts) > max_key_age_s:
            key = None
        return cfg, key

    def _notify_update(self) -> None:
        loop = self._loop
        event = self._event
        if loop is None or event is None:
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except Exception:
            pass


class DeviceClient:
    """
    Server-side proxy for one Android device connected via WebSocket agent.

    Screen frames arrive as JPEG via WebSocket (MediaProjection on device).
    Touch: u2 over WebSocket tunnels; key/pinch: WS → agent.
    """

    def __init__(self, serial: str, index: int, config: Config) -> None:
        self.serial  = serial
        self.index   = index
        self.config  = config

        self._logger    = logging.getLogger(f"device.{serial}")
        self._lock      = threading.Lock()
        self._state     = DeviceState.DISCONNECTED
        self._serial_b  = serial.encode()   # cached bytes — used in every H264 frame
        # Pre-computed prefix for 0x11 video frames: [0x11][slen][serial]
        # The w/h part changes on rotation so it's built per-frame, but this prefix never changes.
        _slen = len(self._serial_b)
        self._h264_video_prefix: bytes = bytes([0x11, _slen]) + self._serial_b
        # Pre-computed prefix for 0x10 config frames: [0x10][slen][serial]
        self._h264_config_prefix: bytes = bytes([0x10, _slen]) + self._serial_b

        # H264 relay FPS counter — initialized here so on_agent_h264_video avoids
        # hasattr() check on every frame at 30fps.
        self._h264_fps_count: int   = 0
        self._h264_fps_t0:    float = 0.0  # set to monotonic() on first frame

        # Device metadata
        self.name:            str = ""
        self.brand:           str = ""
        self.model:           str = ""
        self.android_version: str = ""
        self.sdk_version:     int = 0
        self.screen_width:    int = 0
        self.screen_height:   int = 0
        self.battery_level:   int = -1
        self.battery_status:  str = ""        # charging, discharging, full
        self.battery_source:  str = ""        # ac, usb, wireless
        self.battery_temp:    float = 0.0     # Celsius
        self.wifi_connected:  bool = False
        self.network_type:    str = ""        # wifi, mobile, etc.
        self.network_subtype: str = ""        # LTE, HSPA, etc.
        self.airplane_mode:   bool = False
        self.current_app:     str = ""

        # Latest JPEG frame (from agent MediaProjection or scrcpy)
        self._latest_jpeg:      Optional[bytes] = None
        self._latest_jpeg_lock  = threading.Lock()
        self._last_frame_time:  float = 0.0  # monotonic timestamp of last received frame
        self._last_jpeg_frame_time: float = 0.0

        # Scrcpy receiver for Mode A+scrcpy hybrid (agent touch + scrcpy screen)
        self._scrcpy_receiver:  Optional[ScrcpyReceiver] = None
        self._scrcpy_active:    bool = False  # suppress MediaProjection frames when True
        # Debounce relay scrcpy restarts on gRPC flaps / false negatives.
        self._scrcpy_last_restart_at: float = 0.0
        # Stored args so scrcpy can be restarted on demand after auto-stop
        self._scrcpy_params:    Optional[tuple] = None  # (device_ip, adb_port, enable_control, max_fps?, max_width?, bitrate?)
        self._scrcpy_stop_task: Optional[asyncio.Task] = None  # debounced auto-stop task
        self._scrcpy_attached_at: float = 0.0
        # Pending relay attach: cancel on detach so 30s retry does not override user "stream off".
        self._scrcpy_pending_registered_ip: Optional[str] = None
        self._scrcpy_pending_registered_keys: set[str] = set()
        self._scrcpy_pending_callback: Optional[Any] = None
        self._scrcpy_pending_generation: int = 0
        self._scrcpy_pending_claimed: bool = False
        self._scrcpy_attach_retry_task: Optional[asyncio.Task] = None

        # WebSocket send callback (set when agent connects)
        self._agent_send: Optional[Callable[[Dict[str, Any]], None]] = None

        # Frame sequence counter for optional low-bandwidth throttling
        self._frame_seq: int = 0

        # TCP-over-WebSocket tunnels (u2 / stfservice)
        self._tunnels: Optional[TunnelSet] = None
        self._tunnel_ports: Dict[str, int] = {}
        self._tunnels_ready_channels: set = set()  # channels device actually set up (from tunnels_ready)

        self._u2:          Optional[U2JsonRpcClient]  = None
        self._u2_lock      = threading.Lock()  # identity-safe reads/writes of self._u2
        self._u2_reconnect_lock = threading.Lock()  # serialize reconnect attempts (only 1 at a time)
        self._u2_batch:    Any = None  # _BatchRelaySession (when u2 batch enabled)
        self._hierarchy_lock = threading.Lock()  # only one dumpWindowHierarchy at a time
        self._hierarchy_inflight = False
        self._hierarchy_cond = threading.Condition()
        # Runtime probe port for legacy u2 recovery checks.
        # android-uiautomator-server listens on 9008; atx-agent health uses 7912 separately.
        self._u2_probe_port: int = int(os.environ.get("U2_PROBE_PORT", "9008"))
        self._u2_probe_port_hex: str = f"{self._u2_probe_port:04x}"
        self._stf_service: Optional[STFServiceClient] = None

        # asyncio event loop + subscriber queues
        self._loop:           Optional[asyncio.AbstractEventLoop] = None
        self._frame_queues:   List[asyncio.Queue] = []
        self._frame_lock      = threading.Lock()
        self._last_key_frame: Optional[Union[Dict[str, Any], bytes]] = None  # last H.264 key frame for new subscribers
        self._last_config_frame: Optional[bytes] = None  # last H.264 config (0x10) for new subscribers
        self._latest_stream = LatestFrameStore()
        self._status_queues:  List[asyncio.Queue] = []
        self._status_lock     = threading.Lock()

        # Log ring-buffer
        self._log_lines: List[str] = []
        self._log_lock   = threading.Lock()

        # Hierarchy cache for polling: (timestamp, xml). TTL 0.5s.
        # Short enough to detect UI changes, long enough to share across rapid polls
        # (_hash_hierarchy, _auto_dismiss_popup, stability checks all share one dump).
        self._hierarchy_cache: Optional[tuple[float, str]] = None
        self._hierarchy_cache_ttl = 2.0
        self._hierarchy_failure_until: float = 0.0
        self._hierarchy_failure_reason: str = ""
        self._hierarchy_last_u2_failure_kind: str = ""

        # Reconnect tracking
        self.reconnect_attempts: int = 0
        self._u2_reconnect_failed_at: float = 0.0    # monotonic time of last full-cycle failure
        self._u2_last_ok_at: float = 0.0             # monotonic time of last confirmed-live ping
        self._u2_start_services_requested_at: float = 0.0
        self._atx_restart_triggered_at: float = float("-inf") # dedup guard; -inf = never triggered
        self._u2_restart_triggered_at: float = float("-inf")  # dedup guard for relay restart_u2
        self._u2_keepalive_gen: int = 0  # bumped on WS reconnect so stale keepalive threads exit
        self._relay_u2_bind_at: float = 0.0  # monotonic; hierarchy recovery grace after relay bind
        # At most one relay u2 bind waiter alive per device (see bind_relay_u2).
        self._relay_u2_bind_inflight = threading.BoundedSemaphore(1)
        self._atx_grace_given_at: float = float("-inf")      # time first timeout was seen; -inf = no grace in progress
        self._hierarchy_relay_u2_fail_count: int = 0
        self._hierarchy_relay_u2_last_fail_at: float = 0.0
        self._recovery_started_at: float = 0.0
        self._recovery_reason: str = ""
        # Periodic screenshot timer state
        self._periodic_ss_started: bool = False
        # Agent-reported capabilities (e.g. ["u2","stfservice","h264"])
        self._agent_capabilities: List[str] = []
        # Touch mode parsed from agent log: "a11y" | "inputMgr" | "NONE" | ""
        self._agent_touch_mode: str = ""
        # ADB serial for WS-mode u2 restart (may differ from self.serial on TCP devices)
        self._adb_serial: Optional[str] = None
        self._u2_adb_restart_at: float = 0.0   # monotonic time of last ADB restart attempt
        # Direct IP for atx-agent connection (device_ip:7912). Set by ws.py on WS connect.
        # None → fall back to WS tunnel (USB devices or atx-agent not available).
        self._u2_host: Optional[str] = None
        # open_url: wait for agent to send open_url_result before marking step done
        self._open_url_result_event = threading.Event()
        self._open_url_result: Optional[Tuple[bool, str]] = None  # (success, error_msg)
        # WS hierarchy dump: synchronous wait for async WS response
        self._ws_hierarchy_event = threading.Event()
        self._ws_hierarchy_xml: Optional[str] = None
        self._ws_hierarchy_error: Optional[str] = None
        self._ws_hierarchy_a11y_available: bool = True  # optimistic, disabled on first "accessibility_not_available"
        self._extra_data_event = threading.Event()
        self._extra_data_lock = threading.Lock()
        self._extra_data_result: Optional[Dict[str, Any]] = None
        self._extra_data_request_id: str = ""
        self._event_recorder = None  # EventRecorder, injected by DeviceManager
        self._recovery_logger = self._setup_recovery_logger()
        # A11y gRPC routing controls (u2 path remains unchanged).
        self._a11y_grpc_enabled: bool = os.getenv("A11Y_GRPC_ENABLED", "true").lower() in ("1", "true", "yes")
        self._a11y_force_route: str = os.getenv("A11Y_FORCE_ROUTE", "auto").strip().lower()
        self._a11y_fail_hard_count: int = 0
        self._a11y_route_current: str = "u2"
        self._a11y_session_id: str = uuid.uuid4().hex

    @staticmethod
    def _setup_recovery_logger() -> logging.Logger:
        logger = logging.getLogger("u2_atx_recovery")
        if logger.handlers:
            return logger
        log_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        handler = logging.FileHandler(
            os.path.join(log_dir, "u2_atx_recovery.jsonl"),
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        return logger

    def _recovery_log(self, event: str, **fields: Any) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "serial": self.serial,
            "event": event,
            **fields,
        }
        self._recovery_logger.info(json.dumps(payload, ensure_ascii=True))
        self._recovery_log_to_db(payload)

    def _recovery_log_to_db(self, payload: dict[str, Any]) -> None:
        """Best-effort async DB sink; never blocks caller path."""
        if self._loop is None:
            return
        try:
            from db.database import AsyncSessionLocal
            from db.models import U2RecoveryEvent
        except Exception:
            return

        metadata = {
            k: v for k, v in payload.items()
            if k not in {"ts", "serial", "event", "reason", "outcome", "duration_ms", "host", "port"}
        }

        async def _write() -> None:
            async with AsyncSessionLocal() as db:
                db.add(U2RecoveryEvent(
                    serial=str(payload.get("serial", "")),
                    event=str(payload.get("event", "")),
                    reason=payload.get("reason"),
                    outcome=payload.get("outcome"),
                    duration_ms=payload.get("duration_ms"),
                    host=payload.get("host"),
                    port=payload.get("port"),
                    extra_data=metadata,
                ))
                await db.commit()

        fut = asyncio.run_coroutine_threadsafe(_write(), self._loop)
        fut.add_done_callback(lambda f: None)

    def _mark_recovery_start(self, reason: str) -> None:
        if self._recovery_started_at <= 0.0:
            self._recovery_started_at = time.monotonic()
            self._recovery_reason = reason
            self._recovery_log("recovery_start", reason=reason)

    def _mark_recovery_end(self, outcome: str, **extra: Any) -> None:
        if self._recovery_started_at > 0.0:
            duration_ms = int((time.monotonic() - self._recovery_started_at) * 1000)
            self._recovery_log(
                "recovery_end",
                outcome=outcome,
                reason=self._recovery_reason,
                duration_ms=duration_ms,
                **extra,
            )
            self._recovery_started_at = 0.0
            self._recovery_reason = ""

    def set_agent_capabilities(self, caps: List[str]) -> None:
        """Set capabilities from agent hello (informational)."""
        self._agent_capabilities = list(caps) if caps else []

    def set_agent_touch_mode(self, mode: str) -> None:
        """Set touch mode from agent hello (touch_mode in payload)."""
        if mode and mode != self._agent_touch_mode:
            self._agent_touch_mode = mode
            self._log(f"Agent touch mode (from hello): {mode}")

    # ── State Machine ─────────────────────────────────────────────────────────

    @property
    def state(self) -> DeviceState:
        with self._lock:
            return self._state

    @state.setter
    def state(self, new: DeviceState) -> None:
        with self._lock:
            old, self._state = self._state, new
        if old != new:
            self._log(f"State: {old.value} → {new.value}")
            self._publish_status()
            self._record_state_event(old, new)
            # Auto-start periodic screenshot timer when device becomes READY
            if new == DeviceState.READY and not self._periodic_ss_started:
                if self.config.streaming.mode == "periodic":
                    self._periodic_ss_started = True
                    self.start_periodic_screenshot()

    # ── Agent Lifecycle ───────────────────────────────────────────────────────

    def attach_agent_sender(self, send: Callable[[Dict[str, Any]], None]) -> TunnelSet:
        """
        Called when the Android agent WebSocket connects.
        Creates WS tunnels for u2, stfservice.
        Returns TunnelSet so the session can route tunnel_data messages back.
        """
        self._ws_hierarchy_a11y_available = True  # retry a11y on each new connection
        self._agent_send = send
        # Reset so on_agent_ready() treats the incoming tunnels_ready as is_initial=True.
        # Required for the reconnect-race case: when on_agent_disconnected() is a no-op
        # (stale-sender guard), _tunnels_ready_channels stays populated from the old session.
        self._tunnels_ready_channels = set()
        # Discard stale u2 client — tunnel port is dead after agent reconnect.
        # Relay/atx path: u2 HTTP goes through agent-boot, not the WS tunnel — keep it.
        with self._u2_lock:
            u2 = self._u2
            if u2 is not None and self._u2_session_uses_relay(u2):
                self._log("WS reconnect: preserving relay u2 session", level=logging.DEBUG)
            else:
                self._u2 = None
                self._u2_batch = None
        # Discard stale STF client too. Its reconnect loop otherwise keeps dialing
        # the previous local tunnel port after fast WS reconnects.
        stale_stf = self._stf_service
        if stale_stf is not None:
            try:
                stale_stf.stop_client()
            except Exception:
                pass
            self._stf_service = None
        # Stop prior TunnelSet before binding a new one. On fast WS reconnect,
        # on_agent_disconnected(sender=...) may skip teardown (new _agent_send
        # already replaced) — leaving zombie accept threads that still hit the old
        # port and corrupt JSON-RPC (BadStatusLine / pong / stale timeouts).
        prev = self._tunnels
        if prev is not None:
            try:
                prev.stop_all()
            except Exception:
                pass
            self._tunnels = None
        tunnels = TunnelSet(send, self.serial)
        ports   = tunnels.start_all()
        self._tunnels      = tunnels
        self._tunnel_ports = ports
        self._log(
            f"Agent connected. Tunnels: "
            + " ".join(f"{ch}={ports[ch]}" for ch in ("u2", "stfservice") if ch in ports)
        )
        return tunnels

    def on_agent_ready(self, ready_channels: Optional[set] = None) -> None:
        """
        Called after agent sends tunnels_ready. ready_channels = set of channel names
        the agent actually connected (e.g. {"stfservice"} when u2 is missing).

        May be called multiple times (e.g. agent retries u2 via start_services).
        On re-call: only reconnect u2 if newly available, avoid re-creating other tools.
        """
        new_channels = ready_channels or set()
        is_initial = not self._tunnels_ready_channels  # first tunnels_ready from this agent session

        # u2 newly appeared in a follow-up tunnels_ready → reconnect only u2
        u2_newly_available = (
            not is_initial
            and "u2" in new_channels
            and "u2" not in self._tunnels_ready_channels
        )

        self._tunnels_ready_channels = new_channels

        if is_initial:
            t = threading.Thread(
                target=self._setup_tools,
                daemon=True,
                name=f"setup-{self.serial}",
            )
            t.start()
            self._u2_keepalive_gen = getattr(self, "_u2_keepalive_gen", 0) + 1
            _ka_gen = self._u2_keepalive_gen
            ka = threading.Thread(
                target=self._u2_keepalive_loop,
                args=(_ka_gen,),
                daemon=True,
                name=f"u2-ka-{self.serial}",
            )
            ka.start()
        elif u2_newly_available:
            self._log("u2 tunnel now available (retry) — connecting…")
            threading.Thread(
                target=self._reconnect_u2,
                daemon=True,
                name=f"u2-retry-{self.serial}",
            ).start()

    def on_agent_disconnected(
        self,
        sender: Optional[Callable] = None,
        *,
        reason: str = "unknown",
        ws_code: Optional[int] = None,
    ) -> None:
        """Called when the agent WebSocket disconnects.

        sender: the _send callable that was active for this session.  When a
        reconnect races ahead of the old session's finally-block, _agent_send
        will already point to the NEW session's sender.  In that case we must
        NOT tear down the new session — just return silently.
        """
        if sender is not None and self._agent_send is not sender:
            # New session has already replaced this one — stale disconnect, skip teardown.
            return
        old_state = self._state
        self._agent_send = None
        self._tunnels_ready_channels = set()
        # Keep relay scrcpy alive across APK WS reconnects — relay session is
        # independent of the APK WebSocket lifecycle.  detach_scrcpy_stream()
        # sends scrcpy_stop, which would kill video for browser clients during
        # the reconnect window (typically < 2s on WiFi instability).
        self._teardown_tools(stop_scrcpy=False)
        if self._tunnels:
            self._tunnels.stop_all()
            self._tunnels = None
        # Clear JPEG cache so frontend doesn't see stale preview.
        # Keep H264 config/keyframe cache if relay scrcpy is still actively streaming —
        # the relay session is independent of the APK WS connection and new browser
        # subscribers need the cached frames to start decoding without waiting for the
        # next keyframe (~1-5s).
        with self._latest_jpeg_lock:
            self._latest_jpeg = None
        if not self._scrcpy_active:
            self._last_key_frame = None
            self._last_config_frame = None
        if self.state != DeviceState.DEAD:
            # Record disconnect event with reason before changing state
            if self._event_recorder:
                extra = {"ws_code": ws_code} if ws_code is not None else None
                self._event_recorder.record(
                    serial=self.serial,
                    event="disconnected",
                    reason=reason,
                    old_state=old_state.value,
                    new_state=DeviceState.DISCONNECTED.value,
                    device_model=self.model,
                    device_brand=self.brand,
                    extra=extra,
                )
            self.state = DeviceState.DISCONNECTED

    def route_tunnel_data(self, channel: str, b64_data: str) -> None:
        """Route tunnel_data message from agent to the correct local TCP socket."""
        if self._tunnels:
            self._tunnels.route(channel, b64_data)


    def on_agent_frame_b64(self, jpeg_b64: str) -> None:
        """Receive JPEG frame from agent (MediaProjection). Skipped when scrcpy is active."""
        # Only suppress APK frames once scrcpy has actually delivered its first frame.
        # During the ~2-10s scrcpy startup window, allow APK frames so the browser
        # sees a live image instead of a black/loading screen.
        if self._scrcpy_active and self._last_frame_time > 0:
            return
        jpeg = base64.b64decode(jpeg_b64)
        with self._latest_jpeg_lock:
            self._latest_jpeg = jpeg
            now = time.monotonic()
            self._last_frame_time = now
            self._last_jpeg_frame_time = now
        # In periodic mode, only update cache — periodic timer handles publishing
        if self.config.streaming.mode == "periodic":
            return
        self.publish_frame(jpeg)

    def on_agent_h264_frame(self, msg: Dict[str, Any]) -> None:
        """
        Receive H.264 NAL unit from agent — forward directly to browser subscribers.
        Browser decodes H.264 via WebCodecs VideoDecoder (no server-side decode needed).
        Skipped in periodic mode (no continuous video streaming needed).
        """
        if self.config.streaming.mode == "periodic":
            return
        if not self._loop:
            return
        broadcast: Dict[str, Any] = {
            "type":   "frame",
            "serial": self.serial,
            "codec":  "h264",
            "key":    msg.get("key", False),
            "data":   msg.get("data", ""),
        }
        if msg.get("codec_string"):
            broadcast["codec_string"] = msg["codec_string"]
        if self.screen_width > 0 and self.screen_height > 0:
            broadcast["device_width"]  = self.screen_width
            broadcast["device_height"] = self.screen_height
        if msg.get("key"):
            self._last_key_frame = dict(broadcast)
        with self._frame_lock:
            queues = list(self._frame_queues)
        for q in queues:
            asyncio.run_coroutine_threadsafe(_safe_put(q, broadcast), self._loop)

    def on_agent_frame_bytes(self, jpeg_bytes: bytes) -> None:
        """Receive raw JPEG bytes from agent (binary protocol). Skipped when scrcpy is active."""
        if self._scrcpy_active and self._last_frame_time > 0:
            return
        with self._latest_jpeg_lock:
            self._latest_jpeg = jpeg_bytes
            self._last_jpeg_frame_time = time.monotonic()
        # In periodic mode, only update cache
        if self.config.streaming.mode == "periodic":
            return
        self.publish_frame(jpeg_bytes)

    def on_agent_h264_config(
        self, avcc_record: bytes, w: int, h: int, changed: bool = False
    ) -> None:
        """Relay H264 AVCDecoderConfigurationRecord to browser as binary 0x10 frame.

        Binary layout:
            [0x10][slen:1B][serial][width:2B BE][height:2B BE][flags:1B][avcc_record]
            flags bit 0: config_changed — browser must close+reopen VideoDecoder before
                         reconfiguring (rotation, resolution change, scrcpy reconnect).

        Called when agent sends h264_config message (SPS+PPS codec config) or when
        scrcpy relay detects a SPS/PPS change.
        """
        if self.config.streaming.mode == "periodic":
            return
        if not self._loop:
            return
        fanout_started = time.perf_counter()
        width = max(0, min(w or self.screen_width, 0xFFFF))
        height = max(0, min(h or self.screen_height, 0xFFFF))
        flags = 0x01 if changed else 0x00
        msg: bytes = (
            self._h264_config_prefix
            + struct.pack(">HH", width, height)
            + bytes([flags])
            + avcc_record
        )
        with self._frame_lock:
            self._last_config_frame = msg
            self._latest_stream.set_config(msg)
            queues = list(self._frame_queues)
        self._logger.info("h264 config queued → %d WS subscriber(s), avcc_len=%d",
                          len(queues), len(avcc_record))
        loop = self._loop
        # In relay mode this is called from the asyncio WS receive loop — already on
        # the event loop. call_soon_threadsafe from within the loop adds an extra
        # iteration of latency. Detect context and use the fast path.
        try:
            _already_on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            _already_on_loop = False
        if _already_on_loop:
            for q in queues:
                _sync_put(q, msg)
        else:
            for q in queues:
                loop.call_soon_threadsafe(_sync_put, q, msg)
        stream_telemetry.record_fanout(
            subscribers=len(queues),
            frame_bytes=len(msg),
            elapsed_ms=(time.perf_counter() - fanout_started) * 1000.0,
            is_config=True,
        )

    def on_agent_h264_video(self, avcc_data: bytes, is_key: bool, pts_us: int) -> None:
        """Relay H264 AVCC video frame to browser as binary 0x11 frame.
        Called when agent sends h264_frame message.
        """
        if not self._loop:
            return
        fanout_started = time.perf_counter()
        # Mark that scrcpy has started delivering — APK JPEG fallback will stop now.
        first_h264_frame = self._h264_fps_t0 == 0.0
        self._last_frame_time = time.monotonic()
        w = max(0, min(self.screen_width, 0xFFFF))
        h = max(0, min(self.screen_height, 0xFFFF))
        pts_hi = (pts_us >> 32) & 0xFFFFFFFF
        pts_lo = pts_us & 0xFFFFFFFF
        msg = (
            self._h264_video_prefix
            + struct.pack(">HH", w, h)
            + (b'\x01' if is_key else b'\x00')
            + struct.pack(">II", pts_hi, pts_lo)
            + avcc_data
        )
        with self._frame_lock:
            self._latest_stream.set_frame(msg, is_key=is_key)
            if is_key:
                # Store for late-joining subscribers (replaces _last_key_frame dict)
                self._last_key_frame = msg
            queues = list(self._frame_queues)
        if first_h264_frame:
            self._logger.info(
                "h264 video started key=%s → %d WS subscriber(s), avcc_len=%d",
                is_key,
                len(queues),
                len(avcc_data),
            )
        elif is_key:
            self._logger.debug(
                "h264 keyframe queued → %d WS subscriber(s), avcc_len=%d",
                len(queues),
                len(avcc_data),
            )
        # FPS counter — log relay throughput every 5s
        if self._h264_fps_t0 == 0.0:
            self._h264_fps_t0 = time.monotonic()
        self._h264_fps_count += 1
        _now = time.monotonic()
        if _now - self._h264_fps_t0 >= 5.0:
            fps = self._h264_fps_count / (_now - self._h264_fps_t0)
            self._logger.debug(
                "h264 relay FPS=%.1f frames=%d (5s window)",
                fps,
                self._h264_fps_count,
            )
            self._h264_fps_count = 0
            self._h264_fps_t0 = _now
        # NOTE: do NOT re-send config before every IDR. See on_agent_h264_config.
        loop = self._loop
        # In relay mode this is called directly from the asyncio WS receive loop.
        # Calling call_soon_threadsafe from within the event loop defers the put to
        # the NEXT iteration — adds ~1 ms per frame at 30fps. Use direct path instead.
        try:
            _already_on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            _already_on_loop = False
        if _already_on_loop:
            for q in queues:
                _sync_put(q, msg)
        else:
            for q in queues:
                loop.call_soon_threadsafe(_sync_put, q, msg)
        stream_telemetry.record_fanout(
            subscribers=len(queues),
            frame_bytes=len(msg),
            elapsed_ms=(time.perf_counter() - fanout_started) * 1000.0,
            is_key=is_key,
        )

    def on_agent_status(self, payload: Dict[str, Any]) -> None:
        if "brand" in payload:
            incoming = str(payload.get("brand") or "").strip()
            if incoming:
                self.brand = incoming
        if "model" in payload:
            incoming = str(payload.get("model") or "").strip()
            if incoming:
                self.model = incoming
        self.android_version = payload.get("android",       self.android_version)
        self.screen_width    = payload.get("screen_width",  self.screen_width)
        self.screen_height   = payload.get("screen_height", self.screen_height)
        self.current_app     = payload.get("current_app",   self.current_app)
        sdk = payload.get("sdk")
        if sdk is not None:
            try: self.sdk_version = int(sdk)
            except Exception: pass
        bat = payload.get("battery")
        if bat is not None:
            try: self.battery_level = int(bat)
            except Exception: pass
        state_str = payload.get("state")
        if isinstance(state_str, str) and state_str in DeviceState.__members__:
            self.state = DeviceState[state_str]
        elif self.state in (DeviceState.DISCONNECTED, DeviceState.CONNECTING):
            self.state = DeviceState.READY
        self._publish_status()

    def on_agent_log(self, line: str) -> None:
        self._log(f"[agent] {line}")

    def on_agent_open_url_result(self, success: bool, error: str = "") -> None:
        """Called when agent sends open_url_result; unblocks open_url() wait."""
        self._open_url_result = (success, error or "")
        self._open_url_result_event.set()

    def setup(self) -> bool:
        """Called immediately after ensure_device() — waits for agent hello."""
        self.state = DeviceState.CONNECTING
        return True

    def detach_all_transports(self) -> None:
        """
        Tear down all transport connections (scrcpy, u2, tunnels, ADB bootstrap)
        without changing device state. Used before re-bootstrap.
        """
        self._teardown_tools()
        if self._tunnels:
            try:
                self._tunnels.stop_all()
            except Exception:
                pass
            self._tunnels = None
        # Clear stale frame cache
        with self._latest_jpeg_lock:
            self._latest_jpeg = None
        self._last_key_frame = None
        self._last_config_frame = None

    def teardown(self) -> None:
        # Agent (WS) teardown
        self._agent_send = None
        self._teardown_tools()
        if self._tunnels:
            self._tunnels.stop_all()
            self._tunnels = None

        self.state = DeviceState.DISCONNECTED

    # ── Screenshot ────────────────────────────────────────────────────────────

    def take_screenshot(self) -> Optional[bytes]:
        """Return latest JPEG frame (from agent MediaProjection or ADB scrcpy). Non-blocking."""
        with self._latest_jpeg_lock:
            return self._latest_jpeg

    def request_stream_jpeg_frames(self, duration_s: float = 3.0) -> bool:
        """Enable relay H264→JPEG conversion only while an image consumer is active."""
        receiver = self._scrcpy_receiver
        request = (
            getattr(receiver, "request_jpeg_frames", None)
            if receiver is not None
            else None
        )
        if request is not None:
            request(duration_s=duration_s)
            return True
        return False

    def reset_stream_bootstrap_generation(self) -> None:
        """Atomically invalidate cached stream bootstrap before a new encoder."""
        with self._frame_lock:
            self._latest_stream.reset_bootstrap()
            self._last_config_frame = None
            self._last_key_frame = None

    def capture_screenshot(
        self,
        quality: int = 70,
        max_width: int = 800,
        allow_ws_u2_fallback: bool = False,
        skip_cache: bool = False,
    ) -> Optional[bytes]:
        """
        On-demand screenshot with fallback chain:
          1. Cached _latest_jpeg (from scrcpy or agent frame stream) unless skip_cache=True
          2. U2 HTTP /screenshot/0 (ADB mode only — avoids tunnel contention in agent mode)
          3. ADB shell screencap (ADB mode only)
        Updates _latest_jpeg with the result.

        IMPORTANT: When scrcpy is active, ONLY return cached frame. U2 screenshot
        requests hammer the WS tunnel and starve scrcpy bandwidth.
        For low-FPS recovery paths, skip_cache=True bypasses stale cached frames
        and returns only an actual fresh capture source such as relay screencap.
        """
        jpeg = None

        # When scrcpy is active OR WS agent mode: always use cached frame.
        # U2 screenshot through WS tunnel causes massive tunnel thrashing that
        # kills scrcpy FPS (drops from 30fps to 1fps).
        if not skip_cache and (self._scrcpy_active or self._agent_send is not None):
            with self._latest_jpeg_lock:
                jpeg = self._latest_jpeg
            if jpeg is not None:
                return jpeg

        # Only try U2 screenshot when explicitly allowed (for infrequent snapshot APIs).
        use_u2 = allow_ws_u2_fallback
        if use_u2:
            with self._u2_lock:
                u2 = self._u2
            if u2 is not None:
                try:
                    jpeg = u2.screenshot(timeout=5.0, max_width=max_width, quality=quality)
                except Exception as exc:
                    self._log(f"capture_screenshot u2 error: {exc}", level=logging.DEBUG)

        # Relay fallback: screencap via agent-boot relay
        if jpeg is None and self._loop:
            try:
                from runtime.transports.adb_relay_server import get_relay_manager
                relay = get_relay_manager()
                actual_serial = self._adb_serial or self.serial
                if relay and actual_serial:
                    actual_serial = relay.resolve_serial(actual_serial)
                if relay and relay.relay_for_serial(actual_serial):
                    raw = asyncio.run_coroutine_threadsafe(
                        relay.screencap(actual_serial, timeout=12.0),
                        self._loop,
                    ).result(timeout=15.0)
                    if raw:
                        from PIL import Image
                        import io as _io
                        img = Image.open(_io.BytesIO(raw))
                        if max_width > 0 and img.width > max_width:
                            ratio = max_width / img.width
                            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
                        buf = _io.BytesIO()
                        img.save(buf, format="JPEG", quality=quality)
                        jpeg = buf.getvalue()
            except Exception as exc:
                self._log(f"capture_screenshot relay error: {exc}", level=logging.DEBUG)

        # Fallback: cached frame
        if jpeg is None and not skip_cache:
            with self._latest_jpeg_lock:
                jpeg = self._latest_jpeg

        # Update cache — only for ADB mode (u2 is primary source) or scrcpy frames.
        # WS u2 fallback (allow_ws_u2_fallback=True) must NOT update cache, otherwise
        # take_screenshot() returns the stale fallback frame and MJPEG freezes.
        if jpeg is not None and not allow_ws_u2_fallback and not skip_cache:
            with self._latest_jpeg_lock:
                self._latest_jpeg = jpeg
                self._last_jpeg_frame_time = time.monotonic()

        return jpeg

    def start_periodic_screenshot(self) -> None:
        """Start background thread that captures screenshots at dashboard_interval."""
        interval = self.config.streaming.dashboard_interval
        self._log(f"Periodic screenshot timer started (interval={interval}s)")

        def _loop():
            try:
                while self.state not in (DeviceState.DEAD, DeviceState.DISCONNECTED):
                    time.sleep(interval)
                    if self.state not in (DeviceState.READY, DeviceState.BUSY):
                        continue
                    try:
                        jpeg = self.capture_screenshot()
                        if jpeg:
                            self.publish_frame(jpeg)
                    except Exception as exc:
                        self._log(f"Periodic screenshot error: {exc}", level=logging.DEBUG)
            finally:
                self._periodic_ss_started = False

        t = threading.Thread(target=_loop, daemon=True, name=f"periodic-ss-{self.serial}")
        t.start()

    # ── Touch / Key API ───────────────────────────────────────────────────────

    def _try_u2_tap(self, action: "Callable[[], None]") -> bool:
        """Run touch action via u2. On failure: null _u2, reconnect once, retry."""
        # Do NOT reconnect U2 inline from the manual input path. A reconnect can
        # block for 3-12s and makes the control UI feel frozen. Keepalive/recovery
        # owns reconnects; manual input uses U2 only when a live client is already
        # present, then falls through to the next route if it is not.
        if self._u2 is None:
            return False
        if self._should_skip_stale_u2_proxy_probe_for_relay_batch():
            return False
        if not self.ensure_u2_healthy(ping_timeout=0.8) or self._u2 is None:
            return False
        return self._try_u2_tap_impl(action)

    def _try_u2_tap_impl(self, action: "Callable[[], None]") -> bool:
        u2_snap = self._u2
        try:
            action()
            self._u2_last_ok_at = time.monotonic()
            return True
        except Exception as exc:
            self._log(f"u2 touch failed: {exc}", level=logging.WARNING)
            with self._u2_lock:
                if self._u2 is u2_snap:
                    self._u2 = None
            if self._u2_host:
                self._recover_u2_ws_mode()
        # Don't reconnect inline — let keepalive handle it in background.
        # Inline reconnect blocks the touch caller for 3-12s (tunnel churn)
        # and starves the event loop. Return False → caller falls through to
        # the next input route.
        return False

    def _relay_u2_control_serial(self, relay: Any) -> Optional[str]:
        host = self._u2_host_hint()
        if host:
            actual = self._select_u2_relay_serial(relay, host)
            if actual:
                return actual

        for hint in (self._adb_serial, self.serial):
            h = str(hint or "").strip()
            if not h:
                continue
            actual = relay.resolve_serial(h)
            if relay.relay_for_serial(actual):
                return actual
        return None

    def _should_skip_stale_u2_proxy_probe_for_relay_batch(self) -> bool:
        """Avoid blocking manual input on a stale proxy ping when batch is ready."""
        if self._loop is None:
            return False
        last_ok = float(self._u2_last_ok_at or 0.0)
        if last_ok > 0 and time.monotonic() - last_ok <= self._U2_STALE_CHECK_INTERVAL:
            return False
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            return relay is not None and self._relay_u2_control_serial(relay) is not None
        except Exception:
            return False

    def _try_relay_u2_batch_touch(self, actions: list[dict], timeout: float = 1.5) -> bool:
        """Run coordinate touch through agent-boot u2_batch without inline reconnect."""
        return self._try_relay_u2_batch(actions, timeout=timeout, label="touch")

    def _try_relay_u2_batch(
        self,
        actions: list[dict],
        timeout: float = 1.5,
        label: str = "batch",
    ) -> bool:
        """Run primitive ops on agent-boot's batch executor via the relay.

        Note this reaches the executor through the relay manager, not through
        `self._u2_batch` — that client is None on a relay-served device, which
        is precisely where this route is the only one left.
        """
        if self._loop is None or not actions:
            return False
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return False
            actual = self._relay_u2_control_serial(relay)
            if not actual:
                return False

            touch_timeout = max(0.5, min(float(timeout), 6.0))
            fut = asyncio.run_coroutine_threadsafe(
                relay.u2_batch(
                    actual,
                    actions,
                    timeout=touch_timeout,
                    priority="visible",
                    deadline_ms=int(touch_timeout * 1000),
                ),
                self._loop,
            )
            res = fut.result(timeout=touch_timeout + 0.5)
            results = res.get("results") if isinstance(res, dict) else None
            ok = (
                bool(res.get("ok"))
                and isinstance(results, list)
                and len(results) >= len(actions)
                and all(
                    isinstance(item, dict) and bool(item.get("ok"))
                    for item in results[:len(actions)]
                )
            )
            if ok:
                self._log(
                    f"touch route=agent_boot_u2_batch serial={actual} ops={len(actions)}",
                    level=logging.DEBUG,
                )
                self.hierarchy_invalidate_cache()
                return True
            self._log(
                f"touch u2_batch failed: {res.get('error') if isinstance(res, dict) else res}",
                level=logging.DEBUG,
            )
        except Exception as exc:
            self._log(f"touch u2_batch unavailable: {exc}", level=logging.DEBUG)
        return False

    def _get_scrcpy_control(self) -> Optional[ScrcpyControl]:
        """Return active ScrcpyControl instance if available (thread-safe)."""
        receiver = self._scrcpy_receiver
        if receiver is not None:
            with receiver._ctrl_lock:
                ctrl = receiver.control
            # ctrl is now a local ref — safe to use even if receiver.control is set to None
            if ctrl is not None and ctrl.is_connected:
                return ctrl
        return None

    # Android 14 (SDK 34) tightened INJECT_EVENTS: `input tap/swipe` via shell now requires
    # the system-only INJECT_EVENTS permission.  Using shell input on SDK ≥ 34 produces a
    # SecurityException that corrupts the task log.  Skip it entirely; U2 and scrcpy both
    # work without this permission.
    _SHELL_INPUT_MAX_SDK = 33

    def _shell_input_ok(self) -> bool:
        """Return True when `input tap/swipe` via adb shell is safe to use."""
        return (
            self._agent_send is not None
            and (self.sdk_version == 0 or self.sdk_version <= self._SHELL_INPUT_MAX_SDK)
        )

    def _a11y_fail_hard(self, error: str) -> None:
        """Route hysteresis for fail-hard conditions only."""
        s = (error or "").lower()
        hard = (
            "connection refused" in s
            or "protocol" in s
            or "timeout" in s
            or "queue_overflow" in s
        )
        if hard:
            self._a11y_fail_hard_count += 1
            if self._a11y_fail_hard_count >= 3:
                self._a11y_route_current = "grpc"
        else:
            self._a11y_fail_hard_count = 0

    def _resolve_relay_serial(self) -> str:
        """Return the best adb serial for relay calls.

        Priority:
          1) cached _adb_serial
          2) resolve by known device IP (_u2_host) when available
          3) resolve by device serial
        """
        from runtime.transports.adb_relay_server import get_relay_manager
        relay = get_relay_manager()
        if relay is None:
            return self._adb_serial or self.serial

        if self._adb_serial:
            resolved_adb = relay.resolve_serial(self._adb_serial)
            if relay.relay_for_serial(resolved_adb):
                self._adb_serial = resolved_adb
                return resolved_adb

        if self._u2_host:
            selected = self._select_u2_relay_serial(relay, self._u2_host)
            if selected:
                self._adb_serial = selected
                return selected

        resolved = relay.resolve_serial(self.serial)
        if relay.relay_for_serial(resolved):
            self._adb_serial = resolved
            return resolved

        return self.serial

    async def _a11y_mutate_async(self, action: str, payload: dict, timeout: float = 5.0) -> dict:
        from runtime.transports.adb_relay_server import get_relay_manager
        relay = get_relay_manager()
        if relay is None:
            return {"ok": False, "error": "no_relay_manager"}
        serial = self._resolve_relay_serial()
        return await relay.a11y_mutate(
            serial=serial,
            action=action,
            payload=payload,
            session_id=self._a11y_session_id,
            timeout=timeout,
        )

    async def _a11y_query_async(self, action: str, payload: dict, timeout: float = 5.0) -> dict:
        from runtime.transports.adb_relay_server import get_relay_manager
        relay = get_relay_manager()
        if relay is None:
            return {"ok": False, "error": "no_relay_manager"}
        serial = self._resolve_relay_serial()
        return await relay.a11y_query(
            serial=serial,
            action=action,
            payload=payload,
            session_id=self._a11y_session_id,
            timeout=timeout,
        )

    def _a11y_mutate(self, action: str, payload: dict, timeout: float = 5.0) -> bool:
        """Synchronous wrapper for a11y mutate ack path."""
        if not self._a11y_grpc_enabled:
            return False
        if self._a11y_force_route == "u2":
            return False
        if self._loop is None:
            return False
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._a11y_mutate_async(action, payload, timeout=timeout), self._loop
            )
            res = fut.result(timeout=timeout + 1.0)
            ok = bool(res.get("ok") and res.get("accepted"))
            if ok:
                self._a11y_route_current = "grpc"
                self._a11y_fail_hard_count = 0
            else:
                self._a11y_fail_hard(str(res.get("error", "")))
            return ok
        except Exception as exc:
            self._a11y_fail_hard(str(exc))
            return False

    def _a11y_query(self, action: str, payload: dict, timeout: float = 5.0) -> dict:
        if not self._a11y_grpc_enabled:
            return {"ok": False, "error": "a11y_grpc_disabled"}
        if self._a11y_force_route == "u2":
            return {"ok": False, "error": "a11y_force_route_u2"}
        if self._loop is None:
            return {"ok": False, "error": "no_event_loop"}
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._a11y_query_async(action, payload, timeout=timeout), self._loop
            )
            res = fut.result(timeout=timeout + 2.0)
            if bool(res.get("ok")):
                self._a11y_route_current = "grpc"
                self._a11y_fail_hard_count = 0
            else:
                self._a11y_fail_hard(str(res.get("error", "")))
            return res
        except Exception as exc:
            self._a11y_fail_hard(str(exc))
            return {"ok": False, "error": str(exc)}

    def key_route_hint(self) -> str:
        """Route `key()` would take, for logging.

        Not the same order as tap/swipe: `key()` prefers a u2 session, then the
        batch route, then the WS APK. Logging the tap hint next to a key press
        reported `agent_boot_u2_batch` for presses that never went near the
        batch route, which is how the dropped home key stayed hidden.
        """
        if self._u2 is not None:
            return self.input_route_hint()
        if self._relay_batch_available():
            return "agent_boot_u2_batch"
        if self._agent_send is not None:
            return "device_agent_ws"
        return self.input_route_hint()

    def _relay_batch_available(self) -> bool:
        """Whether the relay can carry a batch for this device right now.

        This is the predicate `_try_relay_u2_batch` itself uses. `_batch_enabled()`
        asks a different question — whether the `self._u2_batch` client exists —
        and answers False on relay-served devices.
        """
        if self._loop is None:
            return False
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            return relay is not None and bool(self._relay_u2_control_serial(relay))
        except Exception:
            return False

    def input_route_hint(self) -> str:
        """
        Best-effort route hint for tap/swipe style inputs.
        This mirrors the runtime priority order and is used for logging only.
        """
        if self._u2 is not None:
            try:
                from runtime.transports.u2_jsonrpc import _RelaySession
                session = getattr(self._u2, "_session", None)
                if isinstance(session, _RelaySession):
                    return "agent_boot_u2_proxy"
            except Exception:
                pass
            return "device_farm_u2_local"
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if self._loop is not None and relay is not None and self._relay_u2_control_serial(relay):
                return "agent_boot_u2_batch"
        except Exception:
            pass
        if self._a11y_grpc_enabled and self._a11y_force_route != "u2":
            return "agent_boot_a11y_grpc"
        if self._shell_input_ok():
            return "device_agent_shell"
        if self._agent_send is not None:
            return "device_agent_ws"
        return "none"

    def _u2_host_hint(self) -> Optional[str]:
        """Best atx-agent host for relay proxy: explicit _u2_host or IP from _adb_serial."""
        host = str(self._u2_host or "").strip()
        if host:
            return host
        adb = str(self._adb_serial or "").strip()
        if ":" in adb:
            ip = adb.rsplit(":", 1)[0].strip()
            if ip and not ip.startswith("127."):
                return ip
        return None

    @staticmethod
    def _u2_session_uses_relay(u2: Any) -> bool:
        """True when u2 client routes HTTP through agent-boot relay (not WS tunnel)."""
        if u2 is None:
            return False
        try:
            from runtime.transports.u2_jsonrpc import _RelaySession

            session = getattr(u2, "_session", None)
            return isinstance(session, _RelaySession)
        except Exception:
            return False

    def bind_relay_u2(self, relay_serial: str, *, host: Optional[str] = None) -> bool:
        """Bind relay ADB serial + u2 host hint and eagerly reconnect u2 via agent-boot.

        Called when relay reports a device online (possibly after WS hello raced ahead
        of relay registration and left _u2_host unset in cloud/tunnel mode).
        """
        relay_serial = str(relay_serial or "").strip()
        if not relay_serial:
            return False

        actual = relay_serial
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return False
            actual = relay.resolve_serial(relay_serial)
            if not relay.relay_for_serial(actual):
                return False
        except Exception:
            return False

        if self._u2 is not None and self._u2_session_uses_relay(self._u2):
            self._adb_serial = actual
            host_hint = str(host or "").strip()
            if not host_hint and ":" in relay_serial:
                host_hint = relay_serial.rsplit(":", 1)[0].strip()
            if host_hint and not host_hint.startswith("127."):
                self._u2_host = host_hint
            return True

        if self._u2 is not None and str(self._adb_serial or "") == actual:
            return True

        self._adb_serial = actual
        host_hint = str(host or "").strip()
        if not host_hint:
            host_hint = str(self._resolve_relay_u2_host(actual) or "").strip()
        # NEVER poll for wlan_ip here. This runs synchronously inside the relay
        # online callback, which the gRPC/WS handler awaits on the same event
        # loop as the whole HTTP API. The old `for _ in range(8): time.sleep(.25)`
        # blocked that loop for a guaranteed 2s per device — guaranteed because
        # the caps it waited for are written by update_capabilities(), which runs
        # after update_serials() returns, on the loop this sleep was holding.
        # 100 phones registering = 200s of a fully frozen backend.
        # _relay_u2_bind_wait_connect below already waits for caps off-loop.
        if not host_hint and ":" in relay_serial:
            host_hint = relay_serial.rsplit(":", 1)[0].strip()
        if host_hint and not host_hint.startswith("127."):
            self._u2_host = host_hint

        self._u2_reconnect_failed_at = 0.0
        self._atx_grace_given_at = float("-inf")
        self._relay_u2_bind_at = time.monotonic()
        self._log(
            f"relay u2 bind: adb_serial={actual} u2_host={self._u2_host or 'unset'}",
            level=logging.INFO,
        )
        # One waiter per device, ever. bind_relay_u2 is re-entered on every
        # capabilities change while u2 is still None (server._on_relay_capabilities_update),
        # so without this guard a phone whose atx-agent is down accumulates a new
        # 15-second waiter thread on every heartbeat that changes caps.
        if not self._relay_u2_bind_inflight.acquire(blocking=False):
            return True
        try:
            threading.Thread(
                target=lambda: self._relay_u2_bind_wait_connect(actual),
                daemon=True,
                name=f"u2-relay-bind-{self.serial}",
            ).start()
        except RuntimeError:
            # Interpreter shutting down — release so a later bind can retry.
            self._relay_u2_bind_inflight.release()
            return False
        return True

    def _relay_u2_bind_wait_connect(self, relay_serial: str) -> None:
        """Wait for relay caps wlan_ip then connect u2 (non-blocking bootstrap)."""
        try:
            if self._reconnect_u2():
                return
            for _ in range(60):
                host = self._resolve_relay_u2_host(relay_serial)
                if host:
                    self._u2_host = host
                    if self._reconnect_u2():
                        return
                time.sleep(0.25)
            self._log(
                f"relay u2 bind: gave up waiting for wlan_ip ({relay_serial})",
                level=logging.WARNING,
            )
        finally:
            self._relay_u2_bind_inflight.release()

    def _has_active_relay(self) -> bool:
        """True when agent-boot relay currently manages this device."""
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return False

            for hint in (self._adb_serial, self.serial):
                h = str(hint or "").strip()
                if not h:
                    continue
                actual = relay.resolve_serial(h)
                if relay.relay_for_serial(actual):
                    return True

            host = self._u2_host_hint()
            if host:
                actual = self._select_u2_relay_serial(relay, host)
                if actual and relay.relay_for_serial(actual):
                    return True
        except Exception:
            return False
        return False

    def _resolve_relay_u2_host(self, relay_serial: Optional[str] = None) -> Optional[str]:
        """WLAN IP from relay caps, else IP portion of relay ADB serial."""
        serial = str(relay_serial or self._adb_serial or self.serial or "").strip()
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay and serial:
                actual = relay.resolve_serial(serial)
                caps = relay.get_capabilities(actual) or {}
                wlan = str(caps.get("wlan_ip") or "").strip()
                if wlan and not wlan.startswith("127."):
                    return wlan
        except Exception:
            pass
        if ":" in serial:
            ip = serial.rsplit(":", 1)[0].strip()
            if ip and not ip.startswith("127."):
                return ip
        return None

    def _should_force_u2_relay(self) -> bool:
        """Return True when this device should run U2 through agent-boot relay."""
        if U2_FORCE_RELAY:
            return self._has_active_relay()
        if not self._has_active_relay():
            return False
        if not str(self._u2_host or "").strip():
            return True
        return bool(getattr(self.config.device, "u2_always_tunnel", False))

    def tap(self, x: int, y: int) -> None:
        """
        Touch priority: U2 → agent shell (SDK ≤ 33) → agent WS (tap)

        Android 14+ (SDK 34+) blocks `input tap` via shell; WsAgent uses
        TouchAccessibilityService or InputManager (SDK < 34) on the same path as drag.
        """
        action = {"op": "click", "x": int(x), "y": int(y)}
        if self._try_u2_tap(lambda: self._u2.click(x, y) if self._u2 else None):
            return
        if self._try_relay_u2_batch_touch([action], timeout=1.5):
            return
        if self._a11y_mutate("tap", {"x": int(x), "y": int(y)}, timeout=4.0):
            return
        if self._shell_input_ok():
            self._send_to_agent({"type": "shell", "cmd": f"input tap {int(x)} {int(y)}"})
            return
        self._send_to_agent({"type": "tap", "x": int(x), "y": int(y), "ms": 50})

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Touch priority: U2 → agent shell (SDK ≤ 33) → agent WS (swipe)"""
        duration_s = max(0.0, int(duration_ms) / 1000.0)
        action = {
            "op": "swipe",
            "fx": int(x1),
            "fy": int(y1),
            "tx": int(x2),
            "ty": int(y2),
            "duration": duration_s,
        }
        relay_timeout = max(1.5, duration_s + 0.8)
        if self._try_u2_tap(lambda: self._u2.swipe(x1, y1, x2, y2, duration=duration_ms / 1000.0) if self._u2 else None):
            return
        if self._try_relay_u2_batch_touch([action], timeout=relay_timeout):
            return
        if self._a11y_mutate(
            "swipe",
            {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2), "ms": int(duration_ms)},
            timeout=5.0,
        ):
            return
        if self._shell_input_ok():
            self._send_to_agent({
                "type": "shell",
                "cmd": f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
            })
            return
        self._send_to_agent({
            "type": "swipe",
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
            "ms": int(duration_ms),
        })

    def long_tap(self, x: int, y: int, duration_ms: int = 800) -> None:
        """Touch priority: U2 → agent shell (SDK ≤ 33) → agent WS (long_tap)"""
        duration_s = max(0.1, int(duration_ms) / 1000.0)
        action = {"op": "long_click", "x": int(x), "y": int(y), "duration": duration_s}
        relay_timeout = max(1.5, duration_s + 0.8)
        if self._try_u2_tap(lambda: self._u2.long_click(x, y, duration=duration_ms / 1000.0) if self._u2 else None):
            return
        if self._try_relay_u2_batch_touch([action], timeout=relay_timeout):
            return
        if self._a11y_mutate(
            "long_tap",
            {"x": int(x), "y": int(y), "ms": int(duration_ms)},
            timeout=5.0,
        ):
            return
        if self._shell_input_ok():
            self._send_to_agent({
                "type": "shell",
                "cmd": f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}",
            })
            return
        self._send_to_agent({"type": "long_tap", "x": int(x), "y": int(y), "ms": int(duration_ms)})

    def double_tap(self, x: int, y: int) -> None:
        """Double-tap at coordinates. U2 → WsAgent (TouchA11y)."""
        actions = [
            {"op": "click", "x": int(x), "y": int(y)},
            {"op": "click", "x": int(x), "y": int(y)},
        ]
        if self._try_u2_tap(lambda: self._u2.double_click(x, y) if self._u2 else None):
            return
        if self._try_relay_u2_batch_touch(actions, timeout=1.5):
            return
        if self._a11y_mutate("double_tap", {"x": int(x), "y": int(y)}, timeout=4.0):
            return
        # WsAgent with TouchAccessibilityService handles double_tap natively
        self._send_to_agent({"type": "double_tap", "x": x, "y": y})

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 1000) -> None:
        """Drag-and-drop (long-press + move). U2 → WsAgent (TouchA11y)."""
        if self._try_u2_tap(
            lambda: self._u2.drag(x1, y1, x2, y2, duration=duration_ms / 1000.0) if self._u2 else None
        ):
            return
        if self._a11y_mutate(
            "drag",
            {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2), "ms": int(duration_ms)},
            timeout=6.0,
        ):
            return
        self._send_to_agent({"type": "drag", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "ms": duration_ms})

    def set_clipboard(self, text: str) -> None:
        """Set device clipboard. STFService → U2 → ADB broadcast fallback."""
        if self.stf_set_clipboard(text):
            return
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.set_clipboard(text)
                return
            except Exception as exc:
                self._log(f"set_clipboard via u2 failed: {exc}", level=logging.WARNING)

    def get_clipboard(self) -> Optional[str]:
        """Get device clipboard text. STFService → U2."""
        text = self.stf_get_clipboard()
        if text is not None:
            return text
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                return u2.get_clipboard()
            except Exception as exc:
                self._log(f"get_clipboard via u2 failed: {exc}", level=logging.WARNING)
        return None

    def input_text(self, text: str) -> None:
        """Type text into currently focused element."""
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.send_keys(text)
                return
            except Exception as exc:
                self._log(f"input_text via u2 failed: {exc}", level=logging.WARNING)
        if self._a11y_mutate("type", {"text": text}, timeout=6.0):
            return
        # Fallback: use APK "type" message which calls injectText() (handles special chars via a11y/clipboard)
        self._send_to_agent({"type": "type", "text": text})

    def sync_input_text(self, text: str) -> None:
        """Legacy alias — live input uses AdbKeyboard IME, not setText/paste."""
        self.apply_live_input_text(text)

    def apply_live_input_text(self, text: str) -> None:
        """Replace focused field via AdbKeyboard IME (Unicode-safe, not clipboard paste)."""
        import unicodedata

        text = unicodedata.normalize("NFC", text)
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.adb_keyboard_replace_text(text)
                return
            except Exception as exc:
                self._log(
                    f"apply_live_input_text via AdbKeyboard failed: {exc}",
                    level=logging.WARNING,
                )
        if text:
            self.input_text(text)
        else:
            self.clear_live_input()

    def clear_live_input(self) -> None:
        """Clear focused field for live input (AdbKeyboard clear, not Ctrl+V)."""
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.adb_keyboard_clear_text()
                return
            except Exception as exc:
                self._log(f"clear_live_input via AdbKeyboard failed: {exc}", level=logging.WARNING)
            try:
                u2.clear_input_text()
                return
            except Exception as exc:
                self._log(f"clear_live_input via u2 clear failed: {exc}", level=logging.WARNING)
        self.key("delete")

    def append_input_text(self, text: str) -> None:
        """Append text to the focused field via IME (live keyboard)."""
        if not text:
            return
        import unicodedata

        text = unicodedata.normalize("NFC", text)
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.send_keys_append(text)
                return
            except Exception as exc:
                self._log(f"append_input_text via IME failed: {exc}", level=logging.WARNING)
        if self._a11y_mutate("type", {"text": text}, timeout=6.0):
            return
        if not text.isascii():
            self._log(
                f"append_input_text: unicode append failed for {text!r}",
                level=logging.WARNING,
            )
            return
        self._send_to_agent({"type": "type", "text": text})

    def scroll(self, direction: str = "down", distance: float = 0.5, *, duration_ms: int = 400) -> None:
        """Scroll screen. direction: up|down|left|right. distance: 0.0-1.0 of screen size."""
        w = self.screen_width or 1080
        h = self.screen_height or 1920
        cx, cy = w // 2, h // 2
        d = max(0.1, min(1.0, distance))
        if direction == "down":
            x1, y1, x2, y2 = cx, int(h * (0.5 + d / 2)), cx, int(h * (0.5 - d / 2))
        elif direction == "up":
            x1, y1, x2, y2 = cx, int(h * (0.5 - d / 2)), cx, int(h * (0.5 + d / 2))
        elif direction == "left":
            x1, y1, x2, y2 = int(w * (0.5 + d / 2)), cy, int(w * (0.5 - d / 2)), cy
        else:  # right
            x1, y1, x2, y2 = int(w * (0.5 - d / 2)), cy, int(w * (0.5 + d / 2)), cy
        self.swipe(x1, y1, x2, y2, duration_ms=max(120, int(duration_ms)))

    # ── STFService Device Control ──────────────────────────────────────────────

    def stf_get_clipboard(self) -> Optional[str]:
        """Get clipboard text via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.get_clipboard()
        return None

    def stf_set_clipboard(self, text: str) -> bool:
        """Set clipboard text via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_clipboard(text)
        return False

    def stf_set_wifi(self, enabled: bool) -> bool:
        """Enable/disable WiFi via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_wifi_enabled(enabled)
        return False

    def stf_set_bluetooth(self, enabled: bool) -> bool:
        """Enable/disable Bluetooth via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_bluetooth_enabled(enabled)
        return False

    def stf_set_keyguard(self, enabled: bool) -> bool:
        """Enable/disable keyguard (lock screen) via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_keyguard(enabled)
        return False

    def stf_set_wake_lock(self, enabled: bool) -> bool:
        """Acquire/release wake lock via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_wake_lock(enabled)
        return False

    def stf_set_ringer_mode(self, mode: str) -> bool:
        """Set ringer mode: 'silent', 'vibrate', 'normal'."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_ringer_mode(mode)
        return False

    def stf_set_master_mute(self, enabled: bool) -> bool:
        """Mute/unmute all audio via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.set_master_mute(enabled)
        return False

    def stf_identify(self) -> bool:
        """Show identification UI on device."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.identify(self.serial)
        return False

    def stf_get_display(self) -> Optional[dict]:
        """Get display info via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            info = svc.get_display()
            if info:
                return {
                    "width": info.width, "height": info.height,
                    "xdpi": info.xdpi, "ydpi": info.ydpi,
                    "fps": info.fps, "density": info.density,
                    "rotation": info.rotation, "secure": info.secure,
                }
        return None

    def stf_get_properties(self) -> Optional[dict]:
        """Get device properties (IMEI, IMSI, etc.) via STFService."""
        svc = self._stf_service
        if svc and svc.connected:
            return svc.get_properties()
        return None

    @staticmethod
    def _adb_keyevent_name(key_name: str) -> Optional[str]:
        key = (key_name or "").strip()
        if not key:
            return None
        key_map = {
            "home": "KEYCODE_HOME",
            "back": "KEYCODE_BACK",
            "recent": "KEYCODE_APP_SWITCH",
            "app_switch": "KEYCODE_APP_SWITCH",
            "menu": "KEYCODE_MENU",
            "power": "KEYCODE_POWER",
            "enter": "KEYCODE_ENTER",
            "tab": "KEYCODE_TAB",
            "delete": "KEYCODE_DEL",
            "del": "KEYCODE_DEL",
            "volume_up": "KEYCODE_VOLUME_UP",
            "volume_down": "KEYCODE_VOLUME_DOWN",
        }
        lower = key.lower()
        if lower in key_map:
            return key_map[lower]
        upper = key.upper()
        if upper.startswith("KEYCODE_"):
            return upper
        if key.isdigit():
            return key
        return None

    @classmethod
    def _adb_key_command(cls, key_name: str) -> Optional[str]:
        key = (key_name or "").strip()
        if not key:
            return None
        if key.lower() == "home":
            return "am start -a android.intent.action.MAIN -c android.intent.category.HOME"
        keyevent = cls._adb_keyevent_name(key)
        if keyevent:
            return f"input keyevent {keyevent}"
        return None

    def _key_via_u2_batch(self, key_name: str, timeout: float = 5.0) -> bool:
        """Press a key through agent-boot's u2_batch, the way tap() already does.

        agent-boot has carried a `press_key` op since the batch executor was
        written, and it retries over adb on the device host when u2 refuses.
        The farm never sent it: `key()` knew only a local/proxy u2 session, the
        WS APK, and its own adb relay. On a device served by the batch route
        `self._u2` is None, so every home/back press fell through to the WS APK
        and was dropped without a word.

        Routed through the relay manager, the same way `tap()` reaches the
        batch executor. `self._u2_batch` is a different client and is None on a
        relay-served device, so gating on it skipped the branch on exactly the
        devices that need it.
        """
        key = (key_name or "").strip().lower()
        if not key:
            return False
        return self._try_relay_u2_batch(
            [{"op": "press_key", "key": key}],
            timeout=timeout,
            label=f"key {key}",
        )

    def _key_via_adb_relay(self, key_name: str, timeout: float = 5.0) -> bool:
        cmd = self._adb_key_command(key_name)
        if not cmd or not self._loop:
            return False
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            serial = self._resolve_relay_serial()
            if not relay or not relay.relay_for_serial(serial):
                return False

            import asyncio

            fut = asyncio.run_coroutine_threadsafe(
                relay.adb_shell(serial, cmd, timeout=timeout),
                self._loop,
            )
            fut.result(timeout=timeout + 5.0)
            self._log(f"key via adb relay ({key_name})")
            return True
        except Exception as exc:
            self._log(f"key via adb relay failed ({key_name}): {exc}", level=logging.WARNING)
            return False

    def key(self, key_name: str) -> None:
        """
        Key press (home, back, power, enter).

        Priority:
        1. uiautomator2 (no INJECT_EVENTS needed)
        2. Agent WS key (TouchA11y/InputManager)
        """
        k = (key_name or "").strip()
        if not k:
            return

        key_l = k.lower()

        # Navigation keys (home/back/recent/app_switch):
        #   1. u2.press() via am instrument — has INJECT_EVENTS implicitly, works on all Android
        #   2. APK {"type":"key"} — uses AccessibilityService.performGlobalAction (if a11y enabled)
        # DO NOT use scrcpy for these: KEYCODE_HOME/BACK injection is silently swallowed on
        # Android 12+ even with INJECT_EVENTS at shell level.
        _NAV_KEYS = {"home", "back", "recent", "app_switch"}
        if key_l in _NAV_KEYS:
            with self._u2_lock:
                u2_nav = self._u2
            if u2_nav is not None:
                try:
                    u2_nav.press(key_l)  # type: ignore[attr-defined]
                    return
                except Exception as exc:
                    self._log(f"key via U2 failed ({key_l}): {exc}", level=logging.WARNING)
            # Same u2 press, run on the agent next to the device. Must come
            # before the WS APK: that send is fire-and-forget, so once it runs
            # nothing else is tried and a dead APK looks like a working press.
            if self._key_via_u2_batch(key_l):
                return
            if self._agent_send is not None:
                self._send_to_agent({"type": "key", "key": key_l})
                return
            if self._key_via_adb_relay(key_l):
                return

        # Non-nav keys: u2 → APK injectKey (InputManager reflection).
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                # For enter: pressImeActionButton triggers Search/Go/Done imeOptions action,
                # which is what most apps expect. Falls back to KEYCODE_ENTER internally.
                if key_l == "enter":
                    u2.press_ime()  # type: ignore[attr-defined]
                else:
                    u2.press(key_l)  # type: ignore[attr-defined]
                return
            except Exception as exc:
                self._log(f"key via U2 failed ({key_l}): {exc}", level=logging.WARNING)

        if self._a11y_mutate("key", {"key": key_l}, timeout=4.0):
            return

        if self._key_via_u2_batch(key_l):
            return

        if self._agent_send is not None:
            self._send_to_agent({"type": "key", "key": key_l})
            return

        if self._key_via_adb_relay(key_l):
            return

        self._log(f"key skipped ({k}): no agent and no u2", level=logging.WARNING)

    def pinch(self, cx: int, cy: int, scale: float, duration_ms: int = 400) -> None:
        """Pinch/zoom via TouchAccessibilityService. scale>1=zoom in, scale<1=zoom out."""
        # Keep WS path for pinch until agent-boot gRPC lane supports it.
        self._send_to_agent({"type": "pinch", "cx": cx, "cy": cy, "scale": scale, "ms": duration_ms})

    # ── Shell (no-ADB; via WsAgentService) ─────────────────────────────────────

    def shell(self, cmd: str) -> None:
        """
        Run a shell command on device via WsAgentService.
        Used for: am start, input keyevent, settings put, etc.
        Output is only visible in agent logs.
        """
        self._send_to_agent({"type": "shell", "cmd": cmd})

    def shell_sync(self, cmd: str, timeout: float = 10.0) -> str:
        """Run shell via relay ADB when available; returns stdout (empty on fire-and-forget)."""
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            serial = self._resolve_relay_serial()
            if relay and relay.relay_for_serial(serial):
                import asyncio

                fut = asyncio.run_coroutine_threadsafe(
                    relay.adb_shell(serial, cmd, timeout=timeout),
                    self._loop,
                )
                return str(fut.result(timeout=timeout + 5.0) or "")
        except Exception as exc:
            self._log(f"shell_sync failed: {exc}", level=logging.WARNING)
        self.shell(cmd)
        return ""

    def launch_app(
        self,
        package: str,
        component: str | None = None,
        *,
        stop_before: bool = False,
        use_monkey: bool = False,
        package_fallbacks: Sequence[str] | None = None,
        adb_fallback: bool = True,
    ) -> None:
        """Launch app reliably: prefer U2 batch, then ADB relay, then local U2/agent."""
        pkg = (package or "").strip()
        comp = (component or "").strip()
        if pkg and "/" in pkg and not comp:
            # Legacy input: package field contains full component.
            comp = pkg
            pkg = pkg.split("/", 1)[0].strip()
        if not pkg and not comp:
            return
        package_candidates: List[str] = []
        for candidate in [pkg, *(package_fallbacks or [])]:
            cleaned = str(candidate or "").strip()
            if cleaned and "/" not in cleaned and cleaned not in package_candidates:
                package_candidates.append(cleaned)
        if not package_candidates and pkg:
            package_candidates = [pkg]

        if self._batch_enabled() and package_candidates:
            try:
                for candidate_pkg in package_candidates:
                    start_action: Dict[str, Any] = {
                        "op": "app_start",
                        "package": candidate_pkg,
                        "stop_before": stop_before,
                        "use_monkey": use_monkey,
                    }
                    candidate_comp = comp if candidate_pkg == pkg else ""
                    if candidate_comp and "/" in candidate_comp:
                        activity = candidate_comp.split("/", 1)[1].strip()
                        if activity:
                            start_action["activity"] = activity
                    results = self.u2_batch(
                        [
                            start_action,
                            {
                                "op": "app_wait",
                                "package": candidate_pkg,
                                "front": True,
                                "timeout": 8.0,
                            },
                        ],
                        timeout=15.0,
                        priority="visible",
                        deadline_ms=3000,
                    )
                    app_wait = results[-1] if results else {}
                    if app_wait.get("ok") and int(app_wait.get("value") or 0) > 0:
                        self._log(
                            "launch_app route=agent_boot_u2_batch "
                            f"pkg={candidate_pkg} component={candidate_comp or '-'}"
                        )
                        return
                    self._log(
                        "launch_app via u2_batch did not reach foreground: "
                        f"pkg={candidate_pkg} component={candidate_comp or '-'}",
                        level=logging.WARNING,
                    )
            except Exception as exc:
                self._log(
                    f"launch_app via u2_batch failed: {exc}",
                    level=logging.WARNING,
                )
        if stop_before:
            try:
                self.stop_app(pkg)
            except Exception as exc:
                self._log(f"launch_app stop_before failed: {exc}", level=logging.DEBUG)
        # Path 2: direct ADB shell via gRPC relay.
        # This is deterministic and independent from APK process privileges.
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            relay = get_relay_manager()
            if adb_fallback and relay and self._loop:
                serial_candidates: List[str] = []
                for s in (self._resolve_relay_serial(), self._adb_serial, self.serial):
                    ss = (s or "").strip()
                    if ss and ss not in serial_candidates:
                        serial_candidates.append(ss)
                if not serial_candidates:
                    serial_candidates = [self.serial]

                def _looks_failed(out: str | None) -> bool:
                    text = (out or "").strip().lower()
                    if not text:
                        return False
                    failure_markers = (
                        "error:",
                        "exception",
                        "unable to resolve intent",
                        "activity not started",
                        "monkey aborted",
                        "not available",
                        "state=unknown",
                    )
                    return any(marker in text for marker in failure_markers)

                total = (
                    len(serial_candidates)
                    * len(package_candidates)
                    * (1 if use_monkey else 2)
                )
                attempt = 0
                for target_serial in serial_candidates:
                    if not relay.relay_for_serial(target_serial):
                        continue
                    for candidate_pkg in package_candidates:
                        candidate_comp = comp if candidate_pkg == pkg else ""
                        launch_cmds: List[str] = []
                        if use_monkey and candidate_pkg:
                            launch_cmds.append(
                                f"monkey -p {candidate_pkg} -c android.intent.category.LAUNCHER 1"
                            )
                        elif candidate_comp and "/" in candidate_comp:
                            launch_cmds.append(f"am start -W -n {candidate_comp}")
                        elif candidate_pkg:
                            launch_cmds.append(
                                "am start -W"
                                " -a android.intent.action.MAIN"
                                " -c android.intent.category.LAUNCHER"
                                f" -p {candidate_pkg}"
                            )
                            if not use_monkey:
                                launch_cmds.append(
                                    "monkey"
                                    f" -p {candidate_pkg}"
                                    " -c android.intent.category.LAUNCHER"
                                    " 1"
                                )
                        for cmd in launch_cmds:
                            attempt += 1
                            fut = asyncio.run_coroutine_threadsafe(
                                relay.adb_shell(target_serial, cmd, timeout=20.0),
                                self._loop,
                            )
                            out = fut.result(timeout=25.0)
                            if _looks_failed(out):
                                self._log(
                                    (
                                        "launch_app via adb relay attempt "
                                        f"{attempt}/{total} failed: "
                                        f"serial={target_serial} pkg={candidate_pkg} "
                                        f"component={candidate_comp or '-'} cmd={cmd} out={out or '-'}"
                                    ),
                                    level=logging.WARNING,
                                )
                                continue
                            self._log(
                                (
                                    "launch_app via adb relay success: "
                                    f"serial={target_serial} "
                                    f"pkg={candidate_pkg} component={candidate_comp or '-'} cmd={cmd}"
                                )
                            )
                            return
        except Exception as exc:
            self._log(f"launch_app via adb relay failed: {exc}", level=logging.WARNING)
        # Path 3: launch via local u2/adb because we can target explicit activity
        # and verify foreground package deterministically.
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None and package_candidates:
            for candidate_pkg in package_candidates:
                try:
                    activity: str | None = None
                    candidate_comp = comp if candidate_pkg == pkg else ""
                    if candidate_comp and "/" in candidate_comp:
                        activity = candidate_comp.split("/", 1)[1].strip() or None
                    u2.app_start(
                        candidate_pkg,
                        activity=activity,
                        stop=stop_before,
                        use_monkey=use_monkey,
                    )
                    if not u2.app_wait(candidate_pkg, timeout=5.0):
                        self._log(
                            "launch_app via u2 did not reach foreground: "
                            f"pkg={candidate_pkg} component={candidate_comp or '-'}",
                            level=logging.WARNING,
                        )
                    else:
                        return
                except Exception as exc:
                    self._log(f"launch_app via u2 failed: {exc}", level=logging.WARNING)
        # WsAgent mode: use the Java intent approach (getLaunchIntentForPackage +
        # queryIntentActivities fallback).  Do NOT use am start via shell here —
        # Runtime.exec() from app UID (non-shell) is blocked by assertPackageMatchesCallingUid
        # on Android 12+ (SecurityException: package=com.android.shell does not belong to uid).
        send = self._agent_send
        if send is None:
            raise RuntimeError(
                f"launch_app: no control channel available for serial={self.serial} "
                "(adb relay/u2 unavailable, agent disconnected)"
            )
        payload: Dict[str, Any] = {"type": "launch_app", "package": pkg, "serial": self.serial}
        if comp:
            payload["component"] = comp
        try:
            send(payload)
        except Exception as exc:
            raise RuntimeError(f"launch_app: agent send failed: {exc}") from exc

    def stop_app(self, package: str) -> None:
        """Force-stop an app (`am force-stop` / u2 stopPackage)."""
        pkg = (package or "").strip()
        if not pkg:
            return
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            relay = get_relay_manager()
            serial = self._resolve_relay_serial() or self._adb_serial or self.serial
            if relay and self._loop and relay.relay_for_serial(serial):
                fut = asyncio.run_coroutine_threadsafe(
                    relay.adb_shell(serial, f"am force-stop {pkg}", timeout=15.0),
                    self._loop,
                )
                fut.result(timeout=20.0)
                return
        except Exception as exc:
            self._log(f"stop_app via adb relay failed: {exc}", level=logging.DEBUG)
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            u2.app_stop(pkg)
            return
        raise RuntimeError(f"stop_app: no adb relay or u2 for serial={self.serial}")

    def clear_app(self, package: str) -> None:
        """Clear app data (`pm clear`)."""
        pkg = (package or "").strip()
        if not pkg:
            return
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            relay = get_relay_manager()
            serial = self._resolve_relay_serial() or self._adb_serial or self.serial
            if relay and self._loop and relay.relay_for_serial(serial):
                fut = asyncio.run_coroutine_threadsafe(
                    relay.adb_shell(serial, f"pm clear {pkg}", timeout=30.0),
                    self._loop,
                )
                out = fut.result(timeout=35.0) or ""
                if "failed" in out.lower() or "error" in out.lower():
                    raise RuntimeError(out.strip() or "pm clear failed")
                return
        except Exception as exc:
            self._log(f"clear_app via adb relay failed: {exc}", level=logging.DEBUG)
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None and hasattr(u2, "app_clear"):
            u2.app_clear(pkg)
            return
        raise RuntimeError(f"clear_app: no adb relay or u2 for serial={self.serial}")

    def wait_app(self, package: str, *, front: bool = True, timeout: float = 20.0) -> bool:
        """Wait until package is foreground (u2 app_wait or dumpsys poll)."""
        pkg = (package or "").strip()
        if not pkg:
            return False
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            return bool(u2.app_wait(pkg, front=front, timeout=timeout))
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            relay = get_relay_manager()
            serial = self._resolve_relay_serial() or self._adb_serial or self.serial
            if relay and self._loop and relay.relay_for_serial(serial):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    fut = asyncio.run_coroutine_threadsafe(
                        relay.adb_shell(
                            serial,
                            "dumpsys activity activities | grep mResumedActivity",
                            timeout=10.0,
                        ),
                        self._loop,
                    )
                    out = fut.result(timeout=12.0) or ""
                    if pkg in out:
                        return True
                    time.sleep(0.5)
                return False
        except Exception as exc:
            self._log(f"wait_app via adb relay failed: {exc}", level=logging.DEBUG)
        return False

    def push_file(
        self,
        local_path: str,
        remote_path: str,
        *,
        mode: int | None = None,
    ) -> None:
        """Push a local file to the device (agent-boot u2 batch or u2 HTTP sync)."""
        if self._batch_enabled():
            actions: list[dict] = [
                {"op": "push_file", "local_path": local_path, "remote_path": remote_path},
            ]
            if mode is not None:
                actions[0]["mode"] = mode
            results = self.u2_batch(actions, timeout=60.0)
            if not results or not results[0].get("ok"):
                err = (results[0].get("error") if results else None) or "push_file failed"
                raise RuntimeError(err)
            return
        raise RuntimeError(
            "push_file requires U2_BATCH_ENABLED and agent-boot relay "
            f"(serial={self.serial})"
        )

    def pull_file(self, remote_path: str, local_path: str) -> None:
        """Pull a device file to local path (agent-boot u2 batch)."""
        if self._batch_enabled():
            results = self.u2_batch(
                [{"op": "pull_file", "remote_path": remote_path, "local_path": local_path}],
                timeout=60.0,
            )
            if not results or not results[0].get("ok"):
                err = (results[0].get("error") if results else None) or "pull_file failed"
                raise RuntimeError(err)
            return
        raise RuntimeError(
            "pull_file requires U2_BATCH_ENABLED and agent-boot relay "
            f"(serial={self.serial})"
        )

    def open_url(self, url: str, package: str | None = None) -> None:
        """
        Open a URL on the device. Optionally force a browser/app by package (e.g. com.android.chrome).
        MCP/scenario decides; agent only applies payload.
        """
        if not url:
            return
        pkg = (package or "").strip() or "com.android.chrome"
        if self._open_url_via_u2_batch(url):
            return
        if self._open_url_via_adb_relay(url, pkg):
            return
        if self._agent_send is None:
            raise RuntimeError(
                f"open_url: no control channel available for serial={self.serial} "
                "(adb relay unavailable, agent disconnected)"
            )
        # WS agent mode: send command and wait for agent to confirm success/failure
        payload: Dict[str, Any] = {"type": "open_url", "url": url}
        payload["package"] = pkg
        self._open_url_result = None
        self._open_url_result_event.clear()
        self._send_to_agent(payload)
        if not self._open_url_result_event.wait(timeout=15.0):
            if self._open_url_via_u2_batch(url):
                return
            if self._open_url_via_adb_relay(url, pkg):
                return
            raise RuntimeError("open_url: no response from agent (timeout 15s)")
        ok, err = self._open_url_result or (False, "unknown")
        if not ok:
            if self._open_url_via_u2_batch(url):
                return
            if self._open_url_via_adb_relay(url, pkg):
                return
            raise RuntimeError(f"open_url failed: {err or 'agent reported failure'}")

    def _open_url_via_u2_batch(self, url: str) -> bool:
        """Open URL through the agent-boot u2 batch lane before falling back to ADB."""
        if not self._batch_enabled():
            return False
        try:
            results = self.u2_batch(
                [{"op": "open_url", "url": url}],
                timeout=10.0,
                priority="visible",
                deadline_ms=2000,
            )
            if results and results[0].get("ok"):
                self._log(f"open_url route=agent_boot_u2_batch url={url[:120]}")
                return True
            err = (results[0].get("error") if results else None) or "open_url u2_batch failed"
            self._log(f"open_url via u2_batch failed: {err}", level=logging.WARNING)
        except Exception as exc:
            self._log(f"open_url via u2_batch failed: {exc}", level=logging.WARNING)
        return False

    def _open_url_via_adb_relay(self, url: str, package: str) -> bool:
        """Open URL through agent-boot relay ADB, independent of the Android WS APK handler."""
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            serial = self._resolve_relay_serial()
            if relay is None or relay.relay_for_serial(serial) is None:
                return False

            packages: list[str | None] = []
            pkg = (package or "").strip()
            if pkg:
                packages.append(pkg)
                if pkg == "com.android.chrome":
                    packages.append("com.android.browser")
            packages.append(None)

            for candidate in packages:
                cmd = self._open_url_shell_command(url, candidate)
                fut = asyncio.run_coroutine_threadsafe(
                    relay.adb_shell(serial, cmd, timeout=10.0),
                    self._loop,
                )
                output = str(fut.result(timeout=15.0) or "")
                lowered = output.lower()
                if "error:" in lowered or "exception" in lowered or "unable to resolve" in lowered:
                    self._log(
                        f"open_url via adb relay failed package={candidate or '-'}: {output[:200]}",
                        level=logging.WARNING,
                    )
                    continue
                self._log(
                    f"open_url via adb relay success package={candidate or '-'} url={url[:120]}"
                )
                return True
        except Exception as exc:
            self._log(f"open_url via adb relay failed: {exc}", level=logging.WARNING)
        return False

    @staticmethod
    def _open_url_shell_command(url: str, package: str | None = None) -> str:
        parts = [
            "am",
            "start",
            "-W",
            "-a",
            "android.intent.action.VIEW",
            "-c",
            "android.intent.category.BROWSABLE",
            "-d",
            url,
        ]
        pkg = (package or "").strip()
        if pkg:
            parts.extend(["-p", pkg])
        return " ".join(shlex.quote(part) for part in parts)


    _U2_START_SERVICES_THROTTLE_S = 12.0

    def _request_u2_start_services(self, reason: str, *, force: bool = False) -> bool:
        """Ask the APK to start/reconnect u2, deduped across hierarchy and keepalive paths."""
        if self._agent_send is None:
            return False
        now = time.monotonic()
        if not force:
            with self._u2_lock:
                if (now - self._u2_start_services_requested_at) < self._U2_START_SERVICES_THROTTLE_S:
                    self._log(
                        f"u2 start_services skipped ({reason}): throttled",
                        level=logging.DEBUG,
                    )
                    return False
                self._u2_start_services_requested_at = now
        try:
            self._send_to_agent({"type": "start_services", "services": ["u2"]})
            self._log(f"u2 start_services requested ({reason})", level=logging.INFO)
            return True
        except Exception as exc:
            self._log(f"u2 start_services failed ({reason}): {exc}", level=logging.WARNING)
            return False


    def on_agent_hierarchy_response(self, xml: Optional[str], error: Optional[str] = None) -> None:
        """Called when agent responds to dump_hierarchy WS command."""
        self._ws_hierarchy_xml = xml
        self._ws_hierarchy_error = error
        if error == "accessibility_not_available":
            if self._ws_hierarchy_a11y_available:
                self._log("a11y not available on device — using u2 fallback for hierarchy", level=logging.WARNING)
                self._ws_hierarchy_a11y_available = False
            # Legacy tunnel auto-heal: ask the APK to reconnect the u2 tunnel.
            # In atx-agent/relay mode the APK cannot reliably restart u2; hard
            # recovery is driven by relay u2 hierarchy failures instead.
            if self._agent_send is not None:
                now_mono = time.monotonic()
                last_req = float(getattr(self, "_a11y_recover_requested_at", 0.0) or 0.0)
                if not self._u2_host and (now_mono - last_req) >= 10.0:
                    setattr(self, "_a11y_recover_requested_at", now_mono)
                    self._request_u2_start_services("a11y_unavailable")
        elif xml:
            self._ws_hierarchy_a11y_available = True  # re-enable if it starts working
        self._ws_hierarchy_event.set()

    def on_agent_extra_data_result(self, payload: Dict[str, Any]) -> None:
        request_id = str(payload.get("request_id") or "")
        if self._extra_data_request_id and request_id != self._extra_data_request_id:
            self._log(
                f"extra_data_result ignored for stale request_id={request_id}",
                level=logging.DEBUG,
            )
            return
        self._extra_data_result = payload
        self._extra_data_event.set()

    async def _extra_data_via_relay_async(
        self,
        *,
        strategy: str,
        context: Dict[str, Any],
        timeout: float,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        from runtime.transports.adb_relay_server import get_relay_manager

        relay = get_relay_manager()
        if relay is None:
            return {"ok": False, "error": "no_relay_manager"}
        serial = self._resolve_relay_serial()
        if not relay.relay_for_serial(serial):
            return {"ok": False, "error": "no_relay"}
        result = await relay.extra_data(
            serial=serial,
            strategy=strategy,
            context=context,
            timeout=timeout,
            cancel_event=cancel_event,
        )
        if not result.get("ok"):
            return {
                "ok": False,
                "error": str(result.get("error") or "extra_data_failed"),
                "route": result.get("route", "relay_u2"),
            }
        ingest = result.get("ingest") if isinstance(result.get("ingest"), dict) else result
        return {
            "ok": True,
            "ingest": ingest,
            "route": result.get("route", "relay_u2"),
            "request_id": result.get("id", ""),
        }

    def request_extra_data_xml(
        self,
        *,
        endpoint: str = "",
        strategy: str = "",
        entity: str = "",
        platform: str = "",
        context: Dict[str, Any],
        token: str = "",
        timeout: float = 45.0,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """PA B relay-only: dump + parse on agent-boot via relay.extra_data.

        Content extraction passes ``entity``/``platform`` (platform-neutral);
        agent-boot's internal probes still pass a bare ``strategy`` name.
        """
        del endpoint, token  # relay path does not use HTTP ingest or APK WS
        if entity:
            context = {**context, "entity": entity, "platform": platform or "auto"}
        if not _env_bool("EDGE_EXTRA_RELAY_ENABLED", True):
            return {"ok": False, "error": "edge_extra_relay_disabled"}
        if self._loop is None:
            return {"ok": False, "error": "no_event_loop"}
        if cancel_event is not None and cancel_event.is_set():
            return {"ok": False, "error": "cancelled", "cancelled": True}
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._extra_data_via_relay_async(
                    strategy=strategy,
                    context=context,
                    timeout=timeout,
                    cancel_event=cancel_event,
                ),
                self._loop,
            )
            deadline = time.monotonic() + timeout + 15.0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        result = fut.result(timeout=0.75)
                        return result
                    except concurrent.futures.TimeoutError:
                        fut.cancel()
                    return {"ok": False, "error": "cancelled", "cancelled": True}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fut.cancel()
                    return {"ok": False, "error": f"relay timeout ({timeout}s)"}
                try:
                    result = fut.result(timeout=min(0.25, remaining))
                    break
                except concurrent.futures.TimeoutError:
                    continue
            if result.get("ok"):
                self._log(
                    f"edge_extra route=relay_u2 strategy={strategy}",
                    level=logging.INFO,
                )
            return result
        except Exception as exc:
            self._log(f"edge_extra relay failed: {exc}", level=logging.WARNING)
            return {"ok": False, "error": str(exc)}

    def ocr_supported(self) -> bool:
        """Whether the agent hosting this device ships an OCR engine.

        Reported per device in the relay heartbeat capabilities, but it is really
        a property of the agent host's image.
        """
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return False
            caps = relay.get_capabilities(self._resolve_relay_serial())
            return bool(caps and caps.get("has_ocr"))
        except Exception:
            return False

    def request_ocr(
        self,
        *,
        languages: Optional[List[str]] = None,
        region: Optional[Dict[str, float]] = None,
        min_confidence: float = 0.5,
        want_image_on_empty: bool = False,
        timeout: float = 30.0,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Screenshot + OCR on agent-boot; returns text boxes, not an image.

        ``take_screenshot()`` is deliberately not used here: it only reads the
        scrcpy JPEG cache, and since media moved to go2rtc nothing fills that
        cache any more.
        """
        if self._loop is None:
            return {"ok": False, "error": "no_event_loop"}
        if cancel_event is not None and cancel_event.is_set():
            return {"ok": False, "error": "cancelled", "cancelled": True}
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._ocr_via_relay_async(
                    languages=languages,
                    region=region,
                    min_confidence=min_confidence,
                    want_image_on_empty=want_image_on_empty,
                    timeout=timeout,
                    cancel_event=cancel_event,
                ),
                self._loop,
            )
            deadline = time.monotonic() + timeout + 15.0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        return fut.result(timeout=0.75)
                    except concurrent.futures.TimeoutError:
                        fut.cancel()
                    return {"ok": False, "error": "cancelled", "cancelled": True}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fut.cancel()
                    return {"ok": False, "error": f"relay timeout ({timeout}s)"}
                try:
                    return fut.result(timeout=min(0.25, remaining))
                except concurrent.futures.TimeoutError:
                    continue
        except Exception as exc:
            self._log(f"ocr relay failed: {exc}", level=logging.WARNING)
            return {"ok": False, "error": str(exc)}

    async def _ocr_via_relay_async(
        self,
        *,
        languages: Optional[List[str]],
        region: Optional[Dict[str, float]],
        min_confidence: float,
        want_image_on_empty: bool,
        timeout: float,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        from runtime.transports.adb_relay_server import get_relay_manager

        relay = get_relay_manager()
        if relay is None:
            return {"ok": False, "error": "no_relay_manager"}
        serial = self._resolve_relay_serial()
        if not relay.relay_for_serial(serial):
            return {"ok": False, "error": "no_relay"}
        return await relay.ocr(
            serial,
            languages=languages,
            region=region,
            min_confidence=min_confidence,
            want_image_on_empty=want_image_on_empty,
            timeout=timeout,
            cancel_event=cancel_event,
        )

    def image_match_supported(self) -> bool:
        """Whether the agent hosting this device can run template matching."""
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return False
            caps = relay.get_capabilities(self._resolve_relay_serial())
            return bool(caps and caps.get("has_image_match"))
        except Exception:
            return False

    def request_image_match(
        self,
        *,
        template: bytes,
        threshold: float = 0.8,
        scale: float = 0.25,
        template_screen_w: Optional[int] = None,
        timeout: float = 20.0,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Locate ``template`` on the device screen. Returns the agent's reply.

        Sends the hash first and only ships the bytes when the agent says it has
        not seen that template — one round trip more on a cold cache, but a
        scenario looping over the same image stops resending it every step.
        """
        if self._loop is None:
            return {"ok": False, "error": "no_event_loop"}
        digest = hashlib.sha256(template).hexdigest()

        def _call(include_bytes: bool) -> Dict[str, Any]:
            return self._run_relay_coro(
                lambda relay, serial: relay.image_match(
                    serial,
                    template_sha256=digest,
                    template_b64=base64.b64encode(template).decode() if include_bytes else None,
                    threshold=threshold,
                    scale=scale,
                    template_screen_w=template_screen_w,
                    timeout=timeout,
                    cancel_event=cancel_event,
                ),
                timeout=timeout,
                cancel_event=cancel_event,
            )

        reply = _call(include_bytes=False)
        if reply.get("need_template"):
            reply = _call(include_bytes=True)
        return reply

    def _run_relay_coro(
        self,
        make_coro,
        *,
        timeout: float,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        """Run a relay coroutine from this (sync) thread and wait for its reply."""
        if cancel_event is not None and cancel_event.is_set():
            return {"ok": False, "error": "cancelled", "cancelled": True}

        async def _run() -> Dict[str, Any]:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return {"ok": False, "error": "no_relay_manager"}
            serial = self._resolve_relay_serial()
            if not relay.relay_for_serial(serial):
                return {"ok": False, "error": "no_relay"}
            return await make_coro(relay, serial)

        try:
            fut = asyncio.run_coroutine_threadsafe(_run(), self._loop)
            deadline = time.monotonic() + timeout + 15.0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        return fut.result(timeout=0.75)
                    except concurrent.futures.TimeoutError:
                        fut.cancel()
                    return {"ok": False, "error": "cancelled", "cancelled": True}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fut.cancel()
                    return {"ok": False, "error": f"relay timeout ({timeout}s)"}
                try:
                    return fut.result(timeout=min(0.25, remaining))
                except concurrent.futures.TimeoutError:
                    continue
        except Exception as exc:
            self._log(f"relay call failed: {exc}", level=logging.WARNING)
            return {"ok": False, "error": str(exc)}

    def _hierarchy_via_ws(self, timeout: float = 5.0) -> Optional[str]:
        """Request hierarchy dump via gRPC a11y query, fallback to WS direct."""
        # Prefer gRPC a11y control-plane (query lane) when enabled.
        q = self._a11y_query("dump_hierarchy", {"timeout": timeout}, timeout=timeout)
        if q.get("ok"):
            data = q.get("data") or {}
            xml = data.get("xml") if isinstance(data, dict) else None
            xml_norm = self._normalize_hierarchy_xml(xml)
            if xml_norm:
                self._log(f"relay u2 dump_hierarchy ok xml_len={len(xml_norm)}", level=logging.INFO)
                self._reset_hierarchy_relay_u2_failures()
                return xml_norm
            self._log("relay u2 dump_hierarchy ok but empty/invalid xml", level=logging.WARNING)
        else:
            relay_u2_error = str(q.get("error") or "unknown")
            self._log(
                f"relay u2 dump_hierarchy failed: {relay_u2_error}",
                level=logging.WARNING,
            )
            self._note_hierarchy_relay_u2_failure(relay_u2_error)
        xml = self._hierarchy_via_u2_batch(timeout=min(timeout, self._U2_HIERARCHY_TIMEOUT))
        if xml:
            return xml
        if self._agent_send is None:
            return None
        self._ws_hierarchy_xml = None
        self._ws_hierarchy_error = None
        self._ws_hierarchy_event.clear()
        self._log(f"hierarchy_via_ws: sending dump_hierarchy (agent_send={'SET' if self._agent_send else 'NULL'})", level=logging.DEBUG)
        self._send_to_agent({"type": "dump_hierarchy"})
        if not self._ws_hierarchy_event.wait(timeout=timeout):
            self._log(f"hierarchy_via_ws: timeout ({timeout:.1f}s)", level=logging.WARNING)
            return None
        if self._ws_hierarchy_error:
            self._log(f"ws a11y dump_hierarchy failed: {self._ws_hierarchy_error}", level=logging.WARNING)
            return None
        xml = self._ws_hierarchy_xml
        if xml:
            xml = self._normalize_hierarchy_xml(xml)
            if xml:
                self._log(f"hierarchy_via_ws: OK ({len(xml)} bytes)", level=logging.DEBUG)
            else:
                self._log("hierarchy_via_ws: invalid/empty xml", level=logging.WARNING)
        else:
            self._log("hierarchy_via_ws: agent returned null xml", level=logging.WARNING)
        return xml

    def _hierarchy_via_u2_batch(
        self,
        timeout: float = 2.5,
        *,
        force_refresh: bool = False,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> Optional[str]:
        """Fallback hierarchy through agent-boot u2_batch when a11y is unavailable."""
        xml = self._hierarchy_via_relay_http_dump(
            timeout=timeout,
            priority=priority,
            deadline_ms=deadline_ms,
        )
        if xml:
            return xml
        if not self._batch_enabled():
            return None
        action = {
            "op": "dump_hierarchy",
            "compressed": self._U2_HIERARCHY_COMPRESSED,
            "timeout": self._U2_HIERARCHY_TIMEOUT,
        }
        if force_refresh:
            action["force_fresh_xml"] = True
        try:
            results = self.u2_batch(
                [action],
                timeout=max(1.0, float(timeout)),
                priority=priority,
                deadline_ms=deadline_ms,
            )
        except Exception as exc:
            self._log(f"u2_batch dump_hierarchy failed: {exc}", level=logging.WARNING)
            return None
        if not results:
            self._log("u2_batch dump_hierarchy returned no results", level=logging.WARNING)
            return None
        first = results[0]
        if not isinstance(first, dict) or not bool(first.get("ok")):
            err = first.get("error") if isinstance(first, dict) else first
            self._log(f"u2_batch dump_hierarchy failed: {err}", level=logging.WARNING)
            return None
        xml_norm = self._normalize_hierarchy_xml(first.get("value"))
        if not xml_norm:
            self._log("u2_batch dump_hierarchy returned empty/invalid xml", level=logging.WARNING)
            return None
        self._log(f"hierarchy: route=u2_batch bytes={len(xml_norm)}", level=logging.DEBUG)
        self._hierarchy_cache = (time.time(), xml_norm)
        self._reset_hierarchy_relay_u2_failures()
        self._hierarchy_last_u2_failure_kind = ""
        return xml_norm

    def _hierarchy_via_relay_http_dump(
        self,
        timeout: float = 2.5,
        *,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> Optional[str]:
        """Fast hierarchy fallback: direct atx-agent HTTP dump through relay."""
        if self._loop is None:
            return None
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay is None:
                return None
            actual = self._relay_u2_control_serial(relay)
            if not actual:
                return None
            path = "/dump/hierarchy"
            if self._U2_HIERARCHY_COMPRESSED:
                path = f"{path}?compressed=1"
            http_timeout = max(1.0, min(float(timeout), self._U2_HIERARCHY_TIMEOUT))
            fut = asyncio.run_coroutine_threadsafe(
                relay.u2_http(
                    actual,
                    "GET",
                    path,
                    "",
                    "application/json",
                    http_timeout,
                    priority=priority,
                    deadline_ms=deadline_ms,
                ),
                self._loop,
            )
            res = fut.result(timeout=http_timeout + 0.5)
            if not isinstance(res, dict) or not bool(res.get("ok")):
                err = res.get("body") if isinstance(res, dict) else res
                self._log(f"relay http dump_hierarchy failed: {err}", level=logging.WARNING)
                return None
            xml_norm = self._normalize_hierarchy_xml(res.get("body"))
            if not xml_norm:
                self._log("relay http dump_hierarchy returned empty/invalid xml", level=logging.WARNING)
                return None
            self._log(f"hierarchy: route=relay_http_dump bytes={len(xml_norm)}", level=logging.DEBUG)
            self._hierarchy_cache = (time.time(), xml_norm)
            self._reset_hierarchy_relay_u2_failures()
            self._hierarchy_last_u2_failure_kind = ""
            return xml_norm
        except Exception as exc:
            self._log(f"relay http dump_hierarchy unavailable: {exc}", level=logging.DEBUG)
            return None

    _HIERARCHY_RELAY_U2_RESTART_FAILS = max(1, _env_int("HIERARCHY_RELAY_U2_RESTART_FAILS", 2))
    _HIERARCHY_RELAY_U2_FAIL_WINDOW_S = max(5.0, _env_float("HIERARCHY_RELAY_U2_FAIL_WINDOW_S", 30.0))

    def _reset_hierarchy_relay_u2_failures(self) -> None:
        self._hierarchy_relay_u2_fail_count = 0
        self._hierarchy_relay_u2_last_fail_at = 0.0

    def _note_hierarchy_relay_u2_failure(self, error: str) -> None:
        s = (error or "").lower()
        timeout_only = (
            ("timed out" in s or "timeout" in s)
            and not any(
                marker in s
                for marker in (
                    "signal: killed",
                    "connection refused",
                    "connection reset",
                    "bad gateway",
                )
            )
        )
        if timeout_only:
            # A slow hierarchy dump is not proof that u2 touch is dead. Keep
            # coordinate control live and let the keepalive path diagnose
            # actual transport death.
            return
        hard = (
            "signal: killed" in s
            or "connection refused" in s
            or "connection reset" in s
            or "bad gateway" in s
        )
        if not hard:
            self._reset_hierarchy_relay_u2_failures()
            return

        now = time.monotonic()
        if now - self._hierarchy_relay_u2_last_fail_at > self._HIERARCHY_RELAY_U2_FAIL_WINDOW_S:
            self._hierarchy_relay_u2_fail_count = 0
        self._hierarchy_relay_u2_last_fail_at = now
        self._hierarchy_relay_u2_fail_count += 1

        if self._hierarchy_relay_u2_fail_count < self._HIERARCHY_RELAY_U2_RESTART_FAILS:
            return

        self._hierarchy_relay_u2_fail_count = 0
        self._mark_recovery_start("hierarchy_relay_u2_failed")
        with self._u2_lock:
            self._u2 = None
        self._u2_reconnect_failed_at = now

        # During bootstrap (first ~45s after relay bind) timeouts are expected — reconnect only.
        bind_age = now - float(getattr(self, "_relay_u2_bind_at", 0.0) or 0.0)
        in_bootstrap = bind_age < 45.0

        if self._has_active_relay() and (in_bootstrap or "timeout" in (error or "").lower()):
            self._log(
                f"hierarchy: relay u2 failed ({error}) — reconnect via relay (skip restart)",
                level=logging.WARNING,
            )
            self._u2_reconnect_failed_at = 0.0
            threading.Thread(
                target=self._reconnect_u2,
                daemon=True,
                name=f"u2-hierarchy-recover-{self.serial}",
            ).start()
            return

        if self._u2_host:
            self._log(
                f"hierarchy: relay u2 failed repeatedly ({error}) — triggering atx restart",
                level=logging.WARNING,
            )
            self._trigger_atx_restart_async(self._u2_host)
        else:
            self._log(
                f"hierarchy: relay u2 failed repeatedly ({error}) — triggering u2 recovery",
                level=logging.WARNING,
            )
            self._recover_u2_ws_mode()

    def hierarchy_xml(
        self,
        force_refresh: bool = False,
        *,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> Optional[str]:
        """
        Dump UI hierarchy XML. Cached 2s for polling.

        Primary: u2 JSON-RPC via tunnel/atx-agent.
        Fallback: a11y path (gRPC query / WS direct) when u2 is unavailable.
        """
        now = time.time()
        if now < self._hierarchy_failure_until:
            if self._hierarchy_cache is not None:
                ts, xml = self._hierarchy_cache
                if xml and (now - ts) < self._HIERARCHY_STALE_CACHE_TTL_S:
                    return xml
            self._log(
                f"hierarchy: short-circuit after recent failure ({self._hierarchy_failure_reason})",
                level=logging.DEBUG,
            )
            return None
        if not force_refresh and self._hierarchy_cache is not None:
            ts, xml = self._hierarchy_cache
            if now - ts < self._hierarchy_cache_ttl and xml:
                return xml  # fast path: no lock needed for cache read

        with self._hierarchy_cond:
            if self._hierarchy_inflight:
                wait_until = time.time() + max(
                    self._U2_HIERARCHY_TIMEOUT + self._A11Y_HIERARCHY_TIMEOUT + 0.5,
                    self._HIERARCHY_LOCK_WAIT_S,
                )
                while self._hierarchy_inflight:
                    remaining = wait_until - time.time()
                    if remaining <= 0:
                        break
                    self._hierarchy_cond.wait(timeout=remaining)
                if self._hierarchy_cache is not None:
                    ts, xml = self._hierarchy_cache
                    cache_age = time.time() - ts
                    if xml and cache_age < self._HIERARCHY_STALE_CACHE_TTL_S:
                        self._log(
                            f"hierarchy: coalesced cache age={cache_age:.2f}s bytes={len(xml)}",
                            level=logging.DEBUG,
                        )
                        return xml
                return None
            self._hierarchy_inflight = True

        if not self._hierarchy_lock.acquire(timeout=self._HIERARCHY_LOCK_WAIT_S):
            try:
                if self._hierarchy_cache is not None:
                    _, xml = self._hierarchy_cache
                    if xml:
                        return xml
                return None
            finally:
                with self._hierarchy_cond:
                    self._hierarchy_inflight = False
                    self._hierarchy_cond.notify_all()
        try:
            now = time.time()
            if not force_refresh and self._hierarchy_cache is not None:
                ts, xml = self._hierarchy_cache
                if now - ts < self._hierarchy_cache_ttl and xml:
                    return xml

            # Primary: u2 first (requested behavior)
            xml = self._hierarchy_xml_via_u2(now)
            if xml and not self._is_empty_hierarchy(xml):
                self._log(f"hierarchy: route=u2 bytes={len(xml)}", level=logging.DEBUG)
                self._reset_hierarchy_relay_u2_failures()
                return xml

            # Fallback: agent-boot u2_batch. A11y is intentionally skipped
            # here because it is unreliable on this fleet and adds seconds of
            # dead wait when the accessibility service is not bound.
            xml = self._hierarchy_via_u2_batch(
                timeout=self._U2_HIERARCHY_TIMEOUT,
                force_refresh=force_refresh,
                priority=priority,
                deadline_ms=deadline_ms,
            )
            if xml and not self._is_empty_hierarchy(xml):
                return xml

            if self._hierarchy_cache is not None:
                ts, cached_xml = self._hierarchy_cache
                if cached_xml and (now - ts) < self._HIERARCHY_STALE_CACHE_TTL_S:
                    self._log(
                        f"hierarchy: serving stale cache age={now - ts:.2f}s after route failure",
                        level=logging.WARNING,
                    )
                    return cached_xml

            self._log("hierarchy: route=u2->u2_batch failed", level=logging.WARNING)
            self._note_hierarchy_failure("route_failed")
            if self._hierarchy_last_u2_failure_kind == "timeout":
                self._log(
                    "hierarchy: XML dump timed out; keeping u2 control session live",
                    level=logging.WARNING,
                )
            elif self._u2_host:
                self._recover_u2_ws_mode()
            else:
                self._request_u2_start_services("hierarchy_route_failed")
            return None
        finally:
            self._hierarchy_lock.release()
            with self._hierarchy_cond:
                self._hierarchy_inflight = False
                self._hierarchy_cond.notify_all()

    @staticmethod
    def _is_empty_hierarchy(s: str) -> bool:
        if not s or not s.strip():
            return True
        t = s.strip()
        return t in ("<hierarchy />", "<?xml version=\"1.0\" encoding=\"UTF-8\"?><hierarchy />") or t.endswith("<hierarchy />")

    @classmethod
    def _normalize_hierarchy_xml(cls, xml: Any) -> Optional[str]:
        s = str(xml or "")
        if cls._is_empty_hierarchy(s) or "<hierarchy" not in s:
            return None
        try:
            parse_xml(s)
        except Exception:
            return None
        return _trim_xml(s)

    def _hierarchy_xml_via_u2(self, now: float) -> Optional[str]:
        """Fallback: hierarchy via u2 (atx-agent or WS tunnel)."""
        return self._hierarchy_xml_u2_impl(now)

    # Hierarchy dump via u2: use compressed layout (skip invisible nodes).
    # compressed=True cuts dump time from 3-10 s to 1-3 s on complex Samsung screens
    # because dumpWindowHierarchy skips off-screen/invisible view sub-trees.
    _U2_HIERARCHY_COMPRESSED = True
    _U2_HIERARCHY_TIMEOUT    = max(1.0, _env_float("U2_HIERARCHY_TIMEOUT", 2.5))
    _A11Y_HIERARCHY_TIMEOUT  = max(1.0, _env_float("A11Y_HIERARCHY_TIMEOUT", 4.0))
    _HIERARCHY_LOCK_WAIT_S   = 0.15  # seconds; fail fast when another dump is running
    _HIERARCHY_STALE_CACHE_TTL_S = 20.0  # soften transient relay/u2/a11y outages
    _HIERARCHY_FAILURE_BACKOFF_S = 2.5  # collapse repeated 503 polling during recovery

    def _note_hierarchy_failure(self, reason: str) -> None:
        self._hierarchy_failure_until = time.time() + self._HIERARCHY_FAILURE_BACKOFF_S
        self._hierarchy_failure_reason = reason

    def _hierarchy_xml_u2_impl(self, now: float) -> Optional[str]:
        self._hierarchy_last_u2_failure_kind = ""
        if not self.ensure_u2_healthy() or self._u2 is None:
            self._hierarchy_last_u2_failure_kind = "unavailable"
            return None
        u2_snap = self._u2
        try:
            xml = u2_snap.page_source(
                timeout=self._U2_HIERARCHY_TIMEOUT,
                compressed=self._U2_HIERARCHY_COMPRESSED,
            )
            if self._is_empty_hierarchy(xml or ""):
                self._hierarchy_last_u2_failure_kind = "empty"
                return None  # Don't cache; UI can show "enable Accessibility" etc.
            # Strip redundant false-boolean and empty-string attributes before
            # caching.  Reduces cached XML size by ~40-50% and speeds up all
            # downstream consumers (HierarchyExtractor, selector_healer, etc.).
            xml = _trim_xml(xml)
            self._hierarchy_cache = (now, xml)
            self._hierarchy_last_u2_failure_kind = ""
            return xml
        except Exception as exc:
            if self._is_u2_hierarchy_timeout(exc):
                self._hierarchy_last_u2_failure_kind = "timeout"
                self._log(
                    f"hierarchy_xml timed out: {exc} — keeping u2 session for keepalive",
                    level=logging.WARNING,
                )
                return None
            self._hierarchy_last_u2_failure_kind = "hard"
            self._log(f"hierarchy_xml failed: {exc}", level=logging.WARNING)
        with self._u2_lock:
            if self._u2 is u2_snap:
                self._u2 = None
        # On timeout/error: do NOT reconnect here.  A slow dumpWindowHierarchy does
        # not mean the server is dead (it might just be a complex screen).  Reconnecting
        # would restart am-instrument unnecessarily and cause a ~5 s outage for touches.
        # The keepalive loop will detect a truly dead server within _MAX_MISSES ticks.
        return None

    @staticmethod
    def _is_u2_hierarchy_timeout(exc: Exception) -> bool:
        """Return True for slow dumpWindowHierarchy timeouts, not transport death."""
        try:
            import requests

            if isinstance(exc, requests.exceptions.Timeout):
                return True
        except Exception:
            pass
        msg = str(exc or "").lower()
        return "timed out" in msg or "timeout" in msg

    def hierarchy_invalidate_cache(self) -> None:
        """Call after tap_selector etc. so next hierarchy_xml() fetches fresh."""
        self._hierarchy_cache = None

    def hit_test_selector(
        self,
        x: int,
        y: int,
        *,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> Optional[Dict[str, str]]:
        """
        Infer stable selector at pixel (x, y) from current UI XML.

        Strategy:
          1. Collect all nodes whose bounds contain (x,y), enabled!=false.
          2. Prefer clickable=true self; else promote to nearest clickable ancestor.
          3. Among candidates, pick smallest area.
          4. Selector priority:
             unique resource-id > unique text > unique content-desc
             > non-unique rid → xpath with clickable + instance
             > class name (non-container) | xpath pinned by class + bounds.
        """
        xml = self.hierarchy_xml(
            force_refresh=False,
            priority=priority,
            deadline_ms=deadline_ms,
        )
        if not xml:
            xml = self.hierarchy_xml(
                force_refresh=True,
                priority=priority,
                deadline_ms=deadline_ms,
            )
        if not xml:
            return None

        import re as _re

        BOUNDS_RE = _re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
        CONTAINER_CLASSES = {
            "android.widget.FrameLayout",
            "android.widget.LinearLayout",
            "android.widget.RelativeLayout",
            "android.view.View",
            "android.view.ViewGroup",
            "androidx.constraintlayout.widget.ConstraintLayout",
            "android.widget.ScrollView",
            "androidx.recyclerview.widget.RecyclerView",
        }

        try:
            root = parse_xml(xml)
        except XML_PARSE_ERRORS:
            return None

        all_nodes = list(root.iter())

        # Uniqueness maps
        rid_count: Dict[str, int] = {}
        text_count: Dict[str, int] = {}
        desc_count: Dict[str, int] = {}
        for n in all_nodes:
            rid = (n.get("resource-id") or "").strip()
            t = (n.get("text") or "").strip()
            d = (n.get("content-desc") or "").strip()
            if rid:
                rid_count[rid] = rid_count.get(rid, 0) + 1
            if t and len(t) < 80:
                text_count[t] = text_count.get(t, 0) + 1
            if d and len(d) < 80:
                desc_count[d] = desc_count.get(d, 0) + 1

        # Parent map (ElementTree has no parent refs)
        parent_of: Dict[int, Optional[object]] = {id(root): None}
        for p in all_nodes:
            for c in list(p):
                parent_of[id(c)] = p

        def clickable_self_or_ancestor(n):
            cur = n
            while cur is not None:
                if (cur.get("clickable") or "").strip() == "true":
                    return cur
                cur = parent_of.get(id(cur))
            return None

        # Ambiguous launcher detector (mirrors frontend hierarchy-tree.ts)
        AMBIG_RID_RE = _re.compile(
            r":id/(icon|label|title|icon_text|text|name|bubble_text)$", _re.I
        )
        AMBIG_PREFIXES = (
            "com.sec.android.app.launcher",
            "com.android.launcher",
            "com.google.android.apps.nexuslauncher",
            "com.miui.home",
            "com.huawei.android.launcher",
            "com.oppo.launcher",
            "com.vivo.launcher",
        )

        def is_ambiguous_launcher(rid: str, pkg: str) -> bool:
            if not rid or "/" not in rid:
                return False
            if not AMBIG_RID_RE.search(rid):
                return False
            return any(pkg.startswith(p) or rid.startswith(p + ":") for p in AMBIG_PREFIXES)

        # Step 1: collect candidates
        candidates = []
        for node in all_nodes:
            m = BOUNDS_RE.search(node.get("bounds") or "")
            if not m:
                continue
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            if not (x1 <= x <= x2 and y1 <= y <= y2):
                continue
            if (node.get("enabled") or "").strip() == "false":
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            candidates.append({
                "node": node, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "area": (x2 - x1) * (y2 - y1),
                "clickable": (node.get("clickable") or "").strip() == "true",
            })
        if not candidates:
            return None

        # Step 2: prefer clickable; else promote to clickable ancestors
        clickable_self = [c for c in candidates if c["clickable"]]
        if clickable_self:
            pool = clickable_self
        else:
            seen = set()
            promoted = []
            for c in candidates:
                anc = clickable_self_or_ancestor(c["node"])
                if anc is not None and id(anc) not in seen:
                    mm = BOUNDS_RE.search(anc.get("bounds") or "")
                    if mm:
                        ax1, ay1, ax2, ay2 = (int(mm.group(i)) for i in (1, 2, 3, 4))
                        promoted.append({
                            "node": anc, "x1": ax1, "y1": ay1, "x2": ax2, "y2": ay2,
                            "area": (ax2 - ax1) * (ay2 - ay1), "clickable": True,
                        })
                        seen.add(id(anc))
            pool = promoted or candidates

        pool.sort(key=lambda c: c["area"])
        chosen = pool[0]
        node = chosen["node"]
        x1, y1, x2, y2 = chosen["x1"], chosen["y1"], chosen["x2"], chosen["y2"]

        # Wide FB row shells are clickable but meaningless — pick the deepest
        # semantic node at (x,y), matching frontend hierarchy-xml-pick behavior.
        if chosen["area"] > 80_000:
            depth_of: Dict[int, int] = {}

            def _node_depth(n) -> int:
                nid = id(n)
                if nid in depth_of:
                    return depth_of[nid]
                p = parent_of.get(id(n))
                depth_of[nid] = 0 if p is None else _node_depth(p) + 1
                return depth_of[nid]

            FB_GROUP_HEADER_DESC_RE = _re.compile(
                r"\b(thành viên|members|Công khai|Public|Nhóm công khai|private group|Private)\b",
                _re.I,
            )

            def _is_fb_group_header_desc(desc: str) -> bool:
                return bool(FB_GROUP_HEADER_DESC_RE.search((desc or "").strip()))

            best_sem = None
            best_score = -1
            start_area = chosen["area"]
            for c in candidates:
                sem = c["node"]
                desc = (sem.get("content-desc") or "").strip()
                text = (sem.get("text") or "").strip()
                rid = (sem.get("resource-id") or "").strip()
                if not desc and not text and not rid:
                    continue
                sem_area = c["area"]
                if (
                    desc
                    and _is_fb_group_header_desc(desc)
                    and sem_area > start_area * 0.5
                ):
                    continue
                depth = _node_depth(sem)
                score = depth * 600
                if desc and len(desc) < 500 and desc_count.get(desc, 0) == 1:
                    score += 3000
                elif text and len(text) < 500 and text_count.get(text, 0) == 1:
                    score += 2500
                elif rid and rid_count.get(rid, 0) == 1:
                    score += 800
                if (sem.get("clickable") or "").strip() == "true":
                    score += 900
                if score > best_score:
                    best_score = score
                    best_sem = sem
            if best_sem is not None:
                node = best_sem
                mm = BOUNDS_RE.search(node.get("bounds") or "")
                if mm:
                    x1, y1, x2, y2 = (int(mm.group(i)) for i in (1, 2, 3, 4))

        rid = (node.get("resource-id") or "").strip()
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls = (node.get("class") or "").strip()
        pkg = (node.get("package") or "").strip()

        ambiguous = is_ambiguous_launcher(rid, pkg)
        rid_unique = bool(rid) and not ambiguous and rid_count.get(rid, 0) == 1
        text_unique = bool(text) and len(text) < 80 and text_count.get(text, 0) == 1
        desc_unique = bool(desc) and len(desc) < 80 and desc_count.get(desc, 0) == 1

        if ambiguous and text and len(text) < 120:
            return {"by": "text", "value": text}
        if ambiguous and desc and len(desc) < 80:
            return {"by": "description", "value": desc}
        if rid_unique:
            return {"by": "resource-id", "value": rid}
        if desc_unique:
            return {"by": "description", "value": desc}
        if text_unique:
            return {"by": "text", "value": text}
        if rid and "/" in rid:
            same = [n for n in all_nodes if (n.get("resource-id") or "") == rid]
            clickable_same = [n for n in same if (n.get("clickable") or "") == "true"]
            if node in clickable_same:
                idx = clickable_same.index(node)
                return {
                    "by": "xpath",
                    "value": f'(//*[@resource-id="{rid}" and @clickable="true"])[{idx + 1}]',
                }
            idx = same.index(node) if node in same else 0
            return {"by": "xpath", "value": f'(//*[@resource-id="{rid}"])[{idx + 1}]'}
        if desc:
            return {"by": "description", "value": desc}
        if text and len(text) < 80:
            return {"by": "text", "value": text}
        if cls:
            if cls in CONTAINER_CLASSES:
                return {
                    "by": "xpath",
                    "value": f'//*[@class="{cls}" and @bounds="[{x1},{y1}][{x2},{y2}]"]',
                }
            return {"by": "class name", "value": cls}
        return None

    def _cancel_scrcpy_pending_attach(self) -> None:
        """Clear relay pending callback + 30s retry task (user detach must stop background re-attach)."""
        with self._lock:
            self._scrcpy_pending_generation += 1
            self._scrcpy_pending_claimed = False
        keys = set(self._scrcpy_pending_registered_keys)
        if self._scrcpy_pending_registered_ip:
            keys.add(self._scrcpy_pending_registered_ip)
        callback = self._scrcpy_pending_callback
        if keys:
            try:
                from runtime.transports.adb_relay_server import get_relay_manager

                _r = get_relay_manager()
                if _r:
                    for key in keys:
                        _r.cancel_pending_scrcpy(key, callback)
            except Exception:
                pass
            self._scrcpy_pending_registered_ip = None
            self._scrcpy_pending_registered_keys.clear()
            self._scrcpy_pending_callback = None
        t = self._scrcpy_attach_retry_task
        self._scrcpy_attach_retry_task = None
        if t is not None and not t.done() and self._loop:
            _loop = self._loop

            def _cancel() -> None:
                if not t.done():
                    t.cancel()

            try:
                _loop.call_soon_threadsafe(_cancel)
            except Exception:
                pass

    def attach_scrcpy_stream(
        self,
        device_ip: str,
        adb_port: int = 5555,
        enable_control: bool = True,
        *,
        profile: str | None = None,
        max_fps: int | None = None,
        max_width: int | None = None,
        bitrate: int | None = None,
    ) -> str:
        """
        Attach scrcpy screen streaming to a WS-Agent device (Mode A hybrid).

        Routing:
          - Cloud deployment (relay available): frames travel device → agent-boot → gRPC → cloud.
            No local adb binary needed.
          - Local / single-machine (no relay): ScrcpyReceiver uses local adb directly (fallback).

        When enable_control=True, scrcpy also opens its control channel for
        stream recovery/keyframe requests. Touch/key input still uses the
        DeviceClient priority order and does not route through scrcpy_control.
        """
        def _positive_int(value: Any) -> int | None:
            try:
                parsed = int(value or 0)
            except Exception:
                return None
            return parsed if parsed > 0 else None

        requested_max_fps = _positive_int(max_fps)
        requested_max_width = _positive_int(max_width)
        requested_bitrate = _positive_int(bitrate)
        effective_profile = str(profile or "visible").strip().lower() or "visible"
        effective_max_fps = requested_max_fps or int(self.config.device.scrcpy_max_fps or 0)
        effective_max_width = requested_max_width or int(self.config.device.scrcpy_max_width or 0)
        effective_bitrate = requested_bitrate or int(self.config.device.scrcpy_relay_bitrate or 0)
        attach_params = (
            device_ip,
            adb_port,
            enable_control,
            requested_max_fps,
            requested_max_width,
            requested_bitrate,
            effective_profile,
        )

        # If relay scrcpy is already streaming for the same device IP, don't tear it down.
        # APK WS reconnects frequently (WiFi instability, atx-agent restarts) and each
        # reconnect calls attach_scrcpy_stream — killing + restarting scrcpy every time
        # causes video freeze for 2-5s per reconnect.
        # The relay scrcpy session is independent of the APK WS lifecycle — keep it alive.
        if self._scrcpy_active and self._scrcpy_receiver is not None:
            # RelayScrcpyReceiver.serial is "ip:port"; extract IP for comparison.
            # device_ip may be a full serial ("ip:port") or bare IP — normalise both.
            existing_serial = getattr(self._scrcpy_receiver, "serial", "") or ""
            existing_ip = existing_serial.rsplit(":", 1)[0] if ":" in existing_serial else existing_serial
            device_ip_norm = device_ip.rsplit(":", 1)[0] if ":" in device_ip else device_ip
            if existing_ip == device_ip_norm:
                current_params = self._scrcpy_params or ()
                current_enable_control = bool(current_params[2]) if len(current_params) >= 3 else True
                current_max_fps = (
                    _positive_int(current_params[3])
                    if len(current_params) >= 4
                    else None
                ) or int(self.config.device.scrcpy_max_fps or 0)
                current_max_width = (
                    _positive_int(current_params[4])
                    if len(current_params) >= 5
                    else None
                ) or int(self.config.device.scrcpy_max_width or 0)
                current_bitrate = (
                    _positive_int(current_params[5])
                    if len(current_params) >= 6
                    else None
                ) or int(self.config.device.scrcpy_relay_bitrate or 0)
                current_profile = (
                    str(current_params[6]).strip().lower()
                    if len(current_params) >= 7 and current_params[6]
                    else "visible"
                )
                needs_reconfigure = (
                    enable_control != current_enable_control
                    or effective_profile != current_profile
                    or effective_max_fps != current_max_fps
                    or effective_max_width != current_max_width
                    or effective_bitrate != current_bitrate
                )
                # Also check if the relay session is still alive.  When gRPC reconnects,
                # stop_all_sessions() kills scrcpy on agent-boot and clears _scrcpy_running.
                # Detect this by asking the relay manager — if the session is gone,
                # fall through to restart WITHOUT clearing _scrcpy_active (which would
                # cause on_agent_disconnect to wipe _last_config_frame and lose bootstrap).
                _session_alive = True
                try:
                    import time as _time
                    from runtime.transports.adb_relay_server import get_relay_manager as _grm
                    _relay_check = _grm()
                    if _relay_check and not _relay_check.is_scrcpy_running(existing_serial):
                        _session_alive = False
                except Exception:
                    pass
                if _session_alive and not needs_reconfigure:
                    self._log(
                        f"scrcpy already streaming for {device_ip} — skipping reattach",
                        level=logging.DEBUG,
                    )
                    # Force IDR so the browser decoder resyncs immediately after
                    # a phone-WS drop/reconnect. Without this, the encoder may be
                    # paused on a static screen and the natural keyframe interval
                    # (up to 14s, or never on idle) leaves the dashboard black.
                    ctrl = getattr(self._scrcpy_receiver, "control", None)
                    if ctrl is not None and hasattr(ctrl, "request_idr"):
                        try:
                            ctrl.request_idr()
                            self._log("request_idr after attach-skip (WS reconnect)", level=logging.DEBUG)
                        except Exception:
                            pass
                    return "active"
                if _session_alive and needs_reconfigure:
                    self._log(
                        f"scrcpy profile reconfigure for {device_ip}: "
                        f"fps {current_max_fps}->{effective_max_fps}, "
                        f"width {current_max_width}->{effective_max_width}, "
                        f"bitrate {current_bitrate}->{effective_bitrate}, "
                        f"profile {current_profile}->{effective_profile}, "
                        f"control {current_enable_control}->{enable_control}",
                        level=logging.INFO,
                    )
                    self._scrcpy_params = attach_params
                    _force_scrcpy_restart = True
                    _reconfigure_old_receiver = self._scrcpy_receiver
                    _reconfigure_old_serial = existing_serial
                    _skip_detach = True
                # If we are still receiving frames recently, treat this as a transient
                # relay flap / false negative and do not restart immediately.
                # This guard is only for suspected relay-loss false negatives.
                # A real profile change must continue to the detach/restart path.
                if not needs_reconfigure:
                    now = _time.monotonic()
                    if self._last_frame_time > 0 and (now - self._last_frame_time) < 1.5:
                        self._log(
                            f"relay session check says dead but frames are fresh "
                            f"({now - self._last_frame_time:.2f}s) — skipping restart",
                            level=logging.INFO,
                        )
                        return "active"
                    # Restart cooldown: avoid repeated stop/restart loops on unstable gRPC.
                    if self._scrcpy_last_restart_at > 0 and (now - self._scrcpy_last_restart_at) < 5.0:
                        self._log(
                            f"relay session lost for {existing_ip} but restart cooldown active "
                            f"({now - self._scrcpy_last_restart_at:.1f}s) — skipping restart",
                            level=logging.WARNING,
                        )
                        return "pending"
                    # Relay session lost — stop the dead receiver (no scrcpy_stop sent,
                    # agent already stopped it) and fall through to restart.
                    # _scrcpy_active stays True so on_agent_disconnect won't clear
                    # _last_config_frame (existing browser subscribers keep their bootstrap).
                    self._log(
                        f"relay session lost for {existing_ip} — restarting scrcpy",
                        level=logging.INFO,
                    )
                    self._scrcpy_last_restart_at = _time.monotonic()
                    try:
                        self._scrcpy_receiver.stop_receiver()
                    except Exception:
                        pass
                    self._scrcpy_receiver = None
                    # fall through to re-create receiver and re-issue scrcpy_start
                    # NOTE: do NOT call detach_scrcpy_stream() here — it sets _scrcpy_active=False
                    # which would allow on_agent_disconnected() to clear _last_config_frame.
                    # We only need the normal detach path for the case where we start fresh.
                    self._scrcpy_active = True  # explicitly keep True for on_agent_disconnect guard
                    _skip_detach = True

        if locals().get("_force_scrcpy_restart"):
            self._cancel_scrcpy_pending_attach()
            old_receiver = locals().get("_reconfigure_old_receiver")
            old_serial = str(locals().get("_reconfigure_old_serial") or "").strip()
            try:
                if old_receiver is not None:
                    old_receiver.stop_receiver()
            except Exception:
                pass
            if old_serial and self._loop:
                try:
                    import asyncio
                    from runtime.transports.adb_relay_server import get_relay_manager
                    from runtime.transports.scrcpy_receiver import RelayScrcpyReceiver

                    if isinstance(old_receiver, RelayScrcpyReceiver):
                        relay = get_relay_manager()
                        if relay:
                            reg = relay.get_scrcpy_receiver(old_serial)
                            if reg is old_receiver:
                                stop_future = asyncio.run_coroutine_threadsafe(
                                    relay.stop_scrcpy(
                                        old_serial,
                                        reason="attach_scrcpy_stream:profile_reconfigure",
                                    ),
                                    self._loop,
                                )
                                try:
                                    stop_future.result(timeout=5.0)
                                except Exception as exc:
                                    stop_future.cancel()
                                    self._log(
                                        f"scrcpy profile reconfigure stop timed out for {old_serial}: {exc}",
                                        level=logging.WARNING,
                                    )
                                    return "pending"
                except Exception as exc:
                    self._log(
                        f"scrcpy profile reconfigure cleanup failed for {old_serial}: {exc}",
                        level=logging.WARNING,
                    )
                    return "pending"
            self._scrcpy_receiver = None
            self._scrcpy_active = False
            self._scrcpy_attached_at = 0.0
        elif not locals().get("_skip_detach"):
            self.detach_scrcpy_stream(reason="attach_scrcpy_stream:replace_previous_receiver")
        else:
            # Restart path: still cancel stale pending/retry from a prior failed attach.
            self._cancel_scrcpy_pending_attach()
        # A newly created receiver is a new encoder generation even when it
        # emits byte-identical SPS/PPS. Never bootstrap it with an IDR from the
        # previous scrcpy process.
        self.reset_stream_bootstrap_generation()
        # Store params so subscribe_frames can restart scrcpy after an auto-stop.
        self._scrcpy_params = attach_params

        # Use IP-only as the lookup key for relay mode — mDNS port is OS-assigned
        # and not known here.  resolve_serial() finds the device by IP in the relay
        # manager's serial index.  adb_port is kept as fallback for local-adb path.
        serial = device_ip if (adb_port is None or adb_port == 5555) else f"{device_ip}:{adb_port}"
        scrcpy_port = 27183 + self.index
        _relay_mode = self.config.streaming.mode != "periodic"

        # ── Shared callbacks (same for both relay and local paths) ──────────────
        def _on_scrcpy_frame(jpeg: bytes) -> None:
            ctrl = receiver.control
            if ctrl is not None and self.screen_width and ctrl.screen_width != self.screen_width:
                ctrl.screen_width = self.screen_width
                ctrl.screen_height = self.screen_height
                self._log(f"ScrcpyControl coords updated to real resolution: {self.screen_width}x{self.screen_height}")
            with self._latest_jpeg_lock:
                self._latest_jpeg = jpeg
                now = time.monotonic()
                self._last_frame_time = now
                self._last_jpeg_frame_time = now

        def _on_scrcpy_h264_config(avcc_record: bytes, w: int, h: int, changed: bool = False) -> None:
            self.on_agent_h264_config(
                avcc_record, w or self.screen_width, h or self.screen_height, changed
            )

        def _on_scrcpy_h264_packet(avcc_data: bytes, is_key: bool, pts_us: int) -> None:
            self.on_agent_h264_video(avcc_data, is_key, pts_us)

        # ── Try relay path first (cloud deployment) ─────────────────────────────
        try:
            import time as _time
            from runtime.transports.adb_relay_server import get_relay_manager
            from runtime.transports.scrcpy_receiver import RelayScrcpyReceiver
            from runtime.transports.scrcpy_control import RelayScrcpyControl

            relay = get_relay_manager()

            # Prefer stable relay ADB serial over stale DB/docker WS client IPs
            # (e.g. 172.19.0.1 gateway when server runs in Docker).
            lookup_hints: list[str] = []
            for hint in (self._adb_serial, self.serial, device_ip, serial):
                h = str(hint or "").strip()
                if h and h not in lookup_hints:
                    lookup_hints.append(h)

            actual_serial = serial
            if relay:
                for hint in lookup_hints:
                    candidate = relay.resolve_serial(hint)
                    if relay.relay_for_serial(candidate):
                        actual_serial = candidate
                        break
                else:
                    actual_serial = relay.resolve_serial(serial)

            # If device still not known to any relay agent, wait up to 4 s for
            # agent-boot's next heartbeat.  Do NOT broadcast `adb connect ip:5555` —
            # mDNS devices are already connected at an OS-assigned port; connecting to
            # :5555 will always fail with "Connection refused".
            if relay and not relay.relay_for_serial(actual_serial):
                for _ in range(16):         # poll 16 × 0.25 s = up to 4 s
                    _time.sleep(0.25)
                    for hint in lookup_hints:
                        candidate = relay.resolve_serial(hint)
                        if relay.relay_for_serial(candidate):
                            actual_serial = candidate
                            break
                    if relay.relay_for_serial(actual_serial):
                        break

            if relay and relay.relay_for_serial(actual_serial) and self._loop:
                # Cache resolved adb serial so a11y gRPC, u2 relay, etc. use
                # the real adb serial instead of the web-registration ID.
                if actual_serial != self.serial:
                    self._adb_serial = actual_serial

                # Populate device metadata from relay capabilities (if not already set)
                caps = relay.get_capabilities(actual_serial)
                if caps:
                    self.brand           = self.brand or caps.get("brand", "")
                    self.model           = self.model or caps.get("model", "")
                    self.android_version = self.android_version or caps.get("android_version", "")
                    self.sdk_version     = self.sdk_version or int(caps.get("sdk") or 0)
                    self.screen_width    = self.screen_width or int(caps.get("screen_width") or 0)
                    self.screen_height   = self.screen_height or int(caps.get("screen_height") or 0)
                    self.name = self.name or f"{caps.get('brand','')} {caps.get('model','')}".strip()
                if (
                    (not self.screen_width or not self.screen_height)
                    and self._loop
                    and hasattr(relay, "adb_shell")
                ):
                    size_future = asyncio.run_coroutine_threadsafe(
                        self._fetch_screen_size_via_relay(relay, actual_serial),
                        self._loop,
                    )
                    try:
                        size_future.result(timeout=2.0)
                    except Exception:
                        size_future.cancel()

                receiver = RelayScrcpyReceiver(
                    serial=actual_serial,
                    on_frame=_on_scrcpy_frame,
                    on_h264_config=_on_scrcpy_h264_config if _relay_mode else None,
                    on_h264_packet=_on_scrcpy_h264_packet if _relay_mode else None,
                )

                if enable_control:
                    receiver.control = RelayScrcpyControl(
                        serial=actual_serial,
                        relay_manager=relay,
                        loop=self._loop,
                        screen_width=self.screen_width or 0,
                        screen_height=self.screen_height or 0,
                    )

                # Register under actual_serial — frames from agent arrive with this serial
                relay.register_scrcpy_receiver(actual_serial, receiver)
                receiver.start_receiver()

                # Only send scrcpy_start if no session is currently running.
                # If a relay-only device already started scrcpy for this serial,
                # we inherit the running session without restarting it — avoids
                # the 3-5s scrcpy restart gap and prevents two scrcpy processes
                # competing for localabstract:scrcpy on the same device.
                import asyncio
                if relay.is_scrcpy_running(actual_serial) and not locals().get("_force_scrcpy_restart"):
                    self._log(
                        f"scrcpy already running for {actual_serial} — inheriting session",
                        level=logging.DEBUG,
                    )
                    # Force scrcpy to resend SPS/PPS config + IDR so this new receiver
                    # gets a fresh keyframe immediately.  Without this, the browser H264
                    # decoder never receives a config frame for this device's serial and
                    # the stream appears frozen until the next natural codec reset.
                    if enable_control and receiver.control is not None:
                        try:
                            receiver.control.request_idr()
                        except Exception:
                            pass
                else:
                    # low_latency (KEY_LATENCY=0): saves ~66-133ms of encoder buffer
                    # but crashes MediaCodec on Android 14+ (API 34+). Safe on API ≤ 33.
                    _sdk = int(self.sdk_version or 0)
                    _low_latency = 0 < _sdk < 34
                    start_future = asyncio.run_coroutine_threadsafe(
                        relay.start_scrcpy(
                            serial=actual_serial,
                            max_fps=effective_max_fps,
                            max_width=effective_max_width,
                            enable_control=enable_control,
                            port=scrcpy_port,
                            bitrate=effective_bitrate,
                            low_latency=_low_latency,
                            profile=effective_profile,
                        ),
                        self._loop,
                    )
                    try:
                        started = bool(start_future.result(timeout=5.0))
                    except Exception as exc:
                        start_future.cancel()

                        def _cleanup_late_scrcpy_start(done_future: Any) -> None:
                            if done_future.cancelled():
                                return
                            try:
                                late_started = bool(done_future.result())
                            except Exception:
                                return
                            if late_started and self._loop:
                                asyncio.run_coroutine_threadsafe(
                                    relay.stop_scrcpy(
                                        actual_serial,
                                        reason="attach_start_abandoned",
                                    ),
                                    self._loop,
                                )

                        start_future.add_done_callback(_cleanup_late_scrcpy_start)
                        relay.unregister_scrcpy_receiver(actual_serial)
                        try:
                            receiver.stop_receiver()
                        except Exception:
                            pass
                        self._log(
                            f"scrcpy_start failed for {actual_serial}: {exc}",
                            level=logging.WARNING,
                        )
                        return "unavailable"
                    if not started:
                        relay.unregister_scrcpy_receiver(actual_serial)
                        try:
                            receiver.stop_receiver()
                        except Exception:
                            pass
                        self._log(
                            f"scrcpy_start rejected: no relay for {actual_serial}",
                            level=logging.WARNING,
                        )
                        return "unavailable"

                # Fetch screen resolution via relay shell (non-blocking, best-effort)
                if not self.screen_width or not self.screen_height:
                    asyncio.run_coroutine_threadsafe(
                        self._fetch_screen_size_via_relay(relay, actual_serial),
                        self._loop,
                    )

                self._scrcpy_receiver = receiver
                self._scrcpy_active = True
                self._scrcpy_attached_at = time.monotonic()
                # Relay scrcpy gives us a live control/video transport even if
                # bootstrap has not sent a full agent status yet.
                if self.state in (DeviceState.DISCONNECTED, DeviceState.CONNECTING):
                    self.state = DeviceState.READY
                ctrl_status = "control=ON (relay)" if enable_control else "video-only (relay)"
                self._log(f"scrcpy stream attached via relay ({actual_serial}) — {ctrl_status}")
                with self._lock:
                    self._scrcpy_pending_generation += 1
                    self._scrcpy_pending_claimed = False
                    self._scrcpy_pending_registered_ip = None
                    self._scrcpy_pending_registered_keys.clear()
                    self._scrcpy_pending_callback = None
                return "active"
        except Exception as exc:
            self._log(f"relay scrcpy unavailable, falling back to local adb: {exc}", level=logging.DEBUG)

        # If relay server is running but no relay agent connected for this device,
        # register a pending callback so scrcpy starts automatically once agent-boot
        # connects and reports the device serial via heartbeat.
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            _relay = get_relay_manager()
            if _relay is not None:
                connected_relays = _relay.registered_relays()
                device_ip = device_ip  # captured in closure below
                _enable_control = enable_control
                _max_fps = requested_max_fps
                _max_width = requested_max_width
                _bitrate = requested_bitrate
                _loop = self._loop
                with self._lock:
                    self._scrcpy_pending_generation += 1
                    _pending_generation = self._scrcpy_pending_generation
                    self._scrcpy_pending_claimed = False

                def _on_relay_serial(actual_serial: str) -> None:
                    skip_reason = ""
                    with self._lock:
                        if _pending_generation != self._scrcpy_pending_generation:
                            skip_reason = "stale generation"
                        elif self._scrcpy_pending_claimed:
                            skip_reason = "already claimed"
                        else:
                            self._scrcpy_pending_claimed = True
                    if skip_reason:
                        self._log(
                            f"[scrcpy] skip duplicate pending attach for {actual_serial}: {skip_reason}",
                            level=logging.DEBUG,
                        )
                        return
                    self._log(
                        f"[scrcpy] relay agent now has {actual_serial} — re-attaching scrcpy",
                        level=logging.INFO,
                    )
                    import concurrent.futures as _cf
                    executor = _cf.ThreadPoolExecutor(max_workers=1)
                    if _max_fps is None and _max_width is None and _bitrate is None:
                        executor.submit(self.attach_scrcpy_stream, actual_serial, 5555, _enable_control)
                    else:
                        executor.submit(
                            lambda: self.attach_scrcpy_stream(
                                actual_serial,
                                5555,
                                _enable_control,
                                max_fps=_max_fps,
                                max_width=_max_width,
                                bitrate=_bitrate,
                            )
                        )

                pending_keys: list[str] = []
                for hint in (self._adb_serial, self.serial, device_ip):
                    h = str(hint or "").strip()
                    if not h:
                        continue
                    pending_keys.append(h)
                    if ":" in h:
                        pending_keys.append(h.rsplit(":", 1)[0])
                pending_keys_deduped = list(dict.fromkeys(pending_keys))
                self._scrcpy_pending_registered_ip = device_ip
                self._scrcpy_pending_registered_keys = set(pending_keys_deduped)
                self._scrcpy_pending_callback = _on_relay_serial
                for key in pending_keys_deduped:
                    _relay.register_pending_scrcpy(key, _on_relay_serial)
                relay_status = (
                    "no relay video agents connected; "
                    "agent-boot RelayService/WS video channel is not registered"
                    if not connected_relays
                    else f"relay agent not yet connected for {device_ip!r}"
                )
                self._log(
                    f"[scrcpy] {relay_status} "
                    f"(pending keys={pending_keys_deduped}) — "
                    f"will auto-start when agent-boot reports the device. "
                    f"Connected relay agents: {connected_relays}",
                    level=logging.WARNING,
                )

                # Also schedule a retry in 30 s — in case the relay connects but
                # the RegisterMsg doesn't include this device (e.g. device joined adb
                # after the relay's initial heartbeat).
                if _loop:
                    async def _delayed_retry() -> None:
                        import asyncio as _asyncio
                        await _asyncio.sleep(30)
                        # Only retry if scrcpy still not active
                        if not self._scrcpy_active and self.state not in (
                            DeviceState.DISCONNECTED, DeviceState.DEAD
                        ):
                            retry_target = device_ip
                            try:
                                from runtime.transports.adb_relay_server import get_relay_manager as _grm

                                _relay_retry = _grm()
                                if _relay_retry is not None:
                                    # Prefer stable bound serials; never retry on raw public client IP.
                                    for _hint in (self._adb_serial, self.serial, device_ip):
                                        _h = str(_hint or "").strip()
                                        if not _h:
                                            continue
                                        _actual = _relay_retry.resolve_serial(_h)
                                        if _relay_retry.relay_for_serial(_actual):
                                            retry_target = _actual
                                            break
                            except Exception:
                                pass
                            self._log(
                                f"[scrcpy] 30s retry: re-attempting attach_scrcpy_stream for {retry_target!r}",
                                level=logging.INFO,
                            )
                            with self._lock:
                                if (
                                    _pending_generation != self._scrcpy_pending_generation
                                    or self._scrcpy_pending_claimed
                                ):
                                    return
                                self._scrcpy_pending_claimed = True
                            import concurrent.futures as _cf2
                            executor = _cf2.ThreadPoolExecutor(max_workers=1)
                            if _max_fps is None and _max_width is None and _bitrate is None:
                                executor.submit(self.attach_scrcpy_stream, retry_target, 5555, _enable_control)
                            else:
                                executor.submit(
                                    lambda: self.attach_scrcpy_stream(
                                        retry_target,
                                        5555,
                                        _enable_control,
                                        max_fps=_max_fps,
                                        max_width=_max_width,
                                        bitrate=_bitrate,
                                    )
                                )

                    def _arm_retry() -> None:
                        old = self._scrcpy_attach_retry_task
                        if old is not None and not old.done():
                            old.cancel()
                        self._scrcpy_attach_retry_task = _loop.create_task(_delayed_retry())

                    _loop.call_soon_threadsafe(_arm_retry)
                return "pending"
        except Exception as exc:
            self._log(
                f"attach_scrcpy_stream: pending relay attach setup failed for {device_ip!r}: {exc}",
                level=logging.WARNING,
            )

        self._log(
            f"attach_scrcpy_stream: no relay agent connected for {device_ip!r}. "
            "Scrcpy requires agent-boot to be running and connected; "
            "leaving stream inactive instead of failing attach.",
            level=logging.WARNING,
        )
        return "unavailable"

    async def _fetch_screen_size_via_relay(self, relay: Any, serial: str) -> None:
        """Best-effort: read wm size from device via relay shell and store on self."""
        try:
            output = await relay.adb_shell(serial, "wm size", timeout=10.0)
            if not output:
                return
            # Prefer the override resolution. `wm size` prints both when the
            # display size was changed from the panel default:
            #
            #   Physical size: 1440x2960
            #   Override size: 1080x2220
            #
            # Touch injection and scrcpy capture both live in the override
            # space, so taking the physical numbers scales every tap by
            # 1440/1080 and pushes the right edge off-screen. Samsung ships
            # Note 10+ on FHD+, so the two differ on normal hardware.
            sizes: dict[str, str] = {}
            for line in output.strip().splitlines():
                label, _, value = line.partition(":")
                label = label.strip().lower()
                if "x" in value and label in ("physical size", "override size"):
                    sizes[label] = value.strip()
            chosen = sizes.get("override size") or sizes.get("physical size")
            if chosen:
                parts = chosen.split("x")
                self.screen_width = int(parts[0])
                self.screen_height = int(parts[1])
                self._log(f"Screen resolution via relay: {self.screen_width}x{self.screen_height}")
                # Propagate to relay control if already created
                recv = self._scrcpy_receiver
                if recv is not None and recv.control is not None:
                    recv.control.screen_width = self.screen_width
                    recv.control.screen_height = self.screen_height
                self._publish_status()
        except Exception as exc:
            self._log(f"relay wm size failed: {exc}", level=logging.DEBUG)

    def _clear_scrcpy_without_stop(self) -> None:
        """Yield the relay scrcpy session to another DeviceClient without stopping it.

        Called when a WS APK device takes over scrcpy for the same physical device.
        We clear our local state so auto-stop timers don't fire and kill the session
        that the new owner will use.  No scrcpy_stop is sent to the relay.
        """
        if self._scrcpy_receiver is not None:
            try:
                self._scrcpy_receiver.stop_receiver()
            except Exception:
                pass
            self._scrcpy_receiver = None
        self._scrcpy_active = False
        self._last_frame_time = 0.0
        self._last_jpeg_frame_time = 0.0
        self._scrcpy_params = None   # prevent demand-restart on subscribe_frames
        # Cancel pending auto-stop so it doesn't call detach_scrcpy_stream
        if self._scrcpy_stop_task is not None:
            try:
                self._scrcpy_stop_task.cancel()
            except Exception:
                pass
            self._scrcpy_stop_task = None

    def mark_scrcpy_relay_offline(self, relay_serial: str) -> bool:
        """Mark the relay-owned scrcpy session dead without sending scrcpy_stop.

        Relay disconnect already killed agent-boot's scrcpy process.  This only
        clears this DeviceClient's stale receiver/active flags so the next attach
        can issue a new scrcpy_start when the relay comes back.
        """
        receiver = self._scrcpy_receiver
        if receiver is None:
            return False

        receiver_serial = str(getattr(receiver, "serial", "") or "")
        relay_serial = str(relay_serial or "").strip()
        if relay_serial and receiver_serial and receiver_serial != relay_serial:
            return False

        try:
            receiver.stop_receiver()
        except Exception:
            pass

        if receiver_serial:
            try:
                from runtime.transports.adb_relay_server import get_relay_manager

                relay = get_relay_manager()
                if relay and relay.get_scrcpy_receiver(receiver_serial) is receiver:
                    relay.unregister_scrcpy_receiver(receiver_serial)
            except Exception:
                pass

        self._scrcpy_receiver = None
        self._scrcpy_active = False
        self._scrcpy_attached_at = 0.0
        self._last_frame_time = 0.0
        self._last_jpeg_frame_time = 0.0
        self._cancel_scrcpy_pending_attach()
        self._log(
            f"scrcpy relay offline for {relay_serial or receiver_serial} — marked inactive",
            level=logging.INFO,
        )
        return True

    def detach_scrcpy_stream(self, reason: str = "unspecified") -> None:
        """Stop scrcpy receiver (+ control) and resume MediaProjection frames.
        For relay receivers, also sends SCRCPY_STOP to the relay agent."""
        self._log(f"detach_scrcpy_stream: reason={reason}", level=logging.INFO)
        if self._scrcpy_receiver is not None:
            serial = getattr(self._scrcpy_receiver, "serial", None)
            try:
                self._scrcpy_receiver.stop_receiver()
            except Exception:
                pass
            # Clean up relay state if this was a relay-mode receiver.
            # Only stop the relay stream if we still own the receiver slot — a WS
            # device can overwrite register_scrcpy_receiver(actual_serial) after
            # a relay-only placeholder attached first; detach on the ghost must not
            # SCRCPY_STOP / unregister the live consumer.
            if serial and self._loop:
                try:
                    from runtime.transports.adb_relay_server import get_relay_manager
                    from runtime.transports.scrcpy_receiver import RelayScrcpyReceiver
                    import asyncio
                    if isinstance(self._scrcpy_receiver, RelayScrcpyReceiver):
                        relay = get_relay_manager()
                        if relay:
                            reg = relay.get_scrcpy_receiver(serial)
                            if reg is self._scrcpy_receiver:
                                asyncio.run_coroutine_threadsafe(
                                    relay.stop_scrcpy(serial, reason=reason), self._loop
                                )
                except Exception:
                    pass
            self._scrcpy_receiver = None
        self._scrcpy_active = False
        self._scrcpy_attached_at = 0.0
        self._cancel_scrcpy_pending_attach()

    _BY_MAP = {
        "xpath":       "xpath",
        "resource-id": "resourceId",
        "id":          "resourceId",
        "resourceId":  "resourceId",
        "text":        "text",
        "content-desc": "description",
        "content_desc": "description",
        "description": "description",
        "class name":  "className",
        "className":   "className",
    }

    def _batch_enabled(self) -> bool:
        return self._u2_batch is not None

    def _selector_dict(self, by: str, value: str) -> dict:
        key = self._BY_MAP.get(by)
        if key is None:
            return {"text": value}
        return {key: value}

    def u2_batch(
        self,
        actions: list,
        timeout: float = 30.0,
        cancel_event: Optional[threading.Event] = None,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> list:
        """Pipeline N primitive u2 ops in a single RPC. Raises if not enabled."""
        if not self._batch_enabled():
            raise RuntimeError("u2 batch not available for this device")
        return self._u2_batch.batch(
            actions,
            timeout=timeout,
            cancel_event=cancel_event,
            priority=priority,
            deadline_ms=deadline_ms,
        )

    def u2_flow(
        self,
        name: str,
        params: dict,
        timeout: float = 30.0,
        priority: str | int | None = None,
        deadline_ms: int | float | None = None,
    ) -> dict:
        """Run a high-level u2 flow, preferring agent-boot batch/flow relay."""
        if self._batch_enabled() and callable(getattr(self._u2_batch, "flow", None)):
            return self._u2_batch.flow(
                name,
                params,
                timeout=timeout,
                priority=priority,
                deadline_ms=deadline_ms,
            )
        with self._u2_lock:
            u2 = self._u2
        flow = getattr(u2, "flow", None)
        if callable(flow):
            return flow(name, params, timeout=timeout)
        raise RuntimeError("u2 flow not available for this device")

    def tap_selector(self, by: str, value: str) -> None:
        """
        Tap element by selector (uiautomator2 find + click).
        On connection/timeout error: null _u2, reconnect, retry once.
        """
        by = (by or "").strip()
        value = (value or "").strip()
        # Normalize common names to our JSON-RPC selector surface.
        if by in ("accessibility id", "accessibility_id", "content-desc", "content_desc"):
            by = "description"
        # Fuzzy description matching: translate to xpath (our JSON-RPC wrapper doesn't expose
        # descriptionContains/StartsWith as native selector fields).
        if by in ("descriptionContains", "content-desc-contains", "content_desc_contains"):
            escaped = value.replace('"', '\\"')
            by = "xpath"
            value = f'//*[contains(@content-desc,"{escaped}")]'
        elif by in ("descriptionStartsWith", "content-desc-starts-with", "content_desc_starts_with"):
            escaped = value.replace('"', '\\"')
            by = "xpath"
            value = f'//*[starts-with(@content-desc,"{escaped}")]'

        if not self.ensure_u2_healthy() or self._u2 is None:
            self._log("tap_selector skipped (U2 not available)", level=logging.WARNING)
            return

        if self._batch_enabled():
            _t0 = time.perf_counter()
            self._log(
                f"tap_selector route=agent_boot_batch_flow by={by} value={value!r}",
                level=logging.INFO,
            )
            try:
                result = self._u2_batch.flow(
                    "find_click_wait",
                    {
                        "selector": self._selector_dict(by, value),
                        "click_timeout": 10.0,
                        "gone_timeout": 2.0,
                    },
                    timeout=15.0,
                )
                _elapsed_ms = (time.perf_counter() - _t0) * 1000
                if result.get("found"):
                    self._log(f"tap_selector batch ok elapsed={_elapsed_ms:.0f}ms", level=logging.DEBUG)
                    self.hierarchy_invalidate_cache()
                    return
                self._log(f"tap_selector: not found via flow {by}={value!r} elapsed={_elapsed_ms:.0f}ms", level=logging.DEBUG)
            except Exception as exc:
                self._log(f"tap_selector flow error: {exc} — falling back", level=logging.WARNING)

        self._log(
            f"tap_selector route=device_farm_u2_wrapper by={by} value={value!r}",
            level=logging.INFO,
        )
        self._tap_selector_legacy(by, value)

    def _tap_selector_legacy(self, by: str, value: str) -> None:
        u2_snap = self._u2
        if u2_snap is None:
            return
        eid = None
        try:
            eid = u2_snap.find_element(by, value)
            if eid is None:
                self._log(f"tap_selector: element not found {by}={value!r}", level=logging.WARNING)
                return
            u2_snap.element_click(eid)
            self.hierarchy_invalidate_cache()
            return
        except Exception as exc:
            self._log(f"tap_selector failed: {exc}", level=logging.WARNING)
        with self._u2_lock:
            if self._u2 is u2_snap:
                self._u2 = None
        if not self._reconnect_u2() or self._u2 is None:
            return
        try:
            eid = self._u2.find_element(by, value)
            if eid is None:
                self._log(f"tap_selector retry: element not found {by}={value!r}", level=logging.WARNING)
                return
            self._u2.element_click(eid)
            self.hierarchy_invalidate_cache()
        except Exception as exc:
            self._log(f"tap_selector retry failed: {exc}", level=logging.WARNING)
            with self._u2_lock:
                if self._u2 is not None:
                    self._u2 = None

    def screen_on(self) -> None:
        """Wake the device screen via U2 (screenOn RPC) or key('power') fallback."""
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.screen_on()
                return
            except Exception as exc:
                self._log(f"screen_on via U2 failed: {exc}", level=logging.WARNING)
        self.key("power")

    def screen_off(self) -> None:
        """Put the device screen to sleep via U2 (screenOff RPC) or key('power') fallback."""
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.screen_off()
                return
            except Exception as exc:
                self._log(f"screen_off via U2 failed: {exc}", level=logging.WARNING)
        self.key("power")

    def unlock(self) -> None:
        """Unlock device via U2 (unlock RPC) or power+swipe-up fallback."""
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.unlock()
                return
            except Exception as exc:
                self._log(f"unlock via U2 failed: {exc}", level=logging.WARNING)
        # Fallback: power press to wake, then swipe-up
        self.key("power")
        time.sleep(0.3)
        self.swipe(540, 1600, 540, 800, 400)

    def swipe_ext(self, direction: str, scale: float = 0.8, duration_ms: int = 500) -> None:
        """Directional screen-relative swipe (up/down/left/right).

        Prefers U2's swipe_ext (reads device info for exact screen size);
        falls back to raw swipe() using screen_width / screen_height from DeviceClient.
        """
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.swipe_ext(direction, scale=scale, duration=duration_ms / 1000.0)
                return
            except Exception as exc:
                self._log(f"swipe_ext via U2 failed ({direction}): {exc}", level=logging.WARNING)
        # Fallback using cached screen dimensions
        w = self.screen_width or 1080
        h = self.screen_height or 1920
        cx, cy = w // 2, h // 2
        hw = int(w * scale / 2)
        hh = int(h * scale / 2)
        d = direction.lower()
        if d == "up":
            self.swipe(cx, cy + hh, cx, cy - hh, duration_ms)
        elif d == "down":
            self.swipe(cx, cy - hh, cx, cy + hh, duration_ms)
        elif d == "left":
            self.swipe(cx + hw, cy, cx - hw, cy, duration_ms)
        elif d == "right":
            self.swipe(cx - hw, cy, cx + hw, cy, duration_ms)
        else:
            self._log(f"swipe_ext: unknown direction {direction!r}", level=logging.WARNING)

    def install(self, apk_source: str, timeout: float = 90.0) -> None:
        """Install APK via atx-agent /install endpoint (URL or local path).

        Requires atx-agent to be running on the device (port 7912).
        Falls back to ADB install for ADB-mode devices.
        """
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.install(apk_source, timeout=timeout)
                self._log(f"install via atx-agent: {apk_source}")
                return
            except Exception as exc:
                self._log(f"install via atx-agent failed: {exc}", level=logging.WARNING)
        else:
            self._log("install: no suitable transport available", level=logging.WARNING)

    # ── uiautomator2 passthrough ──────────────────────────────────────────────

    @property
    def u2_device(self) -> Optional[U2JsonRpcClient]:
        return self._u2

    @property
    def u2(self) -> Optional[U2JsonRpcClient]:
        return self._u2

    # Quick health‑check + lazy reconnect for U2 tunnel
    _U2_STALE_CHECK_INTERVAL = 10.0  # seconds between lazy pings in WS mode

    def ensure_u2_healthy(self, ping_timeout: float = 3.0) -> bool:
        u2 = self._u2
        if u2 is not None and self._should_force_u2_relay():
            try:
                from runtime.transports.u2_jsonrpc import _RelaySession

                session = getattr(u2, "_session", None)
                if not isinstance(session, _RelaySession):
                    self._log(
                        "u2 relay available — switching from local atx session to relay proxy",
                        level=logging.INFO,
                    )
                    with self._u2_lock:
                        if self._u2 is u2:
                            self._u2 = None
                    u2 = None
            except Exception:
                pass

        if u2 is None:
            # atx-agent direct mode: device_ip:7912 reachable (local/same-LAN, u2_always_tunnel=False).
            # Cloud/Docker: use _u2_host or IP derived from relay _adb_serial.
            if self._u2_host_hint():
                # Respect backoff even for direct callers (tap/swipe/hierarchy/WS-reconnect).
                # Without this check, concurrent callers bypass the keepalive's backoff guard
                # and hammer _reconnect_u2_atx every few ms → death loop of restart→timeout.
                if self._u2_reconnect_failed_at > 0:
                    since_fail = time.monotonic() - self._u2_reconnect_failed_at
                    if since_fail < self._U2_ATX_RECONNECT_BACKOFF:
                        return False  # still in backoff — caller should skip or retry later
                return self._reconnect_u2()
            # Legacy WS tunnel mode: need tunnel port
            ports = self._tunnel_ports or {}
            if "u2" not in ports or "u2" not in self._tunnels_ready_channels:
                return False
            return self._reconnect_u2()

        # Lazy ping: every _U2_STALE_CHECK_INTERVAL seconds, verify the u2 server is
        # still alive.  Without this, a crashed am-instrument process stays undetected
        # until the next HTTP request times out (up to 15 s), stalling touch events.
        now = time.monotonic()
        if now - self._u2_last_ok_at > self._U2_STALE_CHECK_INTERVAL:
            if not u2.ping(timeout=min(ping_timeout, 4.0)):
                self._log("u2 stale-ping failed — server likely crashed", level=logging.WARNING)
                self._mark_recovery_start("u2_stale_ping_failed")
                with self._u2_lock:
                    if self._u2 is u2:
                        self._u2 = None
                if self._agent_send is not None:
                    self._recover_u2_ws_mode()
                return self._reconnect_u2()
            self._u2_last_ok_at = now

        return True

    _U2_RECONNECT_ATTEMPTS = 3        # was 8 — fewer attempts to reduce tunnel churn on event loop
    _U2_RECONNECT_DELAY = 2.0        # was 1.5 — longer delay between attempts
    _U2_RECONNECT_PROBE_TIMEOUT = 3.0  # give u2 a bit more time to respond on first connect
    _U2_RECONNECT_BACKOFF = 15.0     # was 10 — longer backoff after full failure cycle
    _U2_RECOVERY_COOLDOWN = 15.0  # min seconds between recovery attempts (atx restarts in ~3s)

    # atx-agent specific tuning.
    #
    # "Read timed out" on port 7912 can mean two different things:
    #   A) atx-agent is alive but waiting for u2 to restart (normal, 3-8s)
    #   B) atx-agent goroutine is genuinely frozen (needs kill+restart)
    #
    # We give it ONE second chance (6s wait + retry) to distinguish A from B.
    # Only on the second consecutive timeout do we trigger an atx restart.
    # This prevents killing a healthy atx-agent that is in the middle of
    # restarting u2 — the most common cause of unnecessary "deaths".
    _U2_ATX_RECONNECT_ATTEMPTS = 4    # max retries for "Connection refused" (atx starting up)
    _U2_ATX_RECONNECT_DELAY    = 1.5
    _U2_ATX_PROBE_TIMEOUT      = 4.0  # allow atx/u2 startup after bootstrap (was 1.5s)
    _U2_ATX_TIMEOUT_GRACE      = 6.0  # wait after first timeout — covers u2 restart (3-8s)
    _U2_ATX_RECONNECT_BACKOFF  = 15.0 # backoff after triggering atx restart (was 30s)
    _U2_RESTART_IN_FLIGHT_MAX_S = 65.0 # restart_u2 can wait up to 60s for port 9008

    def _recover_u2_ws_mode(self) -> None:
        """
        WS-mode u2 recovery after keepalive detects dead connection.

        atx-agent path (_u2_host set):
          Restart u2 instrumentation explicitly through agent-boot relay.  A
          killed u2 process can leave atx-agent alive but proxying 502 forever.

        Legacy path (USB / no atx-agent):
          Rate-limited ADB restart: ask APK to reconnect tunnel, and if u2
          process is dead, restart am instrument via ADB.
        """
        if self._should_force_u2_relay():
            # Cloud/relay: WS reconnect only drops the farm-side client; device u2 is still up.
            self._log("u2 recovery: reconnect via relay (skip device restart)", level=logging.INFO)
            self._u2_reconnect_failed_at = 0.0
            threading.Thread(
                target=self._reconnect_u2,
                daemon=True,
                name=f"u2-recover-relay-{self.serial}",
            ).start()
            return

        if self._u2_host:
            # atx-agent path: when u2 instrumentation is killed, atx-agent may
            # stay alive and return 502/timeout forever.  Restart u2 explicitly
            # through agent-boot; fall back to legacy APK start_services only
            # when no relay is available.
            self._log("u2 recovery: triggering relay restart_u2 (atx-agent path)", level=logging.INFO)
            if self._trigger_u2_restart_async(self._u2_host):
                return
            self._request_u2_start_services("recover_atx_fallback")
            return

        # ── Legacy: no atx-agent — ADB restart ───────────────────────────────
        import shutil

        # Protect check-and-update with _u2_lock to prevent two concurrent
        # threads both passing the cooldown guard and spawning duplicate restarts.
        now = time.monotonic()
        with self._u2_lock:
            if now - self._u2_adb_restart_at < self._U2_RECOVERY_COOLDOWN:
                remaining = self._U2_RECOVERY_COOLDOWN - (now - self._u2_adb_restart_at)
                self._log(f"u2 recovery: cooldown {remaining:.0f}s remaining", level=logging.DEBUG)
                return
            self._u2_adb_restart_at = now
        self._request_u2_start_services("recover_legacy")

        # ── Try gRPC relay first (works in cloud, no local adb needed) ──────────
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if relay:
                serial_hint = self._adb_serial or self.serial
                serial = relay.resolve_serial(serial_hint) or serial_hint
                if relay.relay_for_serial(serial) and self._loop:
                    self._log(f"u2 recovery: triggering restart_u2 via gRPC relay ({serial})")
                    fut = asyncio.run_coroutine_threadsafe(
                        relay.restart_u2(serial, timeout=60.0),
                        self._loop,
                    )

                    def _on_relay_done(f: "concurrent.futures.Future") -> None:
                        try:
                            ok = f.result()
                            if ok:
                                self._u2_reconnect_failed_at = 0.0
                                self._log("u2 recovery: relay restart_u2 succeeded")
                            else:
                                self._log("u2 recovery: relay restart_u2 returned not-ok")
                        except Exception as exc2:
                            self._log(f"u2 recovery: relay restart_u2 error: {exc2}")

                    fut.add_done_callback(_on_relay_done)
                    return

                # Relay manager exists but no matching serial is online yet.
                # In cloud/docker mode local ADB inside server container is not a
                # reliable recovery path, so avoid flapping into local fallback.
                self._log(
                    f"u2 recovery: relay present but serial unresolved "
                    f"(hint={serial_hint}, resolved={serial}) — skip local ADB fallback",
                    level=logging.WARNING,
                )
                return
        except Exception as exc:
            # In device_farm deployments, ADB authority is agent-boot.
            # Keep recovery on relay path only to avoid split-brain with local adb.
            self._log(
                f"u2 recovery: relay unavailable ({exc}) — skip local ADB fallback "
                "(agent-boot is required for ADB)",
                level=logging.WARNING,
            )
            return

        adb_bin = shutil.which("adb")
        if adb_bin is None:
            return

        serial = self._adb_serial or self.serial
        try:
            r = subprocess.run(
                [adb_bin, "-s", serial, "shell",
                 f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':{self._u2_probe_port_hex}' | head -1 || true"],
                capture_output=True, text=True, timeout=5,
            )
            process_alive = bool(r.stdout.strip())
        except Exception:
            process_alive = False

        if process_alive:
            self._log(
                f"u2 recovery: process alive on :{self._u2_probe_port} — tunnel reconnect sufficient"
            )
            self._u2_reconnect_failed_at = 0.0
            return

        self._log("u2 recovery: process dead — launching ADB restart in background")

        def _do_restart() -> None:
            _U2_TEST_PKG = "com.github.uiautomator.test"
            _U2_RUNNER   = "androidx.test.runner.AndroidJUnitRunner"
            try:
                subprocess.run(
                    [adb_bin, "-s", serial, "shell", f"am force-stop {_U2_TEST_PKG}"],
                    timeout=10, capture_output=True,
                )
                subprocess.Popen(
                    [adb_bin, "-s", serial, "shell",
                     f"am instrument -w {_U2_TEST_PKG}/{_U2_RUNNER}"
                     " </dev/null >/data/local/tmp/u2.log 2>&1"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._log("u2 recovery: am instrument launched via ADB")
                for _ in range(15):
                    time.sleep(1.0)
                    try:
                        r2 = subprocess.run(
                            [adb_bin, "-s", serial, "shell",
                             f"cat /proc/net/tcp6 /proc/net/tcp 2>/dev/null | grep -i ':{self._u2_probe_port_hex}' | head -1 || true"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if r2.stdout.strip():
                            self._log(
                                f"u2 recovery: :{self._u2_probe_port} ready — reconnecting now"
                            )
                            self._u2_reconnect_failed_at = 0.0
                            self._request_u2_start_services("recover_legacy_after_adb", force=True)
                            # Reconnect immediately instead of waiting for next keepalive cycle
                            self._reconnect_u2()
                            return
                    except Exception:
                        pass
                self._log(
                    f"u2 recovery: :{self._u2_probe_port} not ready after 15s",
                    level=logging.WARNING,
                )
                self._u2_reconnect_failed_at = 0.0
            except Exception as exc:
                self._log(f"u2 recovery: ADB restart error: {exc}", level=logging.WARNING)

        t = threading.Thread(target=_do_restart, daemon=True, name=f"u2-recover-{self.serial}")
        t.start()

    @staticmethod
    def _looks_like_atx_u2_dead_error(exc: Exception) -> bool:
        """True when atx-agent is reachable but its u2 backend is gone."""
        msg = str(exc or "").lower()
        markers = (
            "json-rpc http 502",
            "502 bad gateway",
            "uiautomator not connected",
            "uiautomator not running",
            "uiautomation not connected",
            "instrumentation process is not running",
        )
        return any(marker in msg for marker in markers)

    def _trigger_u2_restart_async(self, host: str) -> bool:
        """Restart only u2 instrumentation via agent-boot relay, deduped."""
        now = time.monotonic()
        if now - self._u2_restart_triggered_at < self._U2_RESTART_IN_FLIGHT_MAX_S:
            self._log("u2 restart skipped — restart_u2 already in flight", level=logging.DEBUG)
            return True
        self._u2_restart_triggered_at = now
        self._u2_reconnect_failed_at = now
        self._u2_batch = None
        with self._u2_lock:
            self._u2 = None

        loop = self._loop
        if not loop:
            self._u2_restart_triggered_at = float("-inf")
            self._log("u2 restart skipped — event loop unavailable", level=logging.WARNING)
            return False
        try:
            from runtime.transports.adb_relay_server import get_relay_manager

            relay = get_relay_manager()
            if not relay:
                self._u2_restart_triggered_at = float("-inf")
                self._log("u2 restart skipped — relay manager unavailable", level=logging.WARNING)
                return False
            actual_serial = self._select_u2_relay_serial(relay, host)
            if not actual_serial:
                self._u2_restart_triggered_at = float("-inf")
                self._log(
                    "u2 restart skipped — no relay for host "
                    f"{host} (adb_serial={self._adb_serial or 'unset'})",
                    level=logging.WARNING,
                )
                return False

            async def _do_restart() -> None:
                try:
                    ok = await relay.restart_u2(actual_serial, timeout=60.0)
                    if ok:
                        self._log(f"u2 restarted via agent-boot for {actual_serial}")
                        self._u2_reconnect_failed_at = 0.0
                        self._u2_restart_triggered_at = float("-inf")
                        self._atx_grace_given_at = float("-inf")
                        self._recovery_log(
                            "u2_started",
                            source="relay_restart_u2",
                            relay_serial=actual_serial,
                            host=host,
                            port=9008,
                        )
                        self._mark_recovery_end("u2_restarted_via_agent_boot", relay_serial=actual_serial)
                    else:
                        self._u2_reconnect_failed_at = time.monotonic()
                        self._log(f"u2 restart via agent-boot failed for {actual_serial}", level=logging.WARNING)
                except Exception as exc2:
                    self._u2_reconnect_failed_at = time.monotonic()
                    self._log(f"u2 restart error for {actual_serial}: {exc2}", level=logging.WARNING)

            asyncio.run_coroutine_threadsafe(_do_restart(), loop)
            return True
        except Exception as exc:
            self._u2_restart_triggered_at = float("-inf")
            self._log(f"_trigger_u2_restart_async: {exc}", level=logging.DEBUG)
            return False

    def _reconnect_u2(self) -> bool:
        """Connect (or reconnect) the u2 client.

        WS mode + atx-agent (_u2_host set): connect directly to device_ip:7912.
          atx-agent auto-manages u2 lifecycle — no tunnel port needed.

        WS mode legacy (USB / no atx-agent): connect via WS tunnel port.

        Serialized: only one thread can attempt reconnect at a time. Multiple
        concurrent callers (eager-connect, keepalive, touch-retry) would each
        open a TCP connection to the u2 WS tunnel, but the tunnel only handles
        one _client_sock — the second connection overwrites the first, causing
        responses to be dropped and triggering a timeout death spiral.
        """
        if not self._u2_reconnect_lock.acquire(blocking=False):
            # Another thread is already reconnecting — wait for it
            with self._u2_reconnect_lock:
                return self._u2 is not None
        try:
            return self._reconnect_u2_impl()
        finally:
            self._u2_reconnect_lock.release()

    def _reconnect_u2_impl(self) -> bool:
        with self._u2_lock:
            if self._u2 is not None:
                return True

        if self._u2_host_hint():
            return self._reconnect_u2_atx()

        # Relay device without host yet — poll caps; never dial WS tunnel (always dead in cloud).
        if self._has_active_relay():
            host = self._resolve_relay_u2_host()
            if host:
                self._u2_host = host
                return self._reconnect_u2_atx()
            self._log(
                "u2 reconnect: relay mapped but wlan_ip not ready — waiting for bind",
                level=logging.DEBUG,
            )
            return False

        # Legacy WS tunnel path — re-read port each attempt: attach_agent_sender
        # can rotate TunnelSet while this loop is sleeping / retrying.
        cfg = self.config.u2

        for attempt in range(1, self._U2_RECONNECT_ATTEMPTS + 1):
            if attempt > 1:
                time.sleep(self._U2_RECONNECT_DELAY)
                with self._u2_lock:
                    if self._u2 is not None:
                        return True

            ports = self._tunnel_ports or {}
            if "u2" not in ports:
                return False
            port = ports["u2"]

            d_rpc: Any = U2JsonRpcClient(
                "127.0.0.1",
                port,
                timeout=cfg.wait_timeout,
                adb_shell=lambda cmd: self.shell_sync(cmd),
            )
            d_rpc.implicitly_wait(cfg.implicitly_wait)
            d_rpc.settings["wait_timeout"] = cfg.wait_timeout
            try:
                d_rpc.verify(timeout=self._U2_RECONNECT_PROBE_TIMEOUT)
                with self._u2_lock:
                    self._u2 = d_rpc
                self._log(f"uiautomator2 JSON-RPC connected on port {port}")
                return True
            except Exception as exc:
                d_rpc._session.close()
                self._log(
                    f"U2 connect attempt {attempt}/{self._U2_RECONNECT_ATTEMPTS} (port {port}): {exc}",
                    level=logging.WARNING,
                )

        self._u2 = None
        self._u2_reconnect_failed_at = time.monotonic()
        self._tunnels_ready_channels.discard("u2")
        self._mark_recovery_start("u2_legacy_reconnect_failed")
        self._log(
            "u2 reconnect failed after full cycle — requesting u2 service restart",
            level=logging.WARNING,
        )
        if self._agent_send is not None:
            self._recover_u2_ws_mode()
        return False

    def _select_u2_relay_serial(self, relay: Any, host: str) -> Optional[str]:
        """Resolve the relay serial for the current U2 host without trusting stale _adb_serial."""
        if relay is None or not host:
            return None

        hints: list[str] = []
        adb_serial = str(self._adb_serial or "")
        if adb_serial:
            hints.append(adb_serial)
        hints.extend([f"{host}:5555", host])

        for hint in dict.fromkeys(hints):
            actual = relay.resolve_serial(hint)
            if relay.relay_for_serial(actual):
                return actual

        return None

    def _reconnect_u2_atx(self) -> bool:
        """Connect to atx-agent HTTP proxy at device_ip:7912.

        atx-agent manages u2 lifecycle on-device — verify() may need several
        retries while atx-agent restarts u2 instrumentation (typically 3–8s).

        Thread safety: re-checks _u2 under lock before each attempt so
        concurrent callers don't create duplicate connections.
        """
        # Snapshot host under no lock — set on WS connect or relay bind.
        # Also derivable from relay _adb_serial (IP:5555) when WS hello raced relay.
        host = self._u2_host_hint()
        if not host:
            return False
        if not self._u2_host:
            self._u2_host = host

        if time.monotonic() - self._u2_restart_triggered_at < self._U2_RESTART_IN_FLIGHT_MAX_S:
            self._log("u2 ATX: restart_u2 in flight — skipping reconnect probe", level=logging.DEBUG)
            return False

        port = 7912
        cfg = self.config.u2

        # Second-chance flag: first "Read timed out" waits for u2 restart instead of
        # immediately killing atx.  The most common "death" scenario is:
        #   u2 crash → _recover_u2_ws_mode() sends start_services → atx starts restarting u2
        #   (3-8s) → we immediately call verify(1.5s) → timeout → wrongly kill healthy atx.
        for attempt in range(1, self._U2_ATX_RECONNECT_ATTEMPTS + 1):
            # Always check under lock first — another thread may have connected.
            with self._u2_lock:
                if self._u2 is not None:
                    return True

            if attempt > 1:
                time.sleep(self._U2_ATX_RECONNECT_DELAY)
                if not self._u2_host_hint():
                    return False
                with self._u2_lock:
                    if self._u2 is not None:
                        return True

            d_rpc: Any = U2JsonRpcClient(
                host,
                port,
                timeout=cfg.wait_timeout,
                adb_shell=lambda cmd: self.shell_sync(cmd),
            )
            d_rpc.implicitly_wait(cfg.implicitly_wait)
            d_rpc.settings["wait_timeout"] = cfg.wait_timeout

            # In relay mode the farm server cannot reach device_ip:7912 directly.
            # Swap the requests.Session for a _RelaySession that proxies calls
            # through the gRPC relay stream (agent-boot → device_ip:7912 locally).
            relay_attached = False
            if self._loop is not None:
                try:
                    from runtime.transports.adb_relay_server import get_relay_manager
                    from runtime.transports.u2_jsonrpc import _RelaySession
                    _rm = get_relay_manager()
                    _actual = self._select_u2_relay_serial(_rm, host)
                    if _rm is not None and _actual:
                        if _actual != self._adb_serial:
                            self._adb_serial = _actual
                        _rs = _RelaySession(_actual, _rm, self._loop)
                        d_rpc._session = _rs
                        relay_attached = True
                        self._log(f"u2 ATX: using relay session for {_actual}")
                except Exception as _e:
                    self._log(f"u2 ATX relay session setup failed: {_e}", level=logging.DEBUG)

            # Force mode: only allow u2 over agent-boot relay.
            # If relay is not attached, skip local direct-HTTP u2 path.
            if self._should_force_u2_relay() and not relay_attached:
                self._log(
                    "u2 ATX: relay-only mode enabled, skipping local u2 session (no relay attached)",
                    level=logging.WARNING,
                )
                d_rpc._session.close()
                self._u2_reconnect_failed_at = time.monotonic()
                return False

            try:
                d_rpc.verify(timeout=self._U2_ATX_PROBE_TIMEOUT)
                with self._u2_lock:
                    if self._u2 is None:
                        self._u2 = d_rpc
                    else:
                        d_rpc._session.close()
                self._u2_reconnect_failed_at = 0.0   # clear backoff on success
                self._atx_grace_given_at = float("-inf")  # reset grace window
                self._log(f"uiautomator2 connected via atx-agent ({host}:{port})")
                self._recovery_log(
                    "u2_started",
                    source="atx_connect",
                    host=host,
                    port=port,
                )
                self._mark_recovery_end("u2_connected_via_atx", host=host, port=port)
                # Set up batch relay session if enabled
                try:
                    from runtime.transports.adb_relay_server import get_relay_manager
                    from runtime.transports.u2_jsonrpc import _BatchRelaySession
                    _rm = get_relay_manager()
                    _actual = self._select_u2_relay_serial(_rm, host)
                    if (
                        self._loop is not None
                        and _rm is not None
                        and _actual
                        and os.getenv("U2_BATCH_ENABLED", "true").lower() in ("1", "true")
                    ):
                        self._u2_batch = _BatchRelaySession(_rm, _actual, self._loop)
                        self._log(f"u2 batch/flow session active for {_actual}")
                    else:
                        self._u2_batch = None
                except Exception as _be:
                    self._u2_batch = None
                    self._log(f"u2 batch session setup skipped: {_be}", level=logging.DEBUG)
                return True
            except Exception as exc:
                d_rpc._session.close()
                exc_str = str(exc)
                self._log(
                    f"atx-agent connect attempt {attempt}/{self._U2_ATX_RECONNECT_ATTEMPTS}"
                    f" ({host}:{port}): {exc}",
                    level=logging.WARNING,
                )
                self._mark_recovery_start("atx_connect_failed")

                if self._looks_like_atx_u2_dead_error(exc):
                    self._log(
                        "u2 ATX proxy reports dead uiautomator — triggering relay restart_u2",
                        level=logging.WARNING,
                    )
                    self._mark_recovery_start("u2_dead_atx_proxy")
                    if self._trigger_u2_restart_async(host):
                        return False

                if "timed out" in exc_str.lower():
                    now = time.monotonic()
                    grace_age = now - self._atx_grace_given_at
                    if grace_age >= self._U2_ATX_TIMEOUT_GRACE + 2.0:
                        # First timeout seen (or previous grace expired long ago).
                        # atx-agent may be busy restarting u2 (3-8s) — do NOT block
                        # the thread pool worker. Record the grace timestamp and return
                        # with a short backoff; the keepalive will call us again after
                        # _U2_ATX_TIMEOUT_GRACE seconds have passed.
                        self._atx_grace_given_at = now
                        grace_backoff = self._U2_ATX_TIMEOUT_GRACE + 1.0
                        self._u2_reconnect_failed_at = now - (self._U2_ATX_RECONNECT_BACKOFF - grace_backoff)
                        self._log(
                            f"atx-agent slow (may be restarting u2) — "
                            f"backing off {grace_backoff:.0f}s, will retry",
                            level=logging.WARNING,
                        )
                        return False
                    else:
                        # Second timeout within grace window: atx is genuinely frozen.
                        self._atx_grace_given_at = float("-inf")  # reset for next cycle
                        self._log("atx-agent frozen (2nd timeout) — triggering relay restart",
                                  level=logging.WARNING)
                        self._trigger_atx_restart_async(host)
                        self._u2_reconnect_failed_at = time.monotonic()
                        return False  # keepalive will retry after backoff + recovery poll

                # "Connection refused" or other: continue retrying (atx may be starting up)

        # All retries exhausted — atx-agent is completely dead (not just frozen).
        # Trigger an async restart via relay so it comes back without manual intervention.
        # _trigger_atx_restart_async has its own 15s dedup guard so calling it here is safe.
        self._trigger_atx_restart_async(host)
        self._u2_reconnect_failed_at = time.monotonic()
        return False

    def _trigger_atx_restart_async(self, host: str) -> None:
        """Kill and restart the atx-agent binary on device via gRPC relay ADB shell.

        Also kills the uiautomator2 instrumentation process — the #1 reason atx-agent
        freezes is u2 getting stuck and blocking atx's HTTP handler.  Restarting atx
        alone leaves the zombie u2 process alive so atx refreezes immediately.

        After sending the restart command, spins up _poll_atx_recovery() which clears
        the backoff as soon as port 7912 accepts a TCP connection (~5-8s), instead of
        waiting the full _U2_ATX_RECONNECT_BACKOFF.
        """
        # Dedup: if a restart was already triggered within 15s, skip.
        # Both _reconnect_u2_atx (on freeze) and watchdog can call this concurrently.
        now = time.monotonic()
        if now - self._atx_restart_triggered_at < 15.0:
            self._log("atx-agent restart skipped — another restart triggered recently", level=logging.DEBUG)
            return
        self._atx_restart_triggered_at = now

        loop = self._loop
        if not loop:
            return
        try:
            from runtime.transports.adb_relay_server import get_relay_manager
            relay = get_relay_manager()
            if not relay:
                self._log("atx-agent restart skipped — relay manager unavailable", level=logging.WARNING)
                return
            actual_serial = self._select_u2_relay_serial(relay, host)
            if not actual_serial:
                self._log(
                    "atx-agent restart skipped — no relay for host "
                    f"{host} (adb_serial={self._adb_serial or 'unset'})",
                    level=logging.WARNING,
                )
                return

            async def _do_restart() -> None:
                try:
                    # Delegate restart entirely to agent-boot: it runs _restart_atx()
                    # locally via ADB (same LAN as device) — polls port 7912, returns
                    # ok=True only when atx is ready.  No raw shell strings on farm side.
                    ok = await relay.restart_atx(actual_serial, timeout=30.0)
                    if ok:
                        self._log(f"atx-agent restarted via agent-boot for {actual_serial}")
                        self._u2_reconnect_failed_at = 0.0
                        self._atx_grace_given_at = float("-inf")
                        self._recovery_log(
                            "atx_started",
                            source="relay_restart",
                            relay_serial=actual_serial,
                            host=host,
                            port=7912,
                        )
                        self._mark_recovery_end("atx_restarted_via_agent_boot", relay_serial=actual_serial)
                    else:
                        if not relay.relay_for_serial(actual_serial):
                            self._log(
                                f"atx-agent restart skipped recovery poll for {actual_serial} "
                                f"— relay disconnected",
                                level=logging.WARNING,
                            )
                            return
                        self._log(
                            f"atx-agent restart via agent-boot failed for {actual_serial} "
                            f"— starting recovery poll",
                            level=logging.WARNING,
                        )
                        threading.Thread(
                            target=self._poll_atx_recovery,
                            args=(host,),
                            daemon=True,
                            name=f"atx-recovery-{self.serial}",
                        ).start()
                except Exception as exc2:
                    self._log(f"atx-agent restart error for {actual_serial}: {exc2}", level=logging.WARNING)

            asyncio.run_coroutine_threadsafe(_do_restart(), loop)
        except Exception as exc:
            self._log(f"_trigger_atx_restart_async: {exc}", level=logging.DEBUG)

    def _poll_atx_recovery(self, host: str, poll_interval: float = 3.0, max_wait: float = 25.0) -> None:
        """Background thread: poll atx-agent after restart, clear backoff when alive.

        Uses HTTP /ping when possible to avoid treating a wedged HTTP handler as
        healthy just because the TCP port accepts. Once the probe succeeds, resets
        _u2_reconnect_failed_at so the
        next ensure_u2_healthy() call immediately attempts reconnect instead of
        waiting the remaining flat backoff.
        """
        # Prefer relay probe in cloud mode (farm cannot reach device_ip:7912 directly).
        # Falls back to direct HTTP for LAN/local deployments.
        def _probe_alive() -> bool:
            loop = self._loop
            if loop:
                try:
                    from runtime.transports.adb_relay_server import get_relay_manager
                    _rm = get_relay_manager()
                    actual = self._select_u2_relay_serial(_rm, host) if _rm else None
                    if _rm and actual:
                        fut = asyncio.run_coroutine_threadsafe(
                            _rm.u2_http(actual, "GET", "/ping", timeout=3.0),
                            loop,
                        )
                        result = fut.result(timeout=8.0)
                        return result.get("ok", False)
                except Exception:
                    pass
            # LAN fallback: direct TCP connect
            try:
                import urllib.request

                with urllib.request.urlopen(f"http://{host}:7912/ping", timeout=2.0) as resp:
                    return 200 <= int(resp.status) < 300
            except Exception:
                return False

        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            if not self._u2_host:
                return  # device disconnected
            if _probe_alive():
                # Port accepted — atx-agent is alive, clear the backoff.
                self._u2_reconnect_failed_at = 0.0
                self._atx_grace_given_at = float("-inf")
                self._log(f"atx-agent recovery: port 7912 live on {host} — backoff cleared")
                self._recovery_log(
                    "atx_started",
                    source="recovery_poll",
                    host=host,
                    port=7912,
                )
                self._mark_recovery_end("atx_port_recovered", host=host, port=7912)
                return
        self._log(f"atx-agent recovery: port 7912 still unreachable on {host} after {max_wait:.0f}s", level=logging.WARNING)

    # ── Frame / Status Broadcasting ───────────────────────────────────────────

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._latest_stream.bind_loop(loop)
        # Push current state/frame so late-connecting frontends get data (e.g. after ADB bootstrap)
        self._publish_status()
        with self._latest_jpeg_lock:
            jpeg = self._latest_jpeg
        if jpeg:
            self.publish_frame(jpeg)

    def subscribe_frames(
        self,
        queue: asyncio.Queue,
        *,
        max_key_age_s: float = 2.0,
    ) -> tuple[Optional[bytes], Optional[bytes]]:
        with self._frame_lock:
            was_empty = len(self._frame_queues) == 0
            bootstrap = self._latest_stream.get_bootstrap(
                max_key_age_s=max_key_age_s
            )
            if queue not in self._frame_queues:
                # Snapshot + subscribe share the producer lock, so no live
                # delta can be queued before the bootstrap generation selected
                # above. WebSocketManager owns sending these cached frames.
                self._frame_queues.append(queue)

        if self._loop:
            # Cancel any pending auto-stop — viewer is back
            if self._scrcpy_stop_task and not self._scrcpy_stop_task.done():
                self._loop.call_soon_threadsafe(self._scrcpy_stop_task.cancel)
                self._scrcpy_stop_task = None

            # Demand-start: restart scrcpy if it was auto-stopped and params are known
            if was_empty and self._scrcpy_receiver is None and self._scrcpy_params:
                params = self._scrcpy_params

                def _start() -> None:
                    try:
                        if len(params) >= 6:
                            self.attach_scrcpy_stream(
                                params[0],
                                params[1],
                                params[2],
                                max_fps=params[3],
                                max_width=params[4],
                                bitrate=params[5],
                            )
                        else:
                            self.attach_scrcpy_stream(*params)
                    except Exception as exc:
                        self._log(
                            f"subscribe demand-start scrcpy failed: {exc}",
                            level=logging.WARNING,
                        )

                self._loop.run_in_executor(None, _start)
        return bootstrap

    def unsubscribe_frames(self, queue: asyncio.Queue) -> None:
        with self._frame_lock:
            self._frame_queues = [q for q in self._frame_queues if q is not queue]
            is_empty = len(self._frame_queues) == 0

        # Auto-stop scrcpy after debounce when no viewers remain — saves device CPU + bandwidth.
        # Tunable via SCRCPY_AUTO_STOP_IDLE_S to avoid manual_stop churn on unstable dashboards.
        if is_empty and self._scrcpy_receiver is not None and self._loop:
            async def _debounced_stop() -> None:
                await asyncio.sleep(SCRCPY_AUTO_STOP_IDLE_S)
                should_detach = False
                reason = "unsubscribe_frames:idle_no_viewers"
                with self._frame_lock:
                    no_viewers = len(self._frame_queues) == 0
                if not no_viewers:
                    return

                _now = time.monotonic()
                if (
                    self._scrcpy_attached_at > 0
                    and (_now - self._scrcpy_attached_at) < SCRCPY_STOP_GRACE_S
                ):
                    _remain = SCRCPY_STOP_GRACE_S - (_now - self._scrcpy_attached_at)
                    self._logger.info(
                        "scrcpy auto-stop skipped (within grace %.1fs < %.1fs)",
                        (_now - self._scrcpy_attached_at),
                        SCRCPY_STOP_GRACE_S,
                    )
                    if _remain > 0:
                        await asyncio.sleep(_remain)
                    with self._frame_lock:
                        should_detach = len(self._frame_queues) == 0
                    reason = "unsubscribe_frames:post_grace_idle"
                    if not should_detach:
                        return
                    self._logger.info(
                        "scrcpy auto-stopped after grace window (%.1fs)",
                        SCRCPY_STOP_GRACE_S,
                    )
                else:
                    should_detach = True
                    self._logger.info(
                        "scrcpy auto-stopped (no viewers for %.1fs)",
                        SCRCPY_AUTO_STOP_IDLE_S,
                    )

                if should_detach:
                    self.detach_scrcpy_stream(reason=reason)

            task = asyncio.run_coroutine_threadsafe(_debounced_stop(), self._loop)
            # Store as a cancellable Future (not asyncio.Task, but cancel() works the same)
            self._scrcpy_stop_task = task  # type: ignore[assignment]

    def subscribe_status(self, queue: asyncio.Queue) -> None:
        with self._status_lock:
            if queue not in self._status_queues:
                self._status_queues.append(queue)

    def unsubscribe_status(self, queue: asyncio.Queue) -> None:
        with self._status_lock:
            self._status_queues = [q for q in self._status_queues if q is not queue]

    def publish_frame(self, jpeg_bytes: bytes) -> None:
        if not self._loop:
            return
        fanout_started = time.perf_counter()
        if LOW_BW_MODE:
            self._frame_seq += 1
            if self._frame_seq % LOW_BW_FRAME_SKIP != 0:
                return
        # Binary frame protocol: [0x01][serial_len:1B][serial:NB][w:2B BE][h:2B BE][jpeg]
        w = max(0, min(self.screen_width, 0xFFFF))
        h = max(0, min(self.screen_height, 0xFFFF))
        msg: bytes = (
            bytes([0x01, len(self._serial_b)]) + self._serial_b
            + struct.pack(">HH", w, h)
            + jpeg_bytes
        )
        with self._frame_lock:
            self._latest_stream.set_frame(msg, is_key=False)
            queues = list(self._frame_queues)
        loop = self._loop
        for q in queues:
            # call_soon_threadsafe is cheaper than run_coroutine_threadsafe:
            # no Future/Task allocation, just schedules a callback directly.
            loop.call_soon_threadsafe(_sync_put, q, msg)
        stream_telemetry.record_fanout(
            subscribers=len(queues),
            frame_bytes=len(msg),
            elapsed_ms=(time.perf_counter() - fanout_started) * 1000.0,
        )

    async def wait_for_stream_update(self, last_version: int) -> None:
        await self._latest_stream.wait_for_update(last_version)

    def get_stream_snapshot(self) -> tuple[Optional[bytes], int, float, bool]:
        return self._latest_stream.get_snapshot()

    def get_stream_bootstrap(self, *, max_key_age_s: float = 2.0) -> tuple[Optional[bytes], Optional[bytes]]:
        return self._latest_stream.get_bootstrap(max_key_age_s=max_key_age_s)

    def _publish_status(self) -> None:
        if not self._loop:
            return
        msg = self.status_dict()
        msg["type"] = "status"
        with self._status_lock:
            queues = list(self._status_queues)
        for q in queues:
            asyncio.run_coroutine_threadsafe(_safe_put(q, msg), self._loop)

    def status_dict(self) -> Dict[str, Any]:
        u2_ok = self._u2 is not None
        agent_ok = self._agent_send is not None
        if u2_ok:
            touch_method = "u2"
        else:
            touch_method = "agent_shell" if agent_ok else "none"

        # Report the state a client should act on, not the raw watchdog label.
        # The watchdog can leave a device DEAD after a transient stall, but if
        # u2 (or the agent shell) is answering the device is fully controllable
        # — verified: a DEAD-labelled emulator ran a scenario to completion.
        # /api/devices/live already corrects this via _apply_realtime_connectivity;
        # the WS status feed did not, so the control/record dropdown filtered
        # these alive devices out (its predicate rejects state==DEAD outright).
        # This keeps the WS feed consistent with the HTTP view. Only the report
        # is adjusted; the internal state machine is untouched.
        reported_state = self.state.value
        if self.state == DeviceState.DEAD and (u2_ok or agent_ok):
            reported_state = DeviceState.READY.value
        try:
            from services.manual_takeover import is_manual_takeover_local

            manual_takeover_active = is_manual_takeover_local(self.serial)
        except Exception:
            manual_takeover_active = False
        return {
            "type":             "status",
            "serial":           self.serial,
            "brand":            self.brand,
            "model":            self.model,
            "android":          self.android_version,
            "sdk":              self.sdk_version,
            "state":            reported_state,
            "battery":          self.battery_level,
            "battery_status":   self.battery_status,
            "battery_source":   self.battery_source,
            "battery_temp":     self.battery_temp,
            "wifi_connected":   self.wifi_connected,
            "network_type":     self.network_type,
            "network_subtype":  self.network_subtype,
            "airplane_mode":    self.airplane_mode,
            "current_app":      self.current_app,
            "screen_width":     self.screen_width,
            "screen_height":    self.screen_height,
            "agent_connected":  agent_ok,
            "u2_ready":         u2_ok,
            "touch_method":     touch_method,
            "stf_connected":    self._stf_service is not None and self._stf_service.connected,
            "scenario_active":  int(getattr(self, "_scenario_active", 0) or 0),
            "manual_takeover_active": manual_takeover_active,
        }

    def get_log_lines(self) -> List[str]:
        with self._log_lock:
            return list(self._log_lines)

    # ── Internal: Tool Setup / Teardown ──────────────────────────────────────

    def _setup_tools(self) -> None:
        """
        Connect STFService (and, historically, uiautomator2) via tunnel ports.
        Runs in a background thread, does NOT block the WebSocket loop.
        """
        ports = self._tunnel_ports
        cfg   = self.config.u2
        ready = self._tunnels_ready_channels
        w = self.screen_width or 1080
        h = self.screen_height or 1920
        # inputMgr = agent uses InputManager.injectMotionEvent() internally.
        # On Android 14+ (SDK≥34) this requires INJECT_EVENTS (system-only permission)
        # and silently fails on regular APKs — use U2 (accessibility-based) instead.
        input_mgr_mode = self._agent_touch_mode in ("inputMgr",)
        force_u2 = bool(getattr(self.config, "force_u2_mode", False))
        if force_u2:
            self._log("force_u2_mode: touch via U2", level=logging.INFO)
        elif input_mgr_mode:
            self._log("touch=inputMgr: using U2", level=logging.INFO)

        # Connect U2 eagerly so first tap has no latency.
        # Skip when relay u2 survived WS reconnect — reconnect would race a live session.
        # Skip WS-tunnel eager connect when relay owns u2 (bind_relay_u2 already started).
        _skip_u2_eager = False
        with self._u2_lock:
            if self._u2 is not None and self._u2_session_uses_relay(self._u2):
                _skip_u2_eager = True
        if self._has_active_relay() and not self._u2_host_hint():
            _skip_u2_eager = True
        if not _skip_u2_eager:
            threading.Thread(
                target=self._reconnect_u2,
                daemon=True,
                name=f"u2-eager-{self.serial}",
            ).start()

        # ── STFService ────────────────────────────────────────────────────────
        try:
            def _on_battery(level: int) -> None:
                svc = self._stf_service
                if svc:
                    info = svc.get_battery_info()
                    self.battery_level = info.level
                    self.battery_status = info.status
                    self.battery_source = info.source
                    self.battery_temp = info.temp
                else:
                    self.battery_level = level
                self._publish_status()

            def _on_rotation(degrees: int) -> None:
                self._log(f"Rotation: {degrees}°")
                self._publish_status()

            def _on_connectivity(info: ConnectivityInfo) -> None:
                self.wifi_connected = info.connected and info.type == "wifi"
                self.network_type = info.type
                self.network_subtype = info.subtype
                self._publish_status()

            def _on_airplane(enabled: bool) -> None:
                self.airplane_mode = enabled
                self._publish_status()

            def _on_stf_stream_error(exc: Exception) -> None:
                """
                Auto-heal when STF socket keeps refusing connections.
                App UI may still be visible while the background socket server is down.
                """
                if self._agent_send is None:
                    return
                msg = str(exc or "")
                is_refused = (
                    "Connection refused" in msg
                    or "Errno 61" in msg
                    or isinstance(exc, ConnectionRefusedError)
                )
                if not is_refused:
                    return
                now = time.monotonic()
                last = float(getattr(self, "_stf_heal_requested_at", 0.0) or 0.0)
                if (now - last) < 20.0:
                    return
                self._log("STFService socket refused — requesting WsAgentService restart", level=logging.WARNING)
                try:
                    self._send_to_agent({
                        "type": "shell",
                        "cmd": "am start-foreground-service -n jp.co.cyberagent.stf/.WsAgentService -a jp.co.cyberagent.stf.ws.START",
                    })
                    setattr(self, "_stf_heal_requested_at", now)
                except Exception as shell_exc:
                    self._log(f"STFService auto-heal shell request failed: {shell_exc}", level=logging.WARNING)

            svc = STFServiceClient(
                serial=self.serial,
                host="127.0.0.1",
                port=ports["stfservice"],
                on_battery=_on_battery,
                on_rotation=_on_rotation,
                on_connectivity=_on_connectivity,
                on_airplane=_on_airplane,
                on_stream_error=_on_stf_stream_error,
            )
            svc.start_client()
            self._stf_service = svc
            self._log("STFService connected via WS tunnel (full events)")
        except Exception as exc:
            self._log(f"STFService tunnel unavailable: {exc}",
                      level=logging.WARNING)

        self.state = DeviceState.READY
        # U2 eager-connect thread (line ~2964) is already running — don't call
        # ensure_u2_healthy() here too, as both would race to open TCP connections
        # to the u2 WS tunnel simultaneously, causing the tunnel to drop responses.
        if self._u2 is not None:
            touch_status = "u2"
        elif self._get_scrcpy_control() is not None:
            touch_status = "scrcpy_control"
        else:
            touch_status = "agent_shell"
        self._log("Device READY (touch=%s u2=%s stfservice=%s)" % (
            touch_status,
            "yes" if self._u2 else "no",
            "yes" if self._stf_service else "no",
        ))

    def _u2_keepalive_loop(self, generation: int = 0) -> None:
        """Ping uiautomator2 every 5 s to keep HTTP connection alive.

        The uiautomator2 server (port 9008) closes the TCP connection after each
        HTTP response. The Android ServiceTunnel auto-reconnects within ~50ms.
        During that reconnect window, a ping here would fail. We tolerate up to
        4 consecutive misses before declaring u2 dead, so transient reconnects
        don't cascade into a full u2 teardown.

        When u2 is None:
          - Respects a 30s backoff after a full failed reconnect cycle.
          - In WS mode: sends start_services to ask agent to (re)start u2 on device.
        """
        _INTERVAL = max(5.0, float(os.environ.get("U2_KEEPALIVE_INTERVAL", "10.0")))
        _PING_TIMEOUT = 3.0   # atx-agent (Go HTTP) responds fast; 3s is enough
        _MAX_MISSES = 3  # ~30s of misses before declaring dead
        misses = 0

        def _is_alive() -> bool:
            return self._agent_send is not None or self.state in (DeviceState.READY, DeviceState.BUSY)

        while _is_alive():
            time.sleep(_INTERVAL)
            if not _is_alive():
                return
            if generation and generation != getattr(self, "_u2_keepalive_gen", 0):
                return
            if self.state == DeviceState.BUSY:
                misses = 0  # reset: task is using u2, not idle
                continue

            with self._u2_lock:
                u2 = self._u2
            if u2 is None:
                if self.state == DeviceState.READY:
                    now = time.monotonic()
                    since_fail = now - self._u2_reconnect_failed_at
                    # atx-agent path uses a longer backoff (relay restart takes ~5-10s)
                    backoff = self._U2_ATX_RECONNECT_BACKOFF if self._u2_host_hint() else self._U2_RECONNECT_BACKOFF
                    if since_fail < backoff:
                        # Back off: avoid hammering u2 reconnect every 5s after a
                        # full failed cycle.  The agent may need time to restart
                        # the am-instrument process on device.
                        self._log(
                            f"u2 keepalive: backoff {backoff - since_fail:.0f}s remaining",
                            level=logging.DEBUG,
                        )
                    else:
                        if self._should_force_u2_relay():
                            self.ensure_u2_healthy()
                        else:
                            if self._agent_send is not None:
                                self._recover_u2_ws_mode()
                            self.ensure_u2_healthy()
                misses = 0
                continue

            try:
                ok = u2.ping(timeout=_PING_TIMEOUT)
            except Exception as exc:
                ok = False
                self._log(f"u2 keep-alive ping error: {exc}", level=logging.DEBUG)

            if ok:
                misses = 0
                self._u2_last_ok_at = time.monotonic()
            else:
                misses += 1
                if misses < _MAX_MISSES:
                    self._log(f"u2 keep-alive: ping miss {misses}/{_MAX_MISSES} (tunnel reconnecting?)",
                              level=logging.DEBUG)
                else:
                    self._log("u2 keep-alive: connection dead — attempting reconnect",
                              level=logging.WARNING)
                    with self._u2_lock:
                        if self._u2 is u2:
                            self._u2 = None
                    misses = 0
                    if self._should_force_u2_relay():
                        self.ensure_u2_healthy()
                    else:
                        if self._agent_send is not None:
                            self._recover_u2_ws_mode()
                        self.ensure_u2_healthy()

    def _teardown_tools(self, stop_scrcpy: bool = True) -> None:
        if self._stf_service:
            try: self._stf_service.stop_client()
            except Exception: pass
            self._stf_service = None
        self._u2 = None
        if stop_scrcpy:
            self.detach_scrcpy_stream(reason="_teardown_tools")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _send_to_agent(self, msg: Dict[str, Any]) -> None:
        msg["serial"] = self.serial
        send = self._agent_send
        if send is None:
            self._log(f"Drop cmd {msg['type']}: no agent", level=logging.WARNING)
            return
        try:
            send(msg)
        except Exception as exc:
            self._log(f"Agent send error: {exc}", level=logging.WARNING)

    def _log(self, msg: str, level: int = logging.INFO) -> None:
        line = f"[{self.serial}] {msg}"
        self._logger.log(level, line)
        with self._log_lock:
            self._log_lines.append(line)
            if len(self._log_lines) > 50:
                self._log_lines = self._log_lines[-50:]
        if self._loop:
            log_msg = {"type": "log", "serial": self.serial, "line": line}
            with self._status_lock:
                queues = list(self._status_queues)
            for q in queues:
                asyncio.run_coroutine_threadsafe(_safe_put(q, log_msg), self._loop)

    def _record_state_event(self, old: DeviceState, new: DeviceState) -> None:
        """Record a state-change event via EventRecorder (if injected).

        Only records events meaningful to the user:
        - connected / reconnected / error
        Skips:
        - DISCONNECTED (handled by on_agent_disconnected with reason)
        - DEAD (handled by watchdog with explicit reason — avoids duplicate)
        - Internal transitions (DISCONNECTED→CONNECTING, etc.) — noise for users
        """
        if not self._event_recorder:
            return
        # on_agent_disconnected already records "disconnected" with reason
        if new == DeviceState.DISCONNECTED:
            return
        # watchdog records "dead" with explicit reason (duration info)
        if new == DeviceState.DEAD:
            return

        if new == DeviceState.READY and old in (DeviceState.DISCONNECTED, DeviceState.CONNECTING):
            event_type = "connected"
        elif new == DeviceState.READY and old in (DeviceState.ERROR, DeviceState.DEAD):
            event_type = "reconnected"
        elif new == DeviceState.ERROR:
            event_type = "error"
        else:
            # Skip internal transitions (DISCONNECTED→CONNECTING, BUSY→READY, etc.)
            return

        self._event_recorder.record(
            serial=self.serial,
            event=event_type,
            old_state=old.value,
            new_state=new.value,
            device_model=self.model,
            device_brand=self.brand,
        )


def _is_droppable_frame(item: Any) -> bool:
    """Return True if item is a P-frame (not config, not keyframe) — safe to drop."""
    if not isinstance(item, (bytes, bytearray)):
        return False
    if len(item) < 2:
        return False
    ft = item[0]
    if ft == 0x10:
        return False  # SPS/PPS config — never drop
    if ft == 0x11:
        slen = item[1]
        key_off = 2 + slen + 4  # [type][slen][serial:slen][w:2][h:2] then is_key byte
        if len(item) > key_off:
            return item[key_off] == 0  # is_key == 0 → P-frame → droppable
        return False
    return False  # JPEG (0x01) or unknown — keep


def _sync_put(queue: asyncio.Queue, item: Any) -> None:
    """Keyframe-aware queue put — must be called from the event loop thread.

    Priority:
      - SPS/PPS config (0x10) and IDR keyframes (0x11 is_key=1): always deliver;
        evict oldest item if queue is full.
      - P-frames (0x11 is_key=0): drop silently when queue is full. A dropped
        P-frame is undecodable without a preceding IDR anyway — jmuxer will stall
        until the next keyframe, which is the correct recovery path.
      - JSON status/log: evict oldest to make room.
    """
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        if _is_droppable_frame(item):
            return  # silently drop P-frame — wait for next IDR
        # Config, keyframe, or JSON: evict oldest to make room
        try:
            queue.get_nowait()
            queue.put_nowait(item)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass


async def _safe_put(queue: asyncio.Queue, item: Any) -> None:
    _sync_put(queue, item)
