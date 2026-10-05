"""Synthetic campaign runtime bottleneck benchmarks.

These tests keep the real scenario executor and run_scenario composition path,
but replace device-facing actions with controlled latency buckets. The goal is
to separate executor overhead from likely device-bound costs such as XML dumps,
screenshots, waits, network calls, and ADB commands.
"""
from __future__ import annotations

import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from tasks.scenario.steps import register_step
from tasks.scenario_task import run_scenario_task
from tests.perf_assertions import perf_budget, percentile


class _NoopTraceLog:
    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass


@dataclass
class _StepCostStats:
    lock: threading.Lock = field(default_factory=threading.Lock)
    totals_ms: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def record(self, category: str, elapsed_ms: float) -> None:
        with self.lock:
            self.totals_ms[category] = self.totals_ms.get(category, 0.0) + elapsed_ms
            self.counts[category] = self.counts.get(category, 0) + 1

    def top_category(self) -> tuple[str, float]:
        return max(self.totals_ms.items(), key=lambda item: item[1])


_CURRENT_STATS = _StepCostStats()


@register_step("bench.device_step")
def _handle_bench_device_step(sc, step: dict[str, Any], _idx: int, result: dict[str, Any]) -> None:
    category = str(step.get("category") or "unknown")
    delay_ms = float(step.get("delay_ms") or 0.0)
    label = str(step.get("label") or category)

    started = time.perf_counter()
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    _CURRENT_STATS.record(category, elapsed_ms)
    sc.device.events.append(label)
    result["message"] = f"{category}: {elapsed_ms:.2f}ms"


class _SimulatedDevice:
    screen_width = 1080
    screen_height = 1920
    model = "SimulatedBenchPhone"

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.events: list[str] = []

    def ensure_u2_healthy(self) -> None:
        pass

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return "<hierarchy />"

    def take_screenshot(self) -> bytes:
        return b"\xff\xd8\xff\xe0fake"


def _registry(by_campaign_name: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "by_id": {},
        "by_campaign_name": by_campaign_name,
        "by_template_name": {},
    }


def _bench_step(
    scenario_name: str,
    category: str,
    delay_ms: float,
) -> dict[str, Any]:
    return {
        "type": "bench.device_step",
        "category": category,
        "delay_ms": delay_ms,
        "label": f"{scenario_name}:{category}",
    }


def _sim_delay_ms(category: str, default_ms: float) -> float:
    env_name = f"CAMPAIGN_STEP_SIM_{category.upper()}_MS"
    return perf_budget(env_name, default_ms)


def _simulated_campaign_scenario() -> tuple[dict[str, Any], list[str]]:
    scenario_defs = {
        "login": [
            ("uiautomator_xml", _sim_delay_ms("uiautomator_xml", 6.0)),
            ("adb_command", _sim_delay_ms("adb_command", 4.0)),
        ],
        "open_group": [
            ("app_wait", _sim_delay_ms("app_wait", 14.0)),
            ("uiautomator_xml", _sim_delay_ms("uiautomator_xml", 6.0)),
        ],
        "crawl_posts": [
            ("screenshot", _sim_delay_ms("screenshot", 10.0)),
            ("network", _sim_delay_ms("network", 5.0)),
            ("uiautomator_xml", _sim_delay_ms("uiautomator_xml", 6.0)),
        ],
        "crawl_comments": [
            ("screenshot", _sim_delay_ms("screenshot", 10.0)),
            ("network", _sim_delay_ms("network", 5.0)),
            ("app_wait", _sim_delay_ms("app_wait", 14.0)),
        ],
    }
    registry = _registry(
        {
            name: {
                "name": name,
                "variables": {},
                "steps": [
                    _bench_step(name, category, delay_ms)
                    for category, delay_ms in steps
                ],
            }
            for name, steps in scenario_defs.items()
        }
    )
    scenario_names = list(scenario_defs)
    expected_events = [
        f"{scenario_name}:{category}"
        for scenario_name in scenario_names
        for category, _delay_ms in scenario_defs[scenario_name]
    ]
    return (
        {
            "capture_steps": False,
            "settle_timeout_ms": 0,
            "jitter": {"enabled": False},
            "steps": [
                {"type": "run_scenario", "scenario_name": name}
                for name in scenario_names
            ],
            "_scenario_registry": registry,
        },
        expected_events,
    )


def _run_simulated_device(serial: str, scenario: dict[str, Any]) -> tuple[float, list[str]]:
    device = _SimulatedDevice(serial)
    started = time.perf_counter()
    result = run_scenario_task(device, scenario)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert result.get("success") is True, result.get("failed_message")
    return elapsed_ms, device.events


def test_campaign_device_step_bottleneck_simulation_for_many_devices() -> None:
    global _CURRENT_STATS

    scenario, expected_events = _simulated_campaign_scenario()
    device_counts = [20, 100, 500]
    max_workers = int(perf_budget("CAMPAIGN_DEVICE_STEP_SIM_WORKERS", 50))
    results_by_count: dict[int, tuple[float, float, str, float]] = {}

    for device_count in device_counts:
        _CURRENT_STATS = _StepCostStats()
        started_all = time.perf_counter()
        with patch("tasks.scenario.executor.trace_log", _NoopTraceLog()):
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = list(
                    executor.map(
                        lambda idx: _run_simulated_device(f"sim-{idx:04d}", scenario),
                        range(device_count),
                    )
                )
        total_ms = (time.perf_counter() - started_all) * 1000.0
        samples_ms = [elapsed_ms for elapsed_ms, _events in results]

        for _elapsed_ms, events in results:
            assert events == expected_events

        top_category, top_category_total_ms = _CURRENT_STATS.top_category()
        p95_ms = percentile(samples_ms, 0.95)
        results_by_count[device_count] = (
            total_ms,
            p95_ms,
            top_category,
            top_category_total_ms,
        )
        print(
            "\n[campaign-device-step-sim] "
            f"devices={device_count} workers={max_workers} "
            f"total={total_ms:.2f}ms avg={statistics.mean(samples_ms):.2f}ms "
            f"p95={p95_ms:.2f}ms bottleneck={top_category} "
            f"bucket_total={top_category_total_ms:.2f}ms"
        )

    for device_count, default_budget_ms in [
        (20, 450.0),
        (100, 700.0),
        (500, 1800.0),
    ]:
        total_ms, p95_ms, top_category, _top_total = results_by_count[device_count]
        assert total_ms <= perf_budget(
            f"CAMPAIGN_DEVICE_STEP_SIM_{device_count}_TOTAL_MS_BUDGET",
            default_budget_ms,
        )
        assert p95_ms <= perf_budget(
            f"CAMPAIGN_DEVICE_STEP_SIM_{device_count}_P95_MS_BUDGET",
            400.0,
        )
        expected_bottleneck = os.getenv("CAMPAIGN_DEVICE_STEP_SIM_EXPECTED_BOTTLENECK")
        if expected_bottleneck and device_count >= 100:
            assert top_category == expected_bottleneck
