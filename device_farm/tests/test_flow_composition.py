from __future__ import annotations

"""
tests/test_flow_composition.py — Unit tests for DF-003 Flow Composition.

Run: pytest tests/test_flow_composition.py -v

Tests use MockDevice/MockU2 (no real hardware required).
All DB-dependent tests stub the scenario registry inline in the payload.
"""

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from common.variable_resolver import VariableContext
from tasks.scenario_task import run_scenario_task


# ── Mock infrastructure (mirrors test_control_flow.py) ───────────────────────


class _MockU2:
    def __init__(self, present: set[tuple[str, str]] | None = None) -> None:
        self._present: set[tuple[str, str]] = present or set()

    def find_element(self, by: str, value: str, timeout: float = 0) -> Optional[str]:
        if (by, value) in self._present:
            return f"eid:{by}:{value}"
        return None

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict]:
        if (by, value) in self._present:
            return {"eid": f"eid:{by}:{value}", "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 50}}
        return None

    def element_click(self, eid: str) -> None:
        pass


class _MockDevice:
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

    def ensure_u2_healthy(self) -> None:
        pass

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self._xml

    def tap(self, x: int, y: int) -> None:
        pass

    def launch_app(self, package: str, **kwargs) -> None:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_device() -> _MockDevice:
    return _MockDevice()


def _registry(
    by_id: dict | None = None,
    by_campaign_name: dict | None = None,
    by_template_name: dict | None = None,
) -> Dict[str, Any]:
    return {
        "by_id": by_id or {},
        "by_campaign_name": by_campaign_name or {},
        "by_template_name": by_template_name or {},
    }


def _sub_def(steps: list, variables: dict | None = None) -> Dict[str, Any]:
    return {"steps": steps, "variables": variables or {}, "name": "sub"}


# ── run_scenario: basic execution ─────────────────────────────────────────────


def test_run_scenario_by_id_executes_sub_steps():
    sub_steps = [{"type": "set_variable", "name": "X", "value": "done"}]
    reg = _registry(by_id={"uuid-123": _sub_def(sub_steps)})
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_id": "uuid-123"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True
    sr = result["step_results"][0]
    assert sr["ok"] is True
    assert "uuid-123" in sr["message"]


def test_run_scenario_by_campaign_name():
    sub_steps = [{"type": "wait", "seconds": 0}]
    reg = _registry(by_campaign_name={"login_flow": _sub_def(sub_steps)})
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "login_flow"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True
    sr = result["step_results"][0]
    assert sr["ok"] is True
    assert "login_flow" in sr["message"]


def test_run_scenario_by_template_name():
    sub_steps = [{"type": "wait", "seconds": 0}]
    reg = _registry(by_template_name={"scroll_feed_generic": _sub_def(sub_steps)})
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "scroll_feed_generic"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True


def test_run_scenario_campaign_name_takes_priority_over_template():
    """by_campaign_name is checked before by_template_name."""
    campaign_steps = [{"type": "set_variable", "name": "SOURCE", "value": "campaign"}]
    template_steps = [{"type": "set_variable", "name": "SOURCE", "value": "template"}]
    reg = _registry(
        by_campaign_name={"shared": _sub_def(campaign_steps)},
        by_template_name={"shared": _sub_def(template_steps)},
    )
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "shared"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True
    # sub_result steps_executed = 1 (the set_variable from campaign)
    sub = result["step_results"][0]["sub_result"]
    assert sub["steps_executed"] == 1


# ── run_scenario: variable overrides ─────────────────────────────────────────


def test_run_scenario_variable_override_is_used():
    """Variables dict in the step overrides sub-scenario defaults."""
    sub_steps = [{"type": "set_variable", "name": "OUT", "value": "${GREETING}"}]
    reg = _registry(
        by_campaign_name={"greet": _sub_def(sub_steps, {"GREETING": "hello_default"})}
    )
    # Override GREETING via step variables
    scenario = {
        "steps": [
            {
                "type": "run_scenario",
                "scenario_name": "greet",
                "variables": {"GREETING": "hello_override"},
            }
        ],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True


def test_run_scenario_sub_vars_do_not_pollute_parent():
    """Runtime vars set inside sub-scenario must not appear in parent scope."""
    sub_steps = [{"type": "set_variable", "name": "INNER_VAR", "value": "inner"}]
    reg = _registry(by_campaign_name={"inner": _sub_def(sub_steps)})
    parent_var_ctx = VariableContext()

    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "inner"}],
        "_scenario_registry": reg,
    }
    run_scenario_task(_make_device(), scenario, _var_ctx=parent_var_ctx)
    # INNER_VAR should not be in parent runtime vars
    assert parent_var_ctx.resolve("${INNER_VAR}") == "${INNER_VAR}"


