"""Benchmark how much concurrent work the host ADB server can sustain.

The default workload is read-only. It does not install APKs, push files, start
scrcpy, or mutate phone state. Use the optional ``forward`` workload only when
you explicitly want to exercise host-forward churn similar to u2/scrcpy setup.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
import threading


DEFAULT_LEVELS = (1, 2, 4, 8, 12, 16, 24, 32, 48, 64)


@dataclass(frozen=True)
class Device:
    serial: str
    state: str
    detail: str


@dataclass(frozen=True)
class Operation:
    name: str
    argv: tuple[str, ...]
    kind: str = "adb"


@dataclass(frozen=True)
class Sample:
    serial: str
    operation: str
    ok: bool
    timed_out: bool
    duration_ms: int
    returncode: int | None
    error: str
    adb_invocations: int = 1


@dataclass(frozen=True)
class Stats:
    samples: int
    ok: int
    failed: int
    timed_out: int
    p50_ms: int
    p95_ms: int
    p99_ms: int
    max_ms: int


@dataclass(frozen=True)
class LevelResult:
    concurrency: int
    commands: int
    adb_invocations: int
    devices_used: int
    seconds: float
    stats: Stats
    by_operation: dict[str, Stats]
    passed: bool
    reason: str


Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[bytes]]


def _adb_server_flags_from_env(
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Mirror agent-boot remote-ADB routing with explicit -H/-P flags."""
    source = env if env is not None else os.environ
    host = source.get("ADB_HOST", "").strip()
    port = source.get("ADB_PORT", "").strip()
    sock = source.get("ADB_SERVER_SOCKET", "").strip()
    if sock.startswith("tcp:"):
        rest = sock[4:]
        if ":" in rest:
            sock_host, sock_port = rest.rsplit(":", 1)
            host = sock_host.strip() or host
            port = sock_port.strip() or port
        elif rest.isdigit():
            port = rest
    if host and port:
        return ["-H", host, "-P", port]
    return []


def _adb_command(
    adb_bin: str,
    server_flags: Sequence[str],
    argv: Sequence[str],
    *,
    serial: str | None = None,
) -> list[str]:
    cmd = [adb_bin, *server_flags]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(argv)
    return cmd


def _subprocess_runner(
    cmd: Sequence[str],
    timeout_s: float,
) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env.pop("MallocStackLogging", None)
    env.pop("MallocStackLoggingDirectory", None)
    return subprocess.run(
        list(cmd),
        capture_output=True,
        check=False,
        timeout=timeout_s,
        env=env,
    )


def _mock_runner_factory(*, delay_ms: float = 1.0) -> Runner:
    next_port = 43000
    lock = threading.Lock()

    def _runner(
        cmd: Sequence[str],
        timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal next_port
        if delay_ms > 0:
            time.sleep(delay_ms / 1_000)
        if timeout_s <= 0:
            raise subprocess.TimeoutExpired(list(cmd), timeout_s)
        if "forward" in cmd and "tcp:0" in cmd:
            with lock:
                next_port += 1
                port = next_port
            return subprocess.CompletedProcess(
                args=list(cmd),
                returncode=0,
                stdout=f"{port}\n".encode(),
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=b"ok\n",
            stderr=b"",
        )

    return _runner


def parse_adb_devices(output: str, *, include_offline: bool = False) -> list[Device]:
    devices: list[Device] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if state != "device" and not include_offline:
            continue
        devices.append(Device(serial=serial, state=state, detail=" ".join(parts[2:])))
    return devices


def dedupe_serials_prefer_usb(serials: Sequence[str]) -> list[str]:
    """Collapse duplicate TCP/USB routes without disconnecting anything."""
    chosen_by_host: dict[str, str] = {}
    for serial in serials:
        host_key = serial.split(":", 1)[0] if ":" in serial else serial
        existing = chosen_by_host.get(host_key)
        if existing is None:
            chosen_by_host[host_key] = serial
            continue
        existing_is_tcp = ":" in existing
        new_is_tcp = ":" in serial
        if existing_is_tcp and not new_is_tcp:
            chosen_by_host[host_key] = serial
        elif existing_is_tcp == new_is_tcp:
            chosen_by_host[host_key] = serial
    return sorted(chosen_by_host.values())


def discover_devices(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    include_offline: bool,
    runner: Runner = _subprocess_runner,
    timeout_s: float = 5.0,
) -> list[Device]:
    cmd = _adb_command(adb_bin, server_flags, ("devices", "-l"))
    try:
        result = runner(cmd, timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"adb devices timed out after {timeout_s}s") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"adb binary not found: {adb_bin}") from exc
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            output.strip() or f"adb devices failed rc={result.returncode}"
        )
    devices = parse_adb_devices(output, include_offline=include_offline)
    serials = dedupe_serials_prefer_usb([device.serial for device in devices])
    by_serial = {device.serial: device for device in devices}
    return [by_serial[serial] for serial in serials if serial in by_serial]


