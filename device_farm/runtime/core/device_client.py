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
from runtime.transports.minitouch import MinitouchSender
from runtime.transports.minitouch_ws import MinitouchWsClient
from runtime.transports.scrcpy_receiver import ScrcpyReceiver
from runtime.transports.stf_client import STFServiceClient
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
        self.current_app:     str = ""

        # Latest JPEG frame (from agent MediaProjection or scrcpy)
        self._latest_jpeg:      Optional[bytes] = None
        self._latest_jpeg_lock  = threading.Lock()

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

        # Tools connected via tunnels (WS agent) or ADB (MinitouchSender)
        self._minitouch:   Optional[Union[MinitouchWsClient, MinitouchSender]] = None
        self._u2:          Optional[U2JsonRpcClient]  = None
        self._u2_lock      = threading.Lock()  # serializes reconnect + identity-safe nulling
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
        # Agent-reported capabilities (e.g. ["u2","stfservice","h264","minitouch"])
        self._agent_capabilities: List[str] = []
        # Touch mode parsed from agent log: "a11y" | "inputMgr" | "NONE" | ""
        self._agent_touch_mode: str = ""
        # open_url: wait for agent to send open_url_result before marking step done
        self._open_url_result_event = threading.Event()
        self._open_url_result: Optional[Tuple[bool, str]] = None  # (success, error_msg)

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

    # ── Agent Lifecycle ───────────────────────────────────────────────────────

    def attach_agent_sender(self, send: Callable[[Dict[str, Any]], None]) -> TunnelSet:
        """
        Called when the Android agent WebSocket connects.
        Creates WS tunnels for minitouch, u2, stfservice.
        Returns TunnelSet so the session can route tunnel_data messages back.
        """
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
        self.publish_frame(jpeg)

    def on_agent_h264_frame(self, msg: Dict[str, Any]) -> None:
        """
        Receive H.264 NAL unit from agent — forward directly to browser subscribers.
        Browser decodes H.264 via WebCodecs VideoDecoder (no server-side decode needed).
        """
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
        self.publish_frame(jpeg_bytes)

    def on_agent_h264_config(self, avcc_record: bytes, w: int, h: int) -> None:
        """Relay H264 AVCDecoderConfigurationRecord to browser as binary 0x10 frame.
        Called when agent sends h264_config message (SPS+PPS codec config).
        """
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

    # ── Touch / Key API ───────────────────────────────────────────────────────

    def _try_u2_tap(self, action: "Callable[[], None]") -> bool:
        """Run touch action via u2. On failure: null _u2, reconnect once, retry."""
        if not self.ensure_u2_healthy() or self._u2 is None:
            return False
        u2_snap = self._u2
        try:
            action()
            return True
        except Exception as exc:
            self._log(f"u2 touch failed: {exc}", level=logging.WARNING)
            with self._u2_lock:
                if self._u2 is u2_snap:
                    self._u2 = None
        # Reconnect u2 and retry once (same pattern as tap_selector)
        if not self._reconnect_u2() or self._u2 is None:
            return False
        try:
            action()
            return True
        except Exception as exc:
            self._log(f"u2 touch retry failed: {exc}", level=logging.WARNING)
            self._u2 = None
            return False

    def tap(self, x: int, y: int) -> None:
        # Minitouch first: faster and doesn't depend on u2 tunnel stability.
        # u2 click is only tried when minitouch is unavailable (e.g. ADB mode).
        if self._minitouch is not None and self._minitouch.is_connected:
            try:
                self._minitouch.tap(x, y)
                return
            except Exception as exc:
                self._log(f"minitouch tap failed: {exc}", level=logging.WARNING)
        if self._try_u2_tap(lambda: self._u2.click(x, y) if self._u2 else None):
            return
        self._log(
            f"tap skipped (no touch method) minitouch={self._minitouch is not None} "
            f"u2={self._u2 is not None} adb={self.is_adb_mode}",
            level=logging.WARNING,
        )

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        # Minitouch first (same reason as tap).
        if self._minitouch is not None and self._minitouch.is_connected:
            try:
                self._minitouch.swipe(x1, y1, x2, y2, duration_ms=duration_ms)
                return
            except Exception as exc:
                self._log(f"minitouch swipe failed: {exc}", level=logging.WARNING)
        if self._try_u2_tap(lambda: self._u2.swipe(x1, y1, x2, y2, duration=duration_ms / 1000.0) if self._u2 else None):
            return
        self._log("swipe skipped (no touch method available)", level=logging.WARNING)

    def long_tap(self, x: int, y: int, duration_ms: int = 800) -> None:
        # Minitouch first (same reason as tap).
        if self._minitouch is not None and self._minitouch.is_connected:
            try:
                self._minitouch.long_tap(x, y, duration_ms=duration_ms)
                return
            except Exception as exc:
                self._log(f"minitouch long_tap failed: {exc}", level=logging.WARNING)
        if self._try_u2_tap(lambda: self._u2.long_click(x, y, duration=duration_ms / 1000.0) if self._u2 else None):
            return
        self._log("long_tap skipped (no touch method available)", level=logging.WARNING)

    def input_text(self, text: str) -> None:
        """Type text into currently focused element via u2.send_keys()."""
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

    def key(self, key_name: str) -> None:
        """Key press (home, back, power, enter). Via WS → agent."""
        self._send_to_agent({"type": "key", "key": key_name})

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


    def hierarchy_xml(self, force_refresh: bool = False) -> Optional[str]:
        """
        Dump UI hierarchy XML from u2 (am instrument :9008). Cached 2s for polling.
        Pass force_refresh=True to skip cache. Retries once after u2 reconnect on failure.

        Serialised by _hierarchy_lock so concurrent HTTP callers (multiple frontend tabs)
        don't each open a new TCP connection to the tunnel simultaneously.
        """
        now = time.time()
        if not force_refresh and self._hierarchy_cache is not None:
            ts, xml = self._hierarchy_cache
            if now - ts < self._hierarchy_cache_ttl and xml:
                return xml  # fast path: no lock needed for cache read
        with self._hierarchy_lock:
            # Re-check cache after acquiring lock — another thread may have just fetched.
            now = time.time()
            if not force_refresh and self._hierarchy_cache is not None:
                ts, xml = self._hierarchy_cache
                if now - ts < self._hierarchy_cache_ttl and xml:
                    return xml
            return self._hierarchy_xml_locked(now)

    def _hierarchy_xml_locked(self, now: float) -> Optional[str]:
        """Inner impl called while _hierarchy_lock is held (only one dump at a time)."""
        if not self.ensure_u2_healthy() or self._u2 is None:
            return None
        u2_snap = self._u2  # snapshot — stale timeouts can't kill a freshly reconnected client
        def _is_empty_hierarchy(s: str) -> bool:
            if not s or not s.strip():
                return True
            t = s.strip()
            return t in ("<hierarchy />", "<?xml version=\"1.0\" encoding=\"UTF-8\"?><hierarchy />") or t.endswith("<hierarchy />")
        try:
            xml = u2_snap.page_source(timeout=4.0)
            if _is_empty_hierarchy(xml or ""):
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
            xml = self._u2.page_source(timeout=4.0)
            if _is_empty_hierarchy(xml or ""):
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

    # ── Scrcpy Hybrid (Mode A + scrcpy screen) ────────────────────────────────

    def attach_scrcpy_stream(self, device_ip: str, adb_port: int = 5555) -> None:
        """
        Attach scrcpy screen streaming to a WS-Agent device (Mode A hybrid).

        The WS Agent continues to handle touch/control. scrcpy replaces
        MediaProjection as the screen source. Requires ADB access to device.

        Args:
            device_ip:  Device IP address (e.g. "192.168.1.100")
            adb_port:   ADB TCP port on device (default 5555)
        """
        import os as _os
        from runtime.transports.adb_device_bootstrap import AdbDeviceBootstrap

        # Stop any existing scrcpy receiver
        self.detach_scrcpy_stream()

        serial = f"{device_ip}:{adb_port}"
        adb_bin = _os.environ.get("SCRCPY_ADB_BIN", "adb").strip() or "adb"
        scrcpy_port = 27183

        try:
            # adb connect
            subprocess.run([adb_bin, "connect", serial], capture_output=True, timeout=10)
            # adb forward tcp:27183 → localabstract:scrcpy
            result = subprocess.run(
                [adb_bin, "-s", serial, "forward", f"tcp:{scrcpy_port}", "localabstract:scrcpy"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(f"adb forward failed: {result.stderr.strip()}")

            scrcpy_jar = AdbDeviceBootstrap._resolve_scrcpy_jar(None)  # type: ignore[arg-type]
        except Exception as exc:
            self._log(f"attach_scrcpy_stream setup failed: {exc}", level=logging.ERROR)
            return

        def _on_scrcpy_frame(jpeg: bytes) -> None:
            with self._latest_jpeg_lock:
                self._latest_jpeg = jpeg
            self.publish_frame(jpeg)

        receiver = ScrcpyReceiver(
            serial=serial,
            adb_path=adb_bin,
            port=scrcpy_port,
            server_jar=scrcpy_jar,
            max_fps=30,
            max_width=800,
            reconnect_delay=2.0,
        )
        receiver._on_frame = _on_scrcpy_frame  # type: ignore[attr-defined]
        receiver.start_receiver()

        self._scrcpy_receiver = receiver
        self._scrcpy_active = True
        self._log(f"scrcpy stream attached ({serial}) — MediaProjection suppressed")

    def detach_scrcpy_stream(self) -> None:
        """Stop scrcpy receiver and resume MediaProjection frames."""
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
            self._publish_status()

        def _on_rotation(degrees: int) -> None:
            # Frontend currently only cares about frame aspect; rotation is logged.
            self._log(f"Rotation (ADB): {degrees}°")

        def _on_u2_ready(client: U2JsonRpcClient) -> None:
            # Wire AdbDeviceBootstrap's U2JsonRpcClient into this DeviceClient
            with self._u2_lock:
                self._u2 = client
            self._publish_status()
            self._log(f"uiautomator2 ready on {client._base}")

        def _on_minitouch_ready(sender: MinitouchSender) -> None:
            self._minitouch = sender
            self._publish_status()
            self._log("minitouch ready (ADB)")

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

        self._adb_bootstrap = AdbDeviceBootstrap(
            transport=self._adb_transport,
            on_frame=_on_frame,
            on_battery=_on_battery,
            on_rotation=_on_rotation,
            on_u2_ready=_on_u2_ready,
            on_metadata=_on_metadata,
            on_minitouch_ready=_on_minitouch_ready,
        )
        self._adb_bootstrap.start()
        self._log("ADB bootstrap started (scrcpy + u2 over TCP)")

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
        u2_snap = self._u2
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
            return self._u2 is not None

        ports = self._tunnel_ports or {}
        if "u2" not in ports or "u2" not in self._tunnels_ready_channels:
            return False

        if self._u2 is not None:
            return True  # Trust existing connection; reconnect on failure below

        return self._reconnect_u2()

    _U2_RECONNECT_ATTEMPTS = 5
    _U2_RECONNECT_DELAY = 0.3  # Android ServiceTunnel reconnects to :9008 in ~50ms; 0.3s is plenty

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
        minitouch_ok = self._minitouch is not None and (self._minitouch.is_connected if self._minitouch else False)
        u2_ok = self._u2 is not None
        if minitouch_ok:
            touch_method = "minitouch"
        elif u2_ok:
            touch_method = "u2"
        else:
            touch_method = "none"
        return {
            "type":             "status",
            "serial":           self.serial,
            "brand":            self.brand,
            "model":            self.model,
            "android":          self.android_version,
            "sdk":              self.sdk_version,
            "state":            self.state.value,
            "battery":          self.battery_level,
            "current_app":      self.current_app,
            "screen_width":     self.screen_width,
            "screen_height":    self.screen_height,
            "agent_connected":  self._agent_send is not None,
            "minitouch_ready":  minitouch_ok,
            "u2_ready":         u2_ok,
            "touch_method":     touch_method,
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
        use_minitouch = (
            not input_mgr_mode
            and ((not self._agent_capabilities) or ("minitouch" in self._agent_capabilities))
        )
        if use_minitouch and self._agent_send is not None:
            self._minitouch = MinitouchWsClient(
                serial=self.serial,
                send_fn=self._agent_send,
                screen_width=w,
                screen_height=h,
            )
        elif input_mgr_mode:
            self._log(
                "touch=inputMgr — skipping MinitouchWsClient, will use U2 (uiautomator2) for touch",
                level=logging.INFO,
            )
            # Connect U2 eagerly so first tap has no latency
            threading.Thread(
                target=self._reconnect_u2,
                daemon=True,
                name=f"u2-eager-{self.serial}",
            ).start()

        # ── STFService ────────────────────────────────────────────────────────
        try:
            def _on_battery(level: int) -> None:
                self.battery_level = level
                self._publish_status()

            def _on_rotation(degrees: int) -> None:
                self._log(f"Rotation: {degrees}°")
                self._publish_status()

            svc = STFServiceClient(
                serial=self.serial,
                host="127.0.0.1",
                port=ports["stfservice"],
                on_battery=_on_battery,
                on_rotation=_on_rotation,
            )
            svc.start_client()
            self._stf_service = svc
            self._log("STFService connected via WS tunnel")
        except Exception as exc:
            self._log(f"STFService tunnel unavailable: {exc}",
                      level=logging.WARNING)

        self.state = DeviceState.READY
        touch_status = "minitouch(ws)" if self._minitouch else "u2"
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
        _MAX_MISSES = 2  # tolerate this many consecutive ping failures before marking dead
        misses = 0

        def _is_alive() -> bool:
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
                    self._log("u2 keep-alive: connection dead — marking for reconnect",
                              level=logging.WARNING)
                    with self._u2_lock:
                        if self._u2 is u2:
                            self._u2 = None
                    misses = 0
                    # Reconnect happens on next touch/hierarchy call via _reconnect_u2().

    def _teardown_tools(self) -> None:
        if self._stf_service:
            try: self._stf_service.stop_client()
            except Exception: pass
            self._stf_service = None
        if self._minitouch:
            try: self._minitouch.disconnect()
            except Exception: pass
            self._minitouch = None
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
        if is_video:
            try:
                queue.get_nowait()
                queue.put_nowait(item)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
        # JSON status/log messages: drop silently when queue is full (rare)
