from __future__ import annotations

from scripts import benchmark_u2_churn as bench


def test_u2_churn_benchmark_shows_heartbeat_budget_reduces_tick_tail() -> None:
    result = bench.run_u2_churn_benchmark(
        sessions=20,
        dead_fraction=0.25,
        recent_fraction=0.25,
        locked_fraction=0.0,
        alive_delay_ms=0.0,
        dead_delay_ms=0.0,
        reconnect_delay_ms=0.0,
        heartbeat_budget=5,
        forward_limit=5,
        adb_delay_ms=0.0,
    )

    heartbeat = result["heartbeat"]
    current = heartbeat["current"]
    budgeted = heartbeat["budgeted"]
    optimized = heartbeat["optimized"]

    assert current["policy"] == "current_scan_all_keep_warm"
    assert budgeted["policy"] == "budgeted_rotating_heartbeat"
    assert optimized["policy"] == "optimized_budgeted_skip_recent_evict_stale"
    assert current["ticks"] == 1
    assert budgeted["ticks"] == 4
    assert current["probes"] == budgeted["probes"] == 20
    assert current["dead"] == budgeted["dead"] == 5
    assert current["reconnects"] == budgeted["reconnects"] == 5
    assert current["evictions"] == budgeted["evictions"] == 5
    assert current["background_ops"] == budgeted["background_ops"] == 30
    assert optimized["probes"] == 15
    assert optimized["reconnects"] == 0
    assert optimized["background_ops"] < current["background_ops"]
    assert heartbeat["optimized_background_ops_reduction_percent"] > 0


def test_u2_churn_benchmark_shows_forward_limit_reduces_peak_inflight() -> None:
    result = bench.run_u2_churn_benchmark(
        sessions=20,
        dead_fraction=0.0,
        recent_fraction=0.0,
        locked_fraction=0.0,
        alive_delay_ms=0.0,
        dead_delay_ms=0.0,
        reconnect_delay_ms=0.0,
        heartbeat_budget=5,
        forward_limit=4,
        adb_delay_ms=3.0,
    )

    forward = result["forward_create"]
    current = forward["current"]
    limited = forward["limited"]

    assert current["policy"] == "current_no_global_forward_create_limit"
    assert limited["policy"] == "limited_forward_create_burst"
    assert current["adb_forward_calls"] == limited["adb_forward_calls"] == 20
    assert current["peak_inflight"] == 20
    assert limited["peak_inflight"] <= 4
    assert forward["peak_inflight_reduction_percent"] >= 80.0