def _read_workload() -> tuple[Operation, ...]:
    return (
        Operation("shell_true", ("shell", "true")),
        Operation("get_model", ("shell", "getprop", "ro.product.model")),
        Operation("get_sdk", ("shell", "getprop", "ro.build.version.sdk")),
        Operation("get_abi", ("shell", "getprop", "ro.product.cpu.abi")),
    )


def build_workload(name: str) -> tuple[Operation, ...]:
    if name == "read":
        return _read_workload()
    if name == "light":
        return (
            *_read_workload(),
            Operation(
                "get_default_ime",
                ("shell", "settings", "get", "secure", "default_input_method"),
            ),
            Operation("pm_path_u2", ("shell", "pm", "path", "com.github.uiautomator")),
            Operation("pidof_atx", ("shell", "pidof", "atx-agent")),
        )
    if name == "forward":
        return (
            *_read_workload(),
            Operation("forward_atx", tuple(), kind="forward_atx"),
        )
    if name == "forward_cached":
        return (
            *_read_workload(),
            Operation("forward_atx_cached", tuple(), kind="forward_atx_cached"),
        )
    if name == "recovery_legacy":
        return (
            Operation("stability_legacy", tuple(), kind="stability_legacy"),
            Operation("ime_legacy", tuple(), kind="ime_legacy"),
            Operation("cleanup_legacy", tuple(), kind="cleanup_legacy"),
        )
    if name == "recovery_batched":
        return (
            Operation("stability_batched", tuple(), kind="stability_batched"),
            Operation("ime_batched", tuple(), kind="ime_batched"),
            Operation("cleanup_batched", tuple(), kind="cleanup_batched"),
        )
    if name == "recovery_storm_legacy":
        return (
            Operation("restart_u2_legacy", tuple(), kind="recovery_storm_legacy"),
            Operation("restart_atx_legacy", tuple(), kind="recovery_storm_legacy"),
        )
    if name == "recovery_storm_coalesced":
        return (
            Operation("restart_u2_coalesced", tuple(), kind="recovery_storm_coalesced"),
            Operation("restart_atx_coalesced", tuple(), kind="recovery_storm_coalesced"),
        )
    raise ValueError(f"unknown workload: {name}")


def parse_levels(raw: str) -> tuple[int, ...]:
    try:
        levels = tuple(
            int(part.strip())
            for part in raw.split(",")
            if part.strip()
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "levels must be comma-separated integers"
        ) from exc
    if not levels or any(level < 1 for level in levels):
        raise argparse.ArgumentTypeError("levels must contain positive integers")
    return tuple(dict.fromkeys(levels))


