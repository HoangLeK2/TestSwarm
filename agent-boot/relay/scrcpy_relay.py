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
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("relay.scrcpy")

_SCRCPY_PATH_ON_DEVICE = "/data/local/tmp/scrcpy-server"
_CACHE_DIR = Path.home() / ".cache" / "device-farm"
_PTS_CONFIG_MASK = 0x8000_0000_0000_0000
_ADB = shutil.which("adb") or "adb"

# Bundled JAR — agent-boot owns the scrcpy-server binary, no need to receive
# it from the farm server over gRPC.
_BUNDLED_JAR = Path(__file__).parent / "scrcpy-server"
_BUNDLED_JAR_VERSION = "3.3.4"

def _is_idr(data: bytes) -> bool:
    """Return True if the first NAL unit in Annex-B data is an IDR (type 5).

    scrcpy sends exactly one NAL unit per packet, so checking the first
    start code is both sufficient and O(1) — no full-frame scan needed.
    """
    n = len(data)
    if n < 5:
        return False
    # 4-byte start code: 0x00 0x00 0x00 0x01
    if data[0] == 0 and data[1] == 0 and data[2] == 0 and data[3] == 1:
        return (data[4] & 0x1F) == 5
    # 3-byte start code: 0x00 0x00 0x01
    if n >= 4 and data[0] == 0 and data[1] == 0 and data[2] == 1:
        return (data[3] & 0x1F) == 5
    return False


def _relay_enqueue(q: asyncio.Queue, frame: bytes, is_cfg: bool, is_key: bool) -> None:
    """Module-level enqueue — avoids closure allocation per frame at 30fps.

    Called via call_soon_threadsafe from the relay thread.
    Drop-oldest strategy: P-frames silently dropped when queue full;
    IDR/config frames evict the oldest entry to guarantee delivery.
    """
    try:
        q.put_nowait(frame)
    except asyncio.QueueFull:
        if not is_cfg and not is_key:
            return  # P-frame: drop silently, decoder resyncs on next IDR
        try:
            q.get_nowait()   # evict oldest to make room for IDR/config
            q.put_nowait(frame)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass


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


def _per_serial_env(base: str, serial: str, fallback: str) -> str:
    """
    Lookup per-serial env override first, fall back to default.
    Serial format `10AE7S00HD002JK` → env key `<BASE>__10AE7S00HD002JK`.
    WiFi serial `1.2.3.4:5555` → strip colons → `<BASE>__1_2_3_4_5555`.
    """
    safe = serial.replace(":", "_").replace(".", "_")
    key = f"{base}__{safe}"
    return os.environ.get(key, fallback).strip()

# Soft IDR threshold: if we go this many seconds without a frame, request an
# IDR keyframe from scrcpy-server before hitting the hard frame timeout. This
# recovers from decoder-freeze-on-dropped-NAL ~200ms vs full restart ~2-3s.
_IDR_REQUEST_AFTER = float(os.environ.get("SCRCPY_IDR_REQUEST_AFTER_S", "1.5"))

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
    parts = [struct.pack(">I", len(nal)) + nal for nal in _SC_RE.split(data) if nal]
    return b"".join(parts) if parts else data


def _recvall(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"scrcpy socket closed (expected {n}, got {len(buf)})")
        buf.extend(chunk)
    return bytes(buf)


