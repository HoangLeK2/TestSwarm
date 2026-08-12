"""Synthetic benchmark for U2 command scheduling and hierarchy dedupe.

No real phones/ADB are used.  The model focuses on host-side effects that were
measured as expensive in large farms:

* duplicate dump_hierarchy requests for the same serial;
* dump_hierarchy followed by selector reads in one batch;
* background work occupying every U2 slot before a visible request arrives;
* failing serials retrying repeatedly instead of opening a breaker.
* wait_exists/wait_gone holding a U2 session lock for the full wait timeout.
* named u2_flow wait+click patterns holding a U2 session lock across waits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass(frozen=True)
class DumpBurstResult:
    policy: str
    duplicate_requests: int
    actual_dump_calls: int
    p95_latency_ms: int
    total_device_work_ms: int


@dataclass(frozen=True)
class SelectorBatchResult:
    policy: str
    selector_reads: int
    actual_dump_calls: int
    actual_selector_u2_calls: int
    p95_latency_ms: int
    total_device_work_ms: int


@dataclass(frozen=True)
class TouchDirectResult:
    policy: str
    touch_actions: int
    session_lock_ms: int
    rpc_ms: int
    p95_latency_ms: int
    session_locks: int


@dataclass(frozen=True)
class SelectorClickFusionResult:
    policy: str
    selector_reads: int
    actual_selector_u2_calls: int
    session_locks: int
    p95_latency_ms: int


@dataclass(frozen=True)
class ClickSpecDirectResult:
    policy: str
    click_specs: int
    actual_selector_u2_calls: int
    session_locks: int
    p95_latency_ms: int


@dataclass(frozen=True)
class WaitPollResult:
    policy: str
    waits: int
    session_locks: int
    lock_held_ms: int
    p95_latency_ms: int


@dataclass(frozen=True)
class XmlIndexCacheResult:
    policy: str
    flows: int
    polls_per_flow: int
    xml_versions_per_flow: int
    xml_parse_index_builds: int
    total_parse_index_ms: int


@dataclass(frozen=True)
class XmlPollCoalescingResult:
    policy: str
    concurrent_waits: int
    poll_loops: int
    dump_request_attempts: int
    actual_dump_calls: int
    poll_stat_increments: int


@dataclass(frozen=True)
class XmlSelectorLookupCacheResult:
    policy: str
    selector_lookups: int
    unique_selectors: int
    node_scans: int


@dataclass(frozen=True)
class FlowFastPathResult:
    policy: str
    flows: int
    session_locks: int
    selector_u2_calls: int
    lock_held_ms: int
    p95_latency_ms: int


@dataclass(frozen=True)
class PriorityResult:
    policy: str
    background_requests: int
    global_limit: int
    background_limit: int
    visible_wait_ms: int
    background_waves: int


@dataclass(frozen=True)
class LaneIsolationResult:
    policy: str
    phone_count: int
    visible_requests: int
    background_attempts: int
    actual_background_work: int
    global_limit: int
    background_limit: int
    visible_p95_wait_ms: int
    background_peak_inflight: int


@dataclass(frozen=True)
class MockPhoneSoakModeResult:
    policy: str
    phone_count: int
    visible_requests: int
    background_requests: int
    touch_requests: int
    ok: int
    failed: int
    visible_p50_ms: int
    visible_p95_ms: int
    visible_p99_ms: int
    visible_max_ms: int
    background_p95_ms: int
    touch_p95_ms: int
    dump_calls: int
    rpc_calls: int
    slow_dump_calls: int
    injected_failures: int
    executor_visible_queue_wait_p95_ms: int
    executor_background_queue_wait_p95_ms: int
    effective_visible_queue_wait_p95_ms: int
    executor_visible_deadline_drops: int
    executor_background_deadline_drops: int
    executor_dump_cache_hits: int
    executor_dump_singleflight_joins: int
    executor_http_direct_failures: int


@dataclass(frozen=True)
class BreakerResult:
    policy: str
    failing_requests: int
    failure_threshold: int
    actual_attempts: int
    dropped_by_breaker: int


@dataclass(frozen=True)
class HeartbeatCoverageResult:
    policy: str
    session_count: int
    probe_budget_per_tick: int
    heartbeat_interval_s: int
    probe_ticks_for_full_scan: int
    full_scan_seconds: int
    coverage_percent_per_tick: int


@dataclass(frozen=True)
class ChurnDecisionResult:
    policy: str
    unhealthy_sessions: int
    direct_http_healthy_sessions: int
    reset_cooldown_sessions: int
    reset_attempts: int
    local_reconnects: int
    heartbeat_evictions: int


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)]


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, math.ceil(len(ordered) * percentile) - 1),
    )
    return ordered[index]


def _pct_reduction(before: int, after: int) -> float:
    return round((1 - after / max(1, before)) * 100, 2)


def _mock_hierarchy_xml(serial: str, version: int) -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<hierarchy rotation='0'>"
        f"<node index='0' text='Phone {serial}' resource-id='mock:title' "
        "class='android.widget.TextView' package='mock' clickable='false' "
        "enabled='true' bounds='[10,10][300,80]' />"
        f"<node index='1' text='Open {version}' resource-id='mock:open' "
        "class='android.widget.Button' package='mock' clickable='true' "
        "enabled='true' bounds='[30,120][240,190]' />"
        "</hierarchy>"
    )


class _MockU2PhoneFarm:
    """Blocking fake U2/ATX endpoints used by the async soak benchmark.

    The fake is intentionally sync because production `U2Executor` sends these
    calls through its executor pool.  That exercises the real host-side
    semaphore, singleflight, cache, deadline and thread handoff behavior.
    """

    def __init__(
        self,
        *,
        dump_ms: int,
        touch_rpc_ms: int,
        slow_every: int,
        slow_multiplier: int,
        fail_every: int,
    ) -> None:
        self.dump_ms = max(1, dump_ms)
        self.touch_rpc_ms = max(1, touch_rpc_ms)
        self.slow_every = max(0, slow_every)
        self.slow_multiplier = max(1, slow_multiplier)
        self.fail_every = max(0, fail_every)
        self.dump_calls = 0
        self.rpc_calls = 0
        self.slow_dump_calls = 0
        self.injected_failures = 0
        self._versions: defaultdict[str, int] = defaultdict(int)

    @staticmethod
    def _serial_index(serial: str) -> int:
        try:
            return int(str(serial).rsplit("-", 1)[1])
        except Exception:
            return 0

    def dump(self, serial: str, _timeout: float, _compressed: bool) -> str:
        self.dump_calls += 1
        serial_index = self._serial_index(serial)
        delay_ms = self.dump_ms
        if self.slow_every and serial_index and serial_index % self.slow_every == 0:
            delay_ms *= self.slow_multiplier
            self.slow_dump_calls += 1
        time.sleep(delay_ms / 1000.0)
        if self.fail_every and serial_index and serial_index % self.fail_every == 0:
            self.injected_failures += 1
            raise RuntimeError("mock HTTP 502 from atx-agent")
        self._versions[serial] += 1
        return _mock_hierarchy_xml(serial, self._versions[serial])

    def rpc(self, serial: str, payload: dict, _timeout: float) -> tuple[bool, str, Any]:
        self.rpc_calls += 1
        serial_index = self._serial_index(serial)
        time.sleep(self.touch_rpc_ms / 1000.0)
        if self.fail_every and serial_index and serial_index % (self.fail_every * 2) == 0:
            self.injected_failures += 1
            return False, "mock JSON-RPC HTTP 502", None
        return True, "", {"serial": serial, "method": payload.get("method")}


async def _run_mock_phone_soak_mode(
    *,
    policy: str,
    phone_count: int,
    visible_requests: int,
    background_per_phone: int,
    touch_per_visible: int,
    global_limit: int,
    background_limit: int,
    dump_ms: int,
    touch_rpc_ms: int,
    visible_deadline_ms: int,
    background_deadline_ms: int,
    slow_every: int,
    slow_multiplier: int,
    fail_every: int,
    visible_priority_enabled: bool,
) -> dict[str, object]:
    from relay import u2_executor as u2_exec_mod
    from relay.u2_executor import U2Executor
    from relay.u2_session_pool import U2SessionPool

    original_global = u2_exec_mod.U2_EXECUTOR_CONCURRENCY
    original_background = u2_exec_mod.U2_EXECUTOR_BACKGROUND_CONCURRENCY
    original_reserved = u2_exec_mod.U2_EXECUTOR_VISIBLE_RESERVED
    u2_exec_mod.U2_EXECUTOR_CONCURRENCY = max(1, global_limit)
    u2_exec_mod.U2_EXECUTOR_BACKGROUND_CONCURRENCY = max(1, background_limit)
    u2_exec_mod.U2_EXECUTOR_VISIBLE_RESERVED = max(0, global_limit - background_limit)
    loop = asyncio.get_running_loop()
    farm = _MockU2PhoneFarm(
        dump_ms=dump_ms,
        touch_rpc_ms=touch_rpc_ms,
        slow_every=slow_every,
        slow_multiplier=slow_multiplier,
        fail_every=fail_every,
    )
    pool = U2SessionPool(loop=loop, connect_fn=lambda _serial: object())
    executor = U2Executor(
        pool=pool,
        loop=loop,
        http_dump=farm.dump,
        http_rpc=farm.rpc,
    )
    try:
        serials = [f"mock-phone-{index:03d}" for index in range(1, max(1, phone_count) + 1)]
        visible_serials = serials[: max(1, min(visible_requests, len(serials)))]
        background_latencies: list[int] = []
        visible_latencies: list[int] = []
        touch_latencies: list[int] = []
        ok_count = 0
        failed_count = 0

        async def _run(
            serial: str,
            lane: str,
            actions: list[dict],
            *,
            priority: str | None,
            deadline_ms: int,
            latencies: list[int],
        ) -> None:
            nonlocal ok_count, failed_count
            started = time.perf_counter()
            result = await executor.run_batch(
                serial,
                actions,
                priority=priority,
                deadline_ms=deadline_ms,
            )
            latencies.append(int((time.perf_counter() - started) * 1000.0))
            if result.get("ok"):
                ok_count += 1
            else:
                failed_count += 1

        background_tasks: list[asyncio.Task] = []
        background_serials = serials[len(visible_serials):] or serials
        for serial in background_serials:
            for duplicate in range(max(1, background_per_phone)):
                background_tasks.append(
                    asyncio.create_task(
                        _run(
                            serial,
                            "background",
                            [
                                {
                                    "op": "dump_hierarchy",
                                    "compressed": True,
                                    "timeout": max(1.0, background_deadline_ms / 1000.0),
                                    "force_fresh_xml": duplicate == 0,
                                }
                            ],
                            priority="background",
                            deadline_ms=background_deadline_ms,
                            latencies=background_latencies,
                        )
                    )
                )

        # Let background fill its lane before visible work arrives, matching the
        # field failure mode where XML polling is already in progress.
        await asyncio.sleep(0.01)

        visible_priority = "visible" if visible_priority_enabled else "background"
        visible_tasks = [
            asyncio.create_task(
                _run(
                    serial,
                    "visible",
                    [{"op": "dump_hierarchy", "compressed": True, "timeout": 1.0}],
                    priority=visible_priority,
                    deadline_ms=visible_deadline_ms,
                    latencies=visible_latencies,
                )
            )
            for serial in visible_serials
        ]
        touch_tasks: list[asyncio.Task] = []
        for serial in visible_serials:
            for _index in range(max(0, touch_per_visible)):
                touch_tasks.append(
                    asyncio.create_task(
                        _run(
                            serial,
                            "touch",
                            [{"op": "click", "x": 120, "y": 160}],
                            priority=visible_priority,
                            deadline_ms=visible_deadline_ms,
                            latencies=touch_latencies,
                        )
                    )
                )

        await asyncio.gather(*visible_tasks, *touch_tasks, *background_tasks)
        stats = executor.stats_snapshot(reset=False)
        visible_queue_wait_p95_ms = int(stats.get("visible_queue_wait_p95_ms", 0))
        background_queue_wait_p95_ms = int(stats.get("background_queue_wait_p95_ms", 0))
        mode = MockPhoneSoakModeResult(
            policy=policy,
            phone_count=phone_count,
            visible_requests=len(visible_tasks),
            background_requests=len(background_tasks),
            touch_requests=len(touch_tasks),
            ok=ok_count,
            failed=failed_count,
            visible_p50_ms=_percentile(visible_latencies, 0.50),
            visible_p95_ms=_percentile(visible_latencies, 0.95),
            visible_p99_ms=_percentile(visible_latencies, 0.99),
            visible_max_ms=max(visible_latencies, default=0),
            background_p95_ms=_percentile(background_latencies, 0.95),
            touch_p95_ms=_percentile(touch_latencies, 0.95),
            dump_calls=farm.dump_calls,
            rpc_calls=farm.rpc_calls,
            slow_dump_calls=farm.slow_dump_calls,
            injected_failures=farm.injected_failures,
            executor_visible_queue_wait_p95_ms=visible_queue_wait_p95_ms,
            executor_background_queue_wait_p95_ms=background_queue_wait_p95_ms,
            effective_visible_queue_wait_p95_ms=(
                visible_queue_wait_p95_ms
                if visible_priority_enabled
                else background_queue_wait_p95_ms
            ),
            executor_visible_deadline_drops=int(stats.get("visible_deadline_drops", 0)),
            executor_background_deadline_drops=int(stats.get("background_deadline_drops", 0)),
            executor_dump_cache_hits=int(stats.get("dump_cache_hits", 0)),
            executor_dump_singleflight_joins=int(stats.get("dump_singleflight_joins", 0)),
            executor_http_direct_failures=int(stats.get("http_direct_failures", 0)),
        )
        return asdict(mode)
    finally:
        u2_exec_mod.U2_EXECUTOR_CONCURRENCY = original_global
        u2_exec_mod.U2_EXECUTOR_BACKGROUND_CONCURRENCY = original_background
        u2_exec_mod.U2_EXECUTOR_VISIBLE_RESERVED = original_reserved


async def run_mock_phone_soak_benchmark(
    *,
    phone_count: int,
    visible_requests: int,
    background_per_phone: int,
    touch_per_visible: int,
    global_limit: int,
    background_limit: int,
    dump_ms: int,
    touch_rpc_ms: int,
    visible_deadline_ms: int,
    background_deadline_ms: int,
    slow_every: int,
    slow_multiplier: int,
    fail_every: int,
) -> dict[str, object]:
    baseline = await _run_mock_phone_soak_mode(
        policy="baseline_visible_misclassified_as_background",
        phone_count=phone_count,
        visible_requests=visible_requests,
        background_per_phone=background_per_phone,
        touch_per_visible=touch_per_visible,
        global_limit=global_limit,
        background_limit=background_limit,
        dump_ms=dump_ms,
        touch_rpc_ms=touch_rpc_ms,
        visible_deadline_ms=visible_deadline_ms,
        background_deadline_ms=background_deadline_ms,
        slow_every=slow_every,
        slow_multiplier=slow_multiplier,
        fail_every=fail_every,
        visible_priority_enabled=False,
    )
    optimized = await _run_mock_phone_soak_mode(
        policy="optimized_visible_priority_and_background_lane",
        phone_count=phone_count,
        visible_requests=visible_requests,
        background_per_phone=background_per_phone,
        touch_per_visible=touch_per_visible,
        global_limit=global_limit,
        background_limit=background_limit,
        dump_ms=dump_ms,
        touch_rpc_ms=touch_rpc_ms,
        visible_deadline_ms=visible_deadline_ms,
        background_deadline_ms=background_deadline_ms,
        slow_every=slow_every,
        slow_multiplier=slow_multiplier,
        fail_every=fail_every,
        visible_priority_enabled=True,
    )
    return {
        "kind": "u2_mock_phone_soak",
        "scope": "real_U2Executor_with_fake_ATX_HTTP_endpoints",
        "inputs": {
            "phone_count": phone_count,
            "visible_requests": visible_requests,
            "background_per_phone": background_per_phone,
            "touch_per_visible": touch_per_visible,
            "global_limit": global_limit,
            "background_limit": background_limit,
            "dump_ms": dump_ms,
            "touch_rpc_ms": touch_rpc_ms,
            "visible_deadline_ms": visible_deadline_ms,
            "background_deadline_ms": background_deadline_ms,
            "slow_every": slow_every,
            "slow_multiplier": slow_multiplier,
            "fail_every": fail_every,
        },
        "baseline": baseline,
        "optimized": optimized,
        "visible_p95_reduction_percent": _pct_reduction(
            int(baseline["visible_p95_ms"]),
            int(optimized["visible_p95_ms"]),
        ),
        "visible_queue_wait_p95_reduction_percent": _pct_reduction(
            int(baseline["effective_visible_queue_wait_p95_ms"]),
            int(optimized["effective_visible_queue_wait_p95_ms"]),
        ),
        "touch_p95_reduction_percent": _pct_reduction(
            int(baseline["touch_p95_ms"]),
            int(optimized["touch_p95_ms"]),
        ),
        "visible_deadline_drop_reduction_percent": _pct_reduction(
            int(baseline["executor_visible_deadline_drops"]),
            int(optimized["executor_visible_deadline_drops"]),
        ),
    }


def run_dump_burst(
    *,
    duplicate_requests: int,
    dump_ms: int,
) -> dict[str, object]:
    duplicate_requests = max(1, duplicate_requests)
    dump_ms = max(1, dump_ms)
    current_latencies = [dump_ms * (index + 1) for index in range(duplicate_requests)]
    optimized_latencies = [dump_ms for _index in range(duplicate_requests)]
    current = DumpBurstResult(
        policy="current_serialized_duplicate_dumps",
        duplicate_requests=duplicate_requests,
        actual_dump_calls=duplicate_requests,
        p95_latency_ms=_p95(current_latencies),
        total_device_work_ms=duplicate_requests * dump_ms,
    )
    optimized = DumpBurstResult(
        policy="optimized_singleflight_and_cache",
        duplicate_requests=duplicate_requests,
        actual_dump_calls=1,
        p95_latency_ms=_p95(optimized_latencies),
        total_device_work_ms=dump_ms,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "actual_call_reduction_percent": round(
            (1 - optimized.actual_dump_calls / max(1, current.actual_dump_calls)) * 100,
            2,
        ),
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_selector_batch(
    *,
    selector_reads: int,
    dump_ms: int,
    selector_ms: int,
    parse_ms: int,
) -> dict[str, object]:
    selector_reads = max(1, selector_reads)
    dump_ms = max(1, dump_ms)
    selector_ms = max(0, selector_ms)
    parse_ms = max(0, parse_ms)
    current_latency = dump_ms + selector_reads * selector_ms
    optimized_latency = dump_ms + parse_ms
    current = SelectorBatchResult(
        policy="current_dump_then_u2_selector_reads",
        selector_reads=selector_reads,
        actual_dump_calls=1,
        actual_selector_u2_calls=selector_reads,
        p95_latency_ms=current_latency,
        total_device_work_ms=current_latency,
    )
    optimized = SelectorBatchResult(
        policy="optimized_dump_then_xml_selector_reads",
        selector_reads=selector_reads,
        actual_dump_calls=1,
        actual_selector_u2_calls=0,
        p95_latency_ms=optimized_latency,
        total_device_work_ms=dump_ms,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "selector_u2_call_reduction_percent": round(
            (
                1
                - optimized.actual_selector_u2_calls
                / max(1, current.actual_selector_u2_calls)
            )
            * 100,
            2,
        ),
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_touch_direct_batch(
    *,
    touch_actions: int,
    rpc_ms: int,
    session_lock_ms: int,
) -> dict[str, object]:
    touch_actions = max(1, touch_actions)
    rpc_ms = max(1, rpc_ms)
    session_lock_ms = max(0, session_lock_ms)
    current_latency = session_lock_ms + touch_actions * rpc_ms
    optimized_latency = touch_actions * rpc_ms
    current = TouchDirectResult(
        policy="current_touch_batch_via_u2_session_lock",
        touch_actions=touch_actions,
        session_lock_ms=session_lock_ms,
        rpc_ms=rpc_ms,
        p95_latency_ms=current_latency,
        session_locks=1,
    )
    optimized = TouchDirectResult(
        policy="optimized_touch_batch_http_direct",
        touch_actions=touch_actions,
        session_lock_ms=0,
        rpc_ms=rpc_ms,
        p95_latency_ms=optimized_latency,
        session_locks=0,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "session_lock_reduction_percent": 100.0,
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_selector_click_fusion(
    *,
    selector_reads: int,
    dump_ms: int,
    selector_ms: int,
    parse_ms: int,
    touch_rpc_ms: int,
    session_lock_ms: int,
) -> dict[str, object]:
    selector_reads = max(0, selector_reads)
    dump_ms = max(1, dump_ms)
    selector_ms = max(0, selector_ms)
    parse_ms = max(0, parse_ms)
    touch_rpc_ms = max(1, touch_rpc_ms)
    session_lock_ms = max(0, session_lock_ms)
    current_latency = session_lock_ms + dump_ms + (selector_reads + 1) * selector_ms
    optimized_latency = dump_ms + parse_ms + touch_rpc_ms
    current = SelectorClickFusionResult(
        policy="current_dump_read_click_selector_via_u2_session",
        selector_reads=selector_reads,
        actual_selector_u2_calls=selector_reads + 1,
        session_locks=1,
        p95_latency_ms=current_latency,
    )
    optimized = SelectorClickFusionResult(
        policy="optimized_dump_read_click_selector_xml_bounds_http",
        selector_reads=selector_reads,
        actual_selector_u2_calls=0,
        session_locks=0,
        p95_latency_ms=optimized_latency,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "selector_u2_call_reduction_percent": 100.0,
        "session_lock_reduction_percent": 100.0,
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_click_spec_direct_bounds(
    *,
    click_specs: int,
    click_spec_ms: int,
    touch_rpc_ms: int,
    session_lock_ms: int,
) -> dict[str, object]:
    click_specs = max(1, click_specs)
    click_spec_ms = max(1, click_spec_ms)
    touch_rpc_ms = max(1, touch_rpc_ms)
    session_lock_ms = max(0, session_lock_ms)
    current_latency = session_lock_ms + click_specs * click_spec_ms
    optimized_latency = click_specs * touch_rpc_ms
    current = ClickSpecDirectResult(
        policy="current_click_spec_bounds_via_u2_session",
        click_specs=click_specs,
        actual_selector_u2_calls=click_specs,
        session_locks=1,
        p95_latency_ms=current_latency,
    )
    optimized = ClickSpecDirectResult(
        policy="optimized_click_spec_bounds_http_direct",
        click_specs=click_specs,
        actual_selector_u2_calls=0,
        session_locks=0,
        p95_latency_ms=optimized_latency,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "selector_u2_call_reduction_percent": 100.0,
        "session_lock_reduction_percent": 100.0,
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_wait_poll(
    *,
    op_name: str,
    waits: int,
    wait_timeout_ms: int,
    dump_ms: int,
    parse_ms: int,
    poll_interval_ms: int,
    found_after_polls: int,
) -> dict[str, object]:
    waits = max(1, waits)
    wait_timeout_ms = max(1, wait_timeout_ms)
    dump_ms = max(1, dump_ms)
    parse_ms = max(0, parse_ms)
    poll_interval_ms = max(1, poll_interval_ms)
    found_after_polls = max(1, found_after_polls)
    current_latency = wait_timeout_ms
    optimized_latency = min(
        wait_timeout_ms,
        found_after_polls * (dump_ms + parse_ms)
        + max(0, found_after_polls - 1) * poll_interval_ms,
    )
    current = WaitPollResult(
        policy=f"current_{op_name}_holds_u2_session_lock",
        waits=waits,
        session_locks=waits,
        lock_held_ms=waits * wait_timeout_ms,
        p95_latency_ms=current_latency,
    )
    optimized = WaitPollResult(
        policy=f"optimized_{op_name}_http_dump_poll",
        waits=waits,
        session_locks=0,
        lock_held_ms=0,
        p95_latency_ms=optimized_latency,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "session_lock_reduction_percent": 100.0,
        "lock_held_reduction_percent": 100.0,
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_xml_index_cache(
    *,
    flows: int,
    polls_per_flow: int,
    xml_versions_per_flow: int,
    parse_ms: int,
) -> dict[str, object]:
    flows = max(1, flows)
    polls_per_flow = max(1, polls_per_flow)
    xml_versions_per_flow = max(1, min(xml_versions_per_flow, polls_per_flow))
    parse_ms = max(0, parse_ms)
    current_builds = flows * polls_per_flow
    optimized_builds = flows * xml_versions_per_flow
    current = XmlIndexCacheResult(
        policy="current_parse_and_index_every_xml_poll",
        flows=flows,
        polls_per_flow=polls_per_flow,
        xml_versions_per_flow=polls_per_flow,
        xml_parse_index_builds=current_builds,
        total_parse_index_ms=current_builds * parse_ms,
    )
    optimized = XmlIndexCacheResult(
        policy="optimized_parse_and_index_only_when_xml_changes",
        flows=flows,
        polls_per_flow=polls_per_flow,
        xml_versions_per_flow=xml_versions_per_flow,
        xml_parse_index_builds=optimized_builds,
        total_parse_index_ms=optimized_builds * parse_ms,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "parse_index_build_reduction_percent": round(
            (
                1
                - optimized.xml_parse_index_builds
                / max(1, current.xml_parse_index_builds)
            )
            * 100,
            2,
        ),
        "parse_index_cpu_reduction_percent": round(
            (
                1
                - optimized.total_parse_index_ms
                / max(1, current.total_parse_index_ms)
            )
            * 100,
            2,
        ),
    }


def run_xml_poll_coalescing(*, concurrent_waits: int) -> dict[str, object]:
    concurrent_waits = max(1, concurrent_waits)
    current = XmlPollCoalescingResult(
        policy="current_each_wait_runs_own_xml_poll_loop",
        concurrent_waits=concurrent_waits,
        poll_loops=concurrent_waits,
        dump_request_attempts=concurrent_waits,
        actual_dump_calls=1,
        poll_stat_increments=concurrent_waits,
    )
    optimized = XmlPollCoalescingResult(
        policy="optimized_equivalent_waits_join_one_xml_poll_loop",
        concurrent_waits=concurrent_waits,
        poll_loops=1,
        dump_request_attempts=1,
        actual_dump_calls=1,
        poll_stat_increments=1,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "poll_loop_reduction_percent": round(
            (1 - optimized.poll_loops / max(1, current.poll_loops)) * 100,
            2,
        ),
        "dump_request_attempt_reduction_percent": round(
            (
                1
                - optimized.dump_request_attempts
                / max(1, current.dump_request_attempts)
            )
            * 100,
            2,
        ),
        "poll_stat_reduction_percent": round(
            (
                1
                - optimized.poll_stat_increments
                / max(1, current.poll_stat_increments)
            )
            * 100,
            2,
        ),
    }


def run_xml_selector_lookup_cache(
    *,
    selector_lookups: int,
    unique_selectors: int,
) -> dict[str, object]:
    selector_lookups = max(1, selector_lookups)
    unique_selectors = max(1, min(unique_selectors, selector_lookups))
    current = XmlSelectorLookupCacheResult(
        policy="current_scan_candidates_for_every_selector_lookup",
        selector_lookups=selector_lookups,
        unique_selectors=unique_selectors,
        node_scans=selector_lookups,
    )
    optimized = XmlSelectorLookupCacheResult(
        policy="optimized_scan_once_per_unique_selector_per_xml_index",
        selector_lookups=selector_lookups,
        unique_selectors=unique_selectors,
        node_scans=unique_selectors,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "node_scan_reduction_percent": round(
            (1 - optimized.node_scans / max(1, current.node_scans)) * 100,
            2,
        ),
    }


def run_flow_fast_path(
    *,
    flow_name: str,
    flows: int,
    wait_timeout_ms: int,
    dump_ms: int,
    parse_ms: int,
    poll_interval_ms: int,
    found_after_polls: int,
    touch_rpc_ms: int,
    selector_ms: int,
    session_lock_ms: int,
) -> dict[str, object]:
    flows = max(1, flows)
    wait_timeout_ms = max(1, wait_timeout_ms)
    touch_rpc_ms = max(1, touch_rpc_ms)
    selector_ms = max(0, selector_ms)
    session_lock_ms = max(0, session_lock_ms)
    wait_optimized_ms = min(
        wait_timeout_ms,
        max(1, found_after_polls) * (max(1, dump_ms) + max(0, parse_ms))
        + max(0, found_after_polls - 1) * max(1, poll_interval_ms),
    )
    waits_per_flow = 2 if flow_name == "find_click_wait" else 1
    current_latency = (
        session_lock_ms
        + waits_per_flow * wait_timeout_ms
        + (waits_per_flow + 1) * selector_ms
    )
    optimized_latency = waits_per_flow * wait_optimized_ms + touch_rpc_ms
    current = FlowFastPathResult(
        policy=f"current_{flow_name}_via_u2_session",
        flows=flows,
        session_locks=flows,
        selector_u2_calls=flows * (waits_per_flow + 1),
        lock_held_ms=flows * current_latency,
        p95_latency_ms=current_latency,
    )
    optimized = FlowFastPathResult(
        policy=f"optimized_{flow_name}_http_dump_click",
        flows=flows,
        session_locks=0,
        selector_u2_calls=0,
        lock_held_ms=0,
        p95_latency_ms=optimized_latency,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "session_lock_reduction_percent": 100.0,
        "selector_u2_call_reduction_percent": 100.0,
        "lock_held_reduction_percent": 100.0,
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_swipe_until_found_fast_path(
    *,
    flows: int,
    max_swipes: int,
    dump_ms: int,
    parse_ms: int,
    selector_ms: int,
    touch_rpc_ms: int,
    session_lock_ms: int,
) -> dict[str, object]:
    flows = max(1, flows)
    max_swipes = max(0, max_swipes)
    dump_ms = max(1, dump_ms)
    parse_ms = max(0, parse_ms)
    selector_ms = max(0, selector_ms)
    touch_rpc_ms = max(1, touch_rpc_ms)
    session_lock_ms = max(0, session_lock_ms)
    checks = max_swipes + 1
    current_latency = session_lock_ms + checks * selector_ms + max_swipes * touch_rpc_ms
    optimized_latency = checks * selector_ms + max_swipes * touch_rpc_ms
    current = FlowFastPathResult(
        policy="current_swipe_until_found_via_u2_session",
        flows=flows,
        session_locks=flows,
        selector_u2_calls=flows * checks,
        lock_held_ms=flows * current_latency,
        p95_latency_ms=current_latency,
    )
    optimized = FlowFastPathResult(
        policy="optimized_swipe_until_found_http_exists_swipe",
        flows=flows,
        session_locks=0,
        selector_u2_calls=0,
        lock_held_ms=0,
        p95_latency_ms=optimized_latency,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "session_lock_reduction_percent": 100.0,
        "selector_u2_call_reduction_percent": 100.0,
        "lock_held_reduction_percent": 100.0,
        "p95_latency_reduction_percent": round(
            (1 - optimized.p95_latency_ms / max(1, current.p95_latency_ms)) * 100,
            2,
        ),
    }


def run_priority_model(
    *,
    background_requests: int,
    global_limit: int,
    background_limit: int,
    work_ms: int,
) -> dict[str, object]:
    background_requests = max(1, background_requests)
    global_limit = max(1, global_limit)
    background_limit = max(1, min(background_limit, global_limit))
    work_ms = max(1, work_ms)
    current_waves = math.ceil(background_requests / global_limit)
    optimized_waves = math.ceil(background_requests / background_limit)
    current = PriorityResult(
        policy="current_background_can_fill_all_global_slots",
        background_requests=background_requests,
        global_limit=global_limit,
        background_limit=global_limit,
        visible_wait_ms=work_ms,
        background_waves=current_waves,
    )
    optimized = PriorityResult(
        policy="optimized_visible_reserved_slots",
        background_requests=background_requests,
        global_limit=global_limit,
        background_limit=background_limit,
        visible_wait_ms=0 if background_limit < global_limit else work_ms,
        background_waves=optimized_waves,
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "visible_wait_reduction_percent": round(
            (1 - optimized.visible_wait_ms / max(1, current.visible_wait_ms)) * 100,
            2,
        ),
    }


def run_lane_isolation_model(
    *,
    phone_count: int,
    visible_requests: int,
    background_per_phone: int,
    global_limit: int,
    background_limit: int,
    work_ms: int,
) -> dict[str, object]:
    phone_count = max(1, phone_count)
    visible_requests = max(1, visible_requests)
    background_per_phone = max(1, background_per_phone)
    global_limit = max(1, global_limit)
    background_limit = max(1, min(background_limit, global_limit))
    work_ms = max(1, work_ms)

    background_attempts = phone_count * background_per_phone
    reserved_visible = max(0, global_limit - background_limit)
    optimized_visible_wait = (
        0
        if reserved_visible <= 0
        else max(0, math.ceil(visible_requests / reserved_visible) - 1) * work_ms
    )
    current = LaneIsolationResult(
        policy="current_background_xml_can_occupy_all_u2_slots",
        phone_count=phone_count,
        visible_requests=visible_requests,
        background_attempts=background_attempts,
        actual_background_work=background_attempts,
        global_limit=global_limit,
        background_limit=global_limit,
        visible_p95_wait_ms=work_ms,
        background_peak_inflight=min(background_attempts, global_limit),
    )
    optimized = LaneIsolationResult(
        policy="optimized_visible_reserved_and_background_coalesced_by_serial",
        phone_count=phone_count,
        visible_requests=visible_requests,
        background_attempts=background_attempts,
        actual_background_work=phone_count,
        global_limit=global_limit,
        background_limit=background_limit,
        visible_p95_wait_ms=optimized_visible_wait,
        background_peak_inflight=min(phone_count, background_limit),
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "visible_p95_wait_reduction_percent": round(
            (1 - optimized.visible_p95_wait_ms / max(1, current.visible_p95_wait_ms)) * 100,
            2,
        ),
        "background_work_reduction_percent": round(
            (
                1
                - optimized.actual_background_work
                / max(1, current.actual_background_work)
            )
            * 100,
            2,
        ),
        "visible_isolated": optimized.visible_p95_wait_ms == 0,
    }


def run_breaker_model(
    *,
    failing_requests: int,
    failure_threshold: int,
) -> dict[str, object]:
    failing_requests = max(1, failing_requests)
    failure_threshold = max(1, failure_threshold)
    optimized_attempts = min(failing_requests, failure_threshold)
    current = BreakerResult(
        policy="current_retry_every_failure",
        failing_requests=failing_requests,
        failure_threshold=failure_threshold,
        actual_attempts=failing_requests,
        dropped_by_breaker=0,
    )
    optimized = BreakerResult(
        policy="optimized_per_serial_breaker",
        failing_requests=failing_requests,
        failure_threshold=failure_threshold,
        actual_attempts=optimized_attempts,
        dropped_by_breaker=max(0, failing_requests - optimized_attempts),
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "attempt_reduction_percent": round(
            (1 - optimized.actual_attempts / max(1, current.actual_attempts)) * 100,
            2,
        ),
    }


def run_heartbeat_coverage_model(
    *,
    session_count: int,
    probe_budget_per_tick: int,
    heartbeat_interval_s: int,
) -> dict[str, object]:
    session_count = max(1, session_count)
    probe_budget_per_tick = max(1, probe_budget_per_tick)
    heartbeat_interval_s = max(1, heartbeat_interval_s)
    ticks = math.ceil(session_count / probe_budget_per_tick)
    result = HeartbeatCoverageResult(
        policy="bounded_heartbeat_probe_budget",
        session_count=session_count,
        probe_budget_per_tick=probe_budget_per_tick,
        heartbeat_interval_s=heartbeat_interval_s,
        probe_ticks_for_full_scan=ticks,
        full_scan_seconds=ticks * heartbeat_interval_s,
        coverage_percent_per_tick=int(
            min(100, probe_budget_per_tick * 100 / session_count)
        ),
    )
    return asdict(result)


def run_churn_decision_model(
    *,
    unhealthy_sessions: int,
    direct_http_healthy_sessions: int,
    reset_cooldown_sessions: int,
    heartbeat_eviction_budget: int,
) -> dict[str, object]:
    unhealthy_sessions = max(0, unhealthy_sessions)
    direct_http_healthy_sessions = min(
        unhealthy_sessions,
        max(0, direct_http_healthy_sessions),
    )
    remaining = max(0, unhealthy_sessions - direct_http_healthy_sessions)
    reset_cooldown_sessions = min(remaining, max(0, reset_cooldown_sessions))
    heartbeat_eviction_budget = max(0, heartbeat_eviction_budget)

    current = ChurnDecisionResult(
        policy="current_reset_every_stale_u2_session",
        unhealthy_sessions=unhealthy_sessions,
        direct_http_healthy_sessions=direct_http_healthy_sessions,
        reset_cooldown_sessions=reset_cooldown_sessions,
        reset_attempts=unhealthy_sessions,
        local_reconnects=unhealthy_sessions,
        heartbeat_evictions=min(unhealthy_sessions, heartbeat_eviction_budget),
    )
    optimized_reset_attempts = max(
        0,
        unhealthy_sessions - direct_http_healthy_sessions - reset_cooldown_sessions,
    )
    optimized = ChurnDecisionResult(
        policy="optimized_skip_reset_when_http_healthy_or_cooldown_open",
        unhealthy_sessions=unhealthy_sessions,
        direct_http_healthy_sessions=direct_http_healthy_sessions,
        reset_cooldown_sessions=reset_cooldown_sessions,
        reset_attempts=optimized_reset_attempts,
        local_reconnects=unhealthy_sessions,
        heartbeat_evictions=min(unhealthy_sessions, heartbeat_eviction_budget),
    )
    return {
        "current": asdict(current),
        "optimized": asdict(optimized),
        "reset_attempt_reduction_percent": _pct_reduction(
            current.reset_attempts,
            optimized.reset_attempts,
        ),
        "device_side_resets_avoided": current.reset_attempts - optimized.reset_attempts,
    }


def run_u2_scheduler_benchmark(
    *,
    duplicate_requests: int,
    selector_reads: int,
    touch_actions: int,
    background_requests: int,
    failing_requests: int,
    dump_ms: int,
    selector_ms: int,
    parse_ms: int,
    touch_rpc_ms: int,
    click_spec_ms: int,
    wait_timeout_ms: int,
    wait_poll_interval_ms: int,
    wait_found_after_polls: int,
    session_lock_ms: int,
    work_ms: int,
    global_limit: int,
    background_limit: int,
    failure_threshold: int,
    phone_count: int = 40,
    visible_requests: int = 4,
    background_per_phone: int = 2,
    heartbeat_probe_budget: int = 8,
    heartbeat_interval_s: int = 10,
    churn_unhealthy_sessions: int = 20,
    churn_http_healthy_sessions: int = 12,
    churn_reset_cooldown_sessions: int = 5,
) -> dict[str, object]:
    return {
        "kind": "u2_scheduler_synthetic",
        "scope": "agent_boot_u2_executor_no_real_adb",
        "inputs": {
            "duplicate_requests": duplicate_requests,
            "selector_reads": selector_reads,
            "touch_actions": touch_actions,
            "background_requests": background_requests,
            "failing_requests": failing_requests,
            "dump_ms": dump_ms,
            "selector_ms": selector_ms,
            "parse_ms": parse_ms,
            "touch_rpc_ms": touch_rpc_ms,
            "click_spec_ms": click_spec_ms,
            "wait_timeout_ms": wait_timeout_ms,
            "wait_poll_interval_ms": wait_poll_interval_ms,
            "wait_found_after_polls": wait_found_after_polls,
            "session_lock_ms": session_lock_ms,
            "work_ms": work_ms,
            "global_limit": global_limit,
            "background_limit": background_limit,
            "failure_threshold": failure_threshold,
            "phone_count": phone_count,
            "visible_requests": visible_requests,
            "background_per_phone": background_per_phone,
            "heartbeat_probe_budget": heartbeat_probe_budget,
            "heartbeat_interval_s": heartbeat_interval_s,
            "churn_unhealthy_sessions": churn_unhealthy_sessions,
            "churn_http_healthy_sessions": churn_http_healthy_sessions,
            "churn_reset_cooldown_sessions": churn_reset_cooldown_sessions,
        },
        "dump_burst": run_dump_burst(
            duplicate_requests=duplicate_requests,
            dump_ms=dump_ms,
        ),
        "selector_batch": run_selector_batch(
            selector_reads=selector_reads,
            dump_ms=dump_ms,
            selector_ms=selector_ms,
            parse_ms=parse_ms,
        ),
        "touch_direct": run_touch_direct_batch(
            touch_actions=touch_actions,
            rpc_ms=touch_rpc_ms,
            session_lock_ms=session_lock_ms,
        ),
        "selector_click_fusion": run_selector_click_fusion(
            selector_reads=selector_reads,
            dump_ms=dump_ms,
            selector_ms=selector_ms,
            parse_ms=parse_ms,
            touch_rpc_ms=touch_rpc_ms,
            session_lock_ms=session_lock_ms,
        ),
        "click_spec_direct_bounds": run_click_spec_direct_bounds(
            click_specs=touch_actions,
            click_spec_ms=click_spec_ms,
            touch_rpc_ms=touch_rpc_ms,
            session_lock_ms=session_lock_ms,
        ),
        "wait_poll": run_wait_poll(
            op_name="wait_exists",
            waits=background_requests,
            wait_timeout_ms=wait_timeout_ms,
            dump_ms=dump_ms,
            parse_ms=parse_ms,
            poll_interval_ms=wait_poll_interval_ms,
            found_after_polls=wait_found_after_polls,
        ),
        "wait_gone_poll": run_wait_poll(
            op_name="wait_gone",
            waits=background_requests,
            wait_timeout_ms=wait_timeout_ms,
            dump_ms=dump_ms,
            parse_ms=parse_ms,
            poll_interval_ms=wait_poll_interval_ms,
            found_after_polls=wait_found_after_polls,
        ),
        "xml_index_cache": run_xml_index_cache(
            flows=background_requests,
            polls_per_flow=wait_found_after_polls,
            xml_versions_per_flow=min(wait_found_after_polls, 2),
            parse_ms=parse_ms,
        ),
        "xml_poll_coalescing": run_xml_poll_coalescing(
            concurrent_waits=background_requests,
        ),
        "xml_selector_lookup_cache": run_xml_selector_lookup_cache(
            selector_lookups=selector_reads,
            unique_selectors=max(1, selector_reads // 4),
        ),
        "flow_wait_and_click": run_flow_fast_path(
            flow_name="wait_and_click",
            flows=background_requests,
            wait_timeout_ms=wait_timeout_ms,
            dump_ms=dump_ms,
            parse_ms=parse_ms,
            poll_interval_ms=wait_poll_interval_ms,
            found_after_polls=wait_found_after_polls,
            touch_rpc_ms=touch_rpc_ms,
            selector_ms=selector_ms,
            session_lock_ms=session_lock_ms,
        ),
        "flow_find_click_wait": run_flow_fast_path(
            flow_name="find_click_wait",
            flows=background_requests,
            wait_timeout_ms=wait_timeout_ms,
            dump_ms=dump_ms,
            parse_ms=parse_ms,
            poll_interval_ms=wait_poll_interval_ms,
            found_after_polls=wait_found_after_polls,
            touch_rpc_ms=touch_rpc_ms,
            selector_ms=selector_ms,
            session_lock_ms=session_lock_ms,
        ),
        "flow_swipe_until_found": run_swipe_until_found_fast_path(
            flows=background_requests,
            max_swipes=touch_actions,
            dump_ms=dump_ms,
            parse_ms=parse_ms,
            selector_ms=selector_ms,
            touch_rpc_ms=touch_rpc_ms,
            session_lock_ms=session_lock_ms,
        ),
        "priority": run_priority_model(
            background_requests=background_requests,
            global_limit=global_limit,
            background_limit=background_limit,
            work_ms=work_ms,
        ),
        "lane_isolation": run_lane_isolation_model(
            phone_count=phone_count,
            visible_requests=visible_requests,
            background_per_phone=background_per_phone,
            global_limit=global_limit,
            background_limit=background_limit,
            work_ms=work_ms,
        ),
        "breaker": run_breaker_model(
            failing_requests=failing_requests,
            failure_threshold=failure_threshold,
        ),
        "heartbeat_coverage": run_heartbeat_coverage_model(
            session_count=phone_count,
            probe_budget_per_tick=heartbeat_probe_budget,
            heartbeat_interval_s=heartbeat_interval_s,
        ),
        "churn_decision": run_churn_decision_model(
            unhealthy_sessions=churn_unhealthy_sessions,
            direct_http_healthy_sessions=churn_http_healthy_sessions,
            reset_cooldown_sessions=churn_reset_cooldown_sessions,
            heartbeat_eviction_budget=heartbeat_probe_budget,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--soak",
        action="store_true",
        help="Run real U2Executor against fake ATX/U2 endpoints instead of the formula model.",
    )
    parser.add_argument("--duplicate-requests", type=int, default=20)
    parser.add_argument("--selector-reads", type=int, default=20)
    parser.add_argument("--touch-actions", type=int, default=5)
    parser.add_argument("--background-requests", type=int, default=40)
    parser.add_argument("--failing-requests", type=int, default=20)
    parser.add_argument("--dump-ms", type=int, default=50)
    parser.add_argument("--selector-ms", type=int, default=15)
    parser.add_argument("--parse-ms", type=int, default=2)
    parser.add_argument("--touch-rpc-ms", type=int, default=25)
    parser.add_argument("--click-spec-ms", type=int, default=35)
    parser.add_argument("--wait-timeout-ms", type=int, default=5000)
    parser.add_argument("--wait-poll-interval-ms", type=int, default=100)
    parser.add_argument("--wait-found-after-polls", type=int, default=3)
    parser.add_argument("--session-lock-ms", type=int, default=80)
    parser.add_argument("--work-ms", type=int, default=100)
    parser.add_argument("--global-limit", type=int, default=16)
    parser.add_argument("--background-limit", type=int, default=12)
    parser.add_argument("--failure-threshold", type=int, default=3)
    parser.add_argument("--phone-count", type=int, default=40)
    parser.add_argument("--visible-requests", type=int, default=4)
    parser.add_argument("--background-per-phone", type=int, default=2)
    parser.add_argument("--heartbeat-probe-budget", type=int, default=8)
    parser.add_argument("--heartbeat-interval-s", type=int, default=10)
    parser.add_argument("--churn-unhealthy-sessions", type=int, default=20)
    parser.add_argument("--churn-http-healthy-sessions", type=int, default=12)
    parser.add_argument("--churn-reset-cooldown-sessions", type=int, default=5)
    parser.add_argument("--touch-per-visible", type=int, default=1)
    parser.add_argument("--visible-deadline-ms", type=int, default=250)
    parser.add_argument("--background-deadline-ms", type=int, default=3000)
    parser.add_argument("--slow-every", type=int, default=10)
    parser.add_argument("--slow-multiplier", type=int, default=4)
    parser.add_argument("--fail-every", type=int, default=0)
    args = parser.parse_args()
    if args.soak:
        result = asyncio.run(
            run_mock_phone_soak_benchmark(
                phone_count=args.phone_count,
                visible_requests=args.visible_requests,
                background_per_phone=args.background_per_phone,
                touch_per_visible=args.touch_per_visible,
                global_limit=args.global_limit,
                background_limit=args.background_limit,
                dump_ms=args.dump_ms,
                touch_rpc_ms=args.touch_rpc_ms,
                visible_deadline_ms=args.visible_deadline_ms,
                background_deadline_ms=args.background_deadline_ms,
                slow_every=args.slow_every,
                slow_multiplier=args.slow_multiplier,
                fail_every=args.fail_every,
            )
        )
        print(json.dumps(result, sort_keys=True))
        return 0

    result = run_u2_scheduler_benchmark(
        duplicate_requests=args.duplicate_requests,
        selector_reads=args.selector_reads,
        touch_actions=args.touch_actions,
        background_requests=args.background_requests,
        failing_requests=args.failing_requests,
        dump_ms=args.dump_ms,
        selector_ms=args.selector_ms,
        parse_ms=args.parse_ms,
        touch_rpc_ms=args.touch_rpc_ms,
        click_spec_ms=args.click_spec_ms,
        wait_timeout_ms=args.wait_timeout_ms,
        wait_poll_interval_ms=args.wait_poll_interval_ms,
        wait_found_after_polls=args.wait_found_after_polls,
        session_lock_ms=args.session_lock_ms,
        work_ms=args.work_ms,
        global_limit=args.global_limit,
        background_limit=args.background_limit,
        failure_threshold=args.failure_threshold,
        phone_count=args.phone_count,
        visible_requests=args.visible_requests,
        background_per_phone=args.background_per_phone,
        heartbeat_probe_budget=args.heartbeat_probe_budget,
        heartbeat_interval_s=args.heartbeat_interval_s,
        churn_unhealthy_sessions=args.churn_unhealthy_sessions,
        churn_http_healthy_sessions=args.churn_http_healthy_sessions,
        churn_reset_cooldown_sessions=args.churn_reset_cooldown_sessions,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
