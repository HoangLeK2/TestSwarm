"""Benchmark RelayAgent's adb-forward creation path.

This is a synthetic benchmark: it does not touch real adb or real phones. It
isolates the host-side scheduling behavior that matters under load:

* different serials should create forwards in parallel;
* duplicate requests for the same serial should coalesce to one adb forward;
* the global cache lock must not be held while the blocking adb call runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from relay import agent as agent_mod
from relay import adb as relay_adb
from relay.agent import RelayAgent


def _percentile_ms(values: Sequence[float], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int((len(ordered) * percentile) + 0.999999) - 1),
    )
    return round(ordered[index] * 1_000)


def _make_agent() -> RelayAgent:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="benchmark",
        relay_id="benchmark",
        relay_mode="grpc",
    )
    agent._atx_lan_probe_interval_s = 0.0
    return agent


def run_forward_manager_benchmark(
    *,
    serials: int,
    duplicate_requests_per_serial: int,
    concurrency: int,
    adb_delay_ms: float,
) -> dict[str, object]:
    agent = _make_agent()
    serial_values = [f"usb-{index:04d}" for index in range(max(1, serials))]
    requests = [
        serial
        for serial in serial_values
        for _index in range(max(1, duplicate_requests_per_serial))
    ]
    call_count = 0
    call_lock = threading.Lock()

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        nonlocal call_count
        if args != ("forward", "tcp:0", "tcp:7912"):
            raise AssertionError(f"unexpected adb call: {args!r}")
        if timeout != 10:
            raise AssertionError(f"unexpected timeout: {timeout}")
        with call_lock:
            call_count += 1
            port = 43000 + call_count
        if adb_delay_ms > 0:
            time.sleep(adb_delay_ms / 1_000)
        return f"{port}\n", 0

    previous_run = agent_mod._run
    agent_mod._run = fake_run
    latencies: list[float] = []
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = []
            for serial in requests:
                task_started = time.perf_counter()
                futures.append(
                    pool.submit(
                        lambda serial=serial, task_started=task_started: (
                            serial,
                            task_started,
                            agent._ensure_atx_forward_endpoint(serial),
                        )
                    )
                )
            for future in as_completed(futures):
                _serial, task_started, endpoint = future.result()
                if endpoint is None:
                    raise RuntimeError("forward endpoint was not created")
                latencies.append(time.perf_counter() - task_started)
    finally:
        agent_mod._run = previous_run
    elapsed = time.perf_counter() - started
    stats = agent._u2_forward_stats_snapshot(reset=True)
    total_requests = len(requests)
    return {
        "kind": "forward_manager_mock",
        "scope": "agent_boot_relay_agent_forward_cache_no_real_adb",
        "serials": len(serial_values),
        "duplicate_requests_per_serial": max(1, duplicate_requests_per_serial),
        "requests": total_requests,
        "concurrency": max(1, concurrency),
        "adb_delay_ms": adb_delay_ms,
        "seconds": round(elapsed, 6),
        "requests_per_second": round(total_requests / elapsed),
        "request_p50_ms": _percentile_ms(latencies, 0.50),
        "request_p95_ms": _percentile_ms(latencies, 0.95),
        "request_max_ms": _percentile_ms(latencies, 1.0),
        "adb_forward_calls": call_count,
        "adb_call_reduction_percent": round(
            (1 - (call_count / total_requests)) * 100,
            2,
        ),
        "stats": {
            key: stats.get(key, 0)
            for key in (
                "created",
                "create_failed",
                "create_joined",
                "reused",
                "removed",
            )
        },
    }


def run_adb_forward_failure_cooldown_benchmark(
    *,
    serials: int,
    attempts_per_serial: int,
    concurrency: int,
    adb_delay_ms: float,
    cooldown_s: float,
) -> dict[str, object]:
    """Synthetic benchmark for atx adb-forward creation failure storms.

    Real failure mode: many u2/health/bootstrap callers hit phones whose
    tcp:7912 path is down, so they all fall back to `adb forward tcp:0
    tcp:7912`. Without a negative cache, every caller can allocate an ADB
    command slot even though the previous create attempt just failed.
    """
    serial_values = [f"usb-{index:04d}" for index in range(max(1, serials))]
    requests = [
        serial
        for serial in serial_values
        for _index in range(max(1, attempts_per_serial))
    ]
    calls: list[tuple[str, str | None]] = []
    call_lock = threading.Lock()

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        if args == ("forward", "--list"):
            with call_lock:
                calls.append(("list", serial))
            return "", 0
        if args == ("forward", "tcp:0", "tcp:7912"):
            with call_lock:
                calls.append(("create", serial))
            if adb_delay_ms > 0:
                time.sleep(adb_delay_ms / 1_000)
            return "cannot bind", 1
        raise AssertionError(f"unexpected adb call: {args!r}")

    previous_run = relay_adb._run
    previous_resolve = relay_adb._resolve_device_lan_ip
    previous_cooldown = relay_adb._ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS
    latencies: list[float] = []
    started = time.perf_counter()
    try:
        with relay_adb._ADB_CACHE_LOCK:
            relay_adb._ATX_FORWARD_CACHE.clear()
            relay_adb._ATX_FORWARD_FAIL_COUNT.clear()
            relay_adb._ATX_FORWARD_LAST_ERROR.clear()
            relay_adb._ATX_FORWARD_CREATE_RETRY_AFTER.clear()
            relay_adb._ATX_FORWARD_SERIAL_LOCKS.clear()
            relay_adb._ATX_FORWARD_RECONCILE_NEXT_AT = 0.0
        relay_adb._run = fake_run
        relay_adb._resolve_device_lan_ip = lambda _serial: ""
        relay_adb._ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS = max(0.0, cooldown_s)
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = []
            for serial in requests:
                task_started = time.perf_counter()
                futures.append(
                    pool.submit(
                        lambda serial=serial, task_started=task_started: (
                            task_started,
                            relay_adb._atx_http_ping(serial, timeout=0.05),
                        )
                    )
                )
            for future in as_completed(futures):
                task_started, result = future.result()
                ok, message = result
                if ok:
                    raise RuntimeError(f"unexpected healthy ping: {message}")
                latencies.append(time.perf_counter() - task_started)
    finally:
        relay_adb._run = previous_run
        relay_adb._resolve_device_lan_ip = previous_resolve
        relay_adb._ATX_FORWARD_CREATE_FAILURE_COOLDOWN_SECONDS = previous_cooldown
        with relay_adb._ADB_CACHE_LOCK:
            relay_adb._ATX_FORWARD_CACHE.clear()
            relay_adb._ATX_FORWARD_FAIL_COUNT.clear()
            relay_adb._ATX_FORWARD_LAST_ERROR.clear()
            relay_adb._ATX_FORWARD_CREATE_RETRY_AFTER.clear()
            relay_adb._ATX_FORWARD_SERIAL_LOCKS.clear()
            relay_adb._ATX_FORWARD_RECONCILE_NEXT_AT = 0.0

    elapsed = time.perf_counter() - started
    create_calls = sum(1 for kind, _serial in calls if kind == "create")
    list_calls = sum(1 for kind, _serial in calls if kind == "list")
    total_requests = len(requests)
    return {
        "kind": "adb_forward_failure_cooldown_mock",
        "scope": "agent_boot_relay_adb_atx_ping_no_real_adb",
        "serials": len(serial_values),
        "attempts_per_serial": max(1, attempts_per_serial),
        "requests": total_requests,
        "concurrency": max(1, concurrency),
        "adb_delay_ms": adb_delay_ms,
        "cooldown_s": max(0.0, cooldown_s),
        "seconds": round(elapsed, 6),
        "requests_per_second": round(total_requests / elapsed),
        "request_p50_ms": _percentile_ms(latencies, 0.50),
        "request_p95_ms": _percentile_ms(latencies, 0.95),
        "request_max_ms": _percentile_ms(latencies, 1.0),
        "adb_forward_create_calls": create_calls,
        "adb_forward_list_calls": list_calls,
        "adb_command_calls": len(calls),
        "adb_create_reduction_percent": round(
            (1 - (create_calls / total_requests)) * 100,
            2,
        ),
    }


def run_relay_agent_forward_failure_cooldown_benchmark(
    *,
    serials: int,
    attempts_per_serial: int,
    concurrency: int,
    adb_delay_ms: float,
    cooldown_s: float,
) -> dict[str, object]:
    """Synthetic benchmark for RelayAgent's u2 runtime adb-forward failure path."""
    agent = _make_agent()
    agent._atx_forward_create_failure_cooldown_s = max(0.0, cooldown_s)
    serial_values = [f"usb-{index:04d}" for index in range(max(1, serials))]
    requests = [
        serial
        for serial in serial_values
        for _index in range(max(1, attempts_per_serial))
    ]
    call_count = 0
    call_lock = threading.Lock()

    def fake_run(*args: str, serial: str | None = None, timeout: int = 30):
        nonlocal call_count
        if args != ("forward", "tcp:0", "tcp:7912"):
            raise AssertionError(f"unexpected adb call: {args!r}")
        if timeout != 10:
            raise AssertionError(f"unexpected timeout: {timeout}")
        with call_lock:
            call_count += 1
        if adb_delay_ms > 0:
            time.sleep(adb_delay_ms / 1_000)
        return "cannot bind", 1

    previous_run = agent_mod._run
    agent_logger = logging.getLogger("relay.agent")
    previous_log_level = agent_logger.level
    agent_mod._run = fake_run
    agent_logger.setLevel(logging.ERROR)
    latencies: list[float] = []
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = []
            for serial in requests:
                task_started = time.perf_counter()
                futures.append(
                    pool.submit(
                        lambda serial=serial, task_started=task_started: (
                            task_started,
                            agent._ensure_atx_forward_endpoint(serial),
                        )
                    )
                )
            for future in as_completed(futures):
                task_started, endpoint = future.result()
                if endpoint is not None:
                    raise RuntimeError("unexpected forward endpoint")
                latencies.append(time.perf_counter() - task_started)
    finally:
        agent_mod._run = previous_run
        agent_logger.setLevel(previous_log_level)
    elapsed = time.perf_counter() - started
    total_requests = len(requests)
    stats = agent._u2_forward_stats_snapshot(reset=True)
    return {
        "kind": "relay_agent_forward_failure_cooldown_mock",
        "scope": "agent_boot_relay_agent_u2_runtime_no_real_adb",
        "serials": len(serial_values),
        "attempts_per_serial": max(1, attempts_per_serial),
        "requests": total_requests,
        "concurrency": max(1, concurrency),
        "adb_delay_ms": adb_delay_ms,
        "cooldown_s": max(0.0, cooldown_s),
        "seconds": round(elapsed, 6),
        "requests_per_second": round(total_requests / elapsed),
        "request_p50_ms": _percentile_ms(latencies, 0.50),
        "request_p95_ms": _percentile_ms(latencies, 0.95),
        "request_max_ms": _percentile_ms(latencies, 1.0),
        "adb_forward_create_calls": call_count,
        "adb_create_reduction_percent": round(
            (1 - (call_count / total_requests)) * 100,
            2,
        ),
        "stats": {
            key: stats.get(key, 0)
            for key in (
                "create_failed",
                "create_cooldown_skip",
                "create_throttled",
                "create_wait_p95_ms",
                "create_peak_inflight",
                "create_limit",
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serials", type=int, default=100)
    parser.add_argument("--duplicates", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--adb-delay-ms", type=float, default=25.0)
    parser.add_argument("--failure-storm", action="store_true")
    parser.add_argument("--relay-agent-failure-storm", action="store_true")
    parser.add_argument("--cooldown-s", type=float, default=2.0)
    args = parser.parse_args()
    if args.relay_agent_failure_storm:
        result = run_relay_agent_forward_failure_cooldown_benchmark(
            serials=args.serials,
            attempts_per_serial=args.duplicates,
            concurrency=args.concurrency,
            adb_delay_ms=max(0.0, args.adb_delay_ms),
            cooldown_s=max(0.0, args.cooldown_s),
        )
    elif args.failure_storm:
        result = run_adb_forward_failure_cooldown_benchmark(
            serials=args.serials,
            attempts_per_serial=args.duplicates,
            concurrency=args.concurrency,
            adb_delay_ms=max(0.0, args.adb_delay_ms),
            cooldown_s=max(0.0, args.cooldown_s),
        )
    else:
        result = run_forward_manager_benchmark(
            serials=args.serials,
            duplicate_requests_per_serial=args.duplicates,
            concurrency=args.concurrency,
            adb_delay_ms=max(0.0, args.adb_delay_ms),
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
