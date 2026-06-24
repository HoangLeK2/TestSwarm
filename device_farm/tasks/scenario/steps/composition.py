"""Step handler: run_scenario (sub-scenario execution)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext

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


@register_step("run_scenario")
def handle_run_scenario(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    scenario_id = str(step.get("scenario_id") or "").strip()
    scenario_name = str(step.get("scenario_name") or "").strip()
    scenario_ref = scenario_id or scenario_name

    if not scenario_ref:
        result["ok"] = False
        result["message"] = "run_scenario: missing scenario_id or scenario_name"
        return

    if scenario_ref in sc.call_stack:
        result["ok"] = False
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
        result["message"] = f"run_scenario: sub-scenario not found: {scenario_ref!r}"
        log.warning(f"[{sc.serial}] run_scenario: sub-scenario not found: {scenario_ref!r}")
        return

    override_vars: Dict[str, Any] = step.get("variables") or {}
    merged_vars = {**(sub_def.get("variables") or {}), **override_vars}

    sub_scenario: Dict[str, Any] = {
        "steps": sub_def.get("steps") or [],
        "variables": merged_vars,
        "_scenario_registry": registry,
    }
    # Lazy import to break circular import during startup.
    from tasks.scenario.executor import run_nested_scenario

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
    result["sub_result"] = sub
    if not sub.get("success") or _has_failed_step(sub):
        result["ok"] = False
        result["message"] = (
            f"run_scenario: sub-scenario {scenario_ref!r} failed — "
            f"{_first_failed_message(sub)}"
        )
    else:
        result["message"] = f"run_scenario: {scenario_ref!r} completed ({sub.get('steps_executed', 0)} steps)"