def percentile_ms(values: Sequence[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def summarize_samples(samples: Sequence[Sample]) -> Stats:
    durations = [sample.duration_ms for sample in samples]
    ok = sum(1 for sample in samples if sample.ok)
    timed_out = sum(1 for sample in samples if sample.timed_out)
    return Stats(
        samples=len(samples),
        ok=ok,
        failed=len(samples) - ok,
        timed_out=timed_out,
        p50_ms=percentile_ms(durations, 0.50),
        p95_ms=percentile_ms(durations, 0.95),
        p99_ms=percentile_ms(durations, 0.99),
        max_ms=max(durations, default=0),
    )


def _stderr_text(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stderr or b"").decode("utf-8", errors="replace").strip()


def _stdout_text(result: subprocess.CompletedProcess[bytes]) -> str:
    return (result.stdout or b"").decode("utf-8", errors="replace").strip()


def _run_adb_operation(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    serial: str,
    operation: Operation,
    timeout_s: float,
    runner: Runner,
    forward_cache: MutableMapping[str, str] | None = None,
    forward_cache_lock: threading.Lock | None = None,
) -> Sample:
    started = time.perf_counter()
    try:
        if operation.kind == "forward_atx":
            sample = _run_forward_operation(
                adb_bin=adb_bin,
                server_flags=server_flags,
                serial=serial,
                timeout_s=timeout_s,
                runner=runner,
            )
        elif operation.kind == "forward_atx_cached":
            sample = _run_cached_forward_operation(
                adb_bin=adb_bin,
                server_flags=server_flags,
                serial=serial,
                timeout_s=timeout_s,
                runner=runner,
                forward_cache=forward_cache,
                forward_cache_lock=forward_cache_lock,
            )
        elif operation.kind in {
            "stability_legacy",
            "ime_legacy",
            "cleanup_legacy",
            "stability_batched",
            "ime_batched",
            "cleanup_batched",
            "recovery_storm_legacy",
            "recovery_storm_coalesced",
        }:
            sample = _run_fixed_adb_count_operation(
                adb_bin=adb_bin,
                server_flags=server_flags,
                serial=serial,
                operation=operation,
                timeout_s=timeout_s,
                runner=runner,
            )
        else:
            cmd = _adb_command(
                adb_bin,
                server_flags,
                operation.argv,
                serial=serial,
            )
            result = runner(cmd, timeout_s)
            sample = Sample(
                serial=serial,
                operation=operation.name,
                ok=result.returncode == 0,
                timed_out=False,
                duration_ms=round((time.perf_counter() - started) * 1_000),
                returncode=result.returncode,
                error="" if result.returncode == 0 else _stderr_text(result),
                adb_invocations=1,
            )
    except subprocess.TimeoutExpired:
        sample = Sample(
            serial=serial,
            operation=operation.name,
            ok=False,
            timed_out=True,
            duration_ms=round((time.perf_counter() - started) * 1_000),
            returncode=None,
            error=f"timeout after {timeout_s}s",
            adb_invocations=1,
        )
    except FileNotFoundError:
        sample = Sample(
            serial=serial,
            operation=operation.name,
            ok=False,
            timed_out=False,
            duration_ms=round((time.perf_counter() - started) * 1_000),
            returncode=None,
            error=f"adb binary not found: {adb_bin}",
            adb_invocations=0,
        )
    return sample


def _fixed_adb_count_for_operation(operation: Operation) -> int:
    return {
        "stability_legacy": 15,
        "ime_legacy": 7,
        "cleanup_legacy": 5,
        "stability_batched": 1,
        "ime_batched": 1,
        "cleanup_batched": 1,
        # The storm workloads model already-batched u2/atx cleanup. The
        # difference is scheduling: legacy admits every duplicate request,
        # coalesced admits one per (serial, operation).
        "recovery_storm_legacy": 3,
        "recovery_storm_coalesced": 3,
    }.get(operation.kind, 1)


def _run_fixed_adb_count_operation(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    serial: str,
    operation: Operation,
    timeout_s: float,
    runner: Runner,
) -> Sample:
    started = time.perf_counter()
    count = _fixed_adb_count_for_operation(operation)
    ok = True
    returncode = 0
    error = ""
    for _index in range(count):
        cmd = _adb_command(
            adb_bin,
            server_flags,
            ("shell", "true"),
            serial=serial,
        )
        result = runner(cmd, timeout_s)
        if result.returncode != 0:
            ok = False
            returncode = result.returncode
            error = _stderr_text(result) or _stdout_text(result)
            break
    return Sample(
        serial=serial,
        operation=operation.name,
        ok=ok,
        timed_out=False,
        duration_ms=round((time.perf_counter() - started) * 1_000),
        returncode=returncode,
        error=error,
        adb_invocations=count,
    )


def _run_forward_operation(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    serial: str,
    timeout_s: float,
    runner: Runner,
) -> Sample:
    started = time.perf_counter()
    forward_cmd = _adb_command(
        adb_bin,
        server_flags,
        ("forward", "tcp:0", "tcp:7912"),
        serial=serial,
    )
    result = runner(forward_cmd, timeout_s)
    output = _stdout_text(result)
    allocated_port = output.splitlines()[-1].strip() if output else ""
    ok = result.returncode == 0 and allocated_port.isdigit()
    error = "" if ok else (_stderr_text(result) or output)
    if ok:
        remove_cmd = _adb_command(
            adb_bin,
            server_flags,
            ("forward", "--remove", f"tcp:{allocated_port}"),
            serial=serial,
        )
        remove_result = runner(remove_cmd, max(2.0, min(timeout_s, 5.0)))
        if remove_result.returncode != 0:
            ok = False
            error = _stderr_text(remove_result) or _stdout_text(remove_result)
    return Sample(
        serial=serial,
        operation="forward_atx",
        ok=ok,
        timed_out=False,
        duration_ms=round((time.perf_counter() - started) * 1_000),
        returncode=0 if ok else result.returncode,
        error=error,
        adb_invocations=2 if ok else 1,
    )


def _run_cached_forward_operation(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    serial: str,
    timeout_s: float,
    runner: Runner,
    forward_cache: MutableMapping[str, str] | None,
    forward_cache_lock: threading.Lock | None,
) -> Sample:
    started = time.perf_counter()
    if forward_cache is None:
        forward_cache = {}
    if forward_cache_lock is None:
        forward_cache_lock = threading.Lock()
    with forward_cache_lock:
        cached_port = forward_cache.get(serial)
    if cached_port:
        return Sample(
            serial=serial,
            operation="forward_atx_cached",
            ok=True,
            timed_out=False,
            duration_ms=round((time.perf_counter() - started) * 1_000),
            returncode=0,
            error="",
            adb_invocations=0,
        )
    forward_cmd = _adb_command(
        adb_bin,
        server_flags,
        ("forward", "tcp:0", "tcp:7912"),
        serial=serial,
    )
    result = runner(forward_cmd, timeout_s)
    output = _stdout_text(result)
    allocated_port = output.splitlines()[-1].strip() if output else ""
    ok = result.returncode == 0 and allocated_port.isdigit()
    error = "" if ok else (_stderr_text(result) or output)
    if ok:
        with forward_cache_lock:
            forward_cache.setdefault(serial, allocated_port)
    return Sample(
        serial=serial,
        operation="forward_atx_cached",
        ok=ok,
        timed_out=False,
        duration_ms=round((time.perf_counter() - started) * 1_000),
        returncode=0 if ok else result.returncode,
        error=error,
        adb_invocations=1,
    )


def _make_plan(
    *,
    serials: Sequence[str],
    operations: Sequence[Operation],
    concurrency: int,
    iterations_per_device: int,
) -> list[tuple[str, Operation]]:
    base_plan = [
        (serial, operation)
        for _iteration in range(iterations_per_device)
        for serial in serials
        for operation in operations
    ]
    base_samples = len(base_plan)
    # Keep enough samples to actually fill the configured concurrency, even
    # when testing from a small local phone count.
    total_samples = max(base_samples, concurrency * len(operations) * 2)
    return [base_plan[index % base_samples] for index in range(total_samples)]


def evaluate_result(
    stats: Stats,
    *,
    max_p95_ms: int,
    max_failure_rate: float,
    max_timeout_rate: float,
) -> tuple[bool, str]:
    if stats.samples == 0:
        return False, "no samples"
    failure_rate = stats.failed / stats.samples
    timeout_rate = stats.timed_out / stats.samples
    if timeout_rate > max_timeout_rate:
        return False, f"timeout_rate={timeout_rate:.3f}>{max_timeout_rate:.3f}"
    if failure_rate > max_failure_rate:
        return False, f"failure_rate={failure_rate:.3f}>{max_failure_rate:.3f}"
    if stats.p95_ms > max_p95_ms:
        return False, f"p95_ms={stats.p95_ms}>{max_p95_ms}"
    return True, "ok"


def run_level(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    serials: Sequence[str],
    operations: Sequence[Operation],
    concurrency: int,
    iterations_per_device: int,
    timeout_s: float,
    max_p95_ms: int,
    max_failure_rate: float,
    max_timeout_rate: float,
    runner: Runner = _subprocess_runner,
) -> LevelResult:
    plan = _make_plan(
        serials=serials,
        operations=operations,
        concurrency=concurrency,
        iterations_per_device=iterations_per_device,
    )
    if any(operation.kind == "recovery_storm_coalesced" for operation in operations):
        seen_recovery: set[tuple[str, str]] = set()
        coalesced_plan: list[tuple[str, Operation]] = []
        for serial, operation in plan:
            key = (serial, operation.name)
            if key in seen_recovery:
                continue
            seen_recovery.add(key)
            coalesced_plan.append((serial, operation))
        plan = coalesced_plan
    started = time.perf_counter()
    samples: list[Sample] = []
    forward_cache: dict[str, str] = {}
    forward_cache_lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _run_adb_operation,
                adb_bin=adb_bin,
                server_flags=server_flags,
                serial=serial,
                operation=operation,
                timeout_s=timeout_s,
                runner=runner,
                forward_cache=forward_cache,
                forward_cache_lock=forward_cache_lock,
            )
            for serial, operation in plan
        ]
        for future in as_completed(futures):
            samples.append(future.result())
    elapsed = time.perf_counter() - started
    overall = summarize_samples(samples)
    grouped: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.operation].append(sample)
    by_operation = {
        name: summarize_samples(operation_samples)
        for name, operation_samples in sorted(grouped.items())
    }
    passed, reason = evaluate_result(
        overall,
        max_p95_ms=max_p95_ms,
        max_failure_rate=max_failure_rate,
        max_timeout_rate=max_timeout_rate,
    )
    return LevelResult(
        concurrency=concurrency,
        commands=len(samples),
        adb_invocations=sum(sample.adb_invocations for sample in samples),
        devices_used=len(set(sample.serial for sample in samples)),
        seconds=round(elapsed, 3),
        stats=overall,
        by_operation=by_operation,
        passed=passed,
        reason=reason,
    )


