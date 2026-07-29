"""
relay/scrcpy_relay.py — ScrcpyRelaySession

Runs scrcpy-server on a device via subprocess adb and streams raw H264 packets
back to the cloud through the gRPC bidi channel.

Design:
  - All adb operations (push, forward, shell) use subprocess — truly parallel
    across many devices, no ppadb GIL / TCP-daemon bottleneck.
  - scrcpy-server is started via subprocess.Popen (non-blocking long-running process).
  - _relay_loop() auto-reconnects on socket failure (exponential backoff, max N tries).
  - send_control() is fully thread-safe.
  - is_alive() lets ScrcpySessionManager detect zombies.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from relay.adb import _adb_command
from relay.adb_admission import AdbLane, adb_admission, classify_adb_command
from relay.video_packet import VideoPacket

logger = logging.getLogger("relay.scrcpy")

_CACHE_DIR = Path.home() / ".cache" / "device-farm"
_PTS_CONFIG_MASK = 0x8000_0000_0000_0000
# Bundled JAR — agent-boot owns the scrcpy-server binary, no need to receive
# it from the farm server over gRPC.
_BUNDLED_JAR = Path(__file__).parent / "scrcpy-server"
_BUNDLED_JAR_VERSION = "3.3.4"
_SCRCPY_DEVICE_DIR = "/data/local/tmp/device-farm"
_SCRCPY_PATH_ON_DEVICE = (
    f"{_SCRCPY_DEVICE_DIR}/scrcpy-server-{_BUNDLED_JAR_VERSION}.jar"
)
_SCRCPY_JAR_DEPLOY_CONDITION = threading.Condition()
_SCRCPY_JAR_DEPLOYING: set[tuple[str, str]] = set()
_SCRCPY_JAR_READY: set[tuple[str, str]] = set()


def invalidate_scrcpy_server_jar(serial: str) -> None:
    """Force the next start to verify the versioned JAR on one phone."""
    serial = str(serial or "").strip()
    if not serial:
        return
    with _SCRCPY_JAR_DEPLOY_CONDITION:
        stale = [key for key in _SCRCPY_JAR_READY if key[0] == serial]
        for key in stale:
            _SCRCPY_JAR_READY.discard(key)


def annexb_contains_idr(data: bytes) -> bool:
    """Return True if any Annex-B NAL unit is an IDR (type 5)."""
    for match in _SC_RE.finditer(data):
        nal_start = match.end()
        if nal_start < len(data) and (data[nal_start] & 0x1F) == 5:
            return True
    return False


def _is_idr(data: bytes) -> bool:
    """Backward-compatible internal wrapper."""
    return annexb_contains_idr(data)


def _relay_enqueue(
    q: Any,
    frame: VideoPacket,
    on_p_drop=None,
    on_resync=None,
) -> None:
    """Module-level enqueue — avoids closure allocation per frame at 30fps.

    Called via call_soon_threadsafe from the relay thread.
    GOP-aware strategy: after one P-frame drop, later deltas stay suppressed
    until a keyframe is admitted. IDR/config packets may evict old video only.
    on_p_drop is invoked once when a serial first enters recovery.
    Packet routing and recovery facts come from the typed packet so callers
    cannot accidentally pass contradictory serial/config/key arguments.
    """
    serial = frame.serial
    is_cfg = frame.is_config
    is_key = frame.is_key
    # FairSendQueue exposes a dedicated lossy video lane. Older/plain queues
    # keep the legacy enqueue path for compatibility.
    offer_video = getattr(q, "offer_video_nowait", None)
    if offer_video is not None and serial:
        needs_idr = offer_video(
            frame,
            serial,
            is_config=is_cfg,
            is_key=is_key,
        )
        if needs_idr and on_p_drop is not None:
            on_p_drop()
        if (
            is_key
            and on_resync is not None
            and not getattr(
                q,
                "is_video_awaiting_keyframe",
                lambda _serial: False,
            )(serial)
        ):
            on_resync()
        return

    has_video_api = hasattr(q, "put_video_nowait")
    has_serial_api = hasattr(q, "put_nowait_with_serial")

    def _put(item):
        if has_video_api and serial:
            q.put_video_nowait(item, serial)
        elif has_serial_api:
            q.put_nowait_with_serial(item, serial)
        else:
            q.put_nowait(item)

    try:
        _put(frame)
        if is_key and on_resync is not None:
            on_resync()
    except asyncio.QueueFull:
        if not is_cfg and not is_key:
            if has_video_api and serial and hasattr(q, "record_video_drop"):
                q.record_video_drop(serial)
            if on_p_drop is not None:
                on_p_drop()  # signal relay thread to request IDR
            return  # P-frame: drop, IDR will follow shortly
        if has_video_api and serial:
            if q.evict_oldest_video(serial):
                try:
                    _put(frame)
                    if is_key and on_resync is not None:
                        on_resync()
                except asyncio.QueueFull:
                    pass
            return
        # Compatibility fallback: evict from the same legacy per-device lane.
        lane = q._per_dev.get(serial) if has_serial_api and serial else q
        try:
            lane.get_nowait()   # evict oldest to make room for IDR/config
            _put(frame)
            if is_key and on_resync is not None:
                on_resync()
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass


def enqueue_video_packet(
    queue: Any,
    packet: VideoPacket,
    on_drop=None,
    on_resync=None,
) -> None:
    """Public transport adapter for one typed video packet."""
    _relay_enqueue(queue, packet, on_drop, on_resync)


# Retry budget: max _MAX_RECONNECTS failures per _RETRY_WINDOW seconds.
# Outside the window, the counter resets — matches agent.py:SCRCPY_RESTART_WINDOW_SECONDS.
_MAX_RECONNECTS = 10
_RETRY_WINDOW   = 120.0  # seconds
_RECONNECT_BASE = float(os.environ.get("SCRCPY_RECONNECT_BASE_S", "2.0"))
# Cap reconnect backoff so user-visible black screen after an idle stall is
# short. Previous 30s default made a single encoder stall feel like the stream
# was permanently dead. Tunable via env for fleet-wide overrides.
_RECONNECT_MAX  = float(os.environ.get("SCRCPY_RECONNECT_MAX_S", "5.0"))

# Frame timeout: socket.recv raises socket.timeout after this many seconds without
# data. Catches hung streams where TCP is alive but the encoder truly stalled.
# Idle static screens on Android emit zero frames until IDR is requested, and
# the IDR response itself can take >5s on slow encoders (Vivo/Oppo Codec2 wrappers
# especially). A too-tight timeout tears down healthy sessions and triggers the
# reconnect-backoff loop, leaving the viewer black for 30s+. 20s is the sweet
# spot: still catches truly dead streams, tolerates normal idle behavior.
_FRAME_TIMEOUT = float(os.environ.get("SCRCPY_FRAME_TIMEOUT_S", "20.0"))

# ── Tier 1 env overrides (agent-boot-stability-rollout Phase 5) ──────────────
# Per-device encoder / codec pinning for OEMs whose default Codec2 wrapper
# stalls (Vivo Android 16 c2.qti.avc.encoder shows CCodecConfig BAD_INDEX +
# param-skipped in logcat). Empty default = let scrcpy pick.
#
# Usage in .env or launch:
#   SCRCPY_VIDEO_ENCODER=OMX.qcom.video.encoder.avc   # force Qualcomm HW H264
#   SCRCPY_VIDEO_CODEC=h265                           # switch to HEVC (Vivo stable)
# Per-serial form: SCRCPY_VIDEO_ENCODER__10AE7S00HD002JK=...  (double underscore)
_VIDEO_ENCODER_DEFAULT = os.environ.get("SCRCPY_VIDEO_ENCODER", "").strip()
_VIDEO_CODEC_DEFAULT   = os.environ.get("SCRCPY_VIDEO_CODEC", "h264").strip() or "h264"
_VIDEO_CODEC_GLOBAL_EXPLICIT = bool(os.environ.get("SCRCPY_VIDEO_CODEC", "").strip())
_H264_BASELINE_DEFAULT = os.environ.get("SCRCPY_H264_BASELINE", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
_SCRCPY_CLEANUP_DEFAULT = os.environ.get("SCRCPY_CLEANUP", "false").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
# Empty by default: the web dashboard decodes H.264 (avc1) only. Auto HEVC leaves the
# canvas black on Vivo/Oppo while scrcpy logs show "handshake OK" + capture resets.
# Opt in per deploy: SCRCPY_HEVC_OEM_ALLOWLIST=vivo,oppo,realme,oneplus
_HEVC_OEM_ALLOWLIST = {
    s.strip().lower()
    for s in os.environ.get("SCRCPY_HEVC_OEM_ALLOWLIST", "").split(",")
    if s.strip()
}
# Optional fleet-wide H.264 encoder pin for Vivo devices. Empty by default:
# stability policy should stay generic unless ops explicitly opts in.
_VIVO_H264_ENCODER_DEFAULT = os.environ.get("SCRCPY_VIVO_H264_ENCODER", "").strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


SCRCPY_DEFAULT_MAX_FPS = max(1, _env_int("SCRCPY_DEFAULT_MAX_FPS", 12))
SCRCPY_DEFAULT_MAX_WIDTH = max(160, _env_int("SCRCPY_DEFAULT_MAX_WIDTH", 480))
SCRCPY_DEFAULT_BITRATE = max(80_000, _env_int("SCRCPY_DEFAULT_BITRATE", 600_000))


def _per_serial_env(base: str, serial: str, fallback: str) -> str:
    """
    Lookup per-serial env override first, fall back to default.
    Serial format `10AE7S00HD002JK` → env key `<BASE>__10AE7S00HD002JK`.
    WiFi serial `1.2.3.4:5555` → strip colons → `<BASE>__1_2_3_4_5555`.
    """
    safe = serial.replace(":", "_").replace(".", "_")
    key = f"{base}__{safe}"
    return os.environ.get(key, fallback).strip()


def _codec_explicit_for_serial(serial: str) -> bool:
    """
    True when codec is explicitly pinned by env (global or per-serial).
    We only auto-fallback to HEVC when user did not pin codec.
    """
    if _VIDEO_CODEC_GLOBAL_EXPLICIT:
        return True
    safe = serial.replace(":", "_").replace(".", "_")
    key = f"SCRCPY_VIDEO_CODEC__{safe}"
    return bool(os.environ.get(key, "").strip())


# Soft IDR threshold: if we go this many seconds without a frame, request an
# IDR keyframe from scrcpy-server before hitting the hard frame timeout. This
# recovers from decoder-freeze-on-dropped-NAL ~200ms vs full restart ~2-3s.
_IDR_REQUEST_AFTER = float(os.environ.get("SCRCPY_IDR_REQUEST_AFTER_S", "4.0"))
# Guardrail: if we keep requesting IDR too many times in a short window, the
# encoder is not recovering and the stream stays black/frozen. Force a hard
# session restart instead of spinning forever in capture-reset loops.
_IDR_MAX_REQUESTS = max(1, int(os.environ.get("SCRCPY_IDR_MAX_REQUESTS", "14")))
_IDR_REQUEST_WINDOW = max(
    _IDR_REQUEST_AFTER,
    float(os.environ.get("SCRCPY_IDR_REQUEST_WINDOW_S", "20.0")),
)
# Minimum gap between IDR requests. Raises the previous 0.5s to a tunable
# default of 1.0s — multi-day runs with several OEM devices in a soft stall
# would otherwise spam ~120 IDR requests/min total, burning CPU + ADB for
# zero recovery. Per-OEM env override below for stubborn codecs.
_IDR_REQUEST_MIN_GAP = max(0.2, float(os.environ.get("SCRCPY_IDR_REQUEST_MIN_GAP_S", "4.0")))

# scrcpy 3.3.x control message type. Hardcoded to the bundled server version
# (see _BUNDLED_JAR_VERSION); re-check if you bump the jar.
_SC_CTRL_RESET_VIDEO = 17

# TCP keepalive tuned for WiFi: detect dead peer ~9s after last ACK. Defaults
# of 2h are useless — NAT/router drop silent TCP after 5-15min idle.
_KEEPALIVE_IDLE     = 3   # seconds of idle before first probe
_KEEPALIVE_INTERVAL = 3   # seconds between probes
_KEEPALIVE_COUNT    = 3   # fails before the socket is declared dead


def _enable_tcp_keepalive(sock: socket.socket) -> None:
    """
    Enable SO_KEEPALIVE with aggressive timing. macOS exposes TCP_KEEPALIVE
    (seconds until first probe); Linux exposes TCP_KEEPIDLE/INTVL/CNT. Apply
    whichever is available — silently skip unsupported options.
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        return
    # macOS
    TCP_KEEPALIVE = getattr(socket, "TCP_KEEPALIVE", 0x10)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, TCP_KEEPALIVE, _KEEPALIVE_IDLE)
    except OSError:
        pass
    # Linux
    for opt, val in (
        ("TCP_KEEPIDLE", _KEEPALIVE_IDLE),
        ("TCP_KEEPINTVL", _KEEPALIVE_INTERVAL),
        ("TCP_KEEPCNT", _KEEPALIVE_COUNT),
    ):
        n = getattr(socket, opt, None)
        if n is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, n, val)
            except OSError:
                pass

