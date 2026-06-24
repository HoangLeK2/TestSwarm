"""Benchmarks for run_scenario composition overhead.

These tests use a mock device and no database/ADB. They measure the executor
cost of composing parent scenarios with one or many sub-scenarios.
"""
from __future__ import annotations

import statistics
import time
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from typing import Any, Dict, Optional

from tasks.scenario_task import run_scenario_task
from tests.perf_assertions import assert_p95, perf_budget, percentile


class _NullWriter:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


_NULL_WRITER = _NullWriter()


@contextmanager
def _quiet_runtime_output():
    with redirect_stdout(_NULL_WRITER), redirect_stderr(_NULL_WRITER):
        yield


class _MockU2:
    def __init__(self, present: set[tuple[str, str]] | None = None) -> None:
        self._present = present or set()

    def find_element(self, by: str, value: str, timeout: float = 0) -> Optional[str]:
        if (by, value) in self._present:
            return f"eid:{by}:{value}"
        return None

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict[str, Any]]:
        if (by, value) in self._present:
            return {
                "eid": f"eid:{by}:{value}",
                "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 50},
            }
        return None

    def element_click(self, eid: str) -> None:
        pass


class _MockDevice:
    serial = "flow-bench-serial"
    screen_width = 1080
    screen_height = 1920
    model = "BenchPhone"

    def __init__(self) -> None:
        self.u2 = _MockU2()

    def ensure_u2_healthy(self) -> None:
        pass

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return ""

    def tap(self, x: int, y: int) -> None:
        pass

    def launch_app(self, package: str, **kwargs: Any) -> None:
        pass


def _registry(
    by_id: dict[str, dict[str, Any]] | None = None,
    by_campaign_name: dict[str, dict[str, Any]] | None = None,
    by_template_name: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "by_id": by_id or {},
        "by_campaign_name": by_campaign_name or {},
        "by_template_name": by_template_name or {},
    }


def _sub_def(steps: list[dict[str, Any]], variables: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"steps": steps, "variables": variables or {}, "name": "sub"}


def _set_var_steps(count: int, prefix: str) -> list[dict[str, Any]]:
    return [
        {"type": "set_variable", "name": f"{prefix}_{idx}", "value": str(idx)}
        for idx in range(count)
    ]


def _scenario(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "capture_steps": False,
        "settle_timeout_ms": 0,
        "jitter": {"enabled": False},
        **body,
    }


def _bench(label: str, scenario: dict[str, Any], *, iterations: int) -> list[float]:
    samples_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        with _quiet_runtime_output():
            result = run_scenario_task(_MockDevice(), scenario)
        samples_ms.append((time.perf_counter() - started) * 1000.0)
        assert result.get("success") is True, result.get("failed_message")

    avg = statistics.mean(samples_ms)
    p95 = percentile(samples_ms, 0.95)
    print(f"\n[flow-composition-bench] {label} n={iterations} avg={avg:.2f}ms p95={p95:.2f}ms")
    return samples_ms


def test_main_scenario_only_benchmark() -> None:
    samples = _bench(
        "main-only 30 set_variable steps",
        _scenario({"steps": _set_var_steps(30, "main")}),
        iterations=20,
    )
    assert_p95(
        samples,
        perf_budget("FLOW_COMPOSITION_MAIN_ONLY_P95_MS_BUDGET", 180.0),
        label="flow_composition_main_only",
    )


def test_single_sub_scenario_benchmark() -> None:
    registry = _registry(
        by_campaign_name={"child": _sub_def(_set_var_steps(30, "child"))}
    )
    samples = _bench(
        "parent -> one child with 30 set_variable steps",
        _scenario(
            {
                "steps": [{"type": "run_scenario", "scenario_name": "child"}],
                "_scenario_registry": registry,
            }
        ),
        iterations=20,
    )
    assert_p95(
        samples,
        perf_budget("FLOW_COMPOSITION_SINGLE_SUB_P95_MS_BUDGET", 180.0),
        label="flow_composition_single_sub",
    )


def test_many_sub_scenarios_benchmark() -> None:
    registry = _registry(
        by_campaign_name={
            f"child_{idx}": _sub_def(_set_var_steps(3, f"child_{idx}"))
            for idx in range(10)
        }
    )
    samples = _bench(
        "parent -> ten children, three steps each",
        _scenario(
            {
                "steps": [
                    {"type": "run_scenario", "scenario_name": f"child_{idx}"}
                    for idx in range(10)
                ],
                "_scenario_registry": registry,
            }
        ),
        iterations=20,
    )
    assert_p95(
        samples,
        perf_budget("FLOW_COMPOSITION_MANY_SUBS_P95_MS_BUDGET", 250.0),
        label="flow_composition_many_subs",
    )


def test_sub_scenario_failure_order_and_benchmark() -> None:
    registry = _registry(
        by_campaign_name={
            "bad_child": _sub_def(
                [
                    {"type": "set_variable", "name": "CHILD_BEFORE", "value": "1"},
                    {"type": "unknown_bad_step"},
                ]
            )
        }
    )
    scenario = _scenario(
        {
            "steps": [
                {"type": "set_variable", "name": "PARENT_BEFORE", "value": "1"},
                {"type": "run_scenario", "scenario_name": "bad_child"},
                {"type": "set_variable", "name": "PARENT_AFTER", "value": "1"},
            ],
            "_scenario_registry": registry,
        }
    )

    samples_ms: list[float] = []
    last_result: dict[str, Any] | None = None
    for _ in range(20):
        started = time.perf_counter()
        with _quiet_runtime_output():
            last_result = run_scenario_task(_MockDevice(), scenario)
        samples_ms.append((time.perf_counter() - started) * 1000.0)
        assert last_result.get("success") is True

    assert last_result is not None
    parent_steps = last_result["step_results"]
    assert [step["type"] for step in parent_steps] == [
        "set_variable",
        "run_scenario",
        "set_variable",
    ]
    assert parent_steps[1]["ok"] is False
    assert "bad_child" in parent_steps[1]["message"]
    assert parent_steps[1]["error_policy"] == "continue"
    assert any(
        not step.get("ok", True)
        for step in parent_steps[1]["sub_result"]["step_results"]
    )
    assert parent_steps[2]["ok"] is True

    print(
        "\n[flow-composition-bench] child failure with default parent continue "
        f"n=20 avg={statistics.mean(samples_ms):.2f}ms "
        f"p95={percentile(samples_ms, 0.95):.2f}ms"
    )
    assert_p95(
        samples_ms,
        perf_budget("FLOW_COMPOSITION_FAILURE_P95_MS_BUDGET", 160.0),
        label="flow_composition_failure",
    )
