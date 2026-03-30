"""
device_client.py — DeviceClient: per-device abstraction.

Supports two connection modes:

MODE A — WebSocket Agent (existing):
  Android Agent APK  ←→  WebSocket  ←→  Server
  Screen  : MediaProjection → H.264/JPEG → WS → server
  Touch   : MinitouchWsClient → tunnel_data WS → Agent, or U2JsonRpcClient via TcpWsTunnel (9008)
  Events  : STFServiceClient via TcpWsTunnel

MODE B — ADB Transport:
  Farm Server ─── adb TCP ──► device:5555  (shell, push)
  Farm Server ◄── scrcpy (H264→JPEG)       (screen frames)
  Farm Server ◄── TCP:9008   u2-server, minitouch (touch / UI)
  Farm Server ─── poll via shell ── battery / rotation
  No STFService needed, no WS agent needed, no port forwarding.

  Activated via: device.attach_adb_transport(transport)
  Requires Android 11+ Wireless Debugging (or adb tcpip 5555 once via USB).

Touch: minitouch (WS/ADB) or uiautomator2 (U2). No a11y.
State: DISCONNECTED → CONNECTING → READY → BUSY → ERROR → DEAD
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import struct
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import re
import xml.etree.ElementTree as ET

from core.config import Config
from runtime.transports.adb_device_bootstrap import AdbDeviceBootstrap
from runtime.transports.adb_transport import AdbTransport
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


class DeviceClient:
    """
    Server-side proxy for one Android device connected via WebSocket agent.

    Screen frames arrive as JPEG via WebSocket (MediaProjection on device).
    Touch: minitouch or u2 over WebSocket tunnels. Key/pinch: WS → agent.
    """

    def __init__(self, serial: str, index: int, config: Config) -> None:
        self.serial  = serial
        self.index   = index
        self.config  = config

        self._logger = logging.getLogger(f"device.{serial}")
        self._lock   = threading.Lock()
        self._state  = DeviceState.DISCONNECTED

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

        # Scrcpy receiver for Mode A+scrcpy hybrid (agent touch + scrcpy screen)
        self._scrcpy_receiver:  Optional[ScrcpyReceiver] = None
        self._scrcpy_active:    bool = False  # suppress MediaProjection frames when True

        # WebSocket send callback (set when agent connects)
        self._agent_send: Optional[Callable[[Dict[str, Any]], None]] = None

        # Frame sequence counter for optional low-bandwidth throttling
        self._frame_seq: int = 0

        # TCP-over-WebSocket tunnels (minitouch / u2 / stfservice)
        self._tunnels: Optional[TunnelSet] = None
        self._tunnel_ports: Dict[str, int] = {}
        self._tunnels_ready_channels: set = set()  # channels device actually set up (from tunnels_ready)

        # Minitouch support disabled.
        self._minitouch = None
        self._u2:          Optional[U2JsonRpcClient]  = None
        self._u2_lock      = threading.Lock()  # serializes reconnect + identity-safe nulling
        self._u2_request_lock = threading.Lock()  # serializes ALL u2 HTTP requests (NanoHTTPD is single-threaded)
        self._hierarchy_lock = threading.Lock()  # only one dumpWindowHierarchy at a time
        self._stf_service: Optional[STFServiceClient] = None

        # ADB mode (Mode B) state
        self._adb_transport: Optional[AdbTransport] = None
        self._adb_bootstrap: Optional[AdbDeviceBootstrap] = None
        self.is_adb_mode: bool = False

        # asyncio event loop + subscriber queues
        self._loop:           Optional[asyncio.AbstractEventLoop] = None
        self._frame_queues:   List[asyncio.Queue] = []
        self._frame_lock      = threading.Lock()
        self._last_key_frame: Optional[Union[Dict[str, Any], bytes]] = None  # last H.264 key frame for new subscribers
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

        # Reconnect tracking
        self.reconnect_attempts: int = 0
        # Periodic screenshot timer state
        self._periodic_ss_started: bool = False
        # Agent-reported capabilities (e.g. ["u2","stfservice","h264","minitouch"])
        self._agent_capabilities: List[str] = []
        # Touch mode parsed from agent log: "a11y" | "inputMgr" | "NONE" | ""
        self._agent_touch_mode: str = ""
        # open_url: wait for agent to send open_url_result before marking step done
        self._open_url_result_event = threading.Event()
        self._open_url_result: Optional[Tuple[bool, str]] = None  # (success, error_msg)
        # WS hierarchy dump: synchronous wait for async WS response
        self._ws_hierarchy_event = threading.Event()
        self._ws_hierarchy_xml: Optional[str] = None
        self._ws_hierarchy_error: Optional[str] = None
        self._ws_hierarchy_a11y_available: bool = True  # optimistic, disabled on first "accessibility_not_available"

    def set_agent_capabilities(self, caps: List[str]) -> None:
        """Set capabilities from agent hello; server only tries minitouch when \"minitouch\" in caps."""
        self._agent_capabilities = list(caps) if caps else []

    def set_agent_touch_mode(self, mode: str) -> None:
        """Set touch mode from agent hello (touch_mode in payload). Enables minitouch setup before tunnels_ready."""
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
            # Auto-start periodic screenshot timer when device becomes READY
            if new == DeviceState.READY and not self._periodic_ss_started:
                if self.config.streaming.mode == "periodic":
                    self._periodic_ss_started = True
                    self.start_periodic_screenshot()

    # ── Agent Lifecycle ───────────────────────────────────────────────────────

    def attach_agent_sender(self, send: Callable[[Dict[str, Any]], None]) -> TunnelSet:
        """
        Called when the Android agent WebSocket connects.
        Creates WS tunnels for minitouch, u2, stfservice.
        Returns TunnelSet so the session can route tunnel_data messages back.
        """
        self._ws_hierarchy_a11y_available = True  # retry a11y on each new connection
        self._agent_send = send
        tunnels = TunnelSet(send, self.serial)
        ports   = tunnels.start_all()
        self._tunnels      = tunnels
        self._tunnel_ports = ports
        self._log(
            f"Agent connected. Tunnels: "
            + " ".join(f"{ch}={ports[ch]}" for ch in ("u2", "stfservice", "minitouch") if ch in ports)
        )
        return tunnels

    def on_agent_ready(self, ready_channels: Optional[set] = None) -> None:
        """
        Called after agent sends tunnels_ready. ready_channels = set of channel names
        the agent actually connected (e.g. {"minitouch", "stfservice"} when u2 is missing).

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
            ka = threading.Thread(
                target=self._u2_keepalive_loop,
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

    def on_agent_disconnected(self) -> None:
        self._agent_send = None
        self._tunnels_ready_channels = set()
        self._teardown_tools()
        if self._tunnels:
            self._tunnels.stop_all()
            self._tunnels = None
        # Clear cached frame so frontend doesn't see stale preview
        with self._latest_jpeg_lock:
            self._latest_jpeg = None
        self._last_key_frame = None
        if self.state != DeviceState.DEAD:
            self.state = DeviceState.DISCONNECTED

    def route_tunnel_data(self, channel: str, b64_data: str) -> None:
        """Route tunnel_data message from agent to the correct local TCP socket."""
        if self._tunnels:
            self._tunnels.route(channel, b64_data)


    def on_agent_frame_b64(self, jpeg_b64: str) -> None:
        """Receive JPEG frame from agent (MediaProjection). Skipped when scrcpy is active."""
        if self._scrcpy_active:
            return
        jpeg = base64.b64decode(jpeg_b64)
        with self._latest_jpeg_lock:
            self._latest_jpeg = jpeg
            self._last_frame_time = time.monotonic()
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
        if self._scrcpy_active:
            return
        with self._latest_jpeg_lock:
            self._latest_jpeg = jpeg_bytes
        # In periodic mode, only update cache
        if self.config.streaming.mode == "periodic":
            return
        self.publish_frame(jpeg_bytes)

    def on_agent_h264_config(self, avcc_record: bytes, w: int, h: int) -> None:
        """Relay H264 AVCDecoderConfigurationRecord to browser as binary 0x10 frame.
        Called when agent sends h264_config message (SPS+PPS codec config).
        """
        if self.config.streaming.mode == "periodic":
            return
        if not self._loop:
            return
        serial_b = self.serial.encode()
        slen = len(serial_b)
        width = max(0, min(w or self.screen_width, 0xFFFF))
        height = max(0, min(h or self.screen_height, 0xFFFF))
        msg: bytes = bytes([0x10, slen]) + serial_b + struct.pack(">HH", width, height) + avcc_record
        with self._frame_lock:
            queues = list(self._frame_queues)
        for q in queues:
            asyncio.run_coroutine_threadsafe(_safe_put(q, msg), self._loop)

    def on_agent_h264_video(self, avcc_data: bytes, is_key: bool, pts_us: int) -> None:
        """Relay H264 AVCC video frame to browser as binary 0x11 frame.
        Called when agent sends h264_frame message.
        """
        if not self._loop:
            return
        serial_b = self.serial.encode()
        slen = len(serial_b)
        w = max(0, min(self.screen_width, 0xFFFF))
        h = max(0, min(self.screen_height, 0xFFFF))
        pts_hi = (pts_us >> 32) & 0xFFFFFFFF
        pts_lo = pts_us & 0xFFFFFFFF
        header = bytes([0x11, slen]) + serial_b + struct.pack(">HH", w, h)
        meta = bytes([1 if is_key else 0]) + struct.pack(">II", pts_hi, pts_lo)
        msg = header + meta + avcc_data
        if is_key:
            # Store for late-joining subscribers (replaces _last_key_frame dict)
            self._last_key_frame = msg
        with self._frame_lock:
            queues = list(self._frame_queues)
        for q in queues:
            asyncio.run_coroutine_threadsafe(_safe_put(q, msg), self._loop)

    def on_agent_status(self, payload: Dict[str, Any]) -> None:
        self.brand           = payload.get("brand",         self.brand)
        self.model           = payload.get("model",         self.model)
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
        Tear down all transport connections (scrcpy, minitouch, u2, tunnels, ADB bootstrap)
        without changing device state. Used before re-bootstrap.
        """
        self._teardown_tools()
        if self._tunnels:
            try:
                self._tunnels.stop_all()
            except Exception:
                pass
            self._tunnels = None
        if self._adb_bootstrap is not None:
            try:
                self._adb_bootstrap.stop()
            except Exception:
                pass
            self._adb_bootstrap = None
        # Clear stale frame cache
        with self._latest_jpeg_lock:
            self._latest_jpeg = None
        self._last_key_frame = None
        # Don't close ADB transport here — reconnect_adb_device handles that

    def teardown(self) -> None:
        # Agent (WS) teardown
        self._agent_send = None
        self._teardown_tools()
        if self._tunnels:
            self._tunnels.stop_all()
            self._tunnels = None

        # ADB mode teardown
        if self._adb_bootstrap is not None:
            try:
                self._adb_bootstrap.stop()
            except Exception:
                pass
            self._adb_bootstrap = None
        if self._adb_transport is not None:
            try:
                self._adb_transport.close()
            except Exception:
                pass
            self._adb_transport = None
        self.is_adb_mode = False

        self.state = DeviceState.DISCONNECTED

    # ── Screenshot ────────────────────────────────────────────────────────────

    def take_screenshot(self) -> Optional[bytes]:
        """Return latest JPEG frame (from agent MediaProjection or ADB scrcpy). Non-blocking."""
        with self._latest_jpeg_lock:
            return self._latest_jpeg

    def capture_screenshot(
        self,
        quality: int = 70,
        max_width: int = 800,
        allow_ws_u2_fallback: bool = False,
    ) -> Optional[bytes]:
        """
        On-demand screenshot with fallback chain:
          1. Cached _latest_jpeg (from scrcpy or agent frame stream) — always preferred
          2. U2 HTTP /screenshot/0 (ADB mode only — avoids tunnel contention in agent mode)
          3. ADB shell screencap (ADB mode only)
        Updates _latest_jpeg with the result.

        IMPORTANT: When scrcpy is active, ONLY return cached frame. U2 screenshot
        requests hammer the WS tunnel and starve scrcpy bandwidth.
        """
        jpeg = None

        # When scrcpy is active OR WS agent mode: always use cached frame.
        # U2 screenshot through WS tunnel causes massive tunnel thrashing that
        # kills scrcpy FPS (drops from 30fps to 1fps).
        if self._scrcpy_active or not self.is_adb_mode:
            with self._latest_jpeg_lock:
                jpeg = self._latest_jpeg
            if jpeg is not None:
                return jpeg

        # ADB mode: always try U2 screenshot.
        # WS mode: only try when explicitly allowed (for infrequent snapshot APIs).
        use_u2 = self.is_adb_mode or allow_ws_u2_fallback
        if use_u2:
            with self._u2_lock:
                u2 = self._u2
            if u2 is not None:
                try:
                    jpeg = u2.screenshot(timeout=5.0, max_width=max_width, quality=quality)
                except Exception as exc:
                    self._log(f"capture_screenshot u2 error: {exc}", level=logging.DEBUG)

        # Fallback: ADB shell screencap
        if jpeg is None and self._adb_transport is not None and self._adb_transport.connected:
            try:
                png_data = self._adb_transport.shell("screencap -p", timeout=10.0)
                if png_data:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(png_data.encode("latin-1") if isinstance(png_data, str) else png_data))
                    w, h = img.size
                    if max_width > 0 and w > max_width:
                        ratio = max_width / w
                        img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=quality)
                    jpeg = buf.getvalue()
            except Exception as exc:
                self._log(f"capture_screenshot adb error: {exc}", level=logging.DEBUG)

        # Fallback: cached frame
        if jpeg is None:
            with self._latest_jpeg_lock:
                jpeg = self._latest_jpeg

        # Update cache
        if jpeg is not None:
            with self._latest_jpeg_lock:
                self._latest_jpeg = jpeg

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
        # If u2 not ready yet, wait briefly (tunnels may still be setting up)
        if self._u2 is None and self.state in (DeviceState.READY, DeviceState.CONNECTING):
            for _ in range(5):
                time.sleep(0.5)
                if self._u2 is not None:
                    break
        if not self.ensure_u2_healthy() or self._u2 is None:
            return False
        # Serialize with all u2 operations (NanoHTTPD is single-threaded)
        with self._u2_request_lock:
            return self._try_u2_tap_impl(action)

    def _try_u2_tap_impl(self, action: "Callable[[], None]") -> bool:
        u2_snap = self._u2
        try:
            action()
            return True
        except Exception as exc:
            self._log(f"u2 touch failed: {exc}", level=logging.WARNING)
            with self._u2_lock:
                if self._u2 is u2_snap:
                    self._u2 = None
        # Reconnect u2 and retry once — mirrors uiautomator2 jsonrpc_call pattern:
        # stop_uiautomator() + start_uiautomator() + retry in the same call.
        reconnected = (
            self._wait_for_u2_restart(timeout=25.0)
            if self.is_adb_mode
            else self._reconnect_u2()
        )
        if not reconnected or self._u2 is None:
            return False
        try:
            action()
            return True
        except Exception as exc:
            self._log(f"u2 touch retry failed: {exc}", level=logging.WARNING)
            self._u2 = None
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

    def tap(self, x: int, y: int) -> None:
        """
        Touch priority: U2 → Agent shell (a11y fallback)
        When U2 is down, agent `input tap` provides immediate fallback.
        U2 keepalive loop will reconnect U2 in background.
        """
        if self._try_u2_tap(lambda: self._u2.click(x, y) if self._u2 else None):
            return
        # Fallback: agent shell `input tap` (works without U2, uses a11y/InputManager)
        if self._agent_send is not None:
            self._send_to_agent({"type": "shell", "cmd": f"input tap {int(x)} {int(y)}"})
            return
        self._log(f"tap skipped (no touch method)", level=logging.WARNING)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """Touch priority: U2 → Agent shell"""
        if self._try_u2_tap(lambda: self._u2.swipe(x1, y1, x2, y2, duration=duration_ms / 1000.0) if self._u2 else None):
            return
        if self._agent_send is not None:
            self._send_to_agent({
                "type": "shell",
                "cmd": f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
            })
            return
        self._log("swipe skipped (no touch method available)", level=logging.WARNING)

    def long_tap(self, x: int, y: int, duration_ms: int = 800) -> None:
        """Touch priority: U2 → Agent shell (swipe with 0 distance = long press)"""
        if self._try_u2_tap(lambda: self._u2.long_click(x, y, duration=duration_ms / 1000.0) if self._u2 else None):
            return
        if self._agent_send is not None:
            self._send_to_agent({
                "type": "shell",
                "cmd": f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}",
            })
            return
        self._log("long_tap skipped (no touch method available)", level=logging.WARNING)

    def input_text(self, text: str) -> None:
        """Type text into currently focused element."""
        # scrcpy control first: injects text at system level.
        ctrl = self._get_scrcpy_control()
        if ctrl is not None:
            try:
                ctrl.input_text(text)
                return
            except Exception as exc:
                self._log(f"input_text via scrcpy control failed: {exc}", level=logging.WARNING)
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.send_keys(text)
                return
            except Exception as exc:
                self._log(f"input_text via u2 failed: {exc}", level=logging.WARNING)
        # Fallback: use APK "type" message which calls injectText() (handles special chars via a11y/clipboard)
        self._send_to_agent({"type": "type", "text": text})

    def scroll(self, direction: str = "down", distance: float = 0.5) -> None:
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
        self.swipe(x1, y1, x2, y2, duration_ms=400)

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

    def key(self, key_name: str) -> None:
        """
        Key press (home, back, power, enter).

        Priority:
        1. scrcpy control (system-level, smoothest)
        2. uiautomator2 (no INJECT_EVENTS needed)
        3. Agent WS shell
        4. ADB shell
        """
        k = (key_name or "").strip()
        if not k:
            return

        key_l = k.lower()

        # Best path: scrcpy control (system-level injection).
        ctrl = self._get_scrcpy_control()
        if ctrl is not None:
            try:
                ctrl.key(key_l)
                return
            except Exception as exc:
                self._log(f"key via scrcpy control failed ({key_l}): {exc}", level=logging.WARNING)

        # Second: uiautomator2 instrumentation (does NOT require INJECT_EVENTS).
        with self._u2_lock:
            u2 = self._u2
        if u2 is not None:
            try:
                u2.press(key_l)  # type: ignore[attr-defined]
                return
            except Exception as exc:
                self._log(f"key via U2 failed ({key_l}): {exc}", level=logging.WARNING)

        # Prefer agent path when available.
        #
        # NOTE: Some agent builds don't implement {"type":"key"} reliably (observed: WS logs show
        # INPUT KEY but device doesn't react). Shelling `input keyevent` is the most compatible
        # path across Android versions/modes.
        if self._agent_send is not None:
            keycode = {
                "home": "KEYCODE_HOME",
                "back": "KEYCODE_BACK",
                "menu": "KEYCODE_MENU",
                "power": "KEYCODE_POWER",
                "enter": "KEYCODE_ENTER",
                "volumeup": "KEYCODE_VOLUME_UP",
                "volumedown": "KEYCODE_VOLUME_DOWN",
                "recent": "KEYCODE_APP_SWITCH",
                "app_switch": "KEYCODE_APP_SWITCH",
                "del": "KEYCODE_DEL",
                "delete": "KEYCODE_DEL",
                "tab": "KEYCODE_TAB",
            }.get(key_l)
            if not keycode:
                keycode = k if k.upper().startswith("KEYCODE_") else f"KEYCODE_{k.upper()}"
            # Agent executes on-device shell.
            self._send_to_agent({"type": "shell", "cmd": f"input keyevent {keycode}"})
            return

        # Fallback for ADB mode (or anytime an adb transport is present).
        adb = self._adb_transport
        if adb is not None and adb.connected:
            keycode = {
                "home": "KEYCODE_HOME",
                "back": "KEYCODE_BACK",
                "menu": "KEYCODE_MENU",
                "power": "KEYCODE_POWER",
                "enter": "KEYCODE_ENTER",
                "volumeup": "KEYCODE_VOLUME_UP",
                "volumedown": "KEYCODE_VOLUME_DOWN",
                "recent": "KEYCODE_APP_SWITCH",
                "app_switch": "KEYCODE_APP_SWITCH",
                "del": "KEYCODE_DEL",
                "delete": "KEYCODE_DEL",
                "tab": "KEYCODE_TAB",
            }.get(key_l)
            if not keycode:
                keycode = k if k.upper().startswith("KEYCODE_") else f"KEYCODE_{k.upper()}"
            try:
                adb.shell(f"input keyevent {keycode}", timeout=5.0)
                return
            except Exception as exc:
                self._log(f"key via ADB failed ({keycode}): {exc}", level=logging.WARNING)

        self._log(f"key skipped ({k}): no agent and no adb", level=logging.WARNING)

    def pinch(self, cx: int, cy: int, scale: float) -> None:
        """Pinch gesture via WebSocket → agent."""
        self._send_to_agent({"type": "pinch", "cx": cx, "cy": cy, "scale": scale})

    # ── Shell (no-ADB; via WsAgentService) ─────────────────────────────────────

    def shell(self, cmd: str) -> None:
        """
        Run a shell command on device via WsAgentService.
        Used for: am start, input keyevent, settings put, etc.
        Output is only visible in agent logs.
        """
        self._send_to_agent({"type": "shell", "cmd": cmd})

    def launch_app(self, package: str) -> None:
        """Ask agent to start an app by package name via Intent."""
        if not package:
            return
        # ADB mode: use monkey or am start to launch by package
        if self.is_adb_mode and self._adb_transport is not None and self._adb_transport.connected:
            try:
                # monkey -p <pkg> -c android.intent.category.LAUNCHER 1 is reliable
                cmd = f"monkey -p {package} -c android.intent.category.LAUNCHER 1"
                self._adb_transport.shell(cmd, timeout=10.0)
            except Exception as exc:
                self._log(f"launch_app via ADB failed: {exc}", level=logging.WARNING)
            return
        self._send_to_agent({"type": "launch_app", "package": package})

    def open_url(self, url: str, package: str | None = None) -> None:
        """
        Open a URL on the device. Optionally force a browser/app by package (e.g. com.android.chrome).
        MCP/scenario decides; agent only applies payload.
        """
        if not url:
            return
        # ADB mode: launch via am start VIEW intent (package not supported here; use agent for that)
        if self.is_adb_mode and self._adb_transport is not None and self._adb_transport.connected:
            escaped = url.replace('"', r"\\\"")
            cmd = f'am start -a android.intent.action.VIEW -d "{escaped}"'
            try:
                self._adb_transport.shell(cmd, timeout=15.0)
            except Exception as exc:
                self._log(f"open_url via ADB failed: {exc}", level=logging.WARNING)
            return
        # WS agent mode: send command and wait for agent to confirm success/failure
        payload: Dict[str, Any] = {"type": "open_url", "url": url}
        payload["package"] = (package or "").strip() or "com.android.chrome"
        self._open_url_result = None
        self._open_url_result_event.clear()
        self._send_to_agent(payload)
        if not self._open_url_result_event.wait(timeout=15.0):
            raise RuntimeError("open_url: no response from agent (timeout 15s)")
        ok, err = self._open_url_result or (False, "unknown")
        if not ok:
            raise RuntimeError(f"open_url failed: {err or 'agent reported failure'}")


    def on_agent_hierarchy_response(self, xml: Optional[str], error: Optional[str] = None) -> None:
        """Called when agent responds to dump_hierarchy WS command."""
        self._ws_hierarchy_xml = xml
        self._ws_hierarchy_error = error
        if error == "accessibility_not_available":
            if self._ws_hierarchy_a11y_available:
                self._log("a11y not available on device — using u2 fallback for hierarchy", level=logging.WARNING)
                self._ws_hierarchy_a11y_available = False
        elif xml:
            self._ws_hierarchy_a11y_available = True  # re-enable if it starts working
        self._ws_hierarchy_event.set()

    def _hierarchy_via_ws(self, timeout: float = 5.0) -> Optional[str]:
        """Request hierarchy dump via WS direct (AccessibilityService, ~100-500ms)."""
        if self._agent_send is None:
            return None
        self._ws_hierarchy_xml = None
        self._ws_hierarchy_error = None
        self._ws_hierarchy_event.clear()
        self._log(f"hierarchy_via_ws: sending dump_hierarchy (agent_send={'SET' if self._agent_send else 'NULL'})")
        self._send_to_agent({"type": "dump_hierarchy"})
        if not self._ws_hierarchy_event.wait(timeout=timeout):
            self._log("hierarchy_via_ws: timeout (5s)", level=logging.WARNING)
            return None
        if self._ws_hierarchy_error:
            self._log(f"hierarchy_via_ws error: {self._ws_hierarchy_error}", level=logging.WARNING)
            return None
        xml = self._ws_hierarchy_xml
        if xml:
            self._log(f"hierarchy_via_ws: OK ({len(xml)} bytes)")
        else:
            self._log("hierarchy_via_ws: agent returned null xml", level=logging.WARNING)
        return xml

    def hierarchy_xml(self, force_refresh: bool = False) -> Optional[str]:
        """
        Dump UI hierarchy XML. Cached 2s for polling.

        Primary: WS direct via AccessibilityService (100-500ms, no tunnel needed).
        Fallback: u2 JSON-RPC via tunnel (1-4s, for ADB mode or when a11y unavailable).
        """
        now = time.time()
        if not force_refresh and self._hierarchy_cache is not None:
            ts, xml = self._hierarchy_cache
            if now - ts < self._hierarchy_cache_ttl and xml:
                return xml  # fast path: no lock needed for cache read
        with self._hierarchy_lock:
            now = time.time()
            if not force_refresh and self._hierarchy_cache is not None:
                ts, xml = self._hierarchy_cache
                if now - ts < self._hierarchy_cache_ttl and xml:
                    return xml

            # Primary: WS direct via AccessibilityService (fast, no tunnel)
            # Only try if a11y was previously successful (avoid spamming agent)
            if self._agent_send is not None and self._ws_hierarchy_a11y_available:
                xml = self._hierarchy_via_ws(timeout=5.0)
                if xml and not self._is_empty_hierarchy(xml):
                    self._log(f"hierarchy: WS direct OK ({len(xml)} bytes)")
                    self._hierarchy_cache = (now, xml)
                    return xml
                # a11y returned error/empty — stop trying until next reconnect

            # Fallback: u2 tunnel (ADB mode or a11y not enabled)
            return self._hierarchy_xml_via_u2(now)

    @staticmethod
    def _is_empty_hierarchy(s: str) -> bool:
        if not s or not s.strip():
            return True
        t = s.strip()
        return t in ("<hierarchy />", "<?xml version=\"1.0\" encoding=\"UTF-8\"?><hierarchy />") or t.endswith("<hierarchy />")

    def _hierarchy_xml_via_u2(self, now: float) -> Optional[str]:
        """Fallback: hierarchy via u2 tunnel."""
        with self._u2_request_lock:
            return self._hierarchy_xml_u2_impl(now)

    def _hierarchy_xml_u2_impl(self, now: float) -> Optional[str]:
        if not self.ensure_u2_healthy() or self._u2 is None:
            return None
        u2_snap = self._u2
        try:
            xml = u2_snap.page_source(timeout=10.0)
            if self._is_empty_hierarchy(xml or ""):
                return None  # Don't cache; UI can show "enable Accessibility" etc.
            self._hierarchy_cache = (now, xml)
            return xml
        except Exception as exc:
            self._log(f"hierarchy_xml failed: {exc}", level=logging.WARNING)
        with self._u2_lock:
            if self._u2 is u2_snap:
                self._u2 = None
        if not self._reconnect_u2() or self._u2 is None:
            return None
        try:
            xml = self._u2.page_source(timeout=10.0)
            if self._is_empty_hierarchy(xml or ""):
                return None
            self._hierarchy_cache = (now, xml)
            return xml
        except Exception as exc:
            self._log(f"hierarchy_xml retry failed: {exc}", level=logging.WARNING)
            self._u2 = None
        return None

    def hierarchy_invalidate_cache(self) -> None:
        """Call after tap_selector etc. so next hierarchy_xml() fetches fresh."""
        self._hierarchy_cache = None

    def hit_test_selector(self, x: int, y: int) -> Optional[Dict[str, str]]:
        """
        Given screen coordinates (x, y), try to infer a stable selector
        from the current UI hierarchy XML.

        Selector priority (most stable → least stable):
          1. resource-id  — stable across runs, ignores locale/position changes
          2. text         — visible label; works well for buttons/links
          3. content-desc — accessibility label; good for icon-only buttons
          4. xpath        — fragile structural path; last resort

        Finds the smallest-area node containing (x, y) — most specific element.
        Returns {"by": ..., "value": ...} or None.
        """
        # Try cached first (fast), fall back to force-refresh if cache is empty
        xml = self.hierarchy_xml(force_refresh=False)
        if not xml:
            xml = self.hierarchy_xml(force_refresh=True)
        if not xml:
            return None

        import re as _re

        best: Optional[Dict[str, str]] = None
        best_area = float("inf")

        BOUNDS_RE = _re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return None

        for node in root.iter():
            bounds_str = node.get("bounds", "")
            m = BOUNDS_RE.search(bounds_str)
            if not m:
                continue
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            if not (x1 <= x <= x2 and y1 <= y <= y2):
                continue
            area = (x2 - x1) * (y2 - y1)
            if area >= best_area:
                continue

            # Pick selector: text > resource-id (in-app) > content-desc → xpath > resource-id (launcher)
            rid = (node.get("resource-id") or "").strip()
            text = (node.get("text") or "").strip()
            desc = (node.get("content-desc") or "").strip()

            sel: Optional[Dict[str, str]] = None
            if text and len(text) < 80:
                # Visible label — portable across devices and locales as long as text matches
                sel = {"by": "text", "value": text}
            elif rid and "/" in rid:
                # In-app resource-id (stable within the same app version)
                sel = {"by": "resource-id", "value": rid}
            elif desc and len(desc) < 80:
                # Accessibility label — map to native u2 "description" (content-desc)
                sel = {"by": "description", "value": desc}
            elif rid:
                # Launcher/system resource-id — least portable but better than nothing
                sel = {"by": "resource-id", "value": rid}

            if sel:
                best = sel
                best_area = area

        return best


    def attach_scrcpy_stream(
        self,
        device_ip: str,
        adb_port: int = 5555,
        enable_control: bool = True,
    ) -> None:
        """
        Attach scrcpy screen streaming + control to a WS-Agent device (Mode A hybrid).

        When enable_control=True (default), scrcpy also provides touch/key input
        via its control channel — smoother than minitouch/u2.

        Args:
            device_ip:       Device IP address (e.g. "192.168.1.100")
            adb_port:        ADB TCP port on device (default 5555)
            enable_control:  Also enable scrcpy control channel for touch/key input
        """
        # Stop any existing scrcpy receiver
        self.detach_scrcpy_stream()

        serial = f"{device_ip}:{adb_port}"
        adb_bin = os.environ.get("SCRCPY_ADB_BIN", "adb").strip() or "adb"
        # Unique port per device slot to avoid collision when multiple devices are attached
        scrcpy_port = 27183 + self.index

        try:
            # adb connect (ensure device is reachable)
            subprocess.run([adb_bin, "connect", serial], capture_output=True, timeout=10)
            # NOTE: adb forward is handled internally by ScrcpyReceiver._connect_and_stream()
            scrcpy_jar = AdbDeviceBootstrap._resolve_scrcpy_jar()
            # Get real screen resolution via adb (scrcpy downscales, we need real for touch coords)
            if not self.screen_width or not self.screen_height:
                try:
                    wm = subprocess.run(
                        [adb_bin, "-s", serial, "shell", "wm", "size"],
                        capture_output=True, text=True, timeout=5,
                    )
                    # Parse "Physical size: 1080x2316"
                    for line in wm.stdout.strip().splitlines():
                        if line.strip().startswith("Physical size") and "x" in line:
                            parts = line.split(":")[-1].strip().split("x")
                            self.screen_width = int(parts[0])
                            self.screen_height = int(parts[1])
                            self._log(f"Real screen resolution from adb: {self.screen_width}x{self.screen_height}")
                            break
                except Exception as exc2:
                    self._log(f"Failed to get screen size via adb: {exc2}", level=logging.WARNING)
        except Exception as exc:
            self._log(f"attach_scrcpy_stream setup failed: {exc}", level=logging.ERROR)
            return

        def _on_scrcpy_frame(jpeg: bytes) -> None:
            # Ensure ScrcpyControl uses REAL device resolution for coordinate mapping.
            # scrcpy downscales video (e.g. 376x800) but touch coords from frontend
            # are in real resolution (e.g. 1080x2316). scrcpy maps:
            #   actual_x = x * realDeviceWidth / position.screenWidth
            # So we must set position.screenWidth = real device width.
            ctrl = receiver.control
            if ctrl is not None and self.screen_width and ctrl.screen_width != self.screen_width:
                ctrl.screen_width = self.screen_width
                ctrl.screen_height = self.screen_height
                self._log(f"ScrcpyControl coords updated to real resolution: {self.screen_width}x{self.screen_height}")
            with self._latest_jpeg_lock:
                self._latest_jpeg = jpeg
                self._last_frame_time = time.monotonic()
            self.publish_frame(jpeg)

        receiver = ScrcpyReceiver(
            serial=serial,
            adb_path=adb_bin,
            port=scrcpy_port,
            server_jar=scrcpy_jar,
            max_fps=self.config.device.scrcpy_max_fps,
            max_width=self.config.device.scrcpy_max_width,
            reconnect_delay=2.0,
            enable_control=enable_control,
            on_frame=_on_scrcpy_frame,
        )
        receiver.start_receiver()

        self._scrcpy_receiver = receiver
        self._scrcpy_active = True
        ctrl_status = "control=ON" if enable_control else "video-only"
        self._log(f"scrcpy stream attached ({serial}) — {ctrl_status}, MediaProjection suppressed")

    def detach_scrcpy_stream(self) -> None:
        """Stop scrcpy receiver (+ control) and resume MediaProjection frames.
        adb forward cleanup is handled internally by ScrcpyReceiver."""
        if self._scrcpy_receiver is not None:
            try:
                self._scrcpy_receiver.stop_receiver()
            except Exception:
                pass
            self._scrcpy_receiver = None
        self._scrcpy_active = False

    # ── ADB Mode (Mode B) ─────────────────────────────────────────────────────

    def attach_adb_transport(self, transport: AdbTransport) -> None:
        """
        Attach an AdbTransport and start AdbDeviceBootstrap in ADB mode.

        - Screen: scrcpy (in AdbDeviceBootstrap) → self.publish_frame(...)
        - Touch/UI: openatx android-uiautomator-server on TCP :9008
        - Battery/rotation: update local fields for status panel.
        """
        # If we already had an ADB transport, close it.
        if self._adb_bootstrap is not None:
            try:
                self._adb_bootstrap.stop()
            except Exception:
                pass
            self._adb_bootstrap = None
        if self._adb_transport is not None:
            try:
                self._adb_transport.close()
            except Exception:
                pass
            self._adb_transport = None

        self._adb_transport = transport
        self.is_adb_mode = True

        def _on_frame(jpeg: bytes) -> None:
            # Called from AdbDeviceBootstrap thread (scrcpy).
            with self._latest_jpeg_lock:
                self._latest_jpeg = jpeg
            self.publish_frame(jpeg)

        def _on_battery(level: int) -> None:
            try:
                self.battery_level = int(level)
            except Exception:
                self.battery_level = -1
            # If STFService is connected, get rich battery info
            svc = self._stf_service
            if svc and svc.connected:
                info = svc.get_battery_info()
                self.battery_status = info.status
                self.battery_source = info.source
                self.battery_temp = info.temp
            self._publish_status()

        def _on_rotation(degrees: int) -> None:
            self._log(f"Rotation (ADB): {degrees}°")

        def _on_u2_ready(client: U2JsonRpcClient) -> None:
            # Wire AdbDeviceBootstrap's U2JsonRpcClient into this DeviceClient
            with self._u2_lock:
                self._u2 = client
            self._publish_status()
            self._log(f"uiautomator2 ready on {client._base}")

        def _on_stf_ready(svc: STFServiceClient) -> None:
            self._stf_service = svc
            self._publish_status()
            self._log("STFService connected (ADB mode — push events)")

        def _on_metadata(meta: Dict[str, Any]) -> None:
            # Update basic device metadata from AdbDeviceBootstrap; mark READY so frontend shows frame
            self.brand           = meta.get("brand", self.brand)
            self.model           = meta.get("model", self.model)
            self.android_version = meta.get("android", self.android_version)
            self.sdk_version     = int(meta.get("sdk", self.sdk_version) or 0)
            self.screen_width    = int(meta.get("screen_width", self.screen_width) or 0)
            self.screen_height   = int(meta.get("screen_height", self.screen_height) or 0)
            self.state = DeviceState.READY
            self._publish_status()

        skip_scrcpy = self.config.streaming.mode == "periodic"
        self._adb_bootstrap = AdbDeviceBootstrap(
            transport=self._adb_transport,
            on_frame=_on_frame,
            on_battery=_on_battery,
            on_rotation=_on_rotation,
            on_u2_ready=_on_u2_ready,
            on_metadata=_on_metadata,
            on_stf_ready=_on_stf_ready,
            skip_scrcpy=skip_scrcpy,
        )
        self._adb_bootstrap.start()
        mode_label = "periodic screenshots" if skip_scrcpy else "scrcpy + u2 over TCP"
        self._log(f"ADB bootstrap started ({mode_label})")

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
        # Serialize with all u2 operations (NanoHTTPD is single-threaded)
        with self._u2_request_lock:
            self._tap_selector_impl(by, value)

    def _tap_selector_impl(self, by: str, value: str) -> None:
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

    # ── uiautomator2 passthrough ──────────────────────────────────────────────

    @property
    def u2_device(self) -> Optional[U2JsonRpcClient]:
        return self._u2

    # Backwards-compatible alias used by tasks (example_task, etc.)
    @property
    def u2(self) -> Optional[U2JsonRpcClient]:
        return self._u2

    # Quick health‑check + lazy reconnect for U2 tunnel
    def ensure_u2_healthy(self, ping_timeout: float = 3.0) -> bool:
        if self.is_adb_mode:
            return self._ensure_u2_healthy_adb(ping_timeout)

        ports = self._tunnel_ports or {}
        if "u2" not in ports or "u2" not in self._tunnels_ready_channels:
            return False

        if self._u2 is not None:
            return True  # Trust existing connection; reconnect on failure below

        return self._reconnect_u2()

    def _ensure_u2_healthy_adb(self, ping_timeout: float = 3.0) -> bool:
        """
        Health check for ADB mode.

        Pings the u2 HTTP server. If dead, nulls _u2 so subsequent calls
        return False immediately while the watchdog thread (started by
        AdbDeviceBootstrap._start_u2_watchdog) detects the failure and
        restarts atx-agent automatically in the background.

        Returns True only when /ping responds HTTP 200.
        """
        u2_snap = self._u2
        if u2_snap is None:
            return False

        if u2_snap.ping(timeout=ping_timeout):
            return True

        # Ping failed — null out stale client so callers fall back gracefully.
        # The watchdog thread will detect the failure on its next tick and
        # call restart_u2_server() without us needing to spawn anything here.
        self._log("u2 ping failed — waiting for watchdog to restart atx-agent", level=logging.WARNING)
        with self._u2_lock:
            if self._u2 is u2_snap:
                self._u2 = None
        return False

    def _wait_for_u2_restart(self, timeout: float = 25.0) -> bool:
        """
        ADB mode: wait for the watchdog to bring u2 back up.

        Mirrors the uiautomator2 library pattern: after a failed RPC call,
        block briefly so the inline retry can succeed (watchdog is already
        restarting in the background).

        Polls _u2 every 1s until it becomes non-None and passes /ping.
        """
        deadline = time.monotonic() + timeout
        serial = self.serial
        # Trigger an eager restart if watchdog hasn't noticed yet
        bootstrap = self._adb_bootstrap
        if bootstrap is not None:
            t = threading.Thread(
                target=bootstrap.restart_u2_server,
                kwargs={"debounce": 0.0},
                daemon=True,
                name=f"u2-inline-restart-{serial}",
            )
            t.start()

        while time.monotonic() < deadline:
            time.sleep(1.0)
            u2 = self._u2
            if u2 is not None and u2.ping(timeout=2.0):
                self._log("u2 back online after inline restart")
                return True
        self._log(f"u2 did not recover within {timeout:.0f}s", level=logging.ERROR)
        return False

    _U2_RECONNECT_ATTEMPTS = 10
    _U2_RECONNECT_DELAY = 1.0  # Increased: u2 server restart can take 2-5s

    def _reconnect_u2(self) -> bool:
        """Connect (or reconnect) the u2 client. Tries JSON-RPC first, then WebDriver.

        Retries up to _U2_RECONNECT_ATTEMPTS with _U2_RECONNECT_DELAY when tunnel/agent
        returns 404 or connection errors (transient during agent reconnect).
        Serialised by _u2_lock so concurrent callers don't open multiple TCP connections.
        """
        with self._u2_lock:
            if self._u2 is not None:
                return True

        ports = self._tunnel_ports or {}
        if "u2" not in ports:
            return False
        port = ports["u2"]
        cfg = self.config.u2

        for attempt in range(1, self._U2_RECONNECT_ATTEMPTS + 1):
            if attempt > 1:
                time.sleep(self._U2_RECONNECT_DELAY)
                with self._u2_lock:
                    if self._u2 is not None:
                        return True

            # ── JSON-RPC only (android-uiautomator-server on port 9008); U2CompatServer disabled ──────
            d_rpc: Any = U2JsonRpcClient("127.0.0.1", port, timeout=cfg.wait_timeout)
            d_rpc.implicitly_wait(cfg.implicitly_wait)
            d_rpc.settings["wait_timeout"] = cfg.wait_timeout
            try:
                d_rpc.verify()
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
        return False

    # ── Frame / Status Broadcasting ───────────────────────────────────────────

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        # Push current state/frame so late-connecting frontends get data (e.g. after ADB bootstrap)
        self._publish_status()
        with self._latest_jpeg_lock:
            jpeg = self._latest_jpeg
        if jpeg:
            self.publish_frame(jpeg)

    def subscribe_frames(self, queue: asyncio.Queue) -> None:
        with self._frame_lock:
            if queue not in self._frame_queues:
                self._frame_queues.append(queue)
        # Send last key frame to late-joining subscriber (works for both bytes and dict)
        if self._loop and self._last_key_frame is not None:
            asyncio.run_coroutine_threadsafe(_safe_put(queue, self._last_key_frame), self._loop)

    def unsubscribe_frames(self, queue: asyncio.Queue) -> None:
        with self._frame_lock:
            self._frame_queues = [q for q in self._frame_queues if q is not queue]

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
        if LOW_BW_MODE:
            self._frame_seq += 1
            if self._frame_seq % LOW_BW_FRAME_SKIP != 0:
                return
        # Binary frame protocol: [0x01][serial_len:1B][serial:NB][w:2B BE][h:2B BE][jpeg]
        serial_b = self.serial.encode()
        slen = len(serial_b)
        w = max(0, min(self.screen_width, 0xFFFF))
        h = max(0, min(self.screen_height, 0xFFFF))
        msg: bytes = bytes([0x01, slen]) + serial_b + struct.pack(">HH", w, h) + jpeg_bytes
        with self._frame_lock:
            queues = list(self._frame_queues)
        for q in queues:
            asyncio.run_coroutine_threadsafe(_safe_put(q, msg), self._loop)

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
        if u2_ok:
            touch_method = "u2"
        else:
            touch_method = "agent_shell" if self._agent_send is not None else "none"
        return {
            "type":             "status",
            "serial":           self.serial,
            "brand":            self.brand,
            "model":            self.model,
            "android":          self.android_version,
            "sdk":              self.sdk_version,
            "state":            self.state.value,
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
            "agent_connected":  self._agent_send is not None,
            "minitouch_ready":  False,
            "u2_ready":         u2_ok,
            "touch_method":     touch_method,
            "stf_connected":    self._stf_service is not None and self._stf_service.connected,
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
            self._log("force_u2_mode: touch via U2 (minitouch disabled)", level=logging.INFO)
        elif input_mgr_mode:
            self._log("touch=inputMgr: using U2 (minitouch disabled)", level=logging.INFO)

        # Connect U2 eagerly so first tap has no latency.
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

            svc = STFServiceClient(
                serial=self.serial,
                host="127.0.0.1",
                port=ports["stfservice"],
                on_battery=_on_battery,
                on_rotation=_on_rotation,
                on_connectivity=_on_connectivity,
                on_airplane=_on_airplane,
            )
            svc.start_client()
            self._stf_service = svc
            self._log("STFService connected via WS tunnel (full events)")
        except Exception as exc:
            self._log(f"STFService tunnel unavailable: {exc}",
                      level=logging.WARNING)

        self.state = DeviceState.READY
        ctrl = self._get_scrcpy_control()
        if ctrl is not None:
            touch_status = "scrcpy_control"
        elif self._u2 is not None:
            touch_status = "u2"
        else:
            touch_status = "agent_shell"
        self._log("Device READY (touch=%s u2=%s stfservice=%s)" % (
            touch_status,
            "yes" if self._u2 else "no",
            "yes" if self._stf_service else "no",
        ))

    def _u2_keepalive_loop(self) -> None:
        """Ping uiautomator2 every 5 s to keep HTTP connection alive.

        The uiautomator2 server (port 9008) closes the TCP connection after each
        HTTP response. The Android ServiceTunnel auto-reconnects within ~50ms.
        During that reconnect window, a ping here would fail. We tolerate up to
        2 consecutive misses before declaring u2 dead, so transient reconnects
        don't cascade into a full u2 teardown.
        """
        _INTERVAL = max(3.0, float(os.environ.get("U2_KEEPALIVE_INTERVAL", "5.0")))
        _PING_TIMEOUT = 4.0
        _MAX_MISSES = 4  # tolerate more misses (20s window at 5s interval)
        misses = 0

        def _is_alive() -> bool:
            # For ADB mode, keep running while transport is connected
            if self.is_adb_mode:
                return self.state not in (DeviceState.DEAD, DeviceState.DISCONNECTED)
            return self._agent_send is not None

        while _is_alive():
            time.sleep(_INTERVAL)
            if not _is_alive():
                return
            if self.state == DeviceState.BUSY:
                misses = 0  # reset: task is using u2, not idle
                continue

            with self._u2_lock:
                u2 = self._u2
            if u2 is None:
                # Proactively try to reconnect instead of waiting for next operation
                if self.state == DeviceState.READY:
                    self._reconnect_u2()
                misses = 0
                continue

            try:
                ok = u2.ping(timeout=_PING_TIMEOUT)
            except Exception as exc:
                ok = False
                self._log(f"u2 keep-alive ping error: {exc}", level=logging.DEBUG)

            if ok:
                misses = 0
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
                    # Proactively reconnect instead of waiting for next operation
                    self._reconnect_u2()

    def _teardown_tools(self) -> None:
        if self._stf_service:
            try: self._stf_service.stop_client()
            except Exception: pass
            self._stf_service = None
        self._u2 = None
        self.detach_scrcpy_stream()

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


async def _safe_put(queue: asyncio.Queue, item: Any) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        # For video frames (bytes = binary frame protocol, or dict frame type),
        # drop the oldest entry to make room for the latest frame so clients
        # never see stale video when network is slow.
        is_video = isinstance(item, (bytes, bytearray)) or (
            isinstance(item, dict) and item.get("type") == "frame"
        )
        is_status = isinstance(item, dict) and item.get("type") == "status"
        if is_video or is_status:
            # Status messages must NOT be dropped — they carry state changes
            # (DISCONNECTED, DEAD) that the frontend needs immediately.
            try:
                queue.get_nowait()
                queue.put_nowait(item)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