# Regex matches both 3-byte (\x00\x00\x01) and 4-byte (\x00\x00\x00\x01) Annex-B start codes.
# Used to split Annex-B byte streams into individual NAL units in O(n) via the C regex engine.
_SC_RE = re.compile(rb'\x00\x00\x00?\x01')


def _annexb_to_avcc(data: bytes) -> bytes:
    """Convert Annex-B H264 to AVCC (4-byte big-endian length prefix per NAL unit).

    Called from the scrcpy relay daemon thread — NOT on the asyncio event loop.
    This offloads the O(n) conversion from the farm's event loop, removing a key
    source of jitter at 30fps.

    Returns data unchanged if the conversion produces no NAL units.
    """
    converted, _ = annexb_to_avcc_with_idr(data)
    return converted


def annexb_to_avcc_with_idr(data: bytes) -> tuple[bytes, bool]:
    """Convert Annex-B once while classifying all NAL units for IDR."""
    nals = [nal for nal in _SC_RE.split(data) if nal]
    if not nals:
        return data, False
    return (
        b"".join(struct.pack(">I", len(nal)) + nal for nal in nals),
        any((nal[0] & 0x1F) == 5 for nal in nals),
    )


def _annexb_to_avcc_with_idr(data: bytes) -> tuple[bytes, bool]:
    """Backward-compatible internal wrapper."""
    return annexb_to_avcc_with_idr(data)