def _print_table(results: Sequence[LevelResult]) -> None:
    header = (
        "conc  cmds   adb  devs  ok    fail  tout  p50  p95  p99  max  sec    verdict"
    )
    print(header)
    print("-" * len(header))
    for result in results:
        stats = result.stats
        verdict = "PASS" if result.passed else f"FAIL:{result.reason}"
        print(
            f"{result.concurrency:>4}  "
            f"{result.commands:>4}  "
            f"{result.adb_invocations:>4}  "
            f"{result.devices_used:>4}  "
            f"{stats.ok:>4}  "
            f"{stats.failed:>4}  "
            f"{stats.timed_out:>4}  "
            f"{stats.p50_ms:>3}  "
            f"{stats.p95_ms:>3}  "
            f"{stats.p99_ms:>3}  "
            f"{stats.max_ms:>3}  "
            f"{result.seconds:>5.1f}  "
            f"{verdict}"
        )


def _result_payload(
    *,
    adb_bin: str,
    server_flags: Sequence[str],
    workload: str,
    devices: Sequence[Device],
    results: Sequence[LevelResult],
    max_p95_ms: int,
    max_failure_rate: float,
    max_timeout_rate: float,
) -> dict[str, object]:
    passing = [result.concurrency for result in results if result.passed]
    return {
        "kind": "adb_capacity_benchmark",
        "adb_bin": adb_bin,
        "server_flags": list(server_flags),
        "workload": workload,
        "device_count": len(devices),
        "devices": [asdict(device) for device in devices],
        "thresholds": {
            "max_p95_ms": max_p95_ms,
            "max_failure_rate": max_failure_rate,
            "max_timeout_rate": max_timeout_rate,
        },
        "max_passing_concurrency": max(passing) if passing else 0,
        "results": [asdict(result) for result in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure host ADB capacity with safe read-only commands by default."
        )
    )
    parser.add_argument("--adb-bin", default=os.getenv("ADB_BIN", "adb"))
    parser.add_argument(
        "--serial",
        action="append",
        default=[],
        help="device serial to include; repeatable. Default: adb devices -l",
    )
    parser.add_argument(
        "--include-offline",
        action="store_true",
        help="include non-device states from adb devices output",
    )
    parser.add_argument(
        "--levels",
        type=parse_levels,
        default=DEFAULT_LEVELS,
        help="comma-separated concurrency ladder (default: 1,2,4,8,12,16,24,32,48,64)",
    )
    parser.add_argument(
        "--iterations-per-device",
        type=int,
        default=3,
        help="minimum operation rounds per device per level",
    )
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument(
        "--workload",
        choices=(
            "read",
            "light",
            "forward",
            "forward_cached",
            "recovery_legacy",
            "recovery_batched",
            "recovery_storm_legacy",
            "recovery_storm_coalesced",
        ),
        default="read",
    )
    parser.add_argument(
        "--mock-devices",
        type=int,
        default=0,
        help="run with N synthetic serials instead of calling adb devices",
    )
    parser.add_argument(
        "--mock-delay-ms",
        type=float,
        default=1.0,
        help="per-adb-call delay for --mock-devices",
    )
    parser.add_argument("--max-p95-ms", type=int, default=300)
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--max-timeout-rate", type=float, default=0.0)
    parser.add_argument("--stop-on-fail", action="store_true")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    if args.iterations_per_device < 1:
        parser.error("--iterations-per-device must be >= 1")
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be > 0")

    server_flags = _adb_server_flags_from_env()
    runner: Runner = _subprocess_runner
    if args.mock_devices:
        if args.mock_devices < 1:
            parser.error("--mock-devices must be >= 1")
        serials = [f"MOCK{index:04d}" for index in range(1, args.mock_devices + 1)]
        devices = [
            Device(serial=serial, state="mock", detail="")
            for serial in serials
        ]
        runner = _mock_runner_factory(delay_ms=args.mock_delay_ms)
    elif args.serial:
        serials = dedupe_serials_prefer_usb(args.serial)
        devices = [
            Device(serial=serial, state="selected", detail="")
            for serial in serials
        ]
    else:
        devices = discover_devices(
            adb_bin=args.adb_bin,
            server_flags=server_flags,
            include_offline=args.include_offline,
            timeout_s=args.timeout_s,
        )
        serials = [device.serial for device in devices]

    if not serials:
        print("No usable adb devices found.", file=sys.stderr)
        return 2

    operations = build_workload(args.workload)
    print(
        f"ADB capacity benchmark: devices={len(serials)} "
        f"workload={args.workload} levels={','.join(map(str, args.levels))} "
        f"server_flags={' '.join(server_flags) or '<local>'}"
    )
    print(
        "Thresholds: "
        f"p95<={args.max_p95_ms}ms "
        f"failure_rate<={args.max_failure_rate:.3f} "
        f"timeout_rate<={args.max_timeout_rate:.3f}"
    )

    results: list[LevelResult] = []
    for level in args.levels:
        result = run_level(
            adb_bin=args.adb_bin,
            server_flags=server_flags,
            serials=serials,
            operations=operations,
            concurrency=level,
            iterations_per_device=args.iterations_per_device,
            timeout_s=args.timeout_s,
            max_p95_ms=args.max_p95_ms,
            max_failure_rate=args.max_failure_rate,
            max_timeout_rate=args.max_timeout_rate,
            runner=runner,
        )
        results.append(result)
        _print_table([result])
        if args.stop_on_fail and not result.passed:
            break

    payload = _result_payload(
        adb_bin=args.adb_bin,
        server_flags=server_flags,
        workload=args.workload,
        devices=devices,
        results=results,
        max_p95_ms=args.max_p95_ms,
        max_failure_rate=args.max_failure_rate,
        max_timeout_rate=args.max_timeout_rate,
    )
    print(
        f"max_passing_concurrency={payload['max_passing_concurrency']} "
        f"(device_count={len(devices)})"
    )
    if args.json_output:
        args.json_output.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"json_output={args.json_output}")
    return 0 if payload["max_passing_concurrency"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
