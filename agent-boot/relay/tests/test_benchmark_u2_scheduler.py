from __future__ import annotations

import pytest

from scripts import benchmark_u2_scheduler as bench


def test_u2_scheduler_benchmark_shows_dump_singleflight_reduces_work() -> None:
    result = bench.run_u2_scheduler_benchmark(
        duplicate_requests=20,
        selector_reads=20,
        touch_actions=5,
        background_requests=40,
        failing_requests=20,
        dump_ms=50,
        selector_ms=15,
        parse_ms=2,
        touch_rpc_ms=25,
        click_spec_ms=35,
        wait_timeout_ms=5000,
        wait_poll_interval_ms=100,
        wait_found_after_polls=3,
        session_lock_ms=80,
        work_ms=100,
        global_limit=16,
        background_limit=12,
        failure_threshold=3,
    )

    dump_burst = result["dump_burst"]
    current = dump_burst["current"]
    optimized = dump_burst["optimized"]

    assert current["actual_dump_calls"] == 20
    assert optimized["actual_dump_calls"] == 1
    assert dump_burst["actual_call_reduction_percent"] == 95.0
    assert dump_burst["p95_latency_reduction_percent"] > 90.0

    selector_batch = result["selector_batch"]
    assert selector_batch["current"]["actual_selector_u2_calls"] == 20
    assert selector_batch["optimized"]["actual_selector_u2_calls"] == 0
    assert selector_batch["selector_u2_call_reduction_percent"] == 100.0
    assert selector_batch["p95_latency_reduction_percent"] > 80.0

    touch_direct = result["touch_direct"]
    assert touch_direct["current"]["session_locks"] == 1
    assert touch_direct["optimized"]["session_locks"] == 0
    assert touch_direct["session_lock_reduction_percent"] == 100.0
    assert touch_direct["p95_latency_reduction_percent"] > 30.0

    selector_click = result["selector_click_fusion"]
    assert selector_click["current"]["actual_selector_u2_calls"] == 21
    assert selector_click["optimized"]["actual_selector_u2_calls"] == 0
    assert selector_click["optimized"]["session_locks"] == 0
    assert selector_click["p95_latency_reduction_percent"] > 80.0

    click_spec = result["click_spec_direct_bounds"]
    assert click_spec["current"]["actual_selector_u2_calls"] == 5
    assert click_spec["optimized"]["actual_selector_u2_calls"] == 0
    assert click_spec["optimized"]["session_locks"] == 0
    assert click_spec["p95_latency_reduction_percent"] > 40.0

    wait_poll = result["wait_poll"]
    assert wait_poll["current"]["session_locks"] == 40
    assert wait_poll["optimized"]["session_locks"] == 0
    assert wait_poll["lock_held_reduction_percent"] == 100.0
    assert wait_poll["p95_latency_reduction_percent"] > 90.0

    wait_gone_poll = result["wait_gone_poll"]
    assert wait_gone_poll["current"]["session_locks"] == 40
    assert wait_gone_poll["optimized"]["session_locks"] == 0
    assert wait_gone_poll["lock_held_reduction_percent"] == 100.0
    assert wait_gone_poll["p95_latency_reduction_percent"] > 90.0

    xml_index_cache = result["xml_index_cache"]
    assert xml_index_cache["current"]["xml_parse_index_builds"] == 40 * 3
    assert xml_index_cache["optimized"]["xml_parse_index_builds"] == 40 * 2
    assert xml_index_cache["parse_index_build_reduction_percent"] > 30.0

    xml_poll_coalescing = result["xml_poll_coalescing"]
    assert xml_poll_coalescing["current"]["poll_loops"] == 40
    assert xml_poll_coalescing["optimized"]["poll_loops"] == 1
    assert xml_poll_coalescing["poll_loop_reduction_percent"] > 95.0
    assert xml_poll_coalescing["dump_request_attempt_reduction_percent"] > 95.0

    xml_selector_lookup_cache = result["xml_selector_lookup_cache"]
    assert xml_selector_lookup_cache["current"]["node_scans"] == 20
    assert xml_selector_lookup_cache["optimized"]["node_scans"] == 5
    assert xml_selector_lookup_cache["node_scan_reduction_percent"] == 75.0

    flow_wait = result["flow_wait_and_click"]
    assert flow_wait["current"]["session_locks"] == 40
    assert flow_wait["optimized"]["session_locks"] == 0
    assert flow_wait["selector_u2_call_reduction_percent"] == 100.0
    assert flow_wait["p95_latency_reduction_percent"] > 90.0

    flow_find_click = result["flow_find_click_wait"]
    assert flow_find_click["current"]["session_locks"] == 40
    assert flow_find_click["optimized"]["session_locks"] == 0
    assert flow_find_click["selector_u2_call_reduction_percent"] == 100.0
    assert flow_find_click["p95_latency_reduction_percent"] > 90.0

    flow_swipe = result["flow_swipe_until_found"]
    assert flow_swipe["current"]["session_locks"] == 40
    assert flow_swipe["optimized"]["session_locks"] == 0
    assert flow_swipe["current"]["selector_u2_calls"] == 40 * 6
    assert flow_swipe["optimized"]["selector_u2_calls"] == 0
    assert flow_swipe["lock_held_reduction_percent"] == 100.0
    assert flow_swipe["p95_latency_reduction_percent"] > 15.0


