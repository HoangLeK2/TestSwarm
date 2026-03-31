
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

from runtime.transports.h264_utils import (
    annexb_to_avcc_maybe,
    annexb_to_avcc_record_maybe,
    _is_annexb,
)
from runtime.transports.scrcpy_control import ScrcpyControl


SCRCPY_SERVER_PATH_ON_DEVICE = "/data/local/tmp/scrcpy-server"
SCRCPY_SERVER_VERSION = "3.3.4"

# Packet flags
PTS_CONFIG_MASK = 0x8000_0000_0000_0000  # set on codec-config (SPS/PPS) packets

# NAL unit type 5 = IDR (keyframe)
_IDR_NAL_TYPE = 5


log = logging.getLogger(__name__)


def _is_idr(avcc_data: bytes) -> bool:
    if not avcc_data:
        return False
    if avcc_data[:4] == b"\x00\x00\x00\x01" or avcc_data[:3] == b"\x00\x00\x01":
        i = 0
        n = len(avcc_data)
        while i < n - 2:
            if i + 3 < n and avcc_data[i:i+4] == b"\x00\x00\x00\x01":
                nal_start = i + 4
                if nal_start < n and (avcc_data[nal_start] & 0x1F) == _IDR_NAL_TYPE:
                    return True
                i = nal_start
            elif avcc_data[i:i+3] == b"\x00\x00\x01":
                nal_start = i + 3
                if nal_start < n and (avcc_data[nal_start] & 0x1F) == _IDR_NAL_TYPE:
                    return True
                i = nal_start
            else:
                i += 1
        return False
    # AVCC format: iterate length-prefixed NAL units
    i = 0
    n = len(avcc_data)
    while i + 4 <= n:
        length = struct.unpack(">I", avcc_data[i:i+4])[0]
        i += 4
        if length == 0 or i + length > n:
            break
        nal_type = avcc_data[i] & 0x1F
        if nal_type == _IDR_NAL_TYPE:
            return True
        i += length
    return False


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
        on_h264_config: Optional[Callable[[bytes, int, int, bool], None]] = None,
        on_h264_packet: Optional[Callable[[bytes, bool, int], None]] = None,
    ) -> None:
        """
        on_frame(jpeg_bytes)                       — JPEG fallback (take_screenshot / periodic mode)
        on_h264_config(avcc_record, w, h, changed) — fires on every SPS/PPS config packet.
                                                      changed=True when SPS/PPS differs from last
                                                      seen (rotation / resolution / reconnect) →
                                                      browser must reset VideoDecoder before
                                                      reconfiguring.
        on_h264_packet(avcc_data, is_key, pts_us)  — fires per video frame; relay raw AVCC to
                                                      browser (no server-side decode needed).
                                                      P-frames are gated until next IDR after
                                                      any SPS/PPS change.

        When on_h264_packet is set, JPEG encoding is skipped for live streaming —
        on_frame is still called for screenshot/periodic-mode consumers.
        """
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
        self.on_h264_config: Optional[Callable[[bytes, int, int], None]] = on_h264_config
        self.on_h264_packet: Optional[Callable[[bytes, bool, int], None]] = on_h264_packet

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
            # Android MediaCodec H264 options (values = MediaCodecInfo constants,
            # NOT H264 spec profile_idc):
            #   profile=1     AVCProfileBaseline  → no B-frames, no CABAC.
            #                 B-frames cause display_order≠decode_order →
            #                 WebCodecs reorder buffer → latency spike.
            #   level=4096    AVCLevel4 (0x1000)  → supports up to 1080p@30fps.
            #   latency=0     KEY_LATENCY=0       → encoder outputs frame
            #                 immediately; default buffers 2-4 frames (~66-133ms
            #                 at 30fps) before first output.
            f"video_codec_options=profile:int=1,level:int=4096,latency:int=0 "
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
        """Read scrcpy H264 packets and relay to browser via WebCodecs (primary path)
        or decode to JPEG (fallback / screenshot path).

        WebCodecs relay (when on_h264_packet is set):
          - Config packets  → on_h264_config(avcc_record, w, h)
          - Video packets   → on_h264_packet(avcc_data, is_key, pts_us)
          - No server-side decode; no JPEG encode per frame
          - JPEG still produced at keyframes for take_screenshot() consumers

        JPEG-only mode (when on_h264_packet is None):
          - Every frame decoded and JPEG-encoded as before
        """
        # PyAV codec kept for screenshot path (keyframe → JPEG)
        codec = av.CodecContext.create("h264", "r")
        _fps_count = 0
        _fps_t0 = time.monotonic()
        _relay_mode = self.on_h264_packet is not None

        # SPS/PPS lifecycle state — local to this stream session.
        # Reset on every reconnect (_connect_and_stream → _decode_stream).
        _active_avcc_record: Optional[bytes] = None  # last seen SPS/PPS bytes
        _waiting_for_idr: bool = False               # gate: drop frames until IDR

        while self._running:
            t_read0 = time.monotonic()
            header = _recvall(sock, 12)
            pts_raw, size = struct.unpack(">QI", header)
            data = _recvall(sock, size)
            t_read = time.monotonic() - t_read0

            is_config = bool(pts_raw & PTS_CONFIG_MASK)
            pts_us = pts_raw & ~PTS_CONFIG_MASK  # strip config flag to get real PTS

            # ── WebCodecs relay path ─────────────────────────────────────────
            if _relay_mode:
                if is_config:
                    try:
                        avcc_record = annexb_to_avcc_record_maybe(data)
                    except Exception as exc:
                        self._logger.debug(f"[{self.serial}] h264 config parse error: {exc}")
                        avcc_record = data

                    # Detect SPS/PPS change: rotation / resolution / reconnect all produce
                    # a new config packet with different bytes. When changed:
                    #   1. Recreate PyAV codec (old state invalid for new SPS/PPS)
                    #   2. Gate video packets until next IDR (P-frames from old stream
                    #      cannot be decoded with new SPS/PPS → garbage / decoder crash)
                    #   3. Signal browser to reset VideoDecoder before reconfiguring
                    config_changed = (
                        _active_avcc_record is not None
                        and _active_avcc_record != avcc_record
                    )
                    if config_changed:
                        self._logger.info(
                            f"[{self.serial}] SPS/PPS changed — resetting codec, waiting for IDR"
                        )
                        codec = av.CodecContext.create("h264", "r")  # fresh codec
                        _waiting_for_idr = True

                    _active_avcc_record = avcc_record

                    cb_cfg = self.on_h264_config
                    if cb_cfg is not None:
                        try:
                            cb_cfg(avcc_record, self.device_width, self.device_height, config_changed)
                        except Exception as exc:
                            self._logger.debug(f"[{self.serial}] h264 config relay error: {exc}")

                    # Feed config to codec so keyframe JPEG decode works after config change
                    try:
                        codec.decode(av.Packet(data))
                    except Exception:
                        pass
                    continue

                # Video packet: convert Annex-B → AVCC if needed, detect keyframe
                try:
                    avcc_data = annexb_to_avcc_maybe(data)
                except Exception:
                    avcc_data = data

                # Detect IDR (keyframe) from NAL unit type
                is_key = _is_idr(avcc_data)

                # IDR gate: after SPS/PPS change or initial startup, drop delta frames
                # until the first IDR arrives. A P-frame without a preceding I-frame
                # decoded with the new parameters → garbage output or VideoDecoder crash.
                if _waiting_for_idr:
                    if not is_key:
                        _fps_count += 1  # count dropped frames for FPS log accuracy
                        now = time.monotonic()
                        if now - _fps_t0 >= 10.0:
                            dropped = _fps_count
                            self._logger.info(
                                f"[{self.serial}] waiting for IDR, dropped {dropped} frames"
                            )
                            _fps_count = 0
                            _fps_t0 = now
                        continue  # drop P-frame
                    # IDR arrived — clear gate
                    _waiting_for_idr = False
                    self._logger.info(f"[{self.serial}] IDR received, relay resumed")

                # Relay to browser (zero-copy, no decode)
                cb_pkt = self.on_h264_packet
                if cb_pkt is not None:
                    try:
                        cb_pkt(avcc_data, is_key, pts_us)
                    except Exception as exc:
                        self._logger.debug(f"[{self.serial}] h264 packet relay error: {exc}")

                # Update last_frame_time for capture settle guard
                with self._lock:
                    self._last_frame_time = time.monotonic()

                # Decode to JPEG only on keyframes — for take_screenshot() consumers
                if is_key:
                    try:
                        packet = av.Packet(data)
                        frames = codec.decode(packet)
                        for frame in frames:
                            jpeg_bytes = self._frame_to_jpeg(frame, quality=80)
                            with self._lock:
                                self._latest_jpeg = jpeg_bytes
                            cb = self.on_frame
                            if cb is not None:
                                try:
                                    cb(jpeg_bytes)
                                except Exception:
                                    pass
                            break  # only first frame per keyframe
                    except Exception as exc:
                        self._logger.debug(f"[{self.serial}] keyframe jpeg error: {exc}")

                _fps_count += 1
                now = time.monotonic()
                if now - _fps_t0 >= 10.0:
                    fps = _fps_count / (now - _fps_t0)
                    self._logger.info(
                        f"[{self.serial}] scrcpy relay FPS={fps:.1f} "
                        f"read={t_read*1000:.0f}ms mode=webcodecs"
                    )
                    _fps_count = 0
                    _fps_t0 = now
                continue

            # ── JPEG-only fallback path (on_h264_packet not set) ─────────────
            try:
                packet = av.Packet(data)
                frames = codec.decode(packet)
                for frame in frames:
                    if is_config:
                        continue
                    t_jpg0 = time.monotonic()
                    jpeg_bytes = self._frame_to_jpeg(frame, quality=80)
                    t_jpg = time.monotonic() - t_jpg0

                    with self._lock:
                        self._latest_jpeg = jpeg_bytes
                        self._last_frame_time = time.monotonic()
                    cb = self.on_frame
                    if cb is not None:
                        try:
                            cb(jpeg_bytes)
                        except Exception:
                            pass

                    _fps_count += 1
                    now = time.monotonic()
                    if now - _fps_t0 >= 10.0:
                        fps = _fps_count / (now - _fps_t0)
                        self._logger.info(
                            f"[{self.serial}] scrcpy FPS={fps:.1f} "
                            f"read={t_read*1000:.0f}ms "
                            f"jpg={t_jpg*1000:.0f}ms mode=jpeg"
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