def prepare_video_packet(
    *,
    serial: str,
    annexb: bytes,
    is_config: bool,
    pts_us: int,
    width: int = 0,
    height: int = 0,
    received_ns: int | None = None,
    suppress_deltas: bool = False,
) -> VideoPacket | None:
    """Classify and convert one scrcpy packet before transport handoff."""
    is_key = False
    data = annexb
    if not is_config:
        if suppress_deltas:
            is_key = annexb_contains_idr(annexb)
            if not is_key:
                return None
        data, is_key = annexb_to_avcc_with_idr(annexb)
    return VideoPacket(
        serial=serial,
        data=data,
        is_config=is_config,
        is_key=is_key,
        pts_us=pts_us,
        width=width if is_config else 0,
        height=height if is_config else 0,
        received_ns=(
            time.monotonic_ns()
            if received_ns is None
            else received_ns
        ),
    )


def _recvall(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"scrcpy socket closed (expected {n}, got {len(buf)})")
        buf.extend(chunk)
    return bytes(buf)


def _adb_forward_host() -> str:
    """Host for the local end of `adb forward tcp:N localabstract:scrcpy`.

    With a remote adb server (Docker → host.docker.internal:5037), the forward
    binds on the *server* machine — connecting to 127.0.0.1 inside the
    container always fails with connection refused.
    """
    override = os.environ.get("SCRCPY_FORWARD_HOST", "").strip()
    if override:
        return override
    sock = os.environ.get("ADB_SERVER_SOCKET", "").strip()
    if sock.startswith("tcp:"):
        rest = sock[4:]
        if ":" in rest:
            host = rest.rsplit(":", 1)[0].strip()
            if host:
                return host
    adb_host = os.environ.get("ADB_HOST", "").strip()
    if adb_host and adb_host not in ("127.0.0.1", "localhost"):
        return adb_host
    return "127.0.0.1"


def _adb(*args: str, serial: Optional[str] = None, timeout: int = 15) -> tuple[str, int]:
    """Run `adb [-s serial] <args>`. Returns (output, returncode). Never raises."""
    cmd = _adb_command(*args, serial=serial)
    # Suppress macOS MallocStackLogging spam
    env = os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        with adb_admission(
            serial=serial,
            lane=classify_adb_command(
                tuple(args),
                default=AdbLane.STARTUP,
            ),
        ):
            r = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        return (r.stdout + r.stderr).decode("utf-8", errors="replace"), r.returncode
    except subprocess.TimeoutExpired:
        return f"timeout {timeout}s", -1
    except Exception as exc:
        return str(exc), -1