def test_u2_scheduler_benchmark_shows_visible_reserved_slots_and_breaker() -> None:
    result = bench.run_u2_scheduler_benchmark(
        duplicate_requests=20,
        selector_reads=20,
        touch_actions=5,
        background_requests=40,
        failing_requests=20,
        dump_ms=50,
        selector_ms=15,
        parse_ms=2,
        touch_rpc_ms=25,
        click_spec_ms=35,
        wait_timeout_ms=5000,
        wait_poll_interval_ms=100,
        wait_found_after_polls=3,
        session_lock_ms=80,
        work_ms=100,
        global_limit=16,
        background_limit=12,
        failure_threshold=3,
    )

    priority = result["priority"]
    assert priority["current"]["visible_wait_ms"] == 100
    assert priority["optimized"]["visible_wait_ms"] == 0
    assert priority["visible_wait_reduction_percent"] == 100.0

    breaker = result["breaker"]
    assert breaker["current"]["actual_attempts"] == 20
    assert breaker["optimized"]["actual_attempts"] == 3
    assert breaker["optimized"]["dropped_by_breaker"] == 17
    assert breaker["attempt_reduction_percent"] == 85.0

    heartbeat = result["heartbeat_coverage"]
    assert heartbeat["session_count"] == 40
    assert heartbeat["probe_budget_per_tick"] == 8
    assert heartbeat["probe_ticks_for_full_scan"] == 5
    assert heartbeat["full_scan_seconds"] == 50
    assert heartbeat["coverage_percent_per_tick"] == 20

    churn = result["churn_decision"]
    assert churn["current"]["reset_attempts"] == 20
    assert churn["optimized"]["reset_attempts"] == 3
    assert churn["device_side_resets_avoided"] == 17
    assert churn["reset_attempt_reduction_percent"] == 85.0


def test_u2_scheduler_benchmark_models_40_phone_lane_isolation() -> None:
    result = bench.run_u2_scheduler_benchmark(
        duplicate_requests=20,
        selector_reads=20,
        touch_actions=5,
        background_requests=40,
        failing_requests=20,
        dump_ms=50,
        selector_ms=15,
        parse_ms=2,
        touch_rpc_ms=25,
        click_spec_ms=35,
        wait_timeout_ms=5000,
        wait_poll_interval_ms=100,
        wait_found_after_polls=3,
        session_lock_ms=80,
        work_ms=100,
        global_limit=16,
        background_limit=12,
        failure_threshold=3,
        phone_count=40,
        visible_requests=4,
        background_per_phone=2,
    )

    lane = result["lane_isolation"]
    assert lane["current"]["visible_p95_wait_ms"] == 100
    assert lane["optimized"]["visible_p95_wait_ms"] == 0
    assert lane["optimized"]["background_peak_inflight"] == 12
    assert lane["visible_p95_wait_reduction_percent"] == 100.0
    assert lane["background_work_reduction_percent"] == 50.0
    assert lane["visible_isolated"] is True


