"""
temporal/workflows.py — Temporal workflows for scenario execution (DF-002).

Workflows are deterministic orchestrators — they MUST NOT perform I/O directly.
All device interaction happens through activities.

Architecture:
- ScenarioWorkflow: top-level entry point (one per device per campaign)
- ScenarioStepsWorkflow: recursive child workflow for nested step lists
  (repeat, if_element, if_variable, random_pick use child workflows)

Security:
- Max nesting depth enforced (10 levels)
- Max iterations capped for repeat_until (configurable, default 100)
- Input validation on all parameters
- No secrets in workflow state (passwords resolved before workflow starts)
"""

from __future__ import annotations

import asyncio
import re as _re
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

# Pre-compiled regex for variable resolution (deterministic, no I/O).
# Moved to module level to avoid re-compilation on every step.
_EXACT_VAR_RE = _re.compile(r"^\$\{(\w+)\}$")
_VAR_PATTERN = _re.compile(r"\$\{(\w+)\}")

with workflow.unsafe.imports_passed_through():
    from temporal.shared import (
        MAX_NESTING_DEPTH,
        TASK_QUEUE_NAME,
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



_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],  # Don't retry validation errors
)

def _lookup_var(name: str, *dicts: dict[str, Any]) -> Any:
    """Lookup a variable in multiple dicts by priority. Returns None if not found.

    Uses explicit `in` check instead of `or` chaining to correctly handle
    falsy values (0, False, empty string).
    """
    for d in dicts:
        if name in d:
            return d[name]
    return None


_SHORT_TIMEOUT = timedelta(seconds=30)
_LONG_TIMEOUT = timedelta(seconds=60)
_ELEMENT_CHECK_TIMEOUT = timedelta(seconds=15)


# ── ScenarioWorkflow ─────────────────────────────────────────────────────────


@workflow.defn
class ScenarioWorkflow:
    """
    Top-level workflow: executes a full scenario on one device.

    Features:
    - Pause/resume via signals
    - Cancel via signal or Temporal cancellation
    - Progress query for real-time monitoring
    - Delegates step execution to ScenarioStepsWorkflow
    """

    def __init__(self) -> None:
        self._progress = WorkflowProgress()
        self._paused = False
        self._cancelled = False

    @workflow.run
    async def run(self, inp: ScenarioInput) -> StepsResult:
        self._progress.device_serial = inp.device_serial
        self._progress.total_steps = len(inp.steps)
        self._progress.status = WorkflowStatus.RUNNING.value

        # Wait if paused before starting
        await self._wait_if_paused()

        if self._cancelled:
            self._progress.status = WorkflowStatus.CANCELLED.value
            return StepsResult(
                success=False, steps_executed=0,
                failed_message="Cancelled before start",
            )
        try:
            result = await workflow.execute_child_workflow(
                ScenarioStepsWorkflow.run,
                StepsInput(
                    device_serial=inp.device_serial,
                    steps=inp.steps,
                    variables=inp.variables,
                    campaign_vars=inp.campaign_vars,
                    scenario_registry=inp.scenario_registry,
                    depth=0,
                    parent_runtime_vars={},
                    scenario_config=inp.scenario_config,
                ),
                id=f"{workflow.info().workflow_id}:steps",
                task_queue=TASK_QUEUE_NAME,
                execution_timeout=timedelta(seconds=3600),
            )

            if self._cancelled:
                self._progress.status = WorkflowStatus.CANCELLED.value
                return StepsResult(
                    success=False, steps_executed=result.steps_executed,
                    failed_message="Cancelled during execution",
                )

            self._progress.status = (
                WorkflowStatus.COMPLETED.value if result.success
                else WorkflowStatus.FAILED.value
            )
            return result

        except asyncio.CancelledError:
            # Native Temporal cancel (handle.cancel()) — propagated from API
            self._progress.status = WorkflowStatus.CANCELLED.value
            return StepsResult(
                success=False, steps_executed=0,
                failed_message="Cancelled by Temporal",
            )
        except Exception as exc:
            self._progress.status = WorkflowStatus.FAILED.value
            return StepsResult(
                success=False, steps_executed=0,
                failed_message=f"Workflow error: {exc}",
            )

    @workflow.signal
    async def pause(self) -> None:
        """Signal to pause execution at the next step boundary."""
        self._paused = True
        self._progress.status = WorkflowStatus.PAUSED.value

    @workflow.signal
    async def resume(self) -> None:
        """Signal to resume paused execution."""
        self._paused = False
        self._progress.status = WorkflowStatus.RUNNING.value

    @workflow.signal
    async def cancel_scenario(self) -> None:
        """Signal to cancel the scenario gracefully."""
        self._cancelled = True
        self._progress.status = WorkflowStatus.CANCELLED.value

    @workflow.query
    def get_progress(self) -> WorkflowProgress:
        """Query current execution progress."""
        return self._progress

    async def _wait_if_paused(self) -> None:
        """Block until unpaused or cancelled."""
        await workflow.wait_condition(
            lambda: not self._paused or self._cancelled,
        )


