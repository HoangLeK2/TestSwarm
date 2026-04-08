from __future__ import annotations

"""
tests/test_control_flow.py — Unit tests for control flow steps.

Run: pytest tests/test_control_flow.py -v

The tests use MockDevice to avoid needing a real Android device.
Steps that don't need device (set_variable, wait 0s) are used for nested steps
to test control logic without I/O.
"""

import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from common.variable_resolver import VariableContext
from tasks.scenario_task import (
    _eval_ru_condition,
    _xml_has_element,
    run_scenario_task,
)


# ── Mock infrastructure ──────────────────────────────────────────────────────


class _MockU2:
    """Minimal U2 mock: find_element returns a fixed set of element IDs."""

    def __init__(self, present: set[tuple[str, str]] | None = None) -> None:
        # present: set of (by, value) tuples that "exist" on the device
        self._present: set[tuple[str, str]] = present or set()
        self.clicks: list[Any] = []

    def find_element(self, by: str, value: str, timeout: float = 0) -> Optional[str]:
        if (by, value) in self._present:
            return f"eid:{by}:{value}"
        # Simulate server-side wait: if timeout > 0 and not present, return None immediately
        return None

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict]:
        if (by, value) in self._present:
            return {"eid": f"eid:{by}:{value}", "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 50}}
        return None

    def element_click(self, eid: str) -> None:
        self.clicks.append(eid)


class _MockDevice:
    """Minimal DeviceClient mock for control flow tests."""

    def __init__(
        self,
        serial: str = "test_serial",
        u2: Optional[_MockU2] = None,
        xml: str = "",
    ) -> None:
        self.serial = serial
        self.u2 = u2
        self.screen_width = 1080
        self.screen_height = 1920
        self.model = "MockPhone"
        self._xml = xml
        self._xml_refresh_count = 0

    def ensure_u2_healthy(self) -> None:
        pass

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        self._xml_refresh_count += 1
        return self._xml

    def tap(self, x: int, y: int) -> None:
        pass

    def launch_app(self, package: str, **kwargs) -> None:
        pass


def test_xml_has_element_text_found():
    xml = '<hierarchy><node text="Allow" resource-id="" /></hierarchy>'
    assert _xml_has_element(xml, "text", "Allow") is True


def test_xml_has_element_text_not_found():
    xml = '<hierarchy><node text="Deny" resource-id="" /></hierarchy>'
    assert _xml_has_element(xml, "text", "Allow") is False


def test_xml_has_element_resource_id():
    xml = '<hierarchy><node resource-id="com.app:id/btn" /></hierarchy>'
    assert _xml_has_element(xml, "resource-id", "com.app:id/btn") is True


def test_xml_has_element_content_desc():
    xml = '<hierarchy><node content-desc="Close" /></hierarchy>'
    assert _xml_has_element(xml, "content-desc", "Close") is True


def test_xml_has_element_empty_xml():
    assert _xml_has_element("", "text", "foo") is False


def test_xml_has_element_empty_value():
    assert _xml_has_element("<hierarchy/>", "text", "") is False


def test_xml_has_element_invalid_xml():
    assert _xml_has_element("<<<not xml>>>", "text", "foo") is False


def test_eval_ru_element_exists_found():
    xml = '<hierarchy><node text="End of feed" /></hierarchy>'
    dev = _MockDevice(xml=xml)
    ctx = VariableContext()
    assert _eval_ru_condition(dev, {"element_exists": {"by": "text", "value": "End of feed"}}, ctx) is True


def test_eval_ru_element_exists_not_found():
    dev = _MockDevice(xml="<hierarchy/>")
    ctx = VariableContext()
    assert _eval_ru_condition(dev, {"element_exists": {"by": "text", "value": "End of feed"}}, ctx) is False


def test_eval_ru_element_not_exists():
    dev = _MockDevice(xml="<hierarchy/>")  # element absent → condition met
    ctx = VariableContext()
    assert _eval_ru_condition(dev, {"element_not_exists": {"by": "text", "value": "Loading"}}, ctx) is True


def test_eval_ru_variable_equals_match():
    dev = _MockDevice()
    ctx = VariableContext()
    ctx.set("STATUS", "done")
    assert _eval_ru_condition(dev, {"variable_equals": {"name": "STATUS", "value": "done"}}, ctx) is True


def test_eval_ru_variable_equals_no_match():
    dev = _MockDevice()
    ctx = VariableContext()
    ctx.set("STATUS", "running")
    assert _eval_ru_condition(dev, {"variable_equals": {"name": "STATUS", "value": "done"}}, ctx) is False


def test_eval_ru_variable_with_interpolation():
    dev = _MockDevice()
    ctx = VariableContext(scenario_vars={"TARGET": "hello"})
    ctx.set("CURRENT", "hello")
    assert _eval_ru_condition(dev, {"variable_equals": {"name": "CURRENT", "value": "hello"}}, ctx) is True


def test_eval_ru_unknown_condition_returns_false():
    dev = _MockDevice()
    ctx = VariableContext()
    assert _eval_ru_condition(dev, {"unsupported_key": {}}, ctx) is False


def test_repeat_executes_count_times():
    dev = _MockDevice()
    # Use set_variable steps to count iterations via side effects
    scenario = {
        "steps": [
            {"type": "repeat", "count": 3, "steps": [
                {"type": "set_variable", "name": "CNT", "increment": 1},
            ]},
        ]
    }
    var_ctx = VariableContext()
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    step_res = result["step_results"][0]
    assert step_res["iterations"] == 3
    # Counter was incremented 3 times
    assert var_ctx.resolve("${CNT}") == 3


def test_repeat_loop_index_is_set():
    dev = _MockDevice()
    recorded: list[int] = []

    # Patch var_ctx to capture __LOOP_INDEX__ each iteration
    scenario = {
        "steps": [
            {"type": "repeat", "count": 4, "steps": [
                {"type": "set_variable", "name": "IDX_COPY", "value": "${__LOOP_INDEX__}"},
            ]},
        ]
    }
    var_ctx = VariableContext()
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    # After 4 iterations, __LOOP_INDEX__ should be 3 (last iteration)
    assert var_ctx.resolve("${__LOOP_INDEX__}") == 3


def test_repeat_zero_count():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "repeat", "count": 0, "steps": [{"type": "wait", "seconds": 0}]}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is True
    assert result["step_results"][0]["iterations"] == 0


