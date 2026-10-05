"""Step handler: run_scenario (sub-scenario execution)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.failure_details import attach_nested_failure_details
from services.execution.reason_codes import SUBSCENARIO_FAILED
from services.execution.trace_context import (
    TRACE_CONTEXT_KEY,
    push_step_path,
    trace_from_runtime_context,
)

log = logging.getLogger(__name__)


def _first_failed_message(result: Dict[str, Any]) -> str:
    failed_message = result.get("failed_message")
    if failed_message:
        return str(failed_message)
    for entry in result.get("step_results") or []:
        if isinstance(entry, dict) and not entry.get("ok", True):
            return str(entry.get("message") or "step failed")
    return ""


def _has_failed_step(result: Dict[str, Any]) -> bool:
    return any(
        isinstance(entry, dict) and not entry.get("ok", True)
        for entry in result.get("step_results") or []
    )


def _step_id(step: Dict[str, Any], idx: int) -> str:
    return str(step.get("id") or step.get("_id") or step.get("step_id") or idx)


def _first_failed_step(result: Dict[str, Any]) -> Dict[str, Any] | None:
    for entry in result.get("step_results") or []:
        if isinstance(entry, dict) and not entry.get("ok", True):
            return {
                key: value
                for key, value in entry.items()
                if key in {"index", "type", "step_id", "step_path", "message", "reason_code"}
                and value is not None
            }
    return None


@register_step("run_scenario")
def handle_run_scenario(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    scenario_id = str(step.get("scenario_id") or "").strip()
    scenario_name = str(step.get("scenario_name") or "").strip()
    scenario_ref = scenario_id or scenario_name

    if not scenario_ref:
        result["ok"] = False
        result["reason_code"] = SUBSCENARIO_FAILED
        result["message"] = "run_scenario: missing scenario_id or scenario_name"
        return

    if scenario_ref in sc.call_stack:
        result["ok"] = False
        result["reason_code"] = SUBSCENARIO_FAILED
        result["message"] = f"run_scenario: circular reference detected: {scenario_ref!r}"
        return

    registry = sc.scenario.get("_scenario_registry") or {}
    sub_def: Optional[Dict[str, Any]] = None

    if scenario_id:
        sub_def = (registry.get("by_id") or {}).get(scenario_id)
    if sub_def is None and scenario_name:
        sub_def = (registry.get("by_campaign_name") or {}).get(scenario_name)
    if sub_def is None and scenario_name:
        sub_def = (registry.get("by_template_name") or {}).get(scenario_name)

    if sub_def is None:
        result["ok"] = False
        result["reason_code"] = SUBSCENARIO_FAILED
        result["message"] = f"run_scenario: sub-scenario not found: {scenario_ref!r}"
        log.warning(f"[{sc.serial}] run_scenario: sub-scenario not found: {scenario_ref!r}")
        return

    override_vars: Dict[str, Any] = step.get("variables") or {}
    merged_vars = {**(sub_def.get("variables") or {}), **override_vars}
    scenario_updates = {
        "scenario_id": scenario_id or sub_def.get("id"),
        "scenario_name": (
            scenario_name
            or str(sub_def.get("name") or "").strip()
            or scenario_ref
        ),
        "scenario_ref_index": step.get("scenario_ref_index"),
        "scenario_sequence_index": step.get("scenario_sequence_index"),
        "repeat_index": step.get("repeat_index"),
        "repeat_count": step.get("repeat_count"),
    }

    sub_scenario: Dict[str, Any] = {
        "steps": sub_def.get("steps") or [],
        "variables": merged_vars,
        "_scenario_registry": registry,
    }
    # Lazy import to break circular import during startup.
    from tasks.scenario.executor import run_nested_scenario

    runtime_context = getattr(sc, "ctx", None)
    if not isinstance(runtime_context, dict):
        runtime_context = {}
    parent_trace = step.get("_scenario_parent_trace")
    parent_trace = dict(parent_trace) if isinstance(parent_trace, dict) else trace_from_runtime_context(runtime_context)
    base = dict(runtime_context)
    if parent_trace:
        base[TRACE_CONTEXT_KEY] = parent_trace
    else:
        base.pop(TRACE_CONTEXT_KEY, None)
    traced = push_step_path(
        base,
        step_id=_step_id(step, idx),
        step_type="run_scenario",
        step_index=idx,
        scenario_updates=scenario_updates,
    )
    runtime_context[TRACE_CONTEXT_KEY] = trace_from_runtime_context(traced)
    try:
        sub = run_nested_scenario(
            sc,
            sub_scenario.get("steps") or [],
            variables=merged_vars,
            call_stack_add=scenario_ref,
            extra_scenario_keys={
                "_scenario_registry": registry,
                **(
                    {"recovery_policy": sc.scenario["recovery_policy"]}
                    if "recovery_policy" in sc.scenario
                    else {}
                ),
            },
        )
    finally:
        if parent_trace:
            runtime_context[TRACE_CONTEXT_KEY] = parent_trace
        else:
            runtime_context.pop(TRACE_CONTEXT_KEY, None)
    result["sub_result"] = sub
    if not sub.get("success") or _has_failed_step(sub):
        result["ok"] = False
        result["reason_code"] = SUBSCENARIO_FAILED
        attach_nested_failure_details(result, sub)
        result["message"] = (
            f"run_scenario: sub-scenario {scenario_ref!r} failed — "
            f"{_first_failed_message(sub)}"
        )
    else:
        result["sub_steps_executed"] = sub.get("steps_executed", 0)
        result["message"] = f"run_scenario: {scenario_ref!r} completed ({sub.get('steps_executed', 0)} steps)"