@workflow.defn
class ScenarioStepsWorkflow:
    """
    Child workflow: executes a list of steps with control flow support.

    Used recursively for nested steps (repeat body, if branches, etc.).
    Each nesting level creates a new child workflow instance.
    """

    @workflow.run
    async def run(self, inp: StepsInput) -> StepsResult:
        if inp.depth > MAX_NESTING_DEPTH:
            return StepsResult(
                success=False, steps_executed=0,
                failed_message=f"Max nesting depth {MAX_NESTING_DEPTH} exceeded",
            )

        runtime_vars: dict[str, Any] = dict(inp.parent_runtime_vars)
        step_results: list[dict[str, Any]] = []
        steps_executed = 0

        for idx, raw_step in enumerate(inp.steps):
            # Resolve variables in step
            step = _resolve_step(raw_step, runtime_vars, inp.variables, inp.campaign_vars, idx)
            step_type = step.get("type", "")
            if step_type == "set_variable":
                result_dict = _handle_set_variable(
                    step, raw_step, runtime_vars, inp.variables, inp.campaign_vars, idx,
                )
                step_results.append(result_dict)
                steps_executed += 1
                continue

            if step_type == "repeat":
                ok, msg, sub_results = await self._handle_repeat(
                    inp, step, runtime_vars, idx,
                )
                step_results.append({
                    "index": idx, "type": "repeat", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                })
                steps_executed += 1
                if not ok:
                    return StepsResult(
                        success=False, steps_executed=steps_executed,
                        step_results=step_results,
                        runtime_vars=runtime_vars,
                        failed_message=msg,
                    )
                continue

            if step_type == "repeat_until":
                ok, msg = await self._handle_repeat_until(
                    inp, step, runtime_vars, idx,
                )
                step_results.append({
                    "index": idx, "type": "repeat_until", "ok": ok, "message": msg,
                })
                steps_executed += 1
                if not ok:
                    return StepsResult(
                        success=False, steps_executed=steps_executed,
                        step_results=step_results,
                        runtime_vars=runtime_vars,
                        failed_message=msg,
                    )
                continue

            if step_type == "if_element":
                ok, msg = await self._handle_if_element(
                    inp, step, runtime_vars, idx,
                )
                step_results.append({
                    "index": idx, "type": "if_element", "ok": ok, "message": msg,
                })
                steps_executed += 1
                if not ok:
                    return StepsResult(
                        success=False, steps_executed=steps_executed,
                        step_results=step_results,
                        runtime_vars=runtime_vars,
                        failed_message=msg,
                    )
                continue

            if step_type == "if_variable":
                ok, msg = await self._handle_if_variable(
                    inp, step, runtime_vars, idx,
                )
                step_results.append({
                    "index": idx, "type": "if_variable", "ok": ok, "message": msg,
                })
                steps_executed += 1
                if not ok:
                    return StepsResult(
                        success=False, steps_executed=steps_executed,
                        step_results=step_results,
                        runtime_vars=runtime_vars,
                        failed_message=msg,
                    )
                continue

            if step_type == "random_pick":
                ok, msg = await self._handle_random_pick(
                    inp, step, runtime_vars, idx,
                )
                step_results.append({
                    "index": idx, "type": "random_pick", "ok": ok, "message": msg,
                })
                steps_executed += 1
                if not ok:
                    return StepsResult(
                        success=False, steps_executed=steps_executed,
                        step_results=step_results,
                        runtime_vars=runtime_vars,
                        failed_message=msg,
                    )
                continue

            step_result: StepResult = await workflow.execute_activity(
                "execute_device_action",
                DeviceActionInput(
                    device_serial=inp.device_serial,
                    step=step,
                    step_index=idx,
                    variables=inp.variables,
                    campaign_vars=inp.campaign_vars,
                    scenario_config=getattr(inp, "scenario_config", {}),  # compat with pre-field workflows
                    scenario_registry=inp.scenario_registry,
                ),
                result_type=StepResult,
                start_to_close_timeout=_LONG_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
                heartbeat_timeout=timedelta(seconds=30),
            )

            step_results.append({
                "index": idx, "type": step_type,
                "ok": step_result.ok, "message": step_result.message or "",
                "details": step_result.details,
            })
            steps_executed += 1

            if not step_result.ok:
                return StepsResult(
                    success=False, steps_executed=steps_executed,
                    step_results=step_results,
                    runtime_vars=runtime_vars,
                    failed_message=step_result.message or "",
                )

        return StepsResult(
            success=True,
            steps_executed=steps_executed,
            step_results=step_results,
            runtime_vars=runtime_vars,
        )

    async def _handle_repeat(
        self, inp: StepsInput, step: dict, runtime_vars: dict, idx: int,
    ) -> tuple[bool, str, list]:
        """Handle repeat step: loop N times with optional delay."""
        count_raw = step.get("count")
        delay = float(step.get("delay_between", 0.0) or 0.0)
        sub_steps = step.get("steps") or []

        if count_raw is None:
            return False, "repeat: missing count", []
        if not sub_steps:
            return False, "repeat: no nested steps", []

        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            return False, f"repeat: invalid count={count_raw!r}", []

        # Safety cap
        count = min(count, 10_000)
        sub_results = []

        for i in range(count):
            runtime_vars["__LOOP_INDEX__"] = i

            child_result = await self._execute_child_steps(
                inp, sub_steps, runtime_vars,
                workflow_id_suffix=f"repeat:{idx}:iter:{i}",
            )
            sub_results.append({"iteration": i, "success": child_result.success})

            if not child_result.success:
                return (
                    False,
                    f"repeat: iteration {i} failed — {child_result.failed_message}",
                    sub_results,
                )

            # Merge runtime vars back only on success
            runtime_vars.update(child_result.runtime_vars)

            if delay > 0 and i < count - 1:
                # Durable sleep — survives worker restart
                await workflow.sleep(min(delay, 300.0))

        return True, f"repeat: {count} iteration(s) completed", sub_results

    async def _handle_repeat_until(
        self, inp: StepsInput, step: dict, runtime_vars: dict, idx: int,
    ) -> tuple[bool, str]:
        """Handle repeat_until: loop until condition met or max iterations."""
        condition = step.get("condition") or {}
        max_iter = max(1, min(int(step.get("max_iterations", 100) or 100), 10_000))
        sub_steps = step.get("steps") or []

        if not condition:
            return False, "repeat_until: missing condition"
        if not sub_steps:
            return False, "repeat_until: no nested steps"

        for i in range(max_iter):
            runtime_vars["__LOOP_INDEX__"] = i

            # Check condition via activity (reads device state)
            condition_met: bool = await workflow.execute_activity(
                "evaluate_condition",
                ConditionCheckInput(
                    device_serial=inp.device_serial,
                    condition=condition,
                    runtime_vars=runtime_vars,
                ),
                result_type=bool,
                start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

            if condition_met:
                return True, f"repeat_until: condition met after {i} iteration(s)"

            child_result = await self._execute_child_steps(
                inp, sub_steps, runtime_vars,
                workflow_id_suffix=f"repeat_until:{idx}:iter:{i}",
            )

            if not child_result.success:
                return (
                    False,
                    f"repeat_until: iteration {i} failed — {child_result.failed_message}",
                )

            # Merge runtime vars back only on success
            runtime_vars.update(child_result.runtime_vars)

        return False, f"repeat_until: max_iterations ({max_iter}) reached"

    async def _handle_if_element(
        self, inp: StepsInput, step: dict, runtime_vars: dict, idx: int,
    ) -> tuple[bool, str]:
        """Handle if_element: branch based on element existence."""
        by = str(step.get("by") or "")
        value = str(step.get("value") or "").strip()
        timeout = float(step.get("timeout", 3.0) or 3.0)
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not by or not value:
            return False, "if_element: missing by/value"

        # Check element via activity
        check_result: ElementCheckResult = await workflow.execute_activity(
            "check_element_exists",
            ElementCheckInput(
                device_serial=inp.device_serial,
                by=by, value=value, timeout=timeout,
            ),
            result_type=ElementCheckResult,
            start_to_close_timeout=timedelta(seconds=timeout + 10),
            retry_policy=_ACTIVITY_RETRY,
        )

        branch_steps = then_steps if check_result.found else else_steps
        branch_name = "then" if check_result.found else "else"

        if not branch_steps:
            return True, f"if_element(found={check_result.found}): no {branch_name} steps, skip"

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars,
            workflow_id_suffix=f"if_element:{idx}:{branch_name}",
        )
        runtime_vars.update(child_result.runtime_vars)

        if not child_result.success:
            return False, f"if_element: {branch_name} branch failed — {child_result.failed_message}"

        return True, f"if_element(found={check_result.found}): executed {branch_name}"

    async def _handle_if_variable(
        self, inp: StepsInput, step: dict, runtime_vars: dict, idx: int,
    ) -> tuple[bool, str]:
        """Handle if_variable: branch based on variable value."""
        name = str(step.get("name") or "")
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not name:
            return False, "if_variable: missing name"

        # Resolve variable with explicit key check (not `or` chaining)
        # to avoid skipping falsy values like 0, False, ""
        raw_val = _lookup_var(name, runtime_vars, inp.variables, inp.campaign_vars)
        str_val = str(raw_val) if raw_val is not None else ""

        condition_met = False
        if "equals" in step:
            condition_met = str_val == str(step["equals"])
        elif "not_equals" in step:
            condition_met = str_val != str(step["not_equals"])
        elif "contains" in step:
            condition_met = str(step["contains"]) in str_val
        elif "greater_than" in step:
            try:
                condition_met = float(raw_val) > float(step["greater_than"])
            except (TypeError, ValueError):
                condition_met = False
        else:
            # Truthy check
            condition_met = bool(raw_val) and str_val not in ("None", "", "0")

        branch_steps = then_steps if condition_met else else_steps
        branch_name = "then" if condition_met else "else"

        if not branch_steps:
            return True, f"if_variable({name}={str_val!r}): no {branch_name} steps, skip"

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars,
            workflow_id_suffix=f"if_variable:{idx}:{branch_name}",
        )
        runtime_vars.update(child_result.runtime_vars)

        if not child_result.success:
            return False, f"if_variable: {branch_name} branch failed"

        return True, f"if_variable({name}={str_val!r}): executed {branch_name}"

    async def _handle_random_pick(
        self, inp: StepsInput, step: dict, runtime_vars: dict, idx: int,
    ) -> tuple[bool, str]:
        """Handle random_pick: weighted random branch selection."""
        branches = step.get("branches") or []
        if not branches:
            return False, "random_pick: no branches"

        weights = [max(1, int(b.get("weight", 1))) for b in branches]
        # Use workflow.random() for deterministic replay on worker restart
        wf_random = _get_wf_random()
        chosen_idx = wf_random.choices(range(len(branches)), weights=weights, k=1)[0]
        chosen = branches[chosen_idx]
        branch_steps = chosen.get("steps") or []

        if not branch_steps:
            return True, f"random_pick: branch {chosen_idx} has no steps, skip"

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars,
            workflow_id_suffix=f"random_pick:{idx}:branch:{chosen_idx}",
        )
        runtime_vars.update(child_result.runtime_vars)

        if not child_result.success:
            return False, f"random_pick: branch {chosen_idx} failed"

        return True, f"random_pick: executed branch {chosen_idx}"

    # ── Inline step execution (no child workflow spawn) ──────────────────

    async def _execute_child_steps(
        self,
        parent_inp: StepsInput,
        steps: list[dict],
        runtime_vars: dict,
        workflow_id_suffix: str = "",  # kept for API compat, unused
    ) -> StepsResult:
        """Execute a list of steps inline (same workflow, no child spawn).

        Previously this spawned a child workflow per iteration which caused
        N×repeat_count workflows to appear in Temporal UI and wasted resources.
        Now control-flow steps (repeat, if_element, etc.) run in-process.
        Child workflows are only used for truly independent top-level executions
        (one per device per scenario, from ScenarioWorkflow.run).
        """
        if parent_inp.depth > MAX_NESTING_DEPTH:
            return StepsResult(
                success=False, steps_executed=0,
                failed_message=f"Max nesting depth {MAX_NESTING_DEPTH} exceeded",
            )

        nested_inp = StepsInput(
            device_serial=parent_inp.device_serial,
            steps=steps,
            variables=parent_inp.variables,
            campaign_vars=parent_inp.campaign_vars,
            scenario_registry=parent_inp.scenario_registry,
            depth=parent_inp.depth + 1,
            parent_runtime_vars=dict(runtime_vars),
            scenario_config=parent_inp.scenario_config if hasattr(parent_inp, "scenario_config") else {},
        )
        return await self.run(nested_inp)


