#!/usr/bin/env python3
"""Benchmark media session isolation without real phones.

This exercises the Python agent-boot media control plane:
ScrcpySessionManager, per-serial lifecycle, fatal-session cleanup, and stats
aggregation. The actual H264/RTSP hot path is owned by the Go media-adapter;
use cmd/stream-bench there for publisher throughput.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from typing import Callable

from relay import session_manager as sm


def _percentile(values: list[float], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return int(round(ordered[index]))


def _serial_index(serial: str) -> int:
    try:
        return int(serial.rsplit("-", 1)[1])
    except Exception:
        return 0


@dataclass
class MediaSessionIsolationResult:
    kind: str
    scope: str
    phones: int
    visible_phones: int
    fault_every: int
    noisy_every: int
    start_ms: int
    stop_ms: int
    stats_iterations: int
    active_after_start: int
    start_total_ms: int
    start_p50_ms: int
    start_p95_ms: int
    stats_snapshot_p50_ms: int
    stats_snapshot_p95_ms: int
    stats_snapshot_max_ms: int
    stats_snapshot_p50_us: int
    stats_snapshot_p95_us: int
    stats_snapshot_max_us: int
    fatal_injected: int
    fatal_stop_total_ms: int
    active_after_fatal: int
    healthy_survivors: int
    healthy_stopped_by_mistake: int
    stop_all_total_ms: int
    frames_reported: int
    fps_active_sessions: int
    stream_errors: int
    capture_resets: int
    stopped_events: int
    passed: bool
    guardrails: dict[str, bool]


def _fake_session_class(
    *,
    start_ms: int,
    stop_ms: int,
    noisy_every: int,
) -> type:
    class _BenchmarkMediaSession:
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
            on_fatal: Callable[[str, str], None] | None = None,
            on_health: Callable[[str, str], None] | None = None,
        ) -> None:
            del send_queue, loop, on_health
            self.serial = serial
            self.max_fps = max_fps
            self.max_width = max_width
            self.enable_control = bool(enable_control)
            self.port = port
            self.bitrate = bitrate
            self.low_latency = bool(low_latency)
            self.on_fatal = on_fatal
            self.last_frame_time = 0.0
            self._alive = False
            self._started_at = 0.0
            self._snapshot_frames = 0

        def start(self) -> None:
            if start_ms > 0:
                time.sleep(start_ms / 1000.0)
            self._alive = True
            self._started_at = time.monotonic()
            self.last_frame_time = self._started_at

        def stop(self) -> None:
            if stop_ms > 0:
                time.sleep(stop_ms / 1000.0)
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

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
            return (
                self.max_fps == max_fps
                and self.max_width == max_width
                and self.enable_control == bool(enable_control)
                and self.port == port
                and self.bitrate == bitrate
                and self.low_latency == bool(low_latency)
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
                self.max_fps >= max_fps
                and self.max_width >= max_width
                and self.bitrate >= bitrate
                and (self.enable_control or not bool(enable_control))
                and self.low_latency == bool(low_latency)
            )

        def send_control(self, data: bytes) -> None:
            del data

        def stats_snapshot(self, *, reset: bool = False) -> dict[str, int]:
            now = time.monotonic()
            elapsed = max(0.001, now - (self._started_at or now))
            index = _serial_index(self.serial)
            noisy = noisy_every > 0 and index > 0 and index % noisy_every == 0
            fps = self.max_fps * (4 if noisy else 1)
            frames_total = int(elapsed * fps)
            frames = max(0, frames_total - self._snapshot_frames)
            if reset:
                self._snapshot_frames = frames_total
            return {
                "frames": frames,
                "fps_x100": fps * 100 if self._alive else 0,
                "idr_requests": 2 if noisy else 0,
                "idr_recoveries": 0,
                "idr_recovery_p95_ms": 0,
                "idr_recovery_max_ms": 0,
                "idr_pending": 0,
                "producer_suppressed": 0,
                "connect_to_handshake_p95_ms": start_ms,
                "connect_to_handshake_max_ms": start_ms,
                "connect_to_first_frame_p95_ms": start_ms,
                "connect_to_first_frame_max_ms": start_ms,
                "start_to_handshake_p95_ms": start_ms,
                "start_to_handshake_max_ms": start_ms,
                "start_to_first_frame_p95_ms": start_ms,
                "start_to_first_frame_max_ms": start_ms,
                "gop_replay_packets": 0,
                "capture_resets": 1 if noisy else 0,
                "stream_errors": 1 if noisy else 0,
            }

    return _BenchmarkMediaSession


async def run_media_session_isolation_benchmark(
    *,
    phones: int,
    visible_phones: int,
    fault_every: int,
    noisy_every: int,
    start_ms: int,
    stop_ms: int,
    stats_iterations: int,
) -> dict[str, object]:
    phones = max(1, phones)
    visible_phones = max(0, min(visible_phones, phones))
    stats_iterations = max(1, stats_iterations)
    fault_every = max(0, fault_every)
    noisy_every = max(0, noisy_every)
    start_ms = max(0, start_ms)
    stop_ms = max(0, stop_ms)

    original_session_class = sm.ScrcpyRelaySession
    original_max_sessions = sm.MAX_SESSIONS
    sm.ScrcpyRelaySession = _fake_session_class(
        start_ms=start_ms,
        stop_ms=stop_ms,
        noisy_every=noisy_every,
    )
    sm.MAX_SESSIONS = 0

    stopped_events: list[tuple[str, str]] = []
    manager = sm.ScrcpySessionManager(
        on_session_stopped=lambda serial, reason: stopped_events.append((serial, reason))
    )
    serials = [f"media-phone-{index:04d}" for index in range(1, phones + 1)]
    fault_serials = {
        serial
        for serial in serials
        if fault_every > 0 and _serial_index(serial) % fault_every == 0
    }
    healthy_serials = [serial for serial in serials if serial not in fault_serials]
    start_latencies: list[float] = []
    snapshot_latencies: list[float] = []

    async def _start_one(index: int, serial: str) -> None:
        started = time.perf_counter()
        max_fps = 15 if index <= visible_phones else 1
        max_width = 720 if index <= visible_phones else 320
        await manager.start_session(
            serial,
            max_fps,
            max_width,
            True,
            27183 + index,
            asyncio.Queue(),
            asyncio.get_running_loop(),
            bitrate=900_000 if index <= visible_phones else 150_000,
        )
        start_latencies.append((time.perf_counter() - started) * 1000.0)

    await manager.start()
    try:
        start_started = time.perf_counter()
        await asyncio.gather(
            *[
                _start_one(index, serial)
                for index, serial in enumerate(serials, start=1)
            ]
        )
        start_total_ms = int(round((time.perf_counter() - start_started) * 1000.0))
        active_after_start = manager.count

        last_stats: dict[str, int] = {}
        for _ in range(stats_iterations):
            started = time.perf_counter()
            last_stats = manager.stats_snapshot(reset=True)
            snapshot_latencies.append((time.perf_counter() - started) * 1000.0)
            await asyncio.sleep(0)

        fatal_started = time.perf_counter()
        for serial in sorted(fault_serials):
            manager._on_session_fatal(serial, "runtime_error")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if all(manager.get(serial) is None for serial in fault_serials):
                break
            await asyncio.sleep(0.005)
        fatal_stop_total_ms = int(round((time.perf_counter() - fatal_started) * 1000.0))

        active_after_fatal = manager.count
        healthy_survivors = sum(1 for serial in healthy_serials if manager.get(serial) is not None)
        healthy_stopped_by_mistake = len(healthy_serials) - healthy_survivors
        all_fatal_removed = all(manager.get(serial) is None for serial in fault_serials)
        no_healthy_stopped = healthy_stopped_by_mistake == 0

        stop_started = time.perf_counter()
        await manager.stop()
        stop_all_total_ms = int(round((time.perf_counter() - stop_started) * 1000.0))

        guardrails = {
            "all_sessions_started": active_after_start == phones,
            "all_fatal_removed": all_fatal_removed,
            "no_healthy_stopped": no_healthy_stopped,
            "clean_stop": manager.count == 0,
        }
        result = MediaSessionIsolationResult(
            kind="media_session_isolation_mock",
            scope="ScrcpySessionManager_fake_media_adapter_sessions_no_real_phone_no_rtsp",
            phones=phones,
            visible_phones=visible_phones,
            fault_every=fault_every,
            noisy_every=noisy_every,
            start_ms=start_ms,
            stop_ms=stop_ms,
            stats_iterations=stats_iterations,
            active_after_start=active_after_start,
            start_total_ms=start_total_ms,
            start_p50_ms=_percentile(start_latencies, 0.50),
            start_p95_ms=_percentile(start_latencies, 0.95),
            stats_snapshot_p50_ms=_percentile(snapshot_latencies, 0.50),
            stats_snapshot_p95_ms=_percentile(snapshot_latencies, 0.95),
            stats_snapshot_max_ms=max(
                [int(round(value)) for value in snapshot_latencies],
                default=0,
            ),
            stats_snapshot_p50_us=_percentile(
                [value * 1000.0 for value in snapshot_latencies],
                0.50,
            ),
            stats_snapshot_p95_us=_percentile(
                [value * 1000.0 for value in snapshot_latencies],
                0.95,
            ),
            stats_snapshot_max_us=max(
                [int(round(value * 1000.0)) for value in snapshot_latencies],
                default=0,
            ),
            fatal_injected=len(fault_serials),
            fatal_stop_total_ms=fatal_stop_total_ms,
            active_after_fatal=active_after_fatal,
            healthy_survivors=healthy_survivors,
            healthy_stopped_by_mistake=healthy_stopped_by_mistake,
            stop_all_total_ms=stop_all_total_ms,
            frames_reported=int(last_stats.get("frames", 0)),
            fps_active_sessions=int(last_stats.get("fps_active_sessions", 0)),
            stream_errors=int(last_stats.get("stream_errors", 0)),
            capture_resets=int(last_stats.get("capture_resets", 0)),
            stopped_events=len(stopped_events),
            passed=all(guardrails.values()),
            guardrails=guardrails,
        )
        return asdict(result)
    finally:
        if manager.count:
            await manager.stop()
        sm.ScrcpyRelaySession = original_session_class
        sm.MAX_SESSIONS = original_max_sessions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phones", type=int, default=100)
    parser.add_argument("--visible-phones", type=int, default=8)
    parser.add_argument("--fault-every", type=int, default=10)
    parser.add_argument("--noisy-every", type=int, default=7)
    parser.add_argument("--start-ms", type=int, default=5)
    parser.add_argument("--stop-ms", type=int, default=2)
    parser.add_argument("--stats-iterations", type=int, default=5)
    args = parser.parse_args()

    result = asyncio.run(
        run_media_session_isolation_benchmark(
            phones=args.phones,
            visible_phones=args.visible_phones,
            fault_every=args.fault_every,
            noisy_every=args.noisy_every,
            start_ms=args.start_ms,
            stop_ms=args.stop_ms,
            stats_iterations=args.stats_iterations,
        )
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