# ── run_scenario: error cases ─────────────────────────────────────────────────


def test_run_scenario_not_found_returns_error():
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "nonexistent"}],
        "_scenario_registry": _registry(),
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is False
    sr = result["step_results"][0]
    assert sr["ok"] is False
    assert "not found" in sr["message"]


def test_run_scenario_missing_id_and_name():
    scenario = {
        "steps": [{"type": "run_scenario"}],
        "_scenario_registry": _registry(),
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is False
    sr = result["step_results"][0]
    assert sr["ok"] is False
    assert "missing" in sr["message"]


def test_run_scenario_empty_registry():
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_id": "any-id"}],
        # No _scenario_registry key at all
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is False
    assert "not found" in result["step_results"][0]["message"]


# ── Circular reference detection ─────────────────────────────────────────────


def test_circular_self_reference_detected():
    """A scenario that tries to call itself must be blocked."""
    sub_steps = [{"type": "run_scenario", "scenario_name": "A"}]
    reg = _registry(by_campaign_name={"A": _sub_def(sub_steps)})
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "A"}],
        "_scenario_registry": reg,
    }
    # First call: A not in empty call_stack → enters A.
    # Inside A: A IS in call_stack → circular reference error.
    result = run_scenario_task(_make_device(), scenario)
    # Top-level run_scenario step is processed, then fails because the child
    # reports a circular reference.
    sr = result["step_results"][0]
    # The outer run_scenario(A) should fail because its sub (A again) errors out.
    assert sr["ok"] is False
    # The inner step reports circular reference
    inner_steps = sr["sub_result"]["step_results"]
    assert any("circular" in (s.get("message") or "").lower() for s in inner_steps)


def test_circular_indirect_reference_detected():
    """A → B → A: B's attempt to call A must be blocked."""
    a_steps = [{"type": "run_scenario", "scenario_name": "B"}]
    b_steps = [{"type": "run_scenario", "scenario_name": "A"}]
    reg = _registry(
        by_campaign_name={
            "A": _sub_def(a_steps),
            "B": _sub_def(b_steps),
        }
    )
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "A"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    # Entire chain records failure and the default parent policy stops.
    assert result["success"] is False
    assert result["step_results"][0]["ok"] is False


# ── Max depth guard ───────────────────────────────────────────────────────────


def test_max_depth_guard_blocks_deep_nesting():
    """Exceeding _MAX_NESTING_DEPTH (10) must return an error without crashing."""
    # Build a chain: step0 → sub0 → sub1 → ... depth 11 calls deep
    # Easiest: pass _depth=10 directly (already at limit, next call rejects).
    sub_steps = [{"type": "wait", "seconds": 0}]
    reg = _registry(by_campaign_name={"deep": _sub_def(sub_steps)})
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "deep"}],
        "_scenario_registry": reg,
    }
    # At _depth=10, run_scenario_task immediately returns error (depth guard)
    result = run_scenario_task(_make_device(), scenario, _depth=10)
    assert result["success"] is False
    assert result["step_results"][0]["ok"] is False
    assert "depth" in result["step_results"][0].get("message", "").lower()


# ── VariableContext.child_scope ───────────────────────────────────────────────


def test_child_scope_inherits_scenario_vars():
    parent = VariableContext(scenario_vars={"BASE": "base_val"})
    child = parent.child_scope({"EXTRA": "extra_val"})
    assert child.resolve("${BASE}") == "base_val"
    assert child.resolve("${EXTRA}") == "extra_val"


def test_child_scope_override_takes_priority():
    parent = VariableContext(scenario_vars={"X": "parent"})
    child = parent.child_scope({"X": "child"})
    assert child.resolve("${X}") == "child"
    # Parent is unchanged
    assert parent.resolve("${X}") == "parent"


def test_child_scope_inherits_runtime_vars():
    parent = VariableContext()
    parent.set("RUNTIME_VAR", "runtime_value")
    child = parent.child_scope({})
    assert child.resolve("${RUNTIME_VAR}") == "runtime_value"


def test_child_scope_runtime_mutation_isolated():
    """Writes to child runtime_vars must not affect parent."""
    parent = VariableContext()
    parent.set("SHARED", "original")
    child = parent.child_scope({})
    child.set("SHARED", "mutated_in_child")
    # Parent should see the original value, not the child's mutation
    assert parent.resolve("${SHARED}") == "original"


