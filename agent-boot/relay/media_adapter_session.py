"""Session facade for streams owned by the Go media adapter.

This module deliberately does not open scrcpy sockets, parse H264, manage GOPs,
or enqueue video frames. Python only keeps the control-plane intent so the
existing relay lifecycle can start/stop streams while the Go adapter owns the
media hot path end to end.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from relay.media_adapter import (
    direct_scrcpy_status,
    per_serial_env,
    request_direct_keyframe,
    start_direct_scrcpy_stream,
    stop_direct_scrcpy_stream,
)

logger = logging.getLogger("relay.media_adapter_session")

_RESET_VIDEO = 17


class MediaAdapterScrcpySession:
    def __init__(
        self,
        serial: str,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        send_queue,
        loop,
        bitrate: int = 2_000_000,
        low_latency: bool = False,
        on_fatal: Optional[Callable[[str, str], None]] = None,
        on_health: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        del send_queue, loop, on_health
        self.serial = serial
        self._max_fps = max_fps
        self._max_width = max_width
        self._enable_control = bool(enable_control)
        self._requested_port = port
        self._bitrate = bitrate
        self._low_latency = bool(low_latency)
        self._on_fatal = on_fatal
        self._running = False
        self._stopped = False
        self._started_at = 0.0
        self._snapshot_at = 0.0
        self._snapshot_frames = 0
        self._frames_total = 0
        self._idr_total = 0
        self._stream_errors_total = 0
        self._handshake_recorded = False
        self._first_frame_recorded = False
        self._connect_to_handshake_ms: list[int] = []
        self._connect_to_first_frame_ms: list[int] = []
        self._start_to_handshake_ms: list[int] = []
        self._start_to_first_frame_ms: list[int] = []
        self.last_frame_time = 0.0

    def start(self) -> None:
        self._started_at = time.monotonic()
        self._snapshot_at = self._started_at
        self._stopped = False
        logger.info(
            "[%s] media adapter owner start fps=%d width=%d bitrate=%d",
            self.serial,
            self._max_fps,
            self._max_width,
            self._bitrate,
        )
        start_direct_scrcpy_stream(
            serial=self.serial,
            host="",
            port=0,
            control=self._enable_control,
            owns_scrcpy=True,
            max_fps=self._max_fps,
            max_width=self._max_width,
            bitrate=self._bitrate,
            video_codec=per_serial_env("SCRCPY_VIDEO_CODEC", self.serial, "h264"),
            low_latency=self._low_latency,
        )
        self._running = True

    def stop(self) -> None:
        self._stopped = True
        self._running = False
        stop_direct_scrcpy_stream(self.serial)

    def pause_forwarding(self, *, reason: str = "warm_idle") -> None:
        del reason
        self.stop()

    def resume_forwarding(self, *, send_queue, loop, reason: str = "scrcpy_start") -> None:
        del send_queue, loop, reason
        if not self._running:
            self.start()

    def is_alive(self) -> bool:
        return self._running and not self._stopped

    def is_streaming(self) -> bool:
        status = self._status()
        return bool(status and status.get("connected"))

    def supports_warm_forwarding(self) -> bool:
        return False

    def matches_config(
        self,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        bitrate: int,
        low_latency: bool,
    ) -> bool:
        del port
        return (
            self._max_fps == max_fps
            and self._max_width == max_width
            and self._enable_control == bool(enable_control)
            and self._bitrate == bitrate
            and self._low_latency == bool(low_latency)
        )

    def can_satisfy_config(
        self,
        max_fps: int,
        max_width: int,
        enable_control: bool,
        port: int,
        bitrate: int,
        low_latency: bool,
    ) -> bool:
        del port
        return (
            self._max_fps >= max_fps
            and self._max_width >= max_width
            and self._bitrate >= bitrate
            and (self._enable_control or not bool(enable_control))
            and self._low_latency == bool(low_latency)
        )

    def send_control(self, data: bytes) -> None:
        if data == bytes([_RESET_VIDEO]):
            self.request_recovery_keyframe()

    def request_recovery_keyframe(self, *, now: float | None = None) -> bool:
        del now
        requested = request_direct_keyframe(self.serial)
        if requested:
            self._idr_total += 1
        return requested

    def notify_downstream_drop(self) -> None:
        return None

    def notify_downstream_resynced(self) -> None:
        return None

    def stats_snapshot(self, *, reset: bool = False, now: float | None = None) -> dict[str, int]:
        now = time.monotonic() if now is None else now
        status = self._status()
        if status is None:
            self._stream_errors_total += 1
            if self._running and self._on_fatal:
                self._on_fatal(self.serial, "media_adapter_status_missing")
            frames_total = self._frames_total
        else:
            self._running = bool(status.get("running", self._running))
            frames_total = int(status.get("frames") or 0)
            self._record_status(status, frames_total, now)

        elapsed = max(0.001, now - (self._snapshot_at or self._started_at or now))
        frames = max(0, frames_total - self._snapshot_frames)
        stats = {
            "frames": frames,
            "fps_x100": round((frames / elapsed) * 100),
            "idr_requests": self._idr_total,
            "idr_recoveries": 0,
            "idr_recovery_p95_ms": 0,
            "idr_recovery_max_ms": 0,
            "idr_pending": 0,
            "producer_suppressed": 0,
            "max_fps_cap_x100": self._max_fps * 100,
            "connect_to_handshake_p95_ms": max(self._connect_to_handshake_ms, default=0),
            "connect_to_handshake_max_ms": max(self._connect_to_handshake_ms, default=0),
            "connect_to_first_frame_p95_ms": max(self._connect_to_first_frame_ms, default=0),
            "connect_to_first_frame_max_ms": max(self._connect_to_first_frame_ms, default=0),
            "start_to_handshake_p95_ms": max(self._start_to_handshake_ms, default=0),
            "start_to_handshake_max_ms": max(self._start_to_handshake_ms, default=0),
            "start_to_first_frame_p95_ms": max(self._start_to_first_frame_ms, default=0),
            "start_to_first_frame_max_ms": max(self._start_to_first_frame_ms, default=0),
            "gop_replay_packets": 0,
            "capture_resets": 0,
            "stream_errors": self._stream_errors_total,
        }
        if reset:
            self._snapshot_at = now
            self._snapshot_frames = frames_total
            self._idr_total = 0
            self._stream_errors_total = 0
            self._connect_to_handshake_ms.clear()
            self._connect_to_first_frame_ms.clear()
            self._start_to_handshake_ms.clear()
            self._start_to_first_frame_ms.clear()
        return stats

    def _status(self) -> dict | None:
        try:
            return direct_scrcpy_status(self.serial)
        except Exception as exc:
            logger.debug("[%s] media adapter status failed: %s", self.serial, exc)
            return None

    def _record_status(self, status: dict, frames_total: int, now: float) -> None:
        if bool(status.get("connected")) and not self._handshake_recorded:
            start = self._started_at or now
            elapsed_ms = max(0, round((now - start) * 1_000))
            self._connect_to_handshake_ms.append(elapsed_ms)
            self._start_to_handshake_ms.append(elapsed_ms)
            self._handshake_recorded = True
        if frames_total > self._frames_total:
            self.last_frame_time = now
            if not self._first_frame_recorded:
                start = self._started_at or now
                elapsed_ms = max(0, round((now - start) * 1_000))
                self._connect_to_first_frame_ms.append(elapsed_ms)
                self._start_to_first_frame_ms.append(elapsed_ms)
                self._first_frame_recorded = True
        self._frames_total = max(self._frames_total, frames_total)
