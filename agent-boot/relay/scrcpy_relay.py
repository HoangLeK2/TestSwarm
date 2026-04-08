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
import threading
import time
from pathlib import Path
from typing import Optional

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


_MAX_RECONNECTS = 10
_RECONNECT_BASE = 2.0    # seconds
_RECONNECT_MAX  = 30.0   # seconds cap

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

        self._video_sock: Optional[socket.socket] = None
        self._ctrl_sock:  Optional[socket.socket] = None
        self._ctrl_lock   = threading.Lock()

        # Stats used by SessionManager
        self.last_frame_time: float = 0.0
        self._reconnect_count: int  = 0

        # Set on first successful handshake; constant for this session
        self._device_width:  int = 0
        self._device_height: int = 0

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

        # Push bundled JAR only if not already present on the device.
        # Both JAR and stamp must exist — a reboot wipes /data/local/tmp.
        stamp_path = _SCRCPY_PATH_ON_DEVICE + f".{self._jar_version}.ok"
        check_cmd = (
            f"test -f {_SCRCPY_PATH_ON_DEVICE} && "
            f"test -f {stamp_path} && echo ok"
        )
        out, rc = _adb("shell", check_cmd, serial=self._serial, timeout=5)
        if "ok" not in out:
            logger.info("[%s] pushing scrcpy-server %s", self._serial, self._jar_version)
            out, rc = _adb("push", str(_BUNDLED_JAR), _SCRCPY_PATH_ON_DEVICE,
                           serial=self._serial, timeout=20)
            if rc != 0:
                raise RuntimeError(f"adb push failed: {out.strip()}")
            _adb("shell", f"touch {stamp_path}", serial=self._serial, timeout=5)
        else:
            logger.info("[%s] scrcpy-server already on device — skipping push", self._serial)

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
        """
        delay = _RECONNECT_BASE
        server_alive = False

        while self._running:
            try:
                # (Re)start server only if it is dead or has never been started.
                if not server_alive or not self._is_server_running():
                    self._start_scrcpy_server()
                    server_alive = True

                # Connect sockets and stream until error or stop.
                self._connect_and_stream()

                # Clean exit — reset counters.
                delay = _RECONNECT_BASE
                self._reconnect_count = 0
                server_alive = self._is_server_running()

            except Exception as exc:
                if not self._running:
                    break
                self._reconnect_count += 1
                if self._reconnect_count > _MAX_RECONNECTS:
                    logger.error(
                        "[%s] scrcpy: max reconnects (%d) exceeded — giving up",
                        self._serial, _MAX_RECONNECTS,
                    )
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

    # ── Server lifecycle ─────────────────────────────────────────────────────

    def _is_server_running(self) -> bool:
        """True if the adb shell (scrcpy) subprocess is still alive."""
        p = self._server_proc
        return p is not None and p.poll() is None

    def _start_scrcpy_server(self) -> None:
        """
        Kill any leftover scrcpy on device, push JAR if needed, then start
        scrcpy-server via adb shell + set up adb forward.

        No codec options are passed — let Android's H264 encoder use its
        defaults.  Forcing profile/level is the #1 cause of encoder crashes
        on newer Android versions (API 34+).
        """
        self._kill_server()

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
        server_cmd = (
            f"CLASSPATH={_SCRCPY_PATH_ON_DEVICE} "
            f"app_process / com.genymobile.scrcpy.Server {self._jar_version} "
            f"tunnel_forward=true video=true audio=false control={ctrl_flag} "
            f"video_codec=h264 max_fps={self._max_fps} max_size={self._max_width} "
            f"video_bit_rate={self._bitrate} "
            # i-frame-interval:int=4 → IDR every 4 seconds to reduce keyframe bursts
            # when multiple devices stream concurrently over WiFi relay.
            # latency:int=0 (KEY_LATENCY): encoder outputs every frame immediately;
            #   no internal buffer → saves 66-133 ms. Only enabled on API ≤ 33 (farm
            #   sets low_latency=True); crashes MediaCodec on some API 34+ OEM builds.
            # NOTE: profile/level options omitted — crash MediaCodec on API 34+.
            f"video_codec_options=i-frame-interval:int=4,max-bframes:int=0"
            + (",latency:int=0" if self._low_latency else "")
            + " "
            f"stay_awake=true "
            f"send_device_meta=true send_frame_meta=true"
        )

        self._server_proc = subprocess.Popen(
            [_ADB, "-s", self._serial, "shell", server_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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
        video_sock.settimeout(None)
        self._video_sock = video_sock

        # 2. Connect control socket before reading handshake.
        #    scrcpy sends the dummy byte only AFTER all expected sockets connect.
        if self._enable_control:
            ctrl_sock = self._connect_with_retry("127.0.0.1", self._port, timeout=5.0)
            ctrl_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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

        while self._running:
            header = _recvall(video_sock, 12)
            pts_raw, size = struct.unpack(">QI", header)
            data = _recvall(video_sock, size)

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