# ── Variable resolution (deterministic, no I/O) ─────────────────────────────


def _get_wf_random():
    """Get workflow-safe random instance. Falls back to stdlib for testing."""
    try:
        return workflow.random()
    except Exception:
        import random
        return random


def _resolve_step(
    raw_step: dict[str, Any],
    runtime_vars: dict[str, Any],
    scenario_vars: dict[str, Any],
    campaign_vars: dict[str, Any],
    step_index: int,
) -> dict[str, Any]:
    """Resolve ${VAR} references in a step dict. Deterministic — no I/O.

    Uses workflow.random() for list-value selection to maintain Temporal
    replay determinism (Python's random module is not seeded by Temporal).
    """
    wf_random = _get_wf_random()

    def _lookup(name: str) -> Any:
        if name in runtime_vars:
            return runtime_vars[name]
        if name in scenario_vars:
            return scenario_vars[name]
        if name in campaign_vars:
            return campaign_vars[name]
        if name == "__STEP_INDEX__":
            return step_index
        return None

    def _resolve_value(val: Any) -> Any:
        if isinstance(val, str):
            m = _EXACT_VAR_RE.match(val)
            if m:
                result = _lookup(m.group(1))
                return result if result is not None else val
            def _replacer(match: _re.Match) -> str:
                result = _lookup(match.group(1))
                if result is None:
                    return match.group(0)
                if isinstance(result, list):
                    return str(wf_random.choice(result))
                return str(result)
            return _VAR_PATTERN.sub(_replacer, val)
        if isinstance(val, dict):
            return {k: _resolve_value(v) for k, v in val.items()}
        if isinstance(val, list):
            return [_resolve_value(item) for item in val]
        return val

    return _resolve_value(raw_step)