def _adb(*args: str, serial: Optional[str] = None, timeout: int = 15) -> tuple[str, int]:
    """Run `adb [-s serial] <args>`. Returns (output, returncode). Never raises."""
    cmd = [_ADB]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    # Suppress macOS MallocStackLogging spam
    env = os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
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
        self._max_fps        = max_fps or 30
        self._max_width      = max_width or 800
        self._enable_control = enable_control
        self._bitrate        = bitrate or 2_000_000
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

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self) -> None:
        """Non-blocking entry point: push JAR (once), then start relay loop thread."""
        # For TCP/WiFi devices ensure adb connection is established first.
        # USB devices (serial without ':') don't need this.
        if ":" in self._serial:
            out, rc = _adb("connect", self._serial, timeout=10)
            if "connected" not in out.lower() and "already connected" not in out.lower():
                raise RuntimeError(f"adb connect {self._serial} failed: {out.strip()}")
            logger.info("[%s] adb connected", self._serial)

        # Ensure JAR is on device. Stamp file alone is not trustworthy:
        # bootstrap.py's `rm -rf scrcpy-server` removes the JAR but leaves the
        # stamp (different filename), and some OEMs (Vivo/Honor anti-tamper)
        # silently purge binaries from /data/local/tmp while leaving zero-byte
        # marker files intact. Verify the JAR itself + size match the bundled
        # copy; otherwise re-push.
        self._ensure_server_jar_on_device()

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

    def send_control(self, data: bytes) -> None:
        """Forward raw scrcpy control bytes to device (thread-safe)."""
        with self._ctrl_lock:
            sock = self._ctrl_sock
        if sock and self._running:
            try:
                sock.sendall(data)
            except Exception as exc:
                logger.debug("[%s] ctrl send: %s", self._serial, exc)

    def _request_idr(self) -> None:
        """
        Ask scrcpy-server to emit an IDR keyframe NOW. Used by the streaming
        loop when frames stop arriving — forces decoder re-sync ~200ms instead
        of tearing down the session. No-op if control socket not connected.

        Wire format: 1 byte message type (_SC_CTRL_RESET_VIDEO). Tied to the
        bundled scrcpy-server version — see _BUNDLED_JAR_VERSION.
        """
        self.send_control(bytes([_SC_CTRL_RESET_VIDEO]))

    def is_alive(self) -> bool:
        """True while relay thread is running (not zombie)."""
        t = self._relay_thread
        return t is not None and t.is_alive()

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

        try:
            while self._running:
                try:
                    # (Re)start server only if it is dead or has never been started.
                    if not server_alive or not self._is_server_running():
                        self._start_scrcpy_server()
                        server_alive = True

                    # Connect sockets and stream until error or stop.
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

                    # Every 3rd failure force-restart the server (catches hung scrcpy).
                    if self._reconnect_count % 3 == 0 or not self._is_server_running():
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

    def _ensure_server_jar_on_device(self) -> None:
        """Push scrcpy-server JAR if missing OR size doesn't match bundled copy.

        Called both at start() AND before every _start_scrcpy_server() retry.
        Retries are necessary because some OEMs (Vivo Android 16, Honor) wipe
        binaries from /data/local/tmp asynchronously, and the previous logic
        only pushed once at session start.
        """
        expected_size = _BUNDLED_JAR.stat().st_size
        # `stat -c %s` returns size, or empty/error if file missing.
        out, _rc = _adb(
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
        if device_size == str(expected_size):
            return
        logger.info(
            "[%s] pushing scrcpy-server %s (device_size=%r expected=%d)",
            self._serial, self._jar_version, device_size, expected_size,
        )
        out, rc = _adb(
            "push", str(_BUNDLED_JAR), _SCRCPY_PATH_ON_DEVICE,
            serial=self._serial, timeout=20,
        )
        if rc != 0:
            raise RuntimeError(f"adb push failed: {out.strip()}")

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

        ctrl_flag = "true" if self._enable_control else "false"

        # Tier 1 env overrides — per-serial first, fall back to global default.
        # Empty codec override keeps current behavior (h264). Empty encoder
        # override lets scrcpy auto-pick.
        codec = _per_serial_env("SCRCPY_VIDEO_CODEC", self._serial, _VIDEO_CODEC_DEFAULT)
        encoder = _per_serial_env("SCRCPY_VIDEO_ENCODER", self._serial, _VIDEO_ENCODER_DEFAULT)
        encoder_arg = f" video_encoder={encoder}" if encoder else ""
        if encoder or codec != "h264":
            logger.info(
                "[%s] scrcpy encoder override: codec=%s encoder=%s",
                self._serial, codec, encoder or "(auto)",
            )

        server_cmd = (
            f"CLASSPATH={_SCRCPY_PATH_ON_DEVICE} "
            f"app_process / com.genymobile.scrcpy.Server {self._jar_version} "
            f"tunnel_forward=true video=true audio=false control={ctrl_flag} "
            f"video_codec={codec}{encoder_arg} max_fps={self._max_fps} max_size={self._max_width} "
            f"video_bit_rate={self._bitrate} "
            # i-frame-interval:int=1 → faster decoder recovery after dropped deltas
            # when multiple devices stream concurrently over WiFi relay.
            # latency:int=0 (KEY_LATENCY): encoder outputs every frame immediately;
            #   no internal buffer → saves 66-133 ms. Only enabled on API ≤ 33 (farm
            #   sets low_latency=True); crashes MediaCodec on some API 34+ OEM builds.
            # NOTE: profile/level options omitted — crash MediaCodec on API 34+.
            f"video_codec_options=i-frame-interval:int=1,max-bframes:int=0"
            + (",latency:int=0" if self._low_latency else "")
            + " "
            f"stay_awake=true "
            f"send_device_meta=true send_frame_meta=true"
        )

        # Clean env so adb subprocess doesn't spam "MallocStackLogging: process
        # is not in a debuggable environment …" on every start. Matches the
        # cleanup done in the _adb() helper.
        env = os.environ.copy()
        env.pop("MallocStackLogging", None)
        env.pop("MallocStackLoggingDirectory", None)
        env.pop("MallocStackLoggingNoCompact", None)

        self._server_proc = subprocess.Popen(
            [_ADB, "-s", self._serial, "shell", server_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

        # Log server output in background — critical for diagnosing encoder crashes.
        serial = self._serial
        proc   = self._server_proc

        def _log_server_output() -> None:
            try:
                for raw in proc.stdout:  # type: ignore[union-attr]
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
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

        logger.info("[%s] scrcpy-server started, forward tcp:%d → localabstract:scrcpy",
                    self._serial, self._port)

    # ── Socket connect + stream ──────────────────────────────────────────────

    def _connect_and_stream(self) -> None:
        """Connect sockets, read handshake, then stream H264 frames until error."""

        # 1. Connect video socket — poll until scrcpy binds localabstract:scrcpy.
        #    _connect_with_retry retries until scrcpy accepts OR timeout expires.
        video_sock = self._connect_with_retry("127.0.0.1", self._port, timeout=10.0)
        video_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        _enable_tcp_keepalive(video_sock)
        # Frame-timeout: socket.recv raises socket.timeout after _FRAME_TIMEOUT seconds
        # of silence. Catches hung streams where TCP is alive but the encoder stalled.
        # Handshake needs longer grace — temporarily unset, restore before streaming.
        video_sock.settimeout(None)
        self._video_sock = video_sock

        # 2. Connect control socket before reading handshake.
        #    scrcpy sends the dummy byte only AFTER all expected sockets connect.
        if self._enable_control:
            ctrl_sock = self._connect_with_retry("127.0.0.1", self._port, timeout=5.0)
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
        logger.info("[%s] handshake OK — %dx%d", self._serial, self._device_width, self._device_height)

        # 4. Stream H264 packets → gRPC send_queue.
        serial   = self._serial
        serial_b = serial.encode()   # cached once — never changes for this session
        slen     = len(serial_b)
        w, h = self._device_width, self._device_height

        # Two-stage frame recovery:
        #  1. socket timeout at _IDR_REQUEST_AFTER (~1.5s) — if hit, ask
        #     scrcpy-server for an IDR keyframe and retry. Fixes the "frozen
        #     screen" case where the decoder is stuck on a corrupt NAL after
        #     WiFi packet loss; recovery ~200ms.
        #  2. if we STILL have no frame _FRAME_TIMEOUT seconds after the last
        #     good frame → encoder genuinely stalled → raise, outer loop
        #     reconnects the session.
        video_sock.settimeout(_IDR_REQUEST_AFTER)
        last_good_frame = time.monotonic()
        idr_requested = False

        def _read_header_or_idr() -> bytes:
            nonlocal last_good_frame, idr_requested
            while True:
                try:
                    return _recvall(video_sock, 12)
                except socket.timeout:
                    elapsed = time.monotonic() - last_good_frame
                    if elapsed >= _FRAME_TIMEOUT:
                        raise RuntimeError(
                            f"scrcpy frame timeout ({_FRAME_TIMEOUT:.1f}s) — encoder stalled"
                        )
                    if not idr_requested:
                        self._request_idr()
                        idr_requested = True
                        logger.info(
                            "[%s] scrcpy: %.1fs without frame — requested IDR keyframe",
                            self._serial, elapsed,
                        )
                    # keep waiting; loop continues
                    continue

        while self._running:
            header = _read_header_or_idr()
            pts_raw, size = struct.unpack(">QI", header)
            try:
                data = _recvall(video_sock, size)
            except socket.timeout:
                raise RuntimeError(f"scrcpy mid-frame timeout ({_IDR_REQUEST_AFTER}s) — encoder stalled mid-NAL")

            last_good_frame = time.monotonic()
            idr_requested = False

            self.last_frame_time = time.monotonic()

            is_cfg = bool(pts_raw & _PTS_CONFIG_MASK)
            is_key = (not is_cfg) and _is_idr(data)

            # Convert video frames Annex-B → AVCC here in the relay thread so the
            # farm's asyncio event loop never has to do the O(n) conversion at 30fps.
            # Config frames (SPS/PPS) are left as Annex-B — farm handles them via
            # annexb_to_avcc_record_maybe in _handle_config (rare, only at start).
            if not is_cfg:
                data = _annexb_to_avcc(data)

            # Binary frame: [0x53][flags][slen][serial][w:2BE][h:2BE][pts_raw:8BE][data]
            # flags: bit0=is_config, bit1=is_keyframe
            flags = (0x01 if is_cfg else 0) | (0x02 if is_key else 0)
            frame = (
                struct.pack(">BBB", 0x53, flags, slen)
                + serial_b
                + struct.pack(">HHQ",
                              w if is_cfg else 0,
                              h if is_cfg else 0,
                              pts_raw)
                + data
            )

            # Dispatch via module-level function (no closure allocation per frame).
            self._loop.call_soon_threadsafe(
                _relay_enqueue, self._send_queue, frame, is_cfg, is_key
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

