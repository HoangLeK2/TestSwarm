
from __future__ import annotations

import io
import logging
import socket
import struct
import subprocess
import threading
import time
from typing import Callable, Optional

import av

from runtime.transports.scrcpy_control import ScrcpyControl


SCRCPY_SERVER_PATH_ON_DEVICE = "/data/local/tmp/scrcpy-server"
SCRCPY_SERVER_VERSION = "3.3.4" 

# Packet flags
PTS_CONFIG_MASK = 0x8000_0000_0000_0000  # set on codec-config (SPS/PPS) packets


log = logging.getLogger(__name__)


def _recvall(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"scrcpy socket closed (expected {n}, got {len(buf)})")
        buf.extend(chunk)
    return bytes(buf)


class ScrcpyReceiver(threading.Thread):
    """
    Daemon thread that connects to scrcpy-server on device and decodes
    the H264 stream into JPEG frames at up to 60 FPS.

    When enable_control=True, also establishes a control socket for
    sending touch/key/text events via ScrcpyControl.
    """

    def __init__(
        self,
        serial: str,
        adb_path: str,
        port: int,
        server_jar: str,
        max_fps: int = 30,
        max_width: int = 800,
        reconnect_delay: float = 2.0,
        enable_control: bool = False,
        on_frame: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        super().__init__(daemon=True, name=f"scrcpy-{serial}")
        self.serial = serial
        self.adb_path = adb_path
        self.port = port
        self.server_jar = server_jar
        self.max_fps = max_fps
        self.max_width = max_width
        self.reconnect_delay = reconnect_delay
        self.enable_control = enable_control

        self._logger = logging.getLogger(f"scrcpy.{serial}")
        self._lock = threading.Lock()
        self._ctrl_lock = threading.Lock()  # protects self.control reads/writes
        self._running = False
        self._latest_jpeg: Optional[bytes] = None
        self._last_frame_time: float = 0.0
        self._server_proc: Optional[subprocess.Popen] = None
        self.on_frame: Optional[Callable[[bytes], None]] = on_frame

        # ScrcpyControl instance (set when enable_control=True and connected)
        self.control: Optional[ScrcpyControl] = None
        self._control_sock: Optional[socket.socket] = None
        self._device_msg_thread: Optional[threading.Thread] = None

        # Screen dimensions reported by scrcpy
        self.device_width: int = 0
        self.device_height: int = 0

    # ── Public API ──────────────────────────────────────────────────────────

    def start_receiver(self) -> None:
        self._running = True
        if not self.is_alive():
            self.start()

    def stop_receiver(self) -> None:
        self._running = False
        with self._ctrl_lock:
            if self.control is not None:
                self.control.disconnect()
                self.control = None
        self._control_sock = None
        if self._device_msg_thread is not None:
            self._device_msg_thread.join(timeout=1.0)
            self._device_msg_thread = None
        if self._server_proc and self._server_proc.poll() is None:
            self._server_proc.terminate()

    def get_latest_frame(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_last_frame_age(self) -> float:
        with self._lock:
            if self._last_frame_time == 0.0:
                return float("inf")
            return time.monotonic() - self._last_frame_time

    # ── Internal ────────────────────────────────────────────────────────────

    def run(self) -> None:
        while self._running:
            try:
                self._push_server()
                self._connect_and_stream()
            except Exception as exc:
                if self._running:
                    self._logger.warning(
                        f"[{self.serial}] scrcpy error: {exc}; "
                        f"reconnecting in {self.reconnect_delay}s"
                    )
                    time.sleep(self.reconnect_delay)

    def _push_server(self) -> None:
        """Push scrcpy-server JAR to device (idempotent)."""
        result = subprocess.run(
            [self.adb_path, "-s", self.serial, "push",
             self.server_jar, SCRCPY_SERVER_PATH_ON_DEVICE],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to push scrcpy-server: {result.stderr}")
        self._logger.debug(f"[{self.serial}] scrcpy-server pushed")

    def _setup_adb_forward(self) -> None:
        """Set up adb forward tcp:PORT localabstract:scrcpy.
        scrcpy-server with tunnel_forward=true listens on abstract Unix socket 'scrcpy'."""
        result = subprocess.run(
            [self.adb_path, "-s", self.serial, "forward",
             f"tcp:{self.port}", "localabstract:scrcpy"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"adb forward failed: {result.stderr.strip()}")
        self._logger.debug(f"[{self.serial}] adb forward tcp:{self.port} localabstract:scrcpy")

    def _remove_adb_forward(self) -> None:
        """Remove adb forward rule."""
        try:
            subprocess.run(
                [self.adb_path, "-s", self.serial, "forward",
                 "--remove", f"tcp:{self.port}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    def _connect_and_stream(self) -> None:
        """Start scrcpy-server on device and stream H264 (+ optional control)."""

        control_flag = "true" if self.enable_control else "false"

        # Start server process on device FIRST — it must bind localabstract:scrcpy
        cmd = [
            self.adb_path, "-s", self.serial, "shell",
            f"CLASSPATH={SCRCPY_SERVER_PATH_ON_DEVICE} "
            f"app_process / com.genymobile.scrcpy.Server "
            f"{SCRCPY_SERVER_VERSION} "
            f"tunnel_forward=true "          # server listens on localabstract:scrcpy
            f"video=true "
            f"audio=false "
            f"control={control_flag} "
            f"video_codec=h264 "
            f"max_fps={self.max_fps} "
            f"max_size={self.max_width} "
            f"video_bit_rate=8000000 "       # 8 Mbps for smooth video
            f"send_device_meta=true "
            f"send_frame_meta=true "
            f"raw_video_stream=false"
        ]
        # IMPORTANT: stdout/stderr must be DEVNULL, NOT PIPE.
        # If piped and never read, the 64KB pipe buffer fills up and scrcpy-server
        # blocks on any log write — including from the control thread, which makes
        # touch/key injection hang silently.
        self._server_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(1.2)  # Give server time to bind abstract socket

        if self._server_proc.poll() is not None:
            raise RuntimeError("scrcpy-server exited immediately")

        # Set up adb forward AFTER server has bound localabstract:scrcpy
        self._setup_adb_forward()

        # scrcpy v3.x with tunnel_forward=true and control=true:
        # Server accepts sockets in order: video, (audio), control.
        # It sends the dummy byte on video socket ONLY AFTER all sockets are connected.
        # So we must connect ALL sockets first, then read handshake.

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        ctrl_sock: Optional[socket.socket] = None
        try:
            # 1. Connect video socket (first accept on server)
            sock.connect(("127.0.0.1", self.port))
            sock.settimeout(None)
            self._logger.info(f"[{self.serial}] scrcpy video socket connected on port {self.port}")

            # 2. Connect control socket BEFORE reading handshake (second accept on server)
            #    Server won't send dummy byte until all expected sockets are connected.
            if self.enable_control:
                ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                ctrl_sock.settimeout(5.0)
                ctrl_sock.connect(("127.0.0.1", self.port))
                ctrl_sock.settimeout(None)
                self._control_sock = ctrl_sock
                self._logger.info(f"[{self.serial}] scrcpy control socket connected")

            # 3. Now read handshake from video socket (server sends after all sockets ready)
            #    scrcpy 3.x protocol: 1 dummy byte, 64-byte device name, 12-byte codec meta
            _recvall(sock, 1)   # dummy byte
            device_name_buf = _recvall(sock, 64)
            device_name = device_name_buf.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            codec_meta = _recvall(sock, 12)  # codec_id(u32) + width(u32) + height(u32)
            _codec_id, width, height = struct.unpack(">III", codec_meta)
            self.device_width = width
            self.device_height = height
            self._logger.info(
                f"[{self.serial}] scrcpy handshake OK: {device_name} {width}x{height}"
            )

            # 4. Wrap control socket with ScrcpyControl + drain device messages
            if ctrl_sock is not None:
                ctrl = ScrcpyControl(
                    control_sock=ctrl_sock,
                    screen_width=width,
                    screen_height=height,
                    serial=self.serial,
                )
                with self._ctrl_lock:
                    self.control = ctrl
                # Drain thread: read & discard device messages (clipboard, ACK, UHid).
                # Without this, server's write buffer fills → blocks control thread.
                self._device_msg_thread = threading.Thread(
                    target=self._drain_device_messages,
                    args=(ctrl_sock,),
                    daemon=True,
                    name=f"scrcpy-devmsg-{self.serial}",
                )
                self._device_msg_thread.start()
                self._logger.info(
                    f"[{self.serial}] scrcpy control ready (screen {width}x{height})"
                )

            # 5. Decode H264 stream using PyAV
            self._decode_stream(sock)

        finally:
            sock.close()
            with self._ctrl_lock:
                if self.control is not None:
                    self.control.disconnect()
                    self.control = None
            self._control_sock = None
            if self._device_msg_thread is not None:
                self._device_msg_thread.join(timeout=1.0)
                self._device_msg_thread = None
            if self._server_proc and self._server_proc.poll() is None:
                self._server_proc.terminate()
                try:
                    self._server_proc.wait(timeout=3)
                except Exception:
                    pass
            self._remove_adb_forward()

    def _drain_device_messages(self, sock: socket.socket) -> None:
        """Read and discard device messages from scrcpy control socket.

        scrcpy server sends clipboard, ACK, UHid messages back. If never read,
        the kernel socket buffer fills up (~128KB) and the server's write() blocks,
        which also blocks the control message reader thread — making all touch/key
        injection hang silently.
        """
        buf = bytearray(4096)
        while self._running:
            try:
                n = sock.recv_into(buf)
                if n == 0:
                    break  # Socket closed
            except Exception:
                break
        self._logger.debug(f"[{self.serial}] device message drain stopped")

    def _decode_stream(self, sock: socket.socket) -> None:
        """Read scrcpy H264 packets and decode to JPEG via PyAV."""
        codec = av.CodecContext.create("h264", "r")
        _fps_count = 0
        _fps_t0 = time.monotonic()

        while self._running:
            t_read0 = time.monotonic()
            header = _recvall(sock, 12)
            pts_raw, size = struct.unpack(">QI", header)
            data = _recvall(sock, size)
            t_read = time.monotonic() - t_read0

            # Config (SPS/PPS) packets: feed to codec but produce no displayable frames
            is_config = bool(pts_raw & PTS_CONFIG_MASK)

            try:
                packet = av.Packet(data)
                frames = codec.decode(packet)
                for frame in frames:
                    if is_config:
                        continue
                    t_jpg0 = time.monotonic()
                    jpeg_bytes = self._frame_to_jpeg(frame, quality=80)
                    t_jpg = time.monotonic() - t_jpg0

                    t_pub0 = time.monotonic()
                    with self._lock:
                        self._latest_jpeg = jpeg_bytes
                        self._last_frame_time = time.monotonic()
                    cb = self.on_frame
                    if cb is not None:
                        try:
                            cb(jpeg_bytes)
                        except Exception:
                            pass
                    t_pub = time.monotonic() - t_pub0

                    _fps_count += 1
                    now = time.monotonic()
                    if now - _fps_t0 >= 10.0:
                        fps = _fps_count / (now - _fps_t0)
                        self._logger.info(
                            f"[{self.serial}] scrcpy FPS={fps:.1f} "
                            f"read={t_read*1000:.0f}ms "
                            f"jpg={t_jpg*1000:.0f}ms "
                            f"pub={t_pub*1000:.0f}ms"
                        )
                        _fps_count = 0
                        _fps_t0 = now
            except Exception as exc:
                self._logger.debug(f"[{self.serial}] decode error: {exc}")

    @staticmethod
    def _frame_to_jpeg(frame: av.VideoFrame, quality: int = 75) -> bytes:
        """Convert PyAV VideoFrame to JPEG bytes.
        Uses PIL (av+cv2 both bundle libavdevice → objc conflicts on macOS).
        """
        img = frame.to_image()
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()
