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
from services.execution.trace_context import push_step_path
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


def _campaign_flow_scenario(
    scenario_names: list[str],
    *,
    child_step_count: int = 5,
) -> dict[str, Any]:
    registry = _registry(
        by_campaign_name={
            name: _sub_def(_set_var_steps(child_step_count, name))
            for name in scenario_names
        }
    )
    return _scenario(
        {
            "steps": [
                {"type": "run_scenario", "scenario_name": name}
                for name in scenario_names
            ],
            "_scenario_registry": registry,
        }
    )


def _traceability_loop_branch_scenario(loop_count: int) -> dict[str, Any]:
    return _scenario(
        {
            "variables": {"READY": True},
            "steps": [
                {
                    "id": "outer_gate",
                    "type": "if_variable",
                    "name": "READY",
                    "then": [
                        {
                            "id": "cycle",
                            "type": "loop",
                            "count": loop_count,
                            "loop_var": "ITER",
                            "steps": [
                                {
                                    "id": "inner_gate",
                                    "type": "if_variable",
                                    "name": "READY",
                                    "then": [
                                        {
                                            "id": "mark_iter",
                                            "type": "set_variable",
                                            "name": "LAST_ITER",
                                            "value": "${ITER}",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _assert_campaign_flow_result(
    result: dict[str, Any],
    scenario_names: list[str],
    *,
    child_step_count: int,
) -> None:
    assert result.get("success") is True, result.get("failed_message")
    parent_steps = result["step_results"]
    assert [step["type"] for step in parent_steps] == ["run_scenario"] * len(scenario_names)

    for step, scenario_name in zip(parent_steps, scenario_names, strict=True):
        assert step["ok"] is True
        assert scenario_name in step["message"]
        sub_steps = step["sub_result"]["step_results"]
        assert len(sub_steps) == child_step_count
        assert [sub_step["type"] for sub_step in sub_steps] == [
            "set_variable"
        ] * child_step_count
        assert all(
            str(sub_step.get("message") or "").startswith(
                f"set_variable: {scenario_name}_"
            )
            for sub_step in sub_steps
        )


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


def test_step_path_builder_benchmark() -> None:
    samples_ms: list[float] = []
    for _ in range(30):
        ctx: dict[str, Any] = {}
        started = time.perf_counter()
        for idx in range(1000):
            ctx = push_step_path(
                ctx,
                step_id=f"node_{idx}",
                loop_iter=idx,
                step_type="loop",
                step_index=idx,
            )
        samples_ms.append((time.perf_counter() - started) * 1000.0)
        assert "node_999#999" in ctx["__scenario_trace__"]["step_path"]

    print(
        "\n[flow-composition-bench] trace step_path builder "
        f"batches=30 batch_size=1000 avg={statistics.mean(samples_ms):.2f}ms "
        f"p95={percentile(samples_ms, 0.95):.2f}ms"
    )
    assert_p95(
        samples_ms,
        perf_budget("SCENARIO_TRACE_CONTEXT_1000_PUSH_P95_MS_BUDGET", 25.0),
        label="scenario_trace_context_1000_push",
    )


def test_traceability_loop_branch_benchmark() -> None:
    loop_count = 40
    samples = _bench(
        f"traceability if -> loop({loop_count}) -> if -> set_variable",
        _traceability_loop_branch_scenario(loop_count),
        iterations=20,
    )
    with _quiet_runtime_output():
        result = run_scenario_task(
            _MockDevice(),
            _traceability_loop_branch_scenario(loop_count),
        )
    leaf = (
        result["step_results"][0]["sub_result"]["step_results"][0]
        ["sub_results"][-1]["result"]["step_results"][0]
        ["sub_result"]["step_results"][0]
    )
    assert leaf["step_path"] == "outer_gate.then/cycle#39/inner_gate.then/mark_iter"
    assert leaf["trace"]["loop_iter"] == 39
    assert leaf["trace"]["loop_id"] == "cycle"
    assert leaf["trace"]["branch"] == "then"
    assert_p95(
        samples,
        perf_budget("SCENARIO_TRACEABILITY_LOOP_BRANCH_P95_MS_BUDGET", 220.0),
        label="scenario_traceability_loop_branch",
    )


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


def test_campaign_flow_scenario_executes_script_order_for_many_devices_benchmark() -> None:
    scenario_names = ["login", "open_group", "crawl_posts", "crawl_comments"]
    child_step_count = 5
    device_counts = [20, 100, 500]
    scenario = _campaign_flow_scenario(
        scenario_names,
        child_step_count=child_step_count,
    )

    totals_ms: dict[int, float] = {}
    p95s_ms: dict[int, float] = {}
    for device_count in device_counts:
        samples_ms: list[float] = []
        started_all = time.perf_counter()
        for _ in range(device_count):
            started = time.perf_counter()
            with _quiet_runtime_output():
                result = run_scenario_task(_MockDevice(), scenario)
            samples_ms.append((time.perf_counter() - started) * 1000.0)
            _assert_campaign_flow_result(
                result,
                scenario_names,
                child_step_count=child_step_count,
            )

        elapsed_ms = (time.perf_counter() - started_all) * 1000.0
        totals_ms[device_count] = elapsed_ms
        p95s_ms[device_count] = percentile(samples_ms, 0.95)
        print(
            "\n[flow-composition-bench] campaign-flow "
            f"devices={device_count} scenarios={len(scenario_names)} "
            f"child_steps={child_step_count} total={elapsed_ms:.2f}ms "
            f"avg={statistics.mean(samples_ms):.2f}ms "
            f"p95={p95s_ms[device_count]:.2f}ms"
        )

    for device_count, default_total_budget_ms in [
        (20, 500.0),
        (100, 1600.0),
        (500, 6500.0),
    ]:
        assert totals_ms[device_count] <= perf_budget(
            f"CAMPAIGN_FLOW_SCENARIO_{device_count}_DEVICES_TOTAL_MS_BUDGET",
            default_total_budget_ms,
        )
        assert p95s_ms[device_count] <= perf_budget(
            f"CAMPAIGN_FLOW_SCENARIO_{device_count}_DEVICES_P95_MS_BUDGET",
            50.0,
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
                {
                    "type": "run_scenario",
                    "scenario_name": "bad_child",
                    "on_error": "continue",
                },
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
    assert parent_steps[1]["ok"] is True
    assert "bad_child" in parent_steps[1]["message"]
    assert parent_steps[1]["error_policy"] == "continue"
    assert parent_steps[1]["error_ignored"] is True
    assert parent_steps[1]["ignored_failure"] is True
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
