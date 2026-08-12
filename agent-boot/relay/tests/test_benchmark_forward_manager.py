from __future__ import annotations

from scripts import benchmark_forward_manager as bench


def test_forward_manager_benchmark_reports_coalescing() -> None:
    result = bench.run_forward_manager_benchmark(
        serials=1,
        duplicate_requests_per_serial=8,
        concurrency=8,
        adb_delay_ms=5.0,
    )

    assert result["kind"] == "forward_manager_mock"
    assert result["requests"] == 8
    assert result["adb_forward_calls"] == 1
    assert result["adb_call_reduction_percent"] == 87.5
    assert result["stats"] == {
        "created": 1,
        "create_failed": 0,
        "create_joined": 7,
        "reused": 0,
        "removed": 0,
    }


def test_adb_forward_failure_cooldown_benchmark_bounds_create_attempts() -> None:
    result = bench.run_adb_forward_failure_cooldown_benchmark(
        serials=4,
        attempts_per_serial=6,
        concurrency=24,
        adb_delay_ms=1.0,
        cooldown_s=2.0,
    )

    assert result["kind"] == "adb_forward_failure_cooldown_mock"
    assert result["requests"] == 24
    assert result["adb_forward_create_calls"] == 4
    assert result["adb_create_reduction_percent"] == 83.33


def test_relay_agent_forward_failure_cooldown_benchmark_bounds_create_attempts() -> None:
    result = bench.run_relay_agent_forward_failure_cooldown_benchmark(
        serials=4,
        attempts_per_serial=6,
        concurrency=24,
        adb_delay_ms=1.0,
        cooldown_s=2.0,
    )

    assert result["kind"] == "relay_agent_forward_failure_cooldown_mock"
    assert result["requests"] == 24
    assert result["adb_forward_create_calls"] == 4
    assert result["adb_create_reduction_percent"] == 83.33
    assert result["stats"]["create_failed"] == 4
    assert result["stats"]["create_cooldown_skip"] == 20