def test_u2_scheduler_benchmark_models_100_phone_lane_isolation() -> None:
    result = bench.run_u2_scheduler_benchmark(
        duplicate_requests=20,
        selector_reads=20,
        touch_actions=5,
        background_requests=100,
        failing_requests=20,
        dump_ms=50,
        selector_ms=15,
        parse_ms=2,
        touch_rpc_ms=25,
        click_spec_ms=35,
        wait_timeout_ms=5000,
        wait_poll_interval_ms=100,
        wait_found_after_polls=3,
        session_lock_ms=80,
        work_ms=100,
        global_limit=16,
        background_limit=12,
        failure_threshold=3,
        phone_count=100,
        visible_requests=4,
        background_per_phone=2,
    )

    lane = result["lane_isolation"]
    assert lane["current"]["visible_p95_wait_ms"] == 100
    assert lane["optimized"]["visible_p95_wait_ms"] == 0
    assert lane["optimized"]["actual_background_work"] == 100
    assert lane["optimized"]["background_peak_inflight"] == 12
    assert lane["background_work_reduction_percent"] == 50.0
    assert lane["visible_isolated"] is True

    heartbeat = result["heartbeat_coverage"]
    assert heartbeat["session_count"] == 100
    assert heartbeat["probe_ticks_for_full_scan"] == 13
    assert heartbeat["full_scan_seconds"] == 130
    assert heartbeat["coverage_percent_per_tick"] == 8

    churn = result["churn_decision"]
    assert churn["optimized"]["reset_attempts"] == 3
    assert churn["device_side_resets_avoided"] == 17


@pytest.mark.asyncio
async def test_mock_phone_soak_benchmark_runs_real_executor_with_visible_lane() -> None:
    result = await bench.run_mock_phone_soak_benchmark(
        phone_count=12,
        visible_requests=2,
        background_per_phone=2,
        touch_per_visible=1,
        global_limit=4,
        background_limit=2,
        dump_ms=20,
        touch_rpc_ms=5,
        visible_deadline_ms=120,
        background_deadline_ms=1000,
        slow_every=6,
        slow_multiplier=3,
        fail_every=0,
    )

    assert result["kind"] == "u2_mock_phone_soak"
    assert result["scope"] == "real_U2Executor_with_fake_ATX_HTTP_endpoints"

    baseline = result["baseline"]
    optimized = result["optimized"]

    assert baseline["background_requests"] == 20
    assert optimized["background_requests"] == 20
    assert baseline["touch_requests"] == 2
    assert optimized["touch_requests"] == 2
    assert optimized["effective_visible_queue_wait_p95_ms"] < baseline["effective_visible_queue_wait_p95_ms"]
    assert optimized["visible_p95_ms"] < baseline["visible_p95_ms"]
    assert optimized["touch_p95_ms"] < baseline["touch_p95_ms"]
    assert result["visible_p95_reduction_percent"] > 50.0
    assert result["visible_queue_wait_p95_reduction_percent"] > 50.0


@pytest.mark.asyncio
async def test_mock_phone_soak_benchmark_models_100_phone_stability() -> None:
    result = await bench.run_mock_phone_soak_benchmark(
        phone_count=100,
        visible_requests=4,
        background_per_phone=2,
        touch_per_visible=1,
        global_limit=16,
        background_limit=12,
        dump_ms=10,
        touch_rpc_ms=3,
        visible_deadline_ms=150,
        background_deadline_ms=3000,
        slow_every=10,
        slow_multiplier=3,
        fail_every=0,
    )

    baseline = result["baseline"]
    optimized = result["optimized"]

    assert baseline["background_requests"] == 192
    assert optimized["background_requests"] == 192
    assert optimized["visible_requests"] == 4
    assert optimized["failed"] == 0
    assert optimized["executor_visible_deadline_drops"] == 0
    assert optimized["effective_visible_queue_wait_p95_ms"] < baseline["effective_visible_queue_wait_p95_ms"]
    assert optimized["visible_p95_ms"] < baseline["visible_p95_ms"]
    assert result["visible_p95_reduction_percent"] > 70.0