class ScrcpyRelaySession:
    """
    One scrcpy relay session for a single device serial.

    Thread model:
      - start() blocks in the caller's thread/executor (setup only, ~2-3s)
      - _relay_loop() daemon thread: connect sockets → stream → auto-reconnect
      - send_control() thread-safe (lock on ctrl socket sendall)
      - stop() signals _relay_loop to exit and cleans up
    """

    def __init__(
        self,
        serial: str,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        send_queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        bitrate: int = 2_000_000,
        low_latency: bool = False,
        on_fatal: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._serial         = serial
        self._jar_version    = _BUNDLED_JAR_VERSION
        # A new session may follow a reboot or OEM cleanup of /data/local/tmp.
        # Revalidate once per session, while retaining single-flight/cache reuse
        # for reconnect attempts within the same session.
        invalidate_scrcpy_server_jar(serial)
        self._max_fps        = max_fps or SCRCPY_DEFAULT_MAX_FPS
        self._max_width      = max_width or SCRCPY_DEFAULT_MAX_WIDTH
        # Touch/key control originates from the farm's `scrcpy_control` config.
        # Even in video-only mode, we still need scrcpy's control socket for
        # IDR requests to recover from encoder stalls.
        self._enable_touch_control = bool(enable_control)
        self._enable_control_channel = True
        self._bitrate        = bitrate or SCRCPY_DEFAULT_BITRATE
        # KEY_LATENCY=0: encoder outputs every frame immediately (no internal buffer).
        # Saves 66-133 ms on Android ≤ 13 (API ≤ 33). Crashes MediaCodec on some
        # API 34+ OEM builds — farm only enables this when SDK < 34.
        self._low_latency    = low_latency
        self._port           = port
        self._send_queue     = send_queue
        self._loop           = loop

        self._running          = False
        self._relay_thread: Optional[threading.Thread] = None
        self._server_proc: Optional[subprocess.Popen] = None
        self._callback_fired   = False   # guards against double _on_fatal emit
        self._stream_ready     = threading.Event()

        self._video_sock: Optional[socket.socket] = None
        self._ctrl_sock:  Optional[socket.socket] = None
        self._ctrl_lock   = threading.Lock()

        # Stats used by SessionManager
        self.last_frame_time: float = 0.0
        self._reconnect_count: int  = 0

        # Set on first successful handshake; constant for this session
        self._device_width:  int = 0
        self._device_height: int = 0
        self._on_fatal = on_fatal
        self._oem_hint: str = ""
        self._model_hint: str = ""
        # Set to True (from asyncio thread) when a P-frame is dropped from the
        # send queue. The relay thread reads and resets this flag to request an
        # IDR immediately — caps decoder freeze at ~100ms vs 1s IDR interval.
        self._need_idr: bool = False
        self._last_idr_request_t: float = 0.0  # rate-limit to 1 IDR per 0.5s
        self._downstream_recovery = threading.Event()
        # Approximate operational counters. The relay thread is the sole
        # producer; the asyncio stats logger reads/resets once per interval.
        self._stats_started_at: float = 0.0
        self._stats_frames_total: int = 0
        self._stats_idr_requests_total: int = 0
        self._stats_idr_recoveries_total: int = 0
        self._stats_idr_recovery_samples_ms: list[int] = []
        self._stats_idr_pending_since: float = 0.0
        self._stats_producer_suppressed_total: int = 0
        self._stats_lock = threading.Lock()
        self._stats_snapshot_at: float = 0.0
        self._stats_snapshot_frames: int = 0
        self._stats_snapshot_idr_requests: int = 0
        self._stats_snapshot_idr_recoveries: int = 0
        self._stats_snapshot_producer_suppressed: int = 0

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Non-blocking entry point: validate/connect inside the relay thread."""
        # For TCP/WiFi devices ensure adb connection is established first.
        # USB devices (serial without ':') don't need this.
        if ":" in self._serial:
            out, rc = _adb("connect", self._serial, timeout=10)
            if "connected" not in out.lower() and "already connected" not in out.lower():
                raise RuntimeError(f"adb connect {self._serial} failed: {out.strip()}")
            logger.info("[%s] adb connected", self._serial)

        self._stream_ready.clear()
        self._running = True
        self._relay_thread = threading.Thread(
            target=self._relay_loop,
            daemon=True,
            name=f"scrcpy-{self._serial}",
        )
        self._relay_thread.start()

    def stop(self) -> None:
        """Signal relay loop to exit; clean up sockets, process, adb forward."""
        self._running = False
        self._close_sockets()
        self._kill_server()
        _adb("forward", "--remove", f"tcp:{self._port}",
             serial=self._serial, timeout=5)
        relay_thread = self._relay_thread
        if (
            relay_thread is not None
            and relay_thread is not threading.current_thread()
            and relay_thread.is_alive()
        ):
            relay_thread.join(timeout=5.0)
        # The relay thread may have been inside _start_scrcpy_server() when
        # stop() was requested. Kill once more after join so a late-started
        # localabstract:scrcpy server cannot race the next session.
        self._kill_server()
        _adb("forward", "--remove", f"tcp:{self._port}",
             serial=self._serial, timeout=5)

    def send_control(self, data: bytes) -> None:
        """Forward raw scrcpy control bytes to device (thread-safe).

        Touch/key control is gated by `_enable_touch_control`.
        IDR recovery uses `_send_control_raw()` directly.
        """
        if not self._enable_touch_control:
            return
        self._send_control_raw(data)

    def _send_control_raw(self, data: bytes) -> bool:
        """Send scrcpy control bytes to device (thread-safe, unfiltered)."""
        with self._ctrl_lock:
            sock = self._ctrl_sock
            if sock and self._running:
                try:
                    sock.sendall(data)
                    return True
                except Exception as exc:
                    logger.debug("[%s] ctrl send: %s", self._serial, exc)
        return False

    def _request_idr(self, *, now: float | None = None) -> bool:
        """
        Ask scrcpy-server to emit an IDR keyframe NOW. Used by the streaming
        loop when frames stop arriving — forces decoder re-sync ~200ms instead
        of tearing down the session. No-op if control socket not connected.

        Wire format: 1 byte message type (_SC_CTRL_RESET_VIDEO). Tied to the
        bundled scrcpy-server version — see _BUNDLED_JAR_VERSION.
        """
        now = time.monotonic() if now is None else now
        if not self._send_control_raw(bytes([_SC_CTRL_RESET_VIDEO])):
            return False
        self.record_idr_request(now=now)
        return True

    def record_idr_request(self, *, now: float) -> None:
        """Record a successfully transmitted IDR request."""
        with self._stats_lock:
            if self._stats_started_at <= 0.0:
                self._stats_started_at = now
            self._stats_idr_requests_total += 1
            if self._stats_idr_pending_since <= 0.0:
                self._stats_idr_pending_since = now

    def request_recovery_keyframe(self, *, now: float | None = None) -> bool:
        """Request an immediate encoder keyframe and start recovery timing."""
        requested_at = time.monotonic() if now is None else now
        if not self._request_idr(now=requested_at):
            return False
        self._last_idr_request_t = requested_at
        return True

    def _record_video_frame(
        self,
        *,
        is_key: bool,
        now: Optional[float] = None,
    ) -> None:
        """Record one encoded frame and close any pending IDR recovery."""
        now = time.monotonic() if now is None else now
        if self._stats_started_at <= 0.0:
            self._stats_started_at = now
        self._stats_frames_total += 1
        if is_key:
            with self._stats_lock:
                if self._stats_idr_pending_since > 0.0:
                    recovery_ms = max(
                        0,
                        round((now - self._stats_idr_pending_since) * 1_000),
                    )
                    self._stats_idr_recoveries_total += 1
                    self._stats_idr_recovery_samples_ms.append(recovery_ms)
                    self._stats_idr_pending_since = 0.0

    def record_video_frame(
        self,
        *,
        is_key: bool,
        now: float | None = None,
    ) -> None:
        """Record an encoded frame for windowed stream-health metrics."""
        self._record_video_frame(is_key=is_key, now=now)

    def stats_snapshot(
        self,
        *,
        reset: bool = False,
        now: float | None = None,
    ) -> dict[str, int]:
        """Return approximate encoder throughput and IDR recovery counters."""
        now = time.monotonic() if now is None else now
        window_started = self._stats_snapshot_at or self._stats_started_at
        elapsed = (
            max(0.001, now - window_started)
            if window_started > 0.0
            else 0.0
        )
        frames_total = self._stats_frames_total
        producer_suppressed_total = self._stats_producer_suppressed_total
        frames = frames_total - self._stats_snapshot_frames
        producer_suppressed = (
            producer_suppressed_total
            - self._stats_snapshot_producer_suppressed
        )
        with self._stats_lock:
            idr_requests_total = self._stats_idr_requests_total
            idr_recoveries_total = self._stats_idr_recoveries_total
            idr_requests = (
                idr_requests_total - self._stats_snapshot_idr_requests
            )
            idr_recoveries = (
                idr_recoveries_total - self._stats_snapshot_idr_recoveries
            )
            recovery_samples = tuple(self._stats_idr_recovery_samples_ms)
            idr_pending = int(self._stats_idr_pending_since > 0.0)
            if reset:
                self._stats_snapshot_idr_requests = idr_requests_total
                self._stats_snapshot_idr_recoveries = idr_recoveries_total
                self._stats_idr_recovery_samples_ms.clear()
        ordered_recoveries = sorted(recovery_samples)
        recovery_p95 = (
            ordered_recoveries[
                min(
                    len(ordered_recoveries) - 1,
                    max(0, math.ceil(len(ordered_recoveries) * 0.95) - 1),
                )
            ]
            if ordered_recoveries
            else 0
        )
        stats = {
            "frames": frames,
            "fps_x100": (
                round((frames / elapsed) * 100)
                if elapsed > 0.0
                else 0
            ),
            "idr_requests": idr_requests,
            "idr_recoveries": idr_recoveries,
            "idr_recovery_p95_ms": recovery_p95,
            "idr_recovery_max_ms": max(ordered_recoveries, default=0),
            "idr_pending": idr_pending,
            "producer_suppressed": producer_suppressed,
            "max_fps_cap_x100": self._max_fps * 100,
        }
        if reset:
            # Counters stay monotonic so a producer racing this snapshot cannot
            # be zeroed out and lost; only the observation baseline advances.
            self._stats_snapshot_at = now
            self._stats_snapshot_frames = frames_total
            self._stats_snapshot_producer_suppressed = (
                producer_suppressed_total
            )
        return stats

    def _wake_display(self) -> None:
        """Best-effort wake — Samsung/Exynos often ACK RESET_VIDEO but emit no frames while dozing."""
        _adb("shell", "input keyevent KEYCODE_WAKEUP", serial=self._serial, timeout=5)
        _adb("shell", "svc power stayon true", serial=self._serial, timeout=5)

    def _mark_idr_needed(self) -> None:
        """Called from asyncio thread when a P-frame is dropped from send_queue.
        Relay thread reads this flag and requests an IDR keyframe immediately."""
        self._downstream_recovery.set()
        self._need_idr = True

    def notify_downstream_drop(self) -> None:
        """Enter decoder recovery after a downstream delta drop."""
        self._mark_idr_needed()

    def _mark_downstream_resynced(self) -> None:
        """Stop producer-side suppression after config/key reaches the lane."""
        self._need_idr = False
        self._downstream_recovery.clear()

    def notify_downstream_resynced(self) -> None:
        """Leave decoder recovery after a keyframe is admitted."""
        self._mark_downstream_resynced()

    @property
    def recovery_pending(self) -> bool:
        """Whether downstream decode recovery still needs a keyframe."""
        return self._need_idr

    def request_pending_idr_if_due(self, now: float) -> bool:
        """Send one pending recovery request when its rate limit permits."""
        if (
            not self._need_idr
            or now - self._last_idr_request_t < _IDR_REQUEST_MIN_GAP
        ):
            return False
        if not self.request_recovery_keyframe(now=now):
            raise RuntimeError("scrcpy IDR control unavailable")
        self._need_idr = False
        return True

    def is_alive(self) -> bool:
        """True while relay thread is running (not zombie)."""
        t = self._relay_thread
        return t is not None and t.is_alive()

    def is_streaming(self) -> bool:
        """True only after the current scrcpy socket handshake succeeds."""
        return self.is_alive() and self._stream_ready.is_set()

    def matches_config(
        self,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        bitrate: int,
        low_latency: bool,
    ) -> bool:
        """Return True when a duplicate start request can reuse this live session."""
        return (
            self._max_fps == (max_fps or SCRCPY_DEFAULT_MAX_FPS)
            and self._max_width == (max_width or SCRCPY_DEFAULT_MAX_WIDTH)
            and self._enable_touch_control == bool(enable_control)
            and self._port == port
            and self._bitrate == (bitrate or SCRCPY_DEFAULT_BITRATE)
            and self._low_latency == bool(low_latency)
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _relay_loop(self) -> None:
        """
        Outer reconnect loop.

        Strategy:
          - Start scrcpy-server once; only restart if it has died.
          - On socket/stream failure, try reconnecting to the EXISTING server first.
          - Kill + restart server only every 3rd consecutive failure (avoids constant churn).
          - Retry budget is window-based: _MAX_RECONNECTS per _RETRY_WINDOW seconds.
            Failures outside the window reset the counter → transient flaps don't
            exhaust the budget over the device's lifetime.
          - _on_fatal is guaranteed to fire exactly once if the thread ever exits
            while _running is True — even on unexpected exceptions (try/finally).
        """
        delay = _RECONNECT_BASE
        server_alive = False
        window_start = time.monotonic()
        exit_reason: Optional[str] = None

        stream_started = time.monotonic()
        try:
            while self._running:
                try:
                    # (Re)start server only if it is dead or has never been started.
                    if not server_alive or not self._is_server_running():
                        self._start_scrcpy_server()
                        server_alive = True

                    if not self._running:
                        break

                    # Connect sockets and stream until error or stop.
                    self._stream_ready.clear()
                    stream_started = time.monotonic()
                    self._connect_and_stream()

                    # Clean exit — reset counters.
                    delay = _RECONNECT_BASE
                    self._reconnect_count = 0
                    window_start = time.monotonic()
                    server_alive = self._is_server_running()

                except Exception as exc:
                    if not self._running:
                        break

                    # A session that streamed successfully for >10s then died is
                    # a normal transient stall (idle encoder, WiFi blip). Reset
                    # the backoff ladder so the viewer's black window is capped
                    # at _RECONNECT_BASE, not the ramp-up 30s tail.
                    session_lived_s = time.monotonic() - stream_started
                    if session_lived_s > 10.0:
                        delay = _RECONNECT_BASE

                    # Window-based budget: reset counter if we're past the window.
                    now = time.monotonic()
                    if now - window_start > _RETRY_WINDOW:
                        self._reconnect_count = 0
                        window_start = now

                    self._reconnect_count += 1
                    if self._reconnect_count > _MAX_RECONNECTS:
                        logger.error(
                            "[%s] scrcpy: max reconnects (%d) exceeded in %.0fs window — giving up",
                            self._serial, _MAX_RECONNECTS, _RETRY_WINDOW,
                        )
                        exit_reason = "runtime_error"
                        break

                    logger.warning(
                        "[%s] scrcpy error (attempt %d/%d): %s — retry in %.1fs",
                        self._serial, self._reconnect_count, _MAX_RECONNECTS, exc, delay,
                    )
                    self._close_sockets()
                    server_running = self._is_server_running()
                    if not server_running:
                        # A purged/corrupt JAR commonly makes app_process exit
                        # before the socket opens. Re-verify on the next start
                        # instead of trusting the process-local deploy cache.
                        invalidate_scrcpy_server_jar(self._serial)

                    # Every 3rd failure force-restart the server (catches hung scrcpy).
                    if self._reconnect_count % 3 == 0 or not server_running:
                        logger.info("[%s] restarting scrcpy-server (attempt %d)", self._serial, self._reconnect_count)
                        self._kill_server()
                        server_alive = False

                    time.sleep(delay)
                    delay = min(delay * 2, _RECONNECT_MAX)

            # Normal termination path (either stop() called or budget exhausted).
            if exit_reason is None and self._running:
                # Loop exited with running=True but no reason — defensive: treat as
                # runtime_error so the callback can trigger a restart.
                exit_reason = "runtime_error"

        except BaseException as exc:  # includes KeyboardInterrupt / SystemExit
            logger.exception("[%s] scrcpy relay thread crashed: %s", self._serial, exc)
            # Interpreter-shutdown signals are NOT runtime errors — the whole
            # process is going away, so we must not tell the farm to restart
            # this session. Leave exit_reason unset in that case.
            if not isinstance(exc, (KeyboardInterrupt, SystemExit)):
                exit_reason = "runtime_error"
            raise
        finally:
            # Guarantee the callback fires exactly once if _running is still True
            # (i.e. we didn't exit via stop()). This is the load-bearing fix —
            # without try/finally, silent thread exits leave the farm server
            # unaware that the stream is dead.
            if exit_reason and not self._callback_fired and self._on_fatal:
                self._callback_fired = True
                try:
                    self._on_fatal(self._serial, exit_reason)
                except Exception as cb_exc:
                    logger.warning("[%s] on_fatal callback failed: %s", self._serial, cb_exc)

    # ── Server lifecycle ─────────────────────────────────────────────────────

    def _is_server_running(self) -> bool:
        """True if the adb shell (scrcpy) subprocess is still alive."""
        p = self._server_proc
        return p is not None and p.poll() is None

    def _load_device_oem_hints(self) -> tuple[str, str]:
        """Best-effort OEM/model detection (cached per session)."""
        if self._oem_hint and self._model_hint:
            return self._oem_hint, self._model_hint
        oem = ""
        model = ""
        out_oem, _ = _adb("shell", "getprop ro.product.brand", serial=self._serial, timeout=4)
        out_model, _ = _adb("shell", "getprop ro.product.model", serial=self._serial, timeout=4)
        oem = (out_oem or "").strip().splitlines()[-1].strip().lower() if out_oem.strip() else ""
        model = (out_model or "").strip().splitlines()[-1].strip().lower() if out_model.strip() else ""
        self._oem_hint = oem
        self._model_hint = model
        return self._oem_hint, self._model_hint

    def _ensure_server_jar_on_device(self) -> None:
        """Push scrcpy-server JAR if missing OR size doesn't match bundled copy.

        Called before every _start_scrcpy_server() attempt. The versioned path
        cannot be removed or overwritten by bootstrap bundle extraction, and
        temp+rename prevents a reconnect from observing a partial push.
        """
        deployment_key = (self._serial, self._jar_version)
        with _SCRCPY_JAR_DEPLOY_CONDITION:
            while deployment_key in _SCRCPY_JAR_DEPLOYING:
                _SCRCPY_JAR_DEPLOY_CONDITION.wait()
            if deployment_key in _SCRCPY_JAR_READY:
                return
            _SCRCPY_JAR_DEPLOYING.add(deployment_key)

        try:
            self._verify_or_deploy_server_jar()
        except BaseException:
            with _SCRCPY_JAR_DEPLOY_CONDITION:
                _SCRCPY_JAR_DEPLOYING.discard(deployment_key)
                _SCRCPY_JAR_DEPLOY_CONDITION.notify_all()
            raise
        else:
            with _SCRCPY_JAR_DEPLOY_CONDITION:
                _SCRCPY_JAR_DEPLOYING.discard(deployment_key)
                _SCRCPY_JAR_READY.add(deployment_key)
                _SCRCPY_JAR_DEPLOY_CONDITION.notify_all()

    def _verify_or_deploy_server_jar(self) -> None:
        """Verify once, deploying atomically only on confirmed absence/mismatch."""
        expected_size = _BUNDLED_JAR.stat().st_size
        # `stat -c %s` returns size, or empty/error if file missing.
        out, stat_rc = _adb(
            "shell",
            f"stat -c '%s' {_SCRCPY_PATH_ON_DEVICE} 2>/dev/null",
            serial=self._serial,
            timeout=5,
        )
        # Defensive parse: adb daemon can prepend warnings ("* daemon not
        # running; starting now *", "device unauthorized"). Pick the last
        # all-numeric token instead of trusting the whole stdout.
        device_size = ""
        for token in out.split():
            if token.isdigit():
                device_size = token
        if stat_rc == 0 and device_size == str(expected_size):
            return
        confirmed_missing = stat_rc == 1 and not out.strip()
        if stat_rc != 0 and not confirmed_missing:
            raise RuntimeError(
                f"verify scrcpy JAR failed (rc={stat_rc}): {out.strip()}"
            )
        if stat_rc == 0 and not device_size:
            raise RuntimeError(
                f"verify scrcpy JAR failed: unexpected stat output {out.strip()!r}"
            )
        logger.info(
            "[%s] pushing scrcpy-server %s (device_size=%r expected=%d)",
            self._serial, self._jar_version, device_size, expected_size,
        )
        out, rc = _adb(
            "shell",
            f"mkdir -p {_SCRCPY_DEVICE_DIR}",
            serial=self._serial,
            timeout=5,
        )
        if rc != 0:
            raise RuntimeError(f"create scrcpy directory failed: {out.strip()}")
        temp_path = f"{_SCRCPY_PATH_ON_DEVICE}.tmp"
        out, rc = _adb(
            "push", str(_BUNDLED_JAR), temp_path,
            serial=self._serial, timeout=20,
        )
        if rc != 0:
            raise RuntimeError(f"adb push failed: {out.strip()}")
        out, rc = _adb(
            "shell",
            f"mv -f {temp_path} {_SCRCPY_PATH_ON_DEVICE}",
            serial=self._serial,
            timeout=5,
        )
        if rc != 0:
            raise RuntimeError(f"activate scrcpy JAR failed: {out.strip()}")

    def _start_scrcpy_server(self) -> None:
        """
        Kill any leftover scrcpy on device, push JAR if needed, then start
        scrcpy-server via adb shell + set up adb forward.

        No codec options are passed — let Android's H264 encoder use its
        defaults.  Forcing profile/level is the #1 cause of encoder crashes
        on newer Android versions (API 34+).
        """
        self._kill_server()

        # Re-verify JAR on device before every (re)start. OEM cleanup daemons
        # can purge /data/local/tmp between attempts; without this check the
        # retry loop runs forever launching `app_process` against a missing
        # CLASSPATH → ClassNotFoundException → SIGABRT.
        self._ensure_server_jar_on_device()

        # Kill any orphaned scrcpy-server on device.
        # pkill returns 0 if it killed ≥1 process, non-zero if nothing was found.
        _, pkill_rc = _adb("shell", "pkill -f 'app_process.*com.genymobile.scrcpy.Server'",
                           serial=self._serial, timeout=5)
        if pkill_rc == 0:
            # Old process killed — wait for localabstract:scrcpy to be released.
            # Poll /proc/net/unix instead of sleeping 2s flat: socket typically
            # releases within 200-500ms, saving ~1.5s on every reconnect.
            deadline = time.monotonic() + 2.5
            while time.monotonic() < deadline:
                out, _ = _adb(
                    "shell",
                    "grep -c 'scrcpy' /proc/net/unix 2>/dev/null || echo 0",
                    serial=self._serial,
                    timeout=3,
                )
                if out.strip() == "0":
                    break
                time.sleep(0.15)
        else:
            time.sleep(0.3)  # Nothing killed — small buffer for adb state settle

        ctrl_flag = "true" if self._enable_control_channel else "false"

        # Tier 1 env overrides — per-serial first, fall back to global default.
        # Empty codec override keeps current behavior (h264). Empty encoder
        # override lets scrcpy auto-pick.
        codec = _per_serial_env("SCRCPY_VIDEO_CODEC", self._serial, _VIDEO_CODEC_DEFAULT)
        encoder = _per_serial_env("SCRCPY_VIDEO_ENCODER", self._serial, _VIDEO_ENCODER_DEFAULT)
        oem, model = self._load_device_oem_hints()
        # Samsung/Vivo Android 16 can repeatedly stall with this software encoder
        # in relay mode. Prefer scrcpy auto-pick so OEM-specific hardware encoders
        # (or HEVC fallback for allowlisted OEMs) can be selected.
        if oem in {"samsung", "vivo"} and encoder in {
            "c2.android.avc.encoder",
            "c2.qti.avc.encoder",
        }:
            logger.warning(
                "[%s] dropping unstable encoder override on %s (%s): %s -> auto",
                self._serial,
                oem or "?",
                model or "?",
                encoder,
            )
            encoder = ""
        # Vivo/Oppo/Realme/OnePlus on newer Android + Codec2 frequently stall on
        # static screens with H264. If user did not pin codec/encoder, prefer HEVC.
        if (
            codec == "h264"
            and not encoder
            and _HEVC_OEM_ALLOWLIST
            and not _codec_explicit_for_serial(self._serial)
        ):
            if oem in _HEVC_OEM_ALLOWLIST:
                codec = "h265"
                logger.info(
                    "[%s] auto codec fallback: h264 -> h265 (oem=%s model=%s)",
                    self._serial,
                    oem or "?",
                    model or "?",
                )
        elif (
            codec == "h264"
            and not encoder
            and oem == "vivo"
            and _VIVO_H264_ENCODER_DEFAULT
            and not _codec_explicit_for_serial(self._serial)
        ):
            encoder = _VIVO_H264_ENCODER_DEFAULT
            logger.info(
                "[%s] vivo H.264 encoder pin: %s (model=%s)",
                self._serial,
                encoder,
                model or "?",
            )
        encoder_arg = f" video_encoder={encoder}" if encoder else ""
        if encoder or codec != "h264":
            logger.info(
                "[%s] scrcpy encoder override: codec=%s encoder=%s",
                self._serial, codec, encoder or "(auto)",
            )
        codec_options = ["i-frame-interval:int=1", "max-bframes:int=0"]
        if codec == "h264" and _H264_BASELINE_DEFAULT:
            # Chrome/WebCodecs on some operators' machines rejects the default
            # Android High profile stream (avc1.64001e), leaving the dashboard
            # black. Baseline keeps the stream browser-decodable and avoids
            # B/CABAC reorder behavior that adds latency.
            codec_options.insert(0, "profile:int=1")
        if self._low_latency:
            codec_options.append("latency:int=0")

        server_cmd = (
            f"CLASSPATH={_SCRCPY_PATH_ON_DEVICE} "
            f"app_process / com.genymobile.scrcpy.Server {self._jar_version} "
            f"tunnel_forward=true video=true audio=false control={ctrl_flag} "
            f"video_codec={codec}{encoder_arg} max_fps={self._max_fps} max_size={self._max_width} "
            f"video_bit_rate={self._bitrate} "
            f"video_codec_options={','.join(codec_options)} "
            f"stay_awake=true cleanup={str(_SCRCPY_CLEANUP_DEFAULT).lower()} "
            f"send_device_meta=true send_frame_meta=true"
        )

        # Clean env so adb subprocess doesn't spam "MallocStackLogging: process
        # is not in a debuggable environment …" on every start. Matches the
        # cleanup done in the _adb() helper.
        env = os.environ.copy()
        env.pop("MallocStackLogging", None)
        env.pop("MallocStackLoggingDirectory", None)
        env.pop("MallocStackLoggingNoCompact", None)

        with adb_admission(serial=self._serial, lane=AdbLane.STARTUP):
            self._server_proc = subprocess.Popen(
                _adb_command("shell", server_cmd, serial=self._serial),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )

        # Log server output in background — critical for diagnosing encoder crashes.
        serial = self._serial
        proc   = self._server_proc

        def _log_server_output() -> None:
            noisy_last_logged: dict[str, float] = {}
            noisy_patterns = (
                "INFO: Video capture reset",
                "DEBUG: Display: using ",
            )
            try:
                for raw in proc.stdout:  # type: ignore[union-attr]
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        noisy_key = next(
                            (pattern for pattern in noisy_patterns if pattern in line),
                            "",
                        )
                        if noisy_key:
                            now = time.monotonic()
                            last = noisy_last_logged.get(noisy_key, 0.0)
                            if now - last < 30.0:
                                logger.debug("[%s] scrcpy-server: %s", serial, line)
                                continue
                            noisy_last_logged[noisy_key] = now
                        logger.info("[%s] scrcpy-server: %s", serial, line)
            except Exception:
                pass

        threading.Thread(target=_log_server_output, daemon=True).start()

        # Set up adb forward — do this after starting the server so the daemon
        # is aware of the process (helps on some adb versions).
        out, rc = _adb(
            "forward", f"tcp:{self._port}", "localabstract:scrcpy",
            serial=self._serial, timeout=10,
        )
        if rc != 0:
            raise RuntimeError(f"adb forward failed: {out.strip()}")

        fwd_host = _adb_forward_host()
        logger.info(
            "[%s] scrcpy-server started, forward %s:%d → localabstract:scrcpy",
            self._serial, fwd_host, self._port,
        )

    # ── Socket connect + stream ──────────────────────────────────────────────

    def _connect_and_stream(self) -> None:
        """Connect sockets, read handshake, then stream H264 frames until error."""

        fwd_host = _adb_forward_host()

        # 1. Connect video socket — poll until scrcpy binds localabstract:scrcpy.
        #    _connect_with_retry retries until scrcpy accepts OR timeout expires.
        video_sock = self._connect_with_retry(fwd_host, self._port, timeout=10.0)
        video_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        _enable_tcp_keepalive(video_sock)
        # Frame-timeout: socket.recv raises socket.timeout after _FRAME_TIMEOUT seconds
        # of silence. Catches hung streams where TCP is alive but the encoder stalled.
        # Handshake needs longer grace — temporarily unset, restore before streaming.
        video_sock.settimeout(None)
        self._video_sock = video_sock

        # 2. Connect control socket before reading handshake.
        #    scrcpy sends the dummy byte only AFTER all expected sockets connect.
        if self._enable_control_channel:
            ctrl_sock = self._connect_with_retry(fwd_host, self._port, timeout=5.0)
            ctrl_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            _enable_tcp_keepalive(ctrl_sock)
            ctrl_sock.settimeout(None)
            with self._ctrl_lock:
                self._ctrl_sock = ctrl_sock
            threading.Thread(
                target=self._drain_ctrl, args=(ctrl_sock,), daemon=True
            ).start()

        # 3. Read handshake — scrcpy sends this after all sockets are connected.
        #    Use select() with a long timeout to wait for the dummy byte; a short
        #    recv would mask the difference between "server slow to start" and "crash".
        import select as _select
        ready, _, _ = _select.select([video_sock], [], [], 15.0)
        if not ready:
            raise RuntimeError("scrcpy handshake timeout (15s) — server may have crashed")
        _recvall(video_sock, 1)           # dummy byte (0x00)
        _recvall(video_sock, 64)          # device name (null-padded)
        meta = _recvall(video_sock, 12)   # codec_id(u32) + width(u32) + height(u32)
        _, w, h = struct.unpack(">III", meta)
        if w and h:
            self._device_width  = w
            self._device_height = h
        self._stream_ready.set()
        logger.info("[%s] handshake OK — %dx%d", self._serial, self._device_width, self._device_height)

        # 4. Stream H264 packets → gRPC send_queue.
        serial   = self._serial
        w, h = self._device_width, self._device_height

        # Two-stage frame recovery:
        #  1. socket timeout at _IDR_REQUEST_AFTER — if hit before first frame, ask
        #     scrcpy-server for an IDR keyframe and retry. Fixes the "frozen
        #     screen" case where the decoder is stuck on a corrupt NAL after
        #     WiFi packet loss; recovery ~200ms.
        #  2. if we STILL have no frame _FRAME_TIMEOUT seconds after the last
        #     good frame → encoder genuinely stalled → raise, outer loop
        #     reconnects the session.
        video_sock.settimeout(_IDR_REQUEST_AFTER)
        saw_video_frame = False
        last_good_frame = time.monotonic()
        idr_wait_started = 0.0
        idr_window_start = 0.0
        idr_request_count = 0

        def _read_header_or_idr() -> bytes:
            nonlocal last_good_frame, idr_wait_started, idr_window_start, idr_request_count
            while True:
                try:
                    return _recvall(video_sock, 12)
                except socket.timeout:
                    now = time.monotonic()
                    if saw_video_frame:
                        if self.request_pending_idr_if_due(now):
                            if idr_wait_started <= 0.0:
                                idr_wait_started = now
                                idr_window_start = now
                                idr_request_count = 0
                            idr_request_count += 1
                            logger.debug("[%s] IDR requested after downstream recovery signal", self._serial)
                        if idr_wait_started > 0.0:
                            elapsed = now - idr_wait_started
                            if elapsed >= _FRAME_TIMEOUT:
                                raise RuntimeError(
                                    f"scrcpy frame timeout after IDR ({_FRAME_TIMEOUT:.1f}s) — encoder stalled"
                                )
                            if now - self._last_idr_request_t >= _IDR_REQUEST_MIN_GAP:
                                if (now - idr_window_start) > _IDR_REQUEST_WINDOW:
                                    idr_window_start = now
                                    idr_request_count = 0
                                if not self.request_recovery_keyframe(now=now):
                                    raise RuntimeError(
                                        "scrcpy IDR control unavailable"
                                    )
                                idr_request_count += 1
                                logger.debug(
                                    "[%s] scrcpy: %.1fs without frame after IDR — retry %d",
                                    self._serial,
                                    elapsed,
                                    idr_request_count,
                                )
                                if idr_request_count >= _IDR_MAX_REQUESTS:
                                    raise RuntimeError(
                                        "scrcpy repeated no-frame stalls after IDR "
                                        f"({idr_request_count} IDR requests/{_IDR_REQUEST_WINDOW:.1f}s) "
                                        "— forcing session restart"
                                    )
                        continue
                    elapsed = now - last_good_frame
                    if elapsed >= _FRAME_TIMEOUT:
                        raise RuntimeError(
                            f"scrcpy frame timeout ({_FRAME_TIMEOUT:.1f}s) — encoder stalled"
                        )
                    now = time.monotonic()
                    if now - self._last_idr_request_t >= _IDR_REQUEST_MIN_GAP:
                        if not self.request_recovery_keyframe(now=now):
                            raise RuntimeError(
                                "scrcpy IDR control unavailable"
                            )
                        if idr_window_start <= 0 or (now - idr_window_start) > _IDR_REQUEST_WINDOW:
                            idr_window_start = now
                            idr_request_count = 0
                        idr_request_count += 1
                        # Multi-day stability: only log first IDR per stall
                        # episode at INFO; subsequent retries go to DEBUG so a
                        # stuck OEM encoder cannot fill GB of logs in a week.
                        if idr_request_count == 1:
                            logger.info(
                                "[%s] scrcpy: %.1fs without frame — requested IDR keyframe",
                                self._serial, elapsed,
                            )
                        elif idr_request_count == 3:
                            logger.info(
                                "[%s] scrcpy: %.1fs without frame — waking display (IDR retry %d)",
                                self._serial, elapsed, idr_request_count,
                            )
                            self._wake_display()
                        else:
                            logger.debug(
                                "[%s] scrcpy: %.1fs without frame — IDR retry %d",
                                self._serial, elapsed, idr_request_count,
                            )
                        if idr_request_count >= _IDR_MAX_REQUESTS:
                            raise RuntimeError(
                                "scrcpy repeated no-frame stalls "
                                f"({idr_request_count} IDR requests/{_IDR_REQUEST_WINDOW:.1f}s) "
                                "— forcing session restart"
                            )
                    # keep waiting; loop continues
                    continue

        while self._running:
            # If a P-frame was dropped from the send queue (set by asyncio thread),
            # request an IDR keyframe so the browser decoder recovers in ~100ms
            # rather than waiting up to 1s for the next natural IDR interval.
            if self._need_idr:
                now = time.monotonic()
                if self.request_pending_idr_if_due(now):
                    if idr_wait_started <= 0.0:
                        idr_wait_started = now
                        idr_window_start = now
                        idr_request_count = 0
                    idr_request_count += 1
                    logger.debug("[%s] IDR requested after P-frame queue drop", self._serial)

            header = _read_header_or_idr()
            pts_raw, size = struct.unpack(">QI", header)
            try:
                data = _recvall(video_sock, size)
            except socket.timeout:
                raise RuntimeError(f"scrcpy mid-frame timeout ({_IDR_REQUEST_AFTER}s) — encoder stalled mid-NAL")
            received_ns = time.monotonic_ns()

            is_cfg = bool(pts_raw & _PTS_CONFIG_MASK)
            frame = prepare_video_packet(
                serial=serial,
                annexb=data,
                is_config=is_cfg,
                pts_us=int(pts_raw & ~_PTS_CONFIG_MASK),
                width=w,
                height=h,
                received_ns=received_ns,
                suppress_deltas=self._downstream_recovery.is_set(),
            )

            if not is_cfg:
                saw_video_frame = True
                last_good_frame = time.monotonic()
                if frame is None:
                    self.last_frame_time = last_good_frame
                    self.record_video_frame(
                        is_key=False,
                        now=last_good_frame,
                    )
                    self._stats_producer_suppressed_total += 1
                    continue
                idr_wait_started = 0.0
                # We got a real video frame again — clear the stall window so
                # future bursts are measured independently. Config/SPS packets
                # after a capture reset do not prove the encoder recovered.
                idr_window_start = 0.0
                idr_request_count = 0

                self.last_frame_time = time.monotonic()
                self.record_video_frame(
                    is_key=frame.is_key,
                    now=last_good_frame,
                )

            if frame is None:
                continue

            # Dispatch via module-level function. Pass _mark_idr_needed so the
            # asyncio thread can signal back when a P-frame is dropped.
            self._loop.call_soon_threadsafe(
                enqueue_video_packet,
                self._send_queue,
                frame,
                self.notify_downstream_drop,
                self.notify_downstream_resynced,
            )

    def _connect_with_retry(self, host: str, port: int, timeout: float) -> socket.socket:
        """
        Connect to host:port, retrying every 150ms until *timeout* seconds.

        adb forward accepts the TCP connection immediately even when scrcpy hasn't
        bound localabstract:scrcpy yet — adb then closes it (EOF).  We detect this
        via MSG_PEEK with a 0.5s window (long enough for WiFi ADB round-trip latency).

          • recv(MSG_PEEK) returns b'' → EOF → not ready → retry
          • recv(MSG_PEEK) times out  → connection is open, scrcpy is starting → return
          • recv(MSG_PEEK) returns data → connection alive and data ready → return
        """
        deadline = time.monotonic() + timeout
        last_exc: Exception = ConnectionRefusedError("never tried")
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                # 0.15s peek — matches the retry interval; long enough for USB ADB
                # A_OPEN/A_CLSE round-trip (WiFi ADB may take ~100ms).
                # Using 0.15s instead of 0.5s saves up to 350ms on first connect.
                sock.settimeout(0.15)
                try:
                    peek = sock.recv(1, socket.MSG_PEEK)
                    if not peek:
                        raise ConnectionError("adb forward EOF — scrcpy not ready yet")
                    # Data already available → connection alive with data
                except socket.timeout:
                    pass  # No data yet but connection is open → scrcpy is starting
                sock.settimeout(None)
                return sock
            except Exception as exc:
                last_exc = exc
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(0.15)
        raise RuntimeError(
            f"scrcpy-server not ready on {host}:{port} after {timeout}s — {last_exc}"
        )

    def _close_sockets(self) -> None:
        self._stream_ready.clear()
        for attr in ("_video_sock", "_ctrl_sock"):
            s = getattr(self, attr, None)
            if s:
                try:
                    s.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        with self._ctrl_lock:
            self._ctrl_sock = None

    def _kill_server(self) -> None:
        proc = self._server_proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
        self._server_proc = None

    def _drain_ctrl(self, sock: socket.socket) -> None:
        """Discard device→host messages on the control socket to prevent buffer fill."""
        buf = bytearray(4096)
        while self._running:
            try:
                n = sock.recv_into(buf)
                if n == 0:
                    break
            except Exception:
                break