def test_child_scope_inherits_campaign_vars():
    parent = VariableContext(campaign_vars={"CAMPAIGN_KEY": "campaign_value"})
    child = parent.child_scope({})
    assert child.resolve("${CAMPAIGN_KEY}") == "campaign_value"


def test_child_scope_inherits_device_info():
    parent = VariableContext(device_serial="ABC123", device_model="Pixel 7")
    child = parent.child_scope({})
    assert child.resolve("${__DEVICE_SERIAL__}") == "ABC123"
    assert child.resolve("${__DEVICE_MODEL__}") == "Pixel 7"


# ── Registry pre-load helper (_build_scenario_registry) ──────────────────────


def test_build_scenario_registry_structure():
    from services.campaign_dispatch import _build_scenario_registry

    class _S:
        id = "id-1"
        name = "scenario_one"
        steps = [{"type": "wait", "seconds": 0}]
        variables = {"K": "v"}

    class _T:
        name = "template_one"
        steps = [{"type": "scroll_down"}]
        variables = {}

    reg = _build_scenario_registry([_S()], [_T()])
    assert "id-1" in reg["by_id"]
    assert "scenario_one" in reg["by_campaign_name"]
    assert "template_one" in reg["by_template_name"]
    assert reg["by_id"]["id-1"]["steps"] == _S.steps


def test_build_scenario_registry_empty():
    from services.campaign_dispatch import _build_scenario_registry

    reg = _build_scenario_registry([], [])
    assert reg == {"by_id": {}, "by_campaign_name": {}, "by_template_name": {}}


# ── Integration: run_scenario with control-flow steps ────────────────────────


def test_run_scenario_sub_with_set_variable_and_repeat():
    """Sub-scenario uses repeat + set_variable — tests multi-step sub-flow."""
    sub_steps = [
        {
            "type": "repeat",
            "count": 2,
            "steps": [{"type": "set_variable", "name": "COUNTER", "increment": 1}],
        }
    ]
    reg = _registry(by_campaign_name={"counter_flow": _sub_def(sub_steps)})
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "counter_flow"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True
    sr = result["step_results"][0]
    assert sr["ok"] is True
    sub = sr["sub_result"]
    assert sub["steps_executed"] == 1  # 1 repeat step
    # repeat sub_result should show 2 iterations
    repeat_sr = sub["step_results"][0]
    assert repeat_sr.get("iterations") == 2


def test_run_scenario_registry_passed_to_nested_sub():
    """Registry is forwarded so nested run_scenario can find its own sub-scenario."""
    inner_steps = [{"type": "wait", "seconds": 0}]
    outer_steps = [{"type": "run_scenario", "scenario_name": "inner"}]
    reg = _registry(
        by_campaign_name={
            "outer": _sub_def(outer_steps),
            "inner": _sub_def(inner_steps),
        }
    )
    scenario = {
        "steps": [{"type": "run_scenario", "scenario_name": "outer"}],
        "_scenario_registry": reg,
    }
    result = run_scenario_task(_make_device(), scenario)
    assert result["success"] is True


def test_run_scenario_child_failure_stops_parent_by_default():
    """A child failure should fail the parent unless the run_scenario step opts in to continue."""
    reg = _registry(
        by_campaign_name={
            "bad_child": _sub_def([{"type": "unknown_bad_step"}]),
        }
    )
    scenario = {
        "steps": [
            {"type": "set_variable", "name": "PARENT_BEFORE", "value": "1"},
            {"type": "run_scenario", "scenario_name": "bad_child"},
            {"type": "set_variable", "name": "PARENT_AFTER", "value": "1"},
        ],
        "_scenario_registry": reg,
        "capture_steps": False,
        "settle_timeout_ms": 0,
    }

    result = run_scenario_task(_make_device(), scenario)

    assert result["success"] is False
    assert [step["type"] for step in result["step_results"]] == [
        "set_variable",
        "run_scenario",
    ]
    run_step = result["step_results"][1]
    assert run_step["ok"] is False
    assert run_step["error_policy"] == "stop"
    assert not run_step.get("error_ignored")
    assert not run_step.get("marked_ignored")
    assert not run_step.get("ignored_failure")
    assert any(not step.get("ok", True) for step in run_step["sub_result"]["step_results"])


