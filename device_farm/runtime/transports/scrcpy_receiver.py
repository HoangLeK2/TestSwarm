
from __future__ import annotations

import io
import logging
import select
import socket
import struct
import subprocess
import threading
import time
from typing import Callable, Optional

import av
import numpy as np


SCRCPY_SERVER_PATH_ON_DEVICE = "/data/local/tmp/scrcpy-server"
SCRCPY_SERVER_VERSION = "3.3.4"  # Must match scrcpy-server JAR (BuildConfig.VERSION_NAME)

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
    """

    def __init__(
        self,
        serial: str,
        adb_path: str,
        port: int,
        server_jar: str,        # path to scrcpy-server on host machine
        max_fps: int = 30,
        max_width: int = 800,   # downscale for bandwidth; 0 = no limit
        reconnect_delay: float = 2.0,
    ) -> None:
        super().__init__(daemon=True, name=f"scrcpy-{serial}")
        self.serial = serial
        self.adb_path = adb_path
        self.port = port
        self.server_jar = server_jar
        self.max_fps = max_fps
        self.max_width = max_width
        self.reconnect_delay = reconnect_delay

        self._logger = logging.getLogger(f"scrcpy.{serial}")
        self._lock = threading.Lock()
        self._running = False
        self._latest_jpeg: Optional[bytes] = None
        self._last_frame_time: float = 0.0
        self._server_proc: Optional[subprocess.Popen] = None

        # Optional callback for each decoded JPEG frame (used in ADB mode to pipe
        # frames directly into DeviceClient.publish_frame()).
        self._on_frame: Optional[Callable[[bytes], None]] = None

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

    def _connect_and_stream(self) -> None:
        """Start scrcpy-server on device and stream H264."""

        # Start server process on device
        cmd = [
            self.adb_path, "-s", self.serial, "shell",
            f"CLASSPATH={SCRCPY_SERVER_PATH_ON_DEVICE} "
            f"app_process / com.genymobile.scrcpy.Server "
            f"{SCRCPY_SERVER_VERSION} "
            f"tunnel_forward=true "          # use adb forward (not reverse)
            f"video=true "
            f"audio=false "
            f"control=false "                # read-only, no input
            f"video_codec=h264 "
            f"max_fps={self.max_fps} "
            f"max_size={self.max_width} "
            f"video_bit_rate=2000000 "       # 2 Mbps
            f"send_device_meta=true "
            f"send_frame_meta=true "
            f"raw_video_stream=false"
        ]
        self._server_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(0.8)  # Give server time to bind socket

        if self._server_proc.poll() is not None:
            raise RuntimeError("scrcpy-server exited immediately")

        # Connect video socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect(("127.0.0.1", self.port))
            sock.settimeout(None)
            self._logger.info(f"[{self.serial}] scrcpy connected on port {self.port}")

            # scrcpy 3.x protocol: 1 dummy byte, 64-byte device name, 12-byte codec meta
            _recvall(sock, 1)   # dummy byte (forward connection)
            device_name_buf = _recvall(sock, 64)
            device_name = device_name_buf.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            codec_meta = _recvall(sock, 12)  # codec_id(u32) + width(u32) + height(u32)
            _codec_id, width, height = struct.unpack(">III", codec_meta)
            self.device_width = width
            self.device_height = height
            self._logger.info(
                f"[{self.serial}] scrcpy device: {device_name} {width}x{height}"
            )

            # Decode H264 stream using PyAV
            self._decode_stream(sock)

        finally:
            sock.close()
            if self._server_proc and self._server_proc.poll() is None:
                self._server_proc.terminate()

    def _decode_stream(self, sock: socket.socket) -> None:
        """Read scrcpy H264 packets and decode to JPEG via PyAV."""
        codec = av.CodecContext.create("h264", "r")

        while self._running:
            header = _recvall(sock, 12)
            pts_raw, size = struct.unpack(">QI", header)
            data = _recvall(sock, size)

            is_config = bool(pts_raw & PTS_CONFIG_MASK)
            # Drop display if socket still has data queued (we're behind)
            ready, _, _ = select.select([sock], [], [], 0)
            behind = bool(ready) and not is_config

            try:
                packet = av.Packet(data)
                frames = codec.decode(packet)
                for frame in frames:
                    if is_config or behind:
                        continue
                    jpeg_bytes = self._frame_to_jpeg(frame, quality=70)
                    with self._lock:
                        self._latest_jpeg = jpeg_bytes
                        self._last_frame_time = time.monotonic()
                    cb = self._on_frame
                    if cb is not None:
                        try:
                            cb(jpeg_bytes)
                        except Exception:
                            # Don't let callback failures kill the scrcpy loop
                            pass
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