def test_repeat_missing_count():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "repeat", "steps": [{"type": "wait", "seconds": 0}]}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    assert "missing count" in result["step_results"][0]["message"]


def test_repeat_no_steps():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "repeat", "count": 3, "steps": []}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    assert "no nested steps" in result["step_results"][0]["message"]


def test_repeat_with_delay(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    dev = _MockDevice()
    scenario = {"steps": [{"type": "repeat", "count": 3, "delay_between": 0.5, "steps": [
        {"type": "set_variable", "name": "X", "value": "y"},
    ]}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is True
    # delay_between fires between iterations: count-1 = 2 sleeps
    assert slept.count(0.5) == 2


# ── repeat_until ─────────────────────────────────────────────────────────────


def test_repeat_until_condition_met_early():
    dev = _MockDevice()
    var_ctx = VariableContext()

    # After 3 increments, CNT == 3 → condition met
    scenario = {
        "steps": [
            {"type": "repeat_until",
             "condition": {"variable_equals": {"name": "CNT", "value": "3"}},
             "max_iterations": 20,
             "steps": [{"type": "set_variable", "name": "CNT", "increment": 1}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    step = result["step_results"][0]
    assert step["iterations"] == 3
    assert "condition met" in step["message"]


def test_repeat_until_max_iterations_reached():
    dev = _MockDevice(xml="<hierarchy/>")  # element never appears
    scenario = {
        "steps": [
            {"type": "repeat_until",
             "condition": {"element_exists": {"by": "text", "value": "Never appears"}},
             "max_iterations": 5,
             "steps": [{"type": "set_variable", "name": "X", "value": "y"}]},
        ]
    }
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    step = result["step_results"][0]
    assert step["iterations"] == 5
    assert "max_iterations" in step["message"]


def test_repeat_until_missing_condition():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "repeat_until", "steps": [{"type": "wait", "seconds": 0}]}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    assert "missing condition" in result["step_results"][0]["message"]


# ── if_element ───────────────────────────────────────────────────────────────


def test_if_element_then_branch_when_found():
    u2 = _MockU2(present={("text", "Allow")})
    dev = _MockDevice(u2=u2)
    var_ctx = VariableContext()
    scenario = {
        "steps": [
            {"type": "if_element", "by": "text", "value": "Allow",
             "then": [{"type": "set_variable", "name": "RESULT", "value": "then"}],
             "else": [{"type": "set_variable", "name": "RESULT", "value": "else"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${RESULT}") == "then"
    assert result["step_results"][0]["element_found"] is True
    assert result["step_results"][0]["branch"] == "then"


def test_if_element_else_branch_when_not_found():
    u2 = _MockU2(present=set())  # nothing present
    dev = _MockDevice(u2=u2)
    var_ctx = VariableContext()
    scenario = {
        "steps": [
            {"type": "if_element", "by": "text", "value": "Allow",
             "then": [{"type": "set_variable", "name": "RESULT", "value": "then"}],
             "else": [{"type": "set_variable", "name": "RESULT", "value": "else"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${RESULT}") == "else"
    assert result["step_results"][0]["element_found"] is False
    assert result["step_results"][0]["branch"] == "else"


def test_if_element_no_else_skips_gracefully():
    u2 = _MockU2(present=set())
    dev = _MockDevice(u2=u2)
    scenario = {
        "steps": [
            {"type": "if_element", "by": "text", "value": "Missing",
             "then": [{"type": "set_variable", "name": "X", "value": "y"}]},
        ]
    }
    result = run_scenario_task(dev, scenario)
    assert result["success"] is True
    assert "skip" in result["step_results"][0]["message"]


def test_if_element_no_u2_uses_else():
    dev = _MockDevice(u2=None)  # no u2 available → element_found=False
    var_ctx = VariableContext()
    scenario = {
        "steps": [
            {"type": "if_element", "by": "text", "value": "X",
             "then": [{"type": "set_variable", "name": "RESULT", "value": "then"}],
             "else": [{"type": "set_variable", "name": "RESULT", "value": "else"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${RESULT}") == "else"


def test_if_element_missing_by_fails():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "if_element", "value": "X", "then": []}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    assert "missing by/value" in result["step_results"][0]["message"]


# ── if_variable ──────────────────────────────────────────────────────────────


def test_if_variable_equals_match():
    dev = _MockDevice()
    var_ctx = VariableContext(scenario_vars={"PLATFORM": "facebook"})
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "PLATFORM", "equals": "facebook",
             "then": [{"type": "set_variable", "name": "RESULT", "value": "fb"}],
             "else": [{"type": "set_variable", "name": "RESULT", "value": "other"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${RESULT}") == "fb"
    assert result["step_results"][0]["condition_met"] is True


def test_if_variable_equals_no_match():
    dev = _MockDevice()
    var_ctx = VariableContext(scenario_vars={"PLATFORM": "tiktok"})
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "PLATFORM", "equals": "facebook",
             "then": [{"type": "set_variable", "name": "RESULT", "value": "fb"}],
             "else": [{"type": "set_variable", "name": "RESULT", "value": "other"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${RESULT}") == "other"
    assert result["step_results"][0]["condition_met"] is False


def test_if_variable_not_equals():
    dev = _MockDevice()
    var_ctx = VariableContext(scenario_vars={"STATUS": "done"})
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "STATUS", "not_equals": "running",
             "then": [{"type": "set_variable", "name": "R", "value": "yes"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${R}") == "yes"


def test_if_variable_contains():
    dev = _MockDevice()
    var_ctx = VariableContext(scenario_vars={"MSG": "hello world"})
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "MSG", "contains": "world",
             "then": [{"type": "set_variable", "name": "FOUND", "value": "1"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${FOUND}") == "1"


def test_if_variable_greater_than():
    dev = _MockDevice()
    var_ctx = VariableContext()
    var_ctx.increment("CNT")  # CNT = 1
    var_ctx.increment("CNT")  # CNT = 2
    var_ctx.increment("CNT")  # CNT = 3
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "CNT", "greater_than": 2,
             "then": [{"type": "set_variable", "name": "R", "value": "big"}],
             "else": [{"type": "set_variable", "name": "R", "value": "small"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${R}") == "big"


def test_if_variable_truthy_no_condition_op():
    dev = _MockDevice()
    var_ctx = VariableContext()
    var_ctx.set("FLAG", "active")
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "FLAG",
             "then": [{"type": "set_variable", "name": "R", "value": "yes"}],
             "else": [{"type": "set_variable", "name": "R", "value": "no"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${R}") == "yes"


def test_if_variable_missing_name():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "if_variable", "then": [{"type": "wait", "seconds": 0}]}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    assert "missing name" in result["step_results"][0]["message"]


def test_if_variable_unresolved_var_goes_to_else():
    dev = _MockDevice()
    var_ctx = VariableContext()  # MISSING is not set
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "MISSING", "equals": "foo",
             "then": [{"type": "set_variable", "name": "R", "value": "then"}],
             "else": [{"type": "set_variable", "name": "R", "value": "else"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    # ${MISSING} resolves to "${MISSING}" (string), which != "foo"
    assert var_ctx.resolve("${R}") == "else"


# ── random_pick ──────────────────────────────────────────────────────────────


def test_random_pick_executes_one_branch(monkeypatch):
    monkeypatch.setattr("tasks.scenario_task.random.choices", lambda pop, weights, k: [0])
    dev = _MockDevice()
    var_ctx = VariableContext()
    scenario = {
        "steps": [
            {"type": "random_pick", "branches": [
                {"weight": 3, "steps": [{"type": "set_variable", "name": "B", "value": "first"}]},
                {"weight": 1, "steps": [{"type": "set_variable", "name": "B", "value": "second"}]},
            ]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${B}") == "first"
    assert result["step_results"][0]["chosen_branch"] == 0


def test_random_pick_respects_chosen_index(monkeypatch):
    monkeypatch.setattr("tasks.scenario_task.random.choices", lambda pop, weights, k: [1])
    dev = _MockDevice()
    var_ctx = VariableContext()
    scenario = {
        "steps": [
            {"type": "random_pick", "branches": [
                {"steps": [{"type": "set_variable", "name": "B", "value": "first"}]},
                {"steps": [{"type": "set_variable", "name": "B", "value": "second"}]},
            ]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${B}") == "second"


def test_random_pick_no_branches_fails():
    dev = _MockDevice()
    scenario = {"steps": [{"type": "random_pick", "branches": []}]}
    result = run_scenario_task(dev, scenario)
    assert result["success"] is False
    assert "no branches" in result["step_results"][0]["message"]


def test_random_pick_empty_branch_skips():
    dev = _MockDevice()
    scenario = {
        "steps": [
            {"type": "random_pick", "branches": [{"weight": 1, "steps": []}]},
        ]
    }
    result = run_scenario_task(dev, scenario)
    assert result["success"] is True
    assert "skip" in result["step_results"][0]["message"]


def test_random_pick_weight_defaults_to_one():
    """Branches without explicit weight should use weight=1 (no crash)."""
    dev = _MockDevice()
    scenario = {
        "steps": [
            {"type": "random_pick", "branches": [
                {"steps": [{"type": "set_variable", "name": "X", "value": "a"}]},
                {"steps": [{"type": "set_variable", "name": "X", "value": "b"}]},
            ]},
        ]
    }
    result = run_scenario_task(dev, scenario)
    assert result["success"] is True


# ── MAX DEPTH guard ───────────────────────────────────────────────────────────


def test_max_depth_guard():
    """Deeply nested repeat (11 levels) must be rejected with a clear error."""
    dev = _MockDevice()

    def _make_nested(depth: int) -> dict:
        if depth == 0:
            return {"type": "set_variable", "name": "X", "value": "y"}
        return {"type": "repeat", "count": 1, "steps": [_make_nested(depth - 1)]}

    # Build 12 levels of nesting (exceeds MAX_DEPTH=10)
    scenario = {"steps": [_make_nested(12)]}
    result = run_scenario_task(dev, scenario)
    # The scenario itself succeeds at the outer level, but one nested sub-call
    # returns failure due to MAX_DEPTH.
    # Check that max depth error appears somewhere in the result tree.
    outer = result["step_results"][0]
    assert outer["ok"] is False
    assert "failed" in outer.get("message", "").lower() or "Max nesting depth" in str(outer)


# ── Variable interpolation in control flow steps ─────────────────────────────


def test_repeat_count_from_variable():
    dev = _MockDevice()
    var_ctx = VariableContext(scenario_vars={"REPEAT_N": 4})
    scenario = {
        "steps": [
            {"type": "repeat", "count": "${REPEAT_N}", "steps": [
                {"type": "set_variable", "name": "CNT", "increment": 1},
            ]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    # Variable ${REPEAT_N} resolves to int 4 → count=4
    assert result["step_results"][0]["iterations"] == 4


def test_if_element_value_from_variable():
    u2 = _MockU2(present={("text", "Allow")})
    dev = _MockDevice(u2=u2)
    var_ctx = VariableContext(scenario_vars={"BTN": "Allow"})
    scenario = {
        "steps": [
            {"type": "if_element", "by": "text", "value": "${BTN}",
             "then": [{"type": "set_variable", "name": "R", "value": "found"}]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${R}") == "found"


# ── Nested combinations ───────────────────────────────────────────────────────


def test_repeat_inside_if_variable():
    dev = _MockDevice()
    var_ctx = VariableContext(scenario_vars={"DO_REPEAT": "yes"})
    scenario = {
        "steps": [
            {"type": "if_variable", "name": "DO_REPEAT", "equals": "yes",
             "then": [
                 {"type": "repeat", "count": 2, "steps": [
                     {"type": "set_variable", "name": "CNT", "increment": 1},
                 ]},
             ]},
        ]
    }
    result = run_scenario_task(dev, scenario, _var_ctx=var_ctx)
    assert result["success"] is True
    assert var_ctx.resolve("${CNT}") == 2
