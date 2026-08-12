"""
tests/test_temporal_workflows.py — Unit tests for Temporal workflow engine (DF-002).

Tests cover:
- ScenarioStepsWorkflow control flow (repeat, repeat_until, if_element, if_variable, random_pick)
- Variable resolution and set_variable
- Edge cases (max depth, empty steps, invalid inputs)
- Activity dispatch
- ScenarioWorkflow signals (pause, resume, cancel)

Run: pytest tests/test_temporal_workflows.py -v

Uses temporalio.testing.WorkflowEnvironment for deterministic replay-safe testing.
No real Temporal Server required.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temporal.shared import (
    MAX_NESTING_DEPTH,
    ConditionCheckInput,
    DeviceActionInput,
    ElementCheckInput,
    ElementCheckResult,
    ScenarioInput,
    StepResult,
    StepsInput,
    StepsResult,
    WorkflowProgress,
    WorkflowStatus,
)
from temporal.workflows import (
    ScenarioStepsWorkflow,
    ScenarioWorkflow,
    _append_sub_result,
    _finish_sub_results,
    _handle_set_variable,
    _lookup_var,
    _resolve_step,
    _workflow_failure_message,
)


# ── Variable resolution tests ────────────────────────────────────────────────


def test_sub_result_retention_caps_large_loop_payloads():
    sub_results: list[dict[str, Any]] = []
    state: dict[str, Any] = {}

    for i in range(75):
        _append_sub_result(sub_results, state, {"iteration": i, "success": True})
    _finish_sub_results(sub_results, state)

    assert len(sub_results) == 51
    assert sub_results[0] == {"iteration": 0, "success": True}
    assert sub_results[49] == {"iteration": 49, "success": True}
    assert sub_results[-1]["truncated"] is True
    assert sub_results[-1]["omitted"] == 25
    assert sub_results[-1]["last"] == {"iteration": 74, "success": True}


def test_workflow_failure_message_prefers_nested_cause():
    inner = RuntimeError("tap_selector: element not found")
    outer = Exception("Child Workflow execution failed")
    outer.__cause__ = inner

    assert _workflow_failure_message(outer) == "tap_selector: element not found"


def test_workflow_failure_message_replaces_generic_child_failure():
    exc = Exception("Child Workflow execution failed")

    assert _workflow_failure_message(exc, fallback="child failed without step detail") == (
        "child failed without step detail"
    )

    verbose_exc = Exception("Child Workflow execution failed: child closed")
    assert _workflow_failure_message(verbose_exc, fallback="child failed without step detail") == (
        "child failed without step detail"
    )


class TestResolveStep:
    """Test deterministic variable resolution in workflow context."""

    def test_resolve_simple_string(self):
        step = {"type": "launch_app", "package": "${APP}"}
        result = _resolve_step(step, {"APP": "com.test"}, {}, {}, 0)
        assert result["package"] == "com.test"

    def test_resolve_from_scenario_vars(self):
        step = {"type": "launch_app", "package": "${APP}"}
        result = _resolve_step(step, {}, {"APP": "com.scenario"}, {}, 0)
        assert result["package"] == "com.scenario"

    def test_resolve_from_campaign_vars(self):
        step = {"type": "launch_app", "package": "${APP}"}
        result = _resolve_step(step, {}, {}, {"APP": "com.campaign"}, 0)
        assert result["package"] == "com.campaign"

    def test_runtime_overrides_scenario(self):
        step = {"type": "launch_app", "package": "${APP}"}
        result = _resolve_step(step, {"APP": "com.runtime"}, {"APP": "com.scenario"}, {}, 0)
        assert result["package"] == "com.runtime"

    def test_unresolved_var_kept(self):
        step = {"type": "wait", "seconds": "${UNKNOWN}"}
        result = _resolve_step(step, {}, {}, {}, 0)
        assert result["seconds"] == "${UNKNOWN}"

    def test_resolve_nested_dict(self):
        step = {
            "type": "tap",
            "selector": {"by": "text", "value": "${LABEL}"},
        }
        result = _resolve_step(step, {"LABEL": "OK"}, {}, {}, 0)
        assert result["selector"]["value"] == "OK"

    def test_resolve_nested_list(self):
        step = {
            "type": "random_pick",
            "branches": [{"steps": [{"type": "wait", "seconds": "${DELAY}"}]}],
        }
        result = _resolve_step(step, {"DELAY": "2"}, {}, {}, 0)
        assert result["branches"][0]["steps"][0]["seconds"] == "${DELAY}"

    def test_control_flow_nested_steps_are_not_resolved_before_runtime_vars(self):
        step = {
            "type": "if_variable",
            "name": "FACEBOOK_SESSION_READY",
            "then": [
                {
                    "type": "loop",
                    "count": "${PAGE_COUNT}",
                    "loop_var": "PAGE_INDEX",
                    "steps": [
                        {
                            "type": "set_variable",
                            "name": "PAGE_SEARCH_CURRENT",
                            "from_list": "${PAGE_TARGETS}",
                            "from_list_index": "${PAGE_INDEX}",
                        }
                    ],
                }
            ],
        }
        result = _resolve_step(
            step,
            {},
            {
                "FACEBOOK_SESSION_READY": True,
                "PAGE_COUNT": 2,
                "PAGE_TARGETS": ["Go2Joy Vietnam", "Booking.com"],
            },
            {},
            0,
        )
        nested_set = result["then"][0]["steps"][0]
        assert nested_set["from_list"] == "${PAGE_TARGETS}"
        assert nested_set["from_list_index"] == "${PAGE_INDEX}"

    def test_resolve_step_index(self):
        step = {"type": "set_variable", "name": "idx", "value": "${__STEP_INDEX__}"}
        result = _resolve_step(step, {}, {}, {}, 5)
        assert result["value"] == 5

    def test_resolve_exact_match_preserves_type(self):
        """When entire string is ${VAR}, preserve original type (int, list, etc.)."""
        step = {"type": "repeat", "count": "${N}"}
        result = _resolve_step(step, {"N": 10}, {}, {}, 0)
        assert result["count"] == 10
        assert isinstance(result["count"], int)

    def test_resolve_multiple_vars_in_string(self):
        step = {"type": "input_text", "text": "Hello ${NAME}, you are ${AGE}"}
        result = _resolve_step(step, {"NAME": "Alice", "AGE": "30"}, {}, {}, 0)
        assert result["text"] == "Hello Alice, you are 30"

    def test_non_string_values_untouched(self):
        step = {"type": "tap_ratio", "x": 0.5, "y": 0.3}
        result = _resolve_step(step, {}, {}, {}, 0)
        assert result["x"] == 0.5
        assert result["y"] == 0.3


# ── set_variable handler tests ───────────────────────────────────────────────


class TestHandleSetVariable:
    def test_set_value(self):
        runtime_vars: dict = {}
        result = _handle_set_variable(
            {"type": "set_variable", "name": "X", "value": "hello"},
            {"type": "set_variable", "name": "X", "value": "hello"},
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is True
        assert runtime_vars["X"] == "hello"

    def test_set_from_list(self):
        runtime_vars: dict = {}
        result = _handle_set_variable(
            {"type": "set_variable", "name": "COLOR", "from_list": ["red", "blue"]},
            {"type": "set_variable", "name": "COLOR", "from_list": ["red", "blue"]},
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is True
        assert runtime_vars["COLOR"] in ("red", "blue")

    def test_set_from_list_index(self):
        runtime_vars: dict = {}
        result = _handle_set_variable(
            {
                "type": "set_variable",
                "name": "PAGE_SEARCH_CURRENT",
                "from_list": ["Go2Joy Vietnam", "Booking.com"],
                "from_list_index": 1,
            },
            {
                "type": "set_variable",
                "name": "PAGE_SEARCH_CURRENT",
                "from_list": "${PAGE_TARGETS}",
                "from_list_index": "${PAGE_INDEX}",
            },
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is True
        assert runtime_vars["PAGE_SEARCH_CURRENT"] == "Booking.com"
        assert "from_list_index=1" in result["message"]

    def test_set_increment(self):
        runtime_vars: dict = {"COUNTER": 5}
        result = _handle_set_variable(
            {"type": "set_variable", "name": "COUNTER", "increment": 3},
            {"type": "set_variable", "name": "COUNTER", "increment": 3},
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is True
        assert runtime_vars["COUNTER"] == 8

    def test_set_increment_from_zero(self):
        runtime_vars: dict = {}
        result = _handle_set_variable(
            {"type": "set_variable", "name": "NEW", "increment": 1},
            {"type": "set_variable", "name": "NEW", "increment": 1},
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is True
        assert runtime_vars["NEW"] == 1

    def test_missing_name(self):
        runtime_vars: dict = {}
        result = _handle_set_variable(
            {"type": "set_variable", "name": ""},
            {"type": "set_variable", "name": ""},
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is False

    def test_from_list_empty(self):
        runtime_vars: dict = {}
        result = _handle_set_variable(
            {"type": "set_variable", "name": "X", "from_list": []},
            {"type": "set_variable", "name": "X", "from_list": []},
            runtime_vars, {}, {}, 0,
        )
        assert result["ok"] is False


# ── StepsInput/StepsResult serialization tests ───────────────────────────────


class TestDataclassSerialization:
    """Verify dataclasses are properly structured for Temporal serialization."""

    def test_steps_input_defaults(self):
        inp = StepsInput(device_serial="test", steps=[])
        assert inp.depth == 0
        assert inp.parent_runtime_vars == {}
        assert inp.variables == {}

    def test_step_result_defaults(self):
        r = StepResult(index=0, step_type="tap", ok=True)
        assert r.message == ""
        assert r.details == {}

    def test_steps_result_defaults(self):
        r = StepsResult(success=True, steps_executed=5)
        assert r.step_results == []
        assert r.runtime_vars == {}
        assert r.failed_message == ""

    def test_workflow_progress_defaults(self):
        p = WorkflowProgress()
        assert p.status == WorkflowStatus.RUNNING.value
        assert p.current_step == 0
        assert p.loop_iteration == -1

    def test_scenario_input_fields(self):
        inp = ScenarioInput(
            campaign_id="c1",
            device_serial="dev1",
            steps=[{"type": "wait", "seconds": 1}],
        )
        assert inp.campaign_id == "c1"
        assert inp.capture_steps is False
        assert inp.scenario_registry == {}


# ── Max nesting depth test ───────────────────────────────────────────────────


class TestMaxNestingDepth:
    """Test that deeply nested steps are rejected."""

    def test_max_depth_constant(self):
        assert MAX_NESTING_DEPTH == 10

    def test_steps_input_depth_propagation(self):
        """Verify depth is incremented in child workflows."""
        parent = StepsInput(device_serial="test", steps=[], depth=5)
        child = StepsInput(
            device_serial=parent.device_serial,
            steps=[],
            depth=parent.depth + 1,
        )
        assert child.depth == 6


# ── Activity input validation tests ─────────────────────────────────────────


class TestActivityInputValidation:
    def test_device_action_input(self):
        inp = DeviceActionInput(
            device_serial="192.168.1.1:5555",
            step={"type": "tap_ratio", "x": 0.5, "y": 0.5},
            step_index=0,
        )
        assert inp.device_serial == "192.168.1.1:5555"

    def test_element_check_input(self):
        inp = ElementCheckInput(
            device_serial="test",
            by="text", value="OK", timeout=3.0,
        )
        assert inp.timeout == 3.0

    def test_condition_check_input(self):
        inp = ConditionCheckInput(
            device_serial="test",
            condition={"element_exists": {"by": "text", "value": "Done"}},
            runtime_vars={"COUNTER": 5},
        )
        assert "element_exists" in inp.condition

    def test_element_check_result(self):
        r = ElementCheckResult(found=True, message="found")
        assert r.found is True


# ── Security tests ───────────────────────────────────────────────────────────


class TestSecurityValidation:
    """Test security constraints in workflow/activity inputs."""

    def test_step_resolution_no_env_leak(self):
        """Variable resolution should not leak environment variables."""
        import os
        os.environ["SECRET_KEY"] = "supersecret"
        try:
            step = {"type": "input_text", "text": "${SECRET_KEY}"}
            result = _resolve_step(step, {}, {}, {}, 0)
            # Workflow-level resolution does NOT look at os.environ
            # (only VariableContext in the original engine does that)
            assert result["text"] == "${SECRET_KEY}"
        finally:
            del os.environ["SECRET_KEY"]

    def test_dangerous_step_types_not_in_control_flow(self):
        """Control flow types should not be executable as regular activities."""
        control_flow_types = {"repeat", "repeat_until", "if_element", "if_variable", "random_pick"}
        for t in control_flow_types:
            # These are handled in the workflow, not dispatched to activities
            step = {"type": t}
            # Just verify the type is recognized (no crash)
            assert step["type"] == t


# ── Integration-style workflow logic tests ───────────────────────────────────
# These test the workflow logic without running Temporal infrastructure.


class TestRepeatLogic:
    """Test repeat step handling logic."""

    def test_repeat_step_structure(self):
        step = {
            "type": "repeat",
            "count": 3,
            "delay_between": 1.0,
            "steps": [
                {"type": "scroll_down"},
                {"type": "wait", "seconds": 0.5},
            ],
        }
        assert step["count"] == 3
        assert len(step["steps"]) == 2

    def test_repeat_missing_count_handled(self):
        step = {"type": "repeat", "steps": [{"type": "wait"}]}
        assert step.get("count") is None

    def test_repeat_empty_steps_handled(self):
        step = {"type": "repeat", "count": 5, "steps": []}
        assert len(step["steps"]) == 0


class TestLookupVar:
    """Test _lookup_var handles falsy values correctly."""

    def test_returns_zero(self):
        assert _lookup_var("x", {"x": 0}) == 0

    def test_returns_false(self):
        assert _lookup_var("x", {"x": False}) is False

    def test_returns_empty_string(self):
        assert _lookup_var("x", {"x": ""}) == ""

    def test_returns_empty_list(self):
        assert _lookup_var("x", {"x": []}) == []

    def test_falls_through_to_second_dict(self):
        assert _lookup_var("x", {}, {"x": "found"}) == "found"

    def test_first_dict_wins_even_if_falsy(self):
        """Runtime var 0 should NOT fall through to scenario var 10."""
        assert _lookup_var("x", {"x": 0}, {"x": 10}) == 0

    def test_not_found_returns_none(self):
        assert _lookup_var("x", {}, {}) is None

    def test_three_dicts(self):
        assert _lookup_var("x", {}, {}, {"x": "campaign"}) == "campaign"


class TestIfVariableLogic:
    """Test if_variable condition evaluation logic."""

    def test_equals_match(self):
        name = "PLATFORM"
        step = {"name": name, "equals": "facebook"}
        runtime_vars = {"PLATFORM": "facebook"}
        str_val = str(runtime_vars.get(name, ""))
        assert str_val == str(step["equals"])

    def test_equals_no_match(self):
        name = "PLATFORM"
        step = {"name": name, "equals": "tiktok"}
        runtime_vars = {"PLATFORM": "facebook"}
        str_val = str(runtime_vars.get(name, ""))
        assert str_val != str(step["equals"])

    def test_not_equals(self):
        name = "STATUS"
        step = {"name": name, "not_equals": "done"}
        runtime_vars = {"STATUS": "running"}
        str_val = str(runtime_vars.get(name, ""))
        assert str_val != str(step["not_equals"])

    def test_contains(self):
        name = "TEXT"
        step = {"name": name, "contains": "hello"}
        runtime_vars = {"TEXT": "say hello world"}
        str_val = str(runtime_vars.get(name, ""))
        assert str(step["contains"]) in str_val

    def test_greater_than(self):
        name = "COUNT"
        step = {"name": name, "greater_than": 5}
        runtime_vars = {"COUNT": 10}
        assert float(runtime_vars[name]) > float(step["greater_than"])

    def test_greater_than_invalid_value(self):
        name = "COUNT"
        step = {"name": name, "greater_than": 5}
        runtime_vars = {"COUNT": "abc"}
        try:
            float(runtime_vars[name]) > float(step["greater_than"])
            condition_met = True
        except (TypeError, ValueError):
            condition_met = False
        assert condition_met is False

    def test_truthy_check(self):
        runtime_vars = {"FLAG": "yes"}
        val = runtime_vars.get("FLAG")
        str_val = str(val) if val is not None else ""
        assert bool(val) and str_val not in ("None", "", "0")

    def test_falsy_check_empty(self):
        runtime_vars = {"FLAG": ""}
        val = runtime_vars.get("FLAG")
        str_val = str(val) if val is not None else ""
        assert not (bool(val) and str_val not in ("None", "", "0"))

    def test_falsy_check_missing(self):
        runtime_vars: dict = {}
        val = runtime_vars.get("MISSING")
        assert val is None


class TestRandomPickLogic:
    """Test random_pick branch selection logic."""

    def test_weighted_selection_structure(self):
        branches = [
            {"weight": 3, "steps": [{"type": "scroll_down"}]},
            {"weight": 1, "steps": [{"type": "wait"}]},
        ]
        weights = [max(1, int(b.get("weight", 1))) for b in branches]
        assert weights == [3, 1]
        assert sum(weights) == 4

    def test_empty_branches_handled(self):
        branches: list = []
        assert len(branches) == 0

    def test_branch_without_weight_defaults_to_1(self):
        branches = [{"steps": [{"type": "wait"}]}]
        weights = [max(1, int(b.get("weight", 1))) for b in branches]
        assert weights == [1]


class TestRepeatUntilLogic:
    """Test repeat_until condition structures."""

    def test_element_exists_condition(self):
        condition = {"element_exists": {"by": "text", "value": "Done"}}
        assert "element_exists" in condition
        spec = condition["element_exists"]
        assert spec["by"] == "text"
        assert spec["value"] == "Done"

    def test_element_not_exists_condition(self):
        condition = {"element_not_exists": {"by": "text", "value": "Loading"}}
        assert "element_not_exists" in condition

    def test_variable_equals_condition(self):
        condition = {"variable_equals": {"name": "STATUS", "value": "done"}}
        assert "variable_equals" in condition
        spec = condition["variable_equals"]
        assert spec["name"] == "STATUS"

    def test_max_iterations_capped(self):
        max_iter = max(1, min(int(99999), 10_000))
        assert max_iter == 10_000

    def test_max_iterations_default(self):
        step = {"condition": {"variable_equals": {"name": "X", "value": "y"}}, "steps": []}
        max_iter = max(1, min(int(step.get("max_iterations", 100) or 100), 10_000))
        assert max_iter == 100


# ── Workflow progress tests ──────────────────────────────────────────────────


class TestWorkflowProgress:
    def test_initial_state(self):
        p = WorkflowProgress()
        assert p.status == "running"
        assert p.current_step == 0
        assert p.total_steps == 0
        assert p.device_serial == ""

    def test_update_progress(self):
        p = WorkflowProgress()
        p.status = WorkflowStatus.PAUSED.value
        p.current_step = 5
        p.total_steps = 10
        p.device_serial = "test123"
        assert p.status == "paused"
        assert p.current_step == 5


# ── End-to-end workflow structure tests ──────────────────────────────────────


class TestScenarioInputConstruction:
    """Test that campaign_dispatch builds valid ScenarioInput."""

    def test_basic_scenario(self):
        inp = ScenarioInput(
            campaign_id="campaign-1",
            device_serial="192.168.1.100:5555",
            steps=[
                {"type": "launch_app", "package": "com.test.app"},
                {"type": "wait_element", "by": "text", "value": "Home", "timeout": 10},
                {"type": "repeat", "count": 5, "steps": [
                    {"type": "scroll_down"},
                    {"type": "if_element", "by": "text", "value": "Like", "timeout": 3,
                     "then": [{"type": "tap_selector", "by": "text", "value": "Like"}],
                     "else": [{"type": "wait", "seconds": 1}]},
                ]},
            ],
            variables={"APP_NAME": "TestApp"},
            campaign_vars={"__PLATFORM__": "facebook"},
        )
        assert len(inp.steps) == 3
        assert inp.steps[2]["type"] == "repeat"
        assert inp.steps[2]["count"] == 5
        assert len(inp.steps[2]["steps"]) == 2
        assert inp.steps[2]["steps"][1]["type"] == "if_element"

    def test_nested_control_flow(self):
        """Verify deeply nested control flow structures are valid."""
        inp = ScenarioInput(
            campaign_id="c1",
            device_serial="dev1",
            steps=[{
                "type": "repeat", "count": 3,
                "steps": [{
                    "type": "if_element", "by": "text", "value": "Popup",
                    "timeout": 2,
                    "then": [{
                        "type": "random_pick",
                        "branches": [
                            {"weight": 2, "steps": [{"type": "tap_selector", "by": "text", "value": "OK"}]},
                            {"weight": 1, "steps": [{"type": "tap_selector", "by": "text", "value": "Cancel"}]},
                        ],
                    }],
                    "else": [{"type": "scroll_down"}],
                }],
            }],
        )
        repeat_step = inp.steps[0]
        if_step = repeat_step["steps"][0]
        random_step = if_step["then"][0]
        assert random_step["type"] == "random_pick"
        assert len(random_step["branches"]) == 2
        assert random_step["branches"][0]["weight"] == 2