def _handle_set_variable(
    step: dict, raw_step: dict,
    runtime_vars: dict, _scenario_vars: dict, _campaign_vars: dict,
    idx: int,
) -> dict[str, Any]:
    """Handle set_variable step in workflow (no activity needed)."""
    name = str(step.get("name") or "")
    if not name:
        return {"index": idx, "type": "set_variable", "ok": False,
                "message": "set_variable: missing name"}

    if "from_list" in raw_step:
        vals = raw_step["from_list"]
        if not isinstance(vals, list) or not vals:
            return {"index": idx, "type": "set_variable", "ok": False,
                    "message": "set_variable: from_list must be non-empty list"}
        chosen = _get_wf_random().choice(vals)
        runtime_vars[name] = chosen
        return {"index": idx, "type": "set_variable", "ok": True,
                "message": f"set_variable: {name} = {chosen!r} (from_list)"}

    if "increment" in step:
        try:
            inc = int(step["increment"])
        except (TypeError, ValueError):
            inc = 1
        current = runtime_vars.get(name, 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        new_val = current + inc
        runtime_vars[name] = new_val
        return {"index": idx, "type": "set_variable", "ok": True,
                "message": f"set_variable: {name} += {inc} → {new_val}"}

    value = step.get("value")
    runtime_vars[name] = value
    return {"index": idx, "type": "set_variable", "ok": True,
            "message": f"set_variable: {name} = {value!r}"}
