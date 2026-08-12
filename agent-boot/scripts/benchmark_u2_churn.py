"""Synthetic benchmark for U2 background churn.

This benchmark does not touch real adb, real atx-agent, or real phones.  It
models the two host-side behaviours that become expensive at 20-40+ devices:

* U2SessionPool heartbeat scans warm sessions and may reconnect/evict dead
  entries even when there is no foreground user action.
* atx-agent adb-forward creation can be fired for many different serials at
  once.  Per-serial coalescing helps duplicates, but it does not cap the burst
  across different phones.

The output is JSON so it can be pasted into issue reports and compared across
changes.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass(frozen=True)
class U2Entry:
    serial: str
    alive: bool
    recently_used: bool
    locked: bool = False


@dataclass(frozen=True)
class HeartbeatResult:
    policy: str
    sessions: int
    probe_budget: int
    ticks: int
    probes: int
    alive: int
    dead: int
    reconnects: int
    evictions: int
    locked_skips: int
    total_ms: int
    max_tick_ms: int
    p95_tick_ms: int
    avg_tick_ms: int
    background_ops: int


@dataclass(frozen=True)
class ForwardBurstResult:
    policy: str
    serials: int
    concurrency_limit: int
    adb_delay_ms: float
    total_ms: int
    p95_request_ms: int
    max_request_ms: int
    peak_inflight: int
    adb_forward_calls: int


def _percentile_ms(values: Sequence[float], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil(len(ordered) * percentile) - 1),
    )
    return round(ordered[index] * 1_000)


def _sleep_ms(delay_ms: float) -> None:
    if delay_ms > 0:
        time.sleep(delay_ms / 1_000)


def make_entries(
    *,
    sessions: int,
    dead_fraction: float,
    recent_fraction: float,
    locked_fraction: float,
) -> list[U2Entry]:
    sessions = max(1, sessions)
    dead_count = min(sessions, max(0, round(sessions * dead_fraction)))
    recent_count = min(sessions, max(0, round(sessions * recent_fraction)))
    locked_count = min(sessions, max(0, round(sessions * locked_fraction)))
    entries: list[U2Entry] = []
    for index in range(sessions):
        entries.append(
            U2Entry(
                serial=f"phone-{index:04d}",
                alive=index >= dead_count,
                recently_used=index < recent_count,
                locked=(sessions - index) <= locked_count,
            )
        )
    return entries


def run_heartbeat_policy(
    entries: Sequence[U2Entry],
    *,
    policy: str,
    probe_budget: int,
    alive_delay_ms: float,
    dead_delay_ms: float,
    reconnect_delay_ms: float,
    skip_recent_without_probe: bool = False,
    reconnect_recent_dead: bool = True,
    recovered_recent_dead_fraction: float = 0.0,
) -> HeartbeatResult:
    """Run one full sweep under either scan-all or budgeted heartbeat policy."""
    if not entries:
        raise ValueError("entries required")
    probe_budget = max(0, int(probe_budget))
    if probe_budget <= 0:
        probe_budget = len(entries)

    cursor = 0
    remaining = {entry.serial for entry in entries if not entry.locked}
    tick_durations: list[float] = []
    probes = alive = dead = reconnects = evictions = locked_skips = 0
    recovered_budget = max(
        0,
        round(
            sum(1 for entry in entries if (not entry.alive and entry.recently_used))
            * recovered_recent_dead_fraction
        ),
    )
    recovered = 0

    started = time.perf_counter()
    while remaining:
        tick_started = time.perf_counter()
        tick_probes = 0
        scanned = 0
        while tick_probes < probe_budget and scanned < len(entries) and remaining:
            entry = entries[cursor % len(entries)]
            cursor += 1
            scanned += 1
            if entry.serial not in remaining:
                continue
            if entry.locked:
                locked_skips += 1
                remaining.discard(entry.serial)
                continue
            if skip_recent_without_probe and entry.recently_used:
                remaining.discard(entry.serial)
                continue
            remaining.discard(entry.serial)
            tick_probes += 1
            probes += 1
            if entry.alive:
                alive += 1
                _sleep_ms(alive_delay_ms)
                continue

            dead += 1
            _sleep_ms(dead_delay_ms)
            if entry.recently_used and reconnect_recent_dead:
                reconnects += 1
                _sleep_ms(reconnect_delay_ms)
                if recovered < recovered_budget:
                    recovered += 1
                    alive += 1
                    _sleep_ms(alive_delay_ms)
                    continue
                _sleep_ms(dead_delay_ms)
            evictions += 1
        tick_durations.append(time.perf_counter() - tick_started)

    elapsed = time.perf_counter() - started
    ticks = len(tick_durations)
    return HeartbeatResult(
        policy=policy,
        sessions=len(entries),
        probe_budget=probe_budget,
        ticks=ticks,
        probes=probes,
        alive=alive,
        dead=dead,
        reconnects=reconnects,
        evictions=evictions,
        locked_skips=locked_skips,
        total_ms=round(elapsed * 1_000),
        max_tick_ms=_percentile_ms(tick_durations, 1.0),
        p95_tick_ms=_percentile_ms(tick_durations, 0.95),
        avg_tick_ms=round((elapsed / max(1, ticks)) * 1_000),
        background_ops=probes + reconnects + evictions,
    )


def run_forward_burst_policy(
    *,
    serials: int,
    concurrency_limit: int,
    adb_delay_ms: float,
    policy: str,
) -> ForwardBurstResult:
    serials = max(1, serials)
    concurrency_limit = max(1, min(concurrency_limit, serials))
    inflight = 0
    peak_inflight = 0
    forward_calls = 0
    lock = threading.Lock()
    latencies: list[float] = []

    def create_forward(_serial: str) -> None:
        nonlocal inflight, peak_inflight, forward_calls
        started = time.perf_counter()
        with lock:
            inflight += 1
            peak_inflight = max(peak_inflight, inflight)
            forward_calls += 1
        try:
            _sleep_ms(adb_delay_ms)
        finally:
            with lock:
                inflight -= 1
            latencies.append(time.perf_counter() - started)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency_limit) as pool:
        futures = [
            pool.submit(create_forward, f"phone-{index:04d}")
            for index in range(serials)
        ]
        for future in as_completed(futures):
            future.result()
    elapsed = time.perf_counter() - started

    return ForwardBurstResult(
        policy=policy,
        serials=serials,
        concurrency_limit=concurrency_limit,
        adb_delay_ms=adb_delay_ms,
        total_ms=round(elapsed * 1_000),
        p95_request_ms=_percentile_ms(latencies, 0.95),
        max_request_ms=_percentile_ms(latencies, 1.0),
        peak_inflight=peak_inflight,
        adb_forward_calls=forward_calls,
    )


def run_u2_churn_benchmark(
    *,
    sessions: int,
    dead_fraction: float,
    recent_fraction: float,
    locked_fraction: float,
    alive_delay_ms: float,
    dead_delay_ms: float,
    reconnect_delay_ms: float,
    heartbeat_budget: int,
    forward_limit: int,
    adb_delay_ms: float,
) -> dict[str, object]:
    entries = make_entries(
        sessions=sessions,
        dead_fraction=dead_fraction,
        recent_fraction=recent_fraction,
        locked_fraction=locked_fraction,
    )
    current_heartbeat = run_heartbeat_policy(
        entries,
        policy="current_scan_all_keep_warm",
        probe_budget=0,
        alive_delay_ms=alive_delay_ms,
        dead_delay_ms=dead_delay_ms,
        reconnect_delay_ms=reconnect_delay_ms,
    )
    budgeted_heartbeat = run_heartbeat_policy(
        entries,
        policy="budgeted_rotating_heartbeat",
        probe_budget=heartbeat_budget,
        alive_delay_ms=alive_delay_ms,
        dead_delay_ms=dead_delay_ms,
        reconnect_delay_ms=reconnect_delay_ms,
    )
    optimized_heartbeat = run_heartbeat_policy(
        entries,
        policy="optimized_budgeted_skip_recent_evict_stale",
        probe_budget=heartbeat_budget,
        alive_delay_ms=alive_delay_ms,
        dead_delay_ms=dead_delay_ms,
        reconnect_delay_ms=reconnect_delay_ms,
        skip_recent_without_probe=True,
        reconnect_recent_dead=False,
    )
    current_forward = run_forward_burst_policy(
        serials=sessions,
        concurrency_limit=sessions,
        adb_delay_ms=adb_delay_ms,
        policy="current_no_global_forward_create_limit",
    )
    limited_forward = run_forward_burst_policy(
        serials=sessions,
        concurrency_limit=forward_limit,
        adb_delay_ms=adb_delay_ms,
        policy="limited_forward_create_burst",
    )

    return {
        "kind": "u2_churn_synthetic",
        "scope": "agent_boot_u2_pool_heartbeat_and_atx_forward_no_real_adb",
        "inputs": {
            "sessions": sessions,
            "dead_fraction": dead_fraction,
            "recent_fraction": recent_fraction,
            "locked_fraction": locked_fraction,
            "alive_delay_ms": alive_delay_ms,
            "dead_delay_ms": dead_delay_ms,
            "reconnect_delay_ms": reconnect_delay_ms,
            "heartbeat_budget": heartbeat_budget,
            "forward_limit": forward_limit,
            "adb_delay_ms": adb_delay_ms,
        },
        "heartbeat": {
            "current": asdict(current_heartbeat),
            "budgeted": asdict(budgeted_heartbeat),
            "optimized": asdict(optimized_heartbeat),
            "max_tick_reduction_percent": round(
                (
                    1
                    - budgeted_heartbeat.max_tick_ms
                    / max(1, current_heartbeat.max_tick_ms)
                )
                * 100,
                2,
            ),
            "optimized_background_ops_reduction_percent": round(
                (
                    1
                    - optimized_heartbeat.background_ops
                    / max(1, current_heartbeat.background_ops)
                )
                * 100,
                2,
            ),
        },
        "forward_create": {
            "current": asdict(current_forward),
            "limited": asdict(limited_forward),
            "peak_inflight_reduction_percent": round(
                (
                    1
                    - limited_forward.peak_inflight
                    / max(1, current_forward.peak_inflight)
                )
                * 100,
                2,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=40)
    parser.add_argument("--dead-fraction", type=float, default=0.25)
    parser.add_argument("--recent-fraction", type=float, default=0.25)
    parser.add_argument("--locked-fraction", type=float, default=0.0)
    parser.add_argument("--alive-delay-ms", type=float, default=2.0)
    parser.add_argument("--dead-delay-ms", type=float, default=30.0)
    parser.add_argument("--reconnect-delay-ms", type=float, default=40.0)
    parser.add_argument("--heartbeat-budget", type=int, default=8)
    parser.add_argument("--forward-limit", type=int, default=8)
    parser.add_argument("--adb-delay-ms", type=float, default=25.0)
    args = parser.parse_args()
    result = run_u2_churn_benchmark(
        sessions=args.sessions,
        dead_fraction=max(0.0, min(1.0, args.dead_fraction)),
        recent_fraction=max(0.0, min(1.0, args.recent_fraction)),
        locked_fraction=max(0.0, min(1.0, args.locked_fraction)),
        alive_delay_ms=max(0.0, args.alive_delay_ms),
        dead_delay_ms=max(0.0, args.dead_delay_ms),
        reconnect_delay_ms=max(0.0, args.reconnect_delay_ms),
        heartbeat_budget=max(1, args.heartbeat_budget),
        forward_limit=max(1, args.forward_limit),
        adb_delay_ms=max(0.0, args.adb_delay_ms),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
