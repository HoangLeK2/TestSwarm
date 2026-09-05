from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence

import pytest

from scripts import benchmark_adb_capacity as bench


def _completed(
    *,
    returncode: int = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=["adb"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_adb_server_flags_prefer_socket_host_port() -> None:
    flags = bench._adb_server_flags_from_env(
        {
            "ADB_HOST": "ignored.local",
            "ADB_PORT": "1111",
            "ADB_SERVER_SOCKET": "tcp:host.docker.internal:5038",
        }
    )

    assert flags == ["-H", "host.docker.internal", "-P", "5038"]


def test_extract_adb_invocation_removes_binary_server_flags_and_serial() -> None:
    serial, argv = bench._extract_adb_invocation(
        [
            "adb",
            "-H",
            "host.docker.internal",
            "-P",
            "5038",
            "-s",
            "SERIAL1",
            "shell",
            "true",
        ],
        adb_bin="adb",
        server_flags=["-H", "host.docker.internal", "-P", "5038"],
    )

    assert serial == "SERIAL1"
    assert argv == ("shell", "true")


def test_adbutils_transport_runner_adapts_to_completed_process(monkeypatch) -> None:
    calls: list[tuple[tuple[str, ...], str | None, float]] = []

    class FakeTransport:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(
            self,
            argv: Sequence[str],
            *,
            serial: str | None,
            timeout: float,
        ):
            calls.append((tuple(argv), serial, timeout))
            return bench.AdbRunResult("ok\n", 0, transport="adbutils")

    monkeypatch.setattr(bench, "AdbutilsTransport", FakeTransport)

    runner = bench._transport_runner(
        transport="adbutils",
        adb_bin="adb",
        server_flags=[],
    )
    result = runner(["adb", "-s", "SERIAL1", "shell", "true"], 1.5)

    assert result.returncode == 0
    assert result.stdout == b"ok\n"
    assert calls == [(("shell", "true"), "SERIAL1", 1.5)]


def test_hybrid_transport_runner_falls_back_to_binary_for_unsupported(
    monkeypatch,
) -> None:
    binary_calls: list[list[str]] = []

    class FakeTransport:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run(
            self,
            argv: Sequence[str],
            *,
            serial: str | None,
            timeout: float,
        ):
            return bench.AdbRunResult(
                "unsupported",
                -2,
                transport="adbutils",
                supported=False,
            )

    def fake_binary_runner(
        cmd: Sequence[str],
        _timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        binary_calls.append(list(cmd))
        return _completed(stdout=b"binary-ok\n")

    monkeypatch.setattr(bench, "AdbutilsTransport", FakeTransport)
    monkeypatch.setattr(bench, "_subprocess_runner", fake_binary_runner)

    runner = bench._transport_runner(
        transport="hybrid",
        adb_bin="adb",
        server_flags=[],
    )
    result = runner(["adb", "-s", "SERIAL1", "install", "-r", "app.apk"], 1.0)

    assert result.returncode == 0
    assert result.stdout == b"binary-ok\n"
    assert binary_calls == [["adb", "-s", "SERIAL1", "install", "-r", "app.apk"]]


def test_mock_binary_profile_pays_spawn_cost_for_every_command(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(bench.time, "sleep", lambda seconds: sleeps.append(seconds))

    runner = bench._mock_runner_factory(
        delay_ms=1.0,
        transport="binary",
        binary_spawn_ms=9.0,
        adbutils_connect_ms=100.0,
        adbutils_call_ms=100.0,
    )

    runner(["adb", "-s", "SERIAL1", "shell", "true"], 1.0)
    runner(["adb", "-s", "SERIAL1", "shell", "true"], 1.0)

    assert sleeps == [0.010, 0.010]


def test_mock_adbutils_profile_reuses_connection_per_serial(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(bench.time, "sleep", lambda seconds: sleeps.append(seconds))

    runner = bench._mock_runner_factory(
        delay_ms=1.0,
        transport="adbutils",
        binary_spawn_ms=100.0,
        adbutils_connect_ms=9.0,
        adbutils_call_ms=2.0,
    )

    runner(["adb", "-s", "SERIAL1", "shell", "true"], 1.0)
    runner(["adb", "-s", "SERIAL1", "shell", "true"], 1.0)
    runner(["adb", "-s", "SERIAL2", "shell", "true"], 1.0)

    assert sleeps == [0.012, 0.003, 0.012]


def test_mock_runner_can_inject_offline_failures() -> None:
    runner = bench._mock_runner_factory(
        delay_ms=0,
        transport="adbutils",
        offline_every=2,
    )

    ok = runner(["adb", "-s", "MOCK0001", "shell", "true"], 1.0)
    offline = runner(["adb", "-s", "MOCK0002", "shell", "true"], 1.0)

    assert ok.returncode == 0
    assert offline.returncode == 1
    assert offline.stderr == b"error: device offline\n"


def test_fake_adb_subprocess_runner_executes_adb_shim() -> None:
    adb_bin, runner, tmpdir = bench._fake_adb_subprocess_runner_factory(
        serials=["MOCK0001"],
        delay_ms=0,
        offline_every=0,
        fail_every=0,
        timeout_every=0,
        timeout_sleep_ms=10_000,
    )
    try:
        result = runner([adb_bin, "-s", "MOCK0001", "shell", "true"], 1.0)
    finally:
        tmpdir.cleanup()

    assert result.returncode == 0
    assert result.stdout == b"ok\n"


def test_fake_adb_subprocess_runner_can_inject_device_offline() -> None:
    adb_bin, runner, tmpdir = bench._fake_adb_subprocess_runner_factory(
        serials=["MOCK0002"],
        delay_ms=0,
        offline_every=2,
        fail_every=0,
        timeout_every=0,
        timeout_sleep_ms=10_000,
    )
    try:
        result = runner([adb_bin, "-s", "MOCK0002", "shell", "true"], 1.0)
    finally:
        tmpdir.cleanup()

    assert result.returncode == 1
    assert result.stderr == b"error: device offline\n"


def test_fake_adb_subprocess_runner_can_timeout() -> None:
    adb_bin, runner, tmpdir = bench._fake_adb_subprocess_runner_factory(
        serials=["MOCK0003"],
        delay_ms=0,
        offline_every=0,
        fail_every=0,
        timeout_every=3,
        timeout_sleep_ms=100,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            runner([adb_bin, "-s", "MOCK0003", "shell", "true"], 0.01)
    finally:
        tmpdir.cleanup()


def test_parse_devices_filters_offline_and_dedupes_usb_preferred() -> None:
    output = """
List of devices attached
SERIAL1 device product:a model:x
10.0.0.2:5555 device product:a model:y
10.0.0.2 offline
10.0.0.2 device product:a model:y_usb
OFFLINE1 offline
"""

    devices = bench.parse_adb_devices(output)
    serials = bench.dedupe_serials_prefer_usb([device.serial for device in devices])

    assert serials == ["10.0.0.2", "SERIAL1"]


def test_parse_levels_rejects_invalid_values() -> None:
    assert bench.parse_levels("1,2,4,4") == (1, 2, 4)

    with pytest.raises(argparse.ArgumentTypeError):
        bench.parse_levels("1,0")


def test_make_plan_runs_every_operation_for_every_serial() -> None:
    operations = (
        bench.Operation("read", ("shell", "true")),
        bench.Operation("forward", tuple(), kind="forward_atx_cached"),
    )

    plan = bench._make_plan(
        serials=["A", "B", "C"],
        operations=operations,
        concurrency=1,
        iterations_per_device=2,
    )

    assert len(plan) == 12
    assert {
        (serial, operation.name)
        for serial, operation in plan
    } == {
        ("A", "read"),
        ("A", "forward"),
        ("B", "read"),
        ("B", "forward"),
        ("C", "read"),
        ("C", "forward"),
    }


def test_summarize_and_evaluate_p95_threshold() -> None:
    samples = [
        bench.Sample("A", "op", True, False, 10, 0, ""),
        bench.Sample("A", "op", True, False, 20, 0, ""),
        bench.Sample("A", "op", True, False, 30, 0, ""),
        bench.Sample("A", "op", True, False, 500, 0, ""),
    ]

    stats = bench.summarize_samples(samples)
    passed, reason = bench.evaluate_result(
        stats,
        max_p95_ms=100,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
    )

    assert stats.p50_ms == 20
    assert stats.p95_ms == 500
    assert not passed
    assert reason == "p95_ms=500>100"


def test_run_level_uses_remote_flags_and_reports_capacity() -> None:
    calls: list[list[str]] = []

    def fake_runner(
        cmd: Sequence[str],
        _timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(cmd))
        return _completed(stdout=b"ok\n")

    result = bench.run_level(
        adb_bin="adb",
        server_flags=["-H", "host.docker.internal", "-P", "5037"],
        serials=["SERIAL1", "SERIAL2"],
        operations=(bench.Operation("true", ("shell", "true")),),
        concurrency=4,
        iterations_per_device=1,
        timeout_s=1.0,
        max_p95_ms=300,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
        runner=fake_runner,
    )

    assert result.passed
    assert result.commands == 8
    assert result.adb_invocations == 8
    assert result.devices_used == 2
    assert calls
    assert all(
        call[:6] == ["adb", "-H", "host.docker.internal", "-P", "5037", "-s"]
        for call in calls
    )


def test_forward_workload_removes_allocated_port() -> None:
    calls: list[list[str]] = []

    def fake_runner(
        cmd: Sequence[str],
        _timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(cmd))
        if "forward" in cmd and "tcp:0" in cmd:
            return _completed(stdout=b"49231\n")
        return _completed(stdout=b"")

    sample = bench._run_adb_operation(
        adb_bin="adb",
        server_flags=[],
        serial="SERIAL1",
        operation=bench.Operation("forward_atx", tuple(), kind="forward_atx"),
        timeout_s=1.0,
        runner=fake_runner,
    )

    assert sample.ok
    assert sample.adb_invocations == 2
    assert calls[0] == ["adb", "-s", "SERIAL1", "forward", "tcp:0", "tcp:7912"]
    assert calls[1] == [
        "adb",
        "-s",
        "SERIAL1",
        "forward",
        "--remove",
        "tcp:49231",
    ]


def test_cached_forward_workload_reuses_one_forward_per_serial() -> None:
    calls: list[list[str]] = []

    def fake_runner(
        cmd: Sequence[str],
        _timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(cmd))
        if "forward" in cmd and "tcp:0" in cmd:
            port = 49000 + len(calls)
            return _completed(stdout=f"{port}\n".encode())
        return _completed(stdout=b"ok\n")

    result = bench.run_level(
        adb_bin="adb",
        server_flags=[],
        serials=["SERIAL1", "SERIAL2"],
        operations=(bench.Operation("forward_atx_cached", tuple(), kind="forward_atx_cached"),),
        concurrency=4,
        iterations_per_device=3,
        timeout_s=1.0,
        max_p95_ms=300,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
        runner=fake_runner,
    )

    assert result.passed
    assert result.commands == 8
    assert result.adb_invocations == 2
    assert calls == [
        ["adb", "-s", "SERIAL1", "forward", "tcp:0", "tcp:7912"],
        ["adb", "-s", "SERIAL2", "forward", "tcp:0", "tcp:7912"],
    ]


def test_recovery_batched_workload_reduces_adb_invocations() -> None:
    def fake_runner(
        _cmd: Sequence[str],
        _timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        return _completed(stdout=b"ok\n")

    legacy = bench.run_level(
        adb_bin="adb",
        server_flags=[],
        serials=["SERIAL1", "SERIAL2"],
        operations=bench.build_workload("recovery_legacy"),
        concurrency=4,
        iterations_per_device=1,
        timeout_s=1.0,
        max_p95_ms=300,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
        runner=fake_runner,
    )
    batched = bench.run_level(
        adb_bin="adb",
        server_flags=[],
        serials=["SERIAL1", "SERIAL2"],
        operations=bench.build_workload("recovery_batched"),
        concurrency=4,
        iterations_per_device=1,
        timeout_s=1.0,
        max_p95_ms=300,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
        runner=fake_runner,
    )

    assert legacy.commands == batched.commands == 24
    assert legacy.adb_invocations == 216
    assert batched.adb_invocations == 24


def test_recovery_storm_coalesced_admits_one_recovery_per_serial_kind() -> None:
    def fake_runner(
        _cmd: Sequence[str],
        _timeout_s: float,
    ) -> subprocess.CompletedProcess[bytes]:
        return _completed(stdout=b"ok\n")

    legacy = bench.run_level(
        adb_bin="adb",
        server_flags=[],
        serials=["SERIAL1", "SERIAL2"],
        operations=bench.build_workload("recovery_storm_legacy"),
        concurrency=4,
        iterations_per_device=5,
        timeout_s=1.0,
        max_p95_ms=300,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
        runner=fake_runner,
    )
    coalesced = bench.run_level(
        adb_bin="adb",
        server_flags=[],
        serials=["SERIAL1", "SERIAL2"],
        operations=bench.build_workload("recovery_storm_coalesced"),
        concurrency=4,
        iterations_per_device=5,
        timeout_s=1.0,
        max_p95_ms=300,
        max_failure_rate=0.0,
        max_timeout_rate=0.0,
        runner=fake_runner,
    )

    assert legacy.commands == 20
    assert legacy.adb_invocations == 60
    assert coalesced.commands == 4
    assert coalesced.adb_invocations == 12


def test_mock_runner_allocates_forward_ports() -> None:
    runner = bench._mock_runner_factory(delay_ms=0.0)

    first = runner(["adb", "-s", "SERIAL1", "forward", "tcp:0", "tcp:7912"], 1.0)
    second = runner(["adb", "-s", "SERIAL2", "forward", "tcp:0", "tcp:7912"], 1.0)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout != second.stdout
