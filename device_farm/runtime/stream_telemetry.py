"""Low-overhead stream telemetry shared by gRPC, DeviceClient, and WS fanout."""

from __future__ import annotations

import bisect
import math
import threading
from dataclasses import dataclass, field


_MS_BUCKETS = (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)


@dataclass
class _Latency:
    samples: int = 0
    buckets: list[int] = field(default_factory=lambda: [0] * (len(_MS_BUCKETS) + 1))
    max_ms: float = 0.0

    def record(self, value_ms: float) -> None:
        value = max(0.0, value_ms)
        bucket = bisect.bisect_left(_MS_BUCKETS, math.ceil(value))
        self.buckets[bucket] += 1
        self.samples += 1
        self.max_ms = max(self.max_ms, value)

    def percentile(self, percentile: float) -> float:
        if self.samples <= 0:
            return 0.0
        target = max(1, math.ceil(self.samples * percentile))
        seen = 0
        for index, count in enumerate(self.buckets):
            seen += count
            if seen < target:
                continue
            if index < len(_MS_BUCKETS):
                return float(_MS_BUCKETS[index])
            return round(self.max_ms, 3)
        return round(self.max_ms, 3)


class StreamTelemetry:
    """Aggregated stream-path counters.

    The instance is process-local and intentionally phone-id safe: snapshots
    expose aggregate counts and worst affected serial count, not serial labels.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.dispatch_frames = 0
            self.dispatch_no_receiver = 0
            self.dispatch_push_errors = 0
            self.dispatch_push_ms = _Latency()

            self.fanout_frames = 0
            self.fanout_configs = 0
            self.fanout_keyframes = 0
            self.fanout_no_subscriber = 0
            self.fanout_subscribers_total = 0
            self.fanout_subscribers_max = 0
            self.fanout_frame_bytes = 0
            self.fanout_max_frame_bytes = 0
            self.fanout_ms = _Latency()

            self.ws_sent = 0
            self.ws_dropped = 0
            self.ws_send_wait_ms = _Latency()
            self.ws_send_ms = _Latency()

    def record_dispatch(
        self,
        *,
        push_ms: float = 0.0,
        no_receiver: bool = False,
        push_error: bool = False,
    ) -> None:
        with self._lock:
            self.dispatch_frames += 1
            self.dispatch_no_receiver += 1 if no_receiver else 0
            self.dispatch_push_errors += 1 if push_error else 0
            if not no_receiver and not push_error:
                self.dispatch_push_ms.record(push_ms)

    def record_fanout(
        self,
        *,
        subscribers: int,
        frame_bytes: int,
        elapsed_ms: float,
        is_config: bool = False,
        is_key: bool = False,
    ) -> None:
        with self._lock:
            self.fanout_frames += 1
            self.fanout_configs += 1 if is_config else 0
            self.fanout_keyframes += 1 if is_key else 0
            self.fanout_no_subscriber += 1 if subscribers <= 0 else 0
            self.fanout_subscribers_total += max(0, subscribers)
            self.fanout_subscribers_max = max(self.fanout_subscribers_max, max(0, subscribers))
            self.fanout_frame_bytes += max(0, frame_bytes)
            self.fanout_max_frame_bytes = max(self.fanout_max_frame_bytes, max(0, frame_bytes))
            self.fanout_ms.record(elapsed_ms)

    def record_ws_send(
        self,
        *,
        wait_ms: float = 0.0,
        send_ms: float = 0.0,
        dropped: bool = False,
    ) -> None:
        with self._lock:
            if dropped:
                self.ws_dropped += 1
                self.ws_send_wait_ms.record(wait_ms)
                return
            self.ws_sent += 1
            self.ws_send_wait_ms.record(wait_ms)
            self.ws_send_ms.record(send_ms)

    def snapshot(self, *, reset: bool = False) -> dict[str, int | float]:
        with self._lock:
            fanout_avg_subscribers = (
                self.fanout_subscribers_total / self.fanout_frames
                if self.fanout_frames
                else 0.0
            )
            data: dict[str, int | float] = {
                "dispatch_frames": self.dispatch_frames,
                "dispatch_no_receiver": self.dispatch_no_receiver,
                "dispatch_push_errors": self.dispatch_push_errors,
                "dispatch_push_p95_ms": self.dispatch_push_ms.percentile(0.95),
                "dispatch_push_max_ms": round(self.dispatch_push_ms.max_ms, 3),
                "fanout_frames": self.fanout_frames,
                "fanout_configs": self.fanout_configs,
                "fanout_keyframes": self.fanout_keyframes,
                "fanout_no_subscriber": self.fanout_no_subscriber,
                "fanout_avg_subscribers": round(fanout_avg_subscribers, 3),
                "fanout_max_subscribers": self.fanout_subscribers_max,
                "fanout_frame_bytes": self.fanout_frame_bytes,
                "fanout_max_frame_bytes": self.fanout_max_frame_bytes,
                "fanout_p95_ms": self.fanout_ms.percentile(0.95),
                "fanout_max_ms": round(self.fanout_ms.max_ms, 3),
                "ws_sent": self.ws_sent,
                "ws_dropped": self.ws_dropped,
                "ws_send_wait_p95_ms": self.ws_send_wait_ms.percentile(0.95),
                "ws_send_wait_max_ms": round(self.ws_send_wait_ms.max_ms, 3),
                "ws_send_p95_ms": self.ws_send_ms.percentile(0.95),
                "ws_send_max_ms": round(self.ws_send_ms.max_ms, 3),
            }
            if reset:
                self.reset()
            return data


stream_telemetry = StreamTelemetry()