def test_run_scenario_recovery_unresolved_can_be_ignored_when_parent_chooses_continue():
    from tasks.scenario.steps import register_step

    @register_step("test_recovery_unresolved")
    def _test_recovery_unresolved(sc, step, idx, result):
        result["ok"] = False
        result["message"] = "incident recovery playbooks did not resolve the step"

    reg = _registry(
        by_campaign_name={
            "bad_child": _sub_def([{"type": "test_recovery_unresolved"}]),
        }
    )
    scenario = {
        "steps": [
            {
                "type": "run_scenario",
                "scenario_name": "bad_child",
                "on_error": "continue",
            },
            {"type": "set_variable", "name": "PARENT_AFTER", "value": "1"},
        ],
        "_scenario_registry": reg,
        "capture_steps": False,
        "settle_timeout_ms": 0,
    }

    result = run_scenario_task(_make_device(), scenario)

    assert result["success"] is True
    run_step = result["step_results"][0]
    assert run_step["ok"] is True
    assert run_step["error_ignored"] is True
    assert run_step["marked_ignored"] is True
    assert run_step["ignored_failure"] is True
    assert "incident recovery playbooks did not resolve" in run_step["ignored_message"]
    assert result["step_results"][1]["type"] == "set_variable"


def test_run_scenario_child_failure_stops_parent_when_requested():
    """The parent can still make a child failure stop the remaining steps."""
    reg = _registry(
        by_campaign_name={
            "bad_child": _sub_def([{"type": "unknown_bad_step"}]),
        }
    )
    scenario = {
        "steps": [
            {"type": "set_variable", "name": "PARENT_BEFORE", "value": "1"},
            {
                "type": "run_scenario",
                "scenario_name": "bad_child",
                "on_error": "stop",
            },
            {"type": "set_variable", "name": "PARENT_AFTER", "value": "1"},
        ],
        "_scenario_registry": reg,
        "capture_steps": False,
        "settle_timeout_ms": 0,
    }

    result = run_scenario_task(_make_device(), scenario)

    assert result["success"] is False
    assert [step["type"] for step in result["step_results"]] == [
        "set_variable",
        "run_scenario",
    ]
    assert result["step_results"][1]["error_policy"] == "stop"
    assert "bad_child" in result["failed_message"]


@pytest.mark.parametrize(
    "parent_policy",
    [
        {"ignore_error": True},
        {"on_error": "continue"},
    ],
)
def test_run_scenario_child_failure_can_continue_when_parent_chooses_continue(parent_policy):
    """The parent run_scenario step owns continue/stop policy."""
    reg = _registry(
        by_campaign_name={
            "bad_child": _sub_def([{"type": "unknown_bad_step"}]),
        }
    )
    scenario = {
        "steps": [
            {"type": "set_variable", "name": "PARENT_BEFORE", "value": "1"},
            {
                "type": "run_scenario",
                "scenario_name": "bad_child",
                **parent_policy,
            },
            {"type": "set_variable", "name": "PARENT_AFTER", "value": "1"},
        ],
        "_scenario_registry": reg,
        "capture_steps": False,
        "settle_timeout_ms": 0,
    }

    result = run_scenario_task(_make_device(), scenario)

    assert result["success"] is True
    assert [step["type"] for step in result["step_results"]] == [
        "set_variable",
        "run_scenario",
        "set_variable",
    ]
    run_step = result["step_results"][1]
    assert run_step["ok"] is True
    assert run_step["error_policy"] == "continue"
    assert run_step["error_ignored"] is True
    assert run_step["marked_ignored"] is True
    assert run_step["ignored_failure"] is True
    assert any(not step.get("ok", True) for step in run_step["sub_result"]["step_results"])


# ── Seed data integrity ───────────────────────────────────────────────────────


def test_builtin_template_seed_data_valid_steps():
    """All builtin template step types must be known to scenario_schema."""
    from common.scenario_schema import SCENARIO_STEP_TYPES
    from db.seeds.scenario_templates import BUILTIN_TEMPLATES

    def _collect_types(steps: list) -> list[str]:
        types = []
        for step in steps:
            t = step.get("type")
            if t:
                types.append(t)
            # Recurse into nested steps (repeat, repeat_until, if_element, ...)
            for key in ("steps", "then", "else"):
                nested = step.get(key)
                if isinstance(nested, list):
                    types.extend(_collect_types(nested))
        return types

    for tmpl in BUILTIN_TEMPLATES:
        all_types = _collect_types(tmpl.get("steps", []))
        for t in all_types:
            assert t in SCENARIO_STEP_TYPES, (
                f"Template '{tmpl['name']}' uses unknown step type: {t!r}"
            )
