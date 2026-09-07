#!/usr/bin/env python3
"""Measure serial → ADB endpoint routing: lookup cost, discovery cost, dispatch
correctness.

No devices or ADB servers required — the ADB layer is faked so the numbers
isolate the routing decision itself.

    python scripts/benchmark_adb_routes.py
"""
from __future__ import annotations

import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from relay.adb_routes import AdbEndpoint, AdbRouteTable  # noqa: E402

ENDPOINTS = [AdbEndpoint("127.0.0.1", 5037), AdbEndpoint("127.0.0.1", 5038)]
FLEET = {f"PHONE{i:03d}": ENDPOINTS[i % 2] for i in range(40)}
SCAN_COST_S = 0.030  # one `adb -P <port> devices` round trip, measured on host


def _fake_discover(counter: list[int]):
    def discover(serial: str) -> AdbEndpoint | None:
        for endpoint in ENDPOINTS:
            counter[0] += 1
            time.sleep(SCAN_COST_S)
            if FLEET.get(serial) == endpoint:
                return endpoint
        return None

    return discover


def bench_cached_lookup() -> None:
    table = AdbRouteTable()
    for serial, endpoint in FLEET.items():
        table.set(serial, endpoint)
    serials = list(FLEET)

    samples = []
    for _ in range(20_000):
        serial = serials[_ % len(serials)]
        start = time.perf_counter_ns()
        table.get(serial)
        samples.append(time.perf_counter_ns() - start)

    samples.sort()
    print("cached route lookup (20k)")
    print(f"  p50 {samples[len(samples)//2]/1000:.3f} us")
    print(f"  p99 {samples[int(len(samples)*0.99)]/1000:.3f} us")
    print(f"  mean {statistics.mean(samples)/1000:.3f} us")


def bench_uncached_discovery() -> None:
    table = AdbRouteTable()
    scans = [0]
    discover = _fake_discover(scans)

    start = time.perf_counter()
    for serial in FLEET:
        table.resolve(serial, discover)
    elapsed = time.perf_counter() - start

    print("\nuncached discovery (40 serials, cold)")
    print(f"  endpoint scans {scans[0]}  ({scans[0]/len(FLEET):.2f} per serial)")
    print(f"  wall {elapsed*1000:.0f} ms")


def bench_concurrent_miss() -> None:
    """64 commands hit the same uncached serial at once."""
    table = AdbRouteTable()
    scans = [0]
    discover = _fake_discover(scans)
    gate = threading.Barrier(64)

    def worker():
        gate.wait()
        table.resolve("PHONE001", discover)

    threads = [threading.Thread(target=worker) for _ in range(64)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start

    print("\nconcurrent cache miss (64 callers, same serial)")
    print(f"  endpoint scans {scans[0]}  (no single-flight would give 128)")
    print(f"  wall {elapsed*1000:.0f} ms")


def bench_dispatch_correctness() -> None:
    """Steady-state dispatch: routed endpoint vs the pre-change 'always specs[0]'.

    Counts commands that reach the ADB server that does NOT own the device —
    each one is an `error: device not found` and a wasted round trip upstream.
    """
    table = AdbRouteTable()
    for endpoint in ENDPOINTS:
        table.sync_endpoint(
            endpoint,
            {s: "device" for s, e in FLEET.items() if e == endpoint},
        )

    commands = [s for s in FLEET for _ in range(50)]

    before_wrong = sum(1 for s in commands if FLEET[s] != ENDPOINTS[0])
    after_wrong = sum(1 for s in commands if table.get(s).endpoint != FLEET[s])

    print(f"\nADB command dispatch ({len(commands)} commands, 40 phones, 2 servers)")
    print(f"  before (always first configured server): {before_wrong} wrong-endpoint")
    print(f"  after  (routed):                         {after_wrong} wrong-endpoint")
    print(f"  route table scans in steady state:       {table.stats().get('discovery_scans', 0)}")


if __name__ == "__main__":
    bench_cached_lookup()
    bench_uncached_discovery()
    bench_concurrent_miss()
    bench_dispatch_correctness()
