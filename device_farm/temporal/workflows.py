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
import logging
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
    try:
        import web.metrics  # noqa: F401 — preload before workflow retry loop
    except Exception:
        pass
    from services.execution.retry_policy import (
        compute_wait_ms,
        emit_retry_metrics,
        is_step_failure_retryable,
        parse_step_retry_policy,
        record_attempt,
        step_for_single_attempt,
    )
    from temporal.shared import (
        MAX_NESTING_DEPTH,
        TASK_QUEUE_NAME,
        ConditionCheckInput,
        DeviceActionBatchInput,
        DeviceActionBatchResult,
        DeviceActionInput,
        ElementCheckInput,
        ElementCheckResult,
        ExtractInput,
        ExtractResult,
        LegacyConditionCheckInput,
        SaveExtractionInput,
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

_DEVICE_ACTION_RETRY = RetryPolicy(
    maximum_attempts=1,
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


_LONG_TIMEOUT = timedelta(seconds=120)
_ELEMENT_CHECK_TIMEOUT = timedelta(seconds=15)

# Step types that require individual activity calls (cannot be batched).
# All other step types are "leaf" steps dispatched via execute_device_action_batch.
_CONTROL_FLOW_TYPES = frozenset({
    "set_variable", "set_var", "break_if",
    "loop", "if", "repeat", "repeat_until",
    "if_element", "if_variable", "random_pick",
    "run_scenario",
    "extract", "save_extraction",
})


def _error_policy(step: dict, cfg: dict) -> str:
    """Return error handling policy: 'pause' | 'continue' | 'stop'.

    Priority: step-level on_error → step-level ignore_error → scenario-level on_error
    → scenario-level continue_on_error → default 'stop'.

    Usage in scenario JSON:
        Step-level:     {"type": "tap", ..., "on_error": "pause"}
        Scenario-level: {"continue_on_error": true, "steps": [...]}
        Pause all:      {"on_error": "pause", "steps": [...]}
    """
    step_policy = step.get("on_error", "")
    if step_policy in ("pause", "continue", "stop"):
        return step_policy
    if step.get("ignore_error"):
        return "continue"
    cfg_policy = cfg.get("on_error", "")
    if cfg_policy in ("pause", "continue", "stop"):
        return cfg_policy
    if cfg.get("continue_on_error"):
        return "continue"
    return "stop"


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
        result: StepsResult | None = None
        try:
            # Merge capture_steps from ScenarioInput into scenario_config so activities
            # can access it via inp.scenario_config["capture_steps"].
            merged_config = dict(inp.scenario_config or {})
            if inp.capture_steps:
                merged_config["capture_steps"] = True
            elif inp.execution_id or inp.run_id:
                merged_config.setdefault("capture_steps", True)
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
                    scenario_config=merged_config,
                    campaign_id=inp.campaign_id,
                    run_id=inp.run_id,
                    execution_id=inp.execution_id,
                    start_step=int(getattr(inp, "start_step", 0) or 0),
                ),
                id=f"{workflow.info().workflow_id}:steps",
                task_queue=TASK_QUEUE_NAME,
            )

            if self._cancelled:
                self._progress.status = WorkflowStatus.CANCELLED.value
                await self._finalize(
                    inp.campaign_id, inp.run_id, success=False,
                    execution_id=inp.execution_id, device_serial=inp.device_serial,
                    failed_message="Cancelled during execution",
                )
                return StepsResult(
                    success=False, steps_executed=result.steps_executed,
                    failed_message="Cancelled during execution",
                )

            self._progress.status = (
                WorkflowStatus.COMPLETED.value if result.success
                else WorkflowStatus.FAILED.value
            )
            await self._finalize(
                inp.campaign_id, inp.run_id, success=result.success,
                execution_id=inp.execution_id, device_serial=inp.device_serial,
                step_results=result.step_results,
                failed_message=None if result.success else result.failed_message,
            )
            return result

        except asyncio.CancelledError:
            # Native Temporal cancel (handle.cancel()) — propagated from API
            self._progress.status = WorkflowStatus.CANCELLED.value
            # Best-effort finalize — may fail if Temporal rejects activities after cancel
            try:
                await self._finalize(
                    inp.campaign_id, inp.run_id, success=False,
                    execution_id=inp.execution_id, device_serial=inp.device_serial,
                    failed_message="Cancelled by Temporal",
                )
            except Exception:
                pass
            return StepsResult(
                success=False,
                steps_executed=result.steps_executed if result else 0,
                failed_message="Cancelled by Temporal",
            )
        except Exception as exc:
            self._progress.status = WorkflowStatus.FAILED.value
            await self._finalize(
                inp.campaign_id, inp.run_id, success=False,
                execution_id=inp.execution_id, device_serial=inp.device_serial,
                failed_message=f"Workflow error: {exc}",
            )
            return StepsResult(
                success=False,
                steps_executed=result.steps_executed if result else 0,
                failed_message=f"Workflow error: {exc}",
            )

    async def _forward_signal(self, signal_name: str) -> None:
        child_id = f"{workflow.info().workflow_id}:steps"
        try:
            await workflow.get_external_workflow_handle(child_id).signal(signal_name)
        except Exception:
            pass

    @workflow.signal
    async def pause(self) -> None:
        """Pause at the next step boundary (child workflow polls between steps)."""
        self._paused = True
        self._progress.status = WorkflowStatus.PAUSED.value
        await self._forward_signal("pause")

    @workflow.signal
    async def resume(self) -> None:
        """Resume paused execution."""
        self._paused = False
        self._progress.status = WorkflowStatus.RUNNING.value
        await self._forward_signal("resume")

    @workflow.signal
    async def cancel_scenario(self) -> None:
        """Cancel gracefully: finish current atomic step, then stop."""
        self._cancelled = True
        self._progress.status = WorkflowStatus.CANCELLED.value
        await self._forward_signal("cancel_scenario")

    @workflow.signal
    async def retry_step(self) -> None:
        """Forward retry_step to the child ScenarioStepsWorkflow."""
        child_id = f"{workflow.info().workflow_id}:steps"
        try:
            await workflow.get_external_workflow_handle(child_id).signal("retry_step")
        except Exception:
            pass

    @workflow.signal
    async def skip_step(self) -> None:
        """Forward skip_step to the child ScenarioStepsWorkflow."""
        child_id = f"{workflow.info().workflow_id}:steps"
        try:
            await workflow.get_external_workflow_handle(child_id).signal("skip_step")
        except Exception:
            pass

    @workflow.query
    def get_progress(self) -> WorkflowProgress:
        """Query current execution progress."""
        return self._progress

    async def _wait_if_paused(self) -> None:
        """Block until unpaused or cancelled."""
        await workflow.wait_condition(
            lambda: not self._paused or self._cancelled,
        )

    async def _finalize(
        self,
        campaign_id: str,
        run_id: str | None,
        *,
        success: bool,
        execution_id: str | None = None,
        device_serial: str | None = None,
        step_results: list | None = None,
        failed_message: str | None = None,
    ) -> None:
        """Call finalize_campaign activity to update DB status when this workflow ends."""
        if not campaign_id:
            return
        payload: dict[str, Any] = {
            "campaign_id": campaign_id,
            "run_id": run_id,
            "success": success,
            "execution_id": execution_id,
            "device_serial": device_serial,
            "step_results": step_results or [],
        }
        if failed_message:
            payload["failed_message"] = failed_message
        await workflow.execute_activity(
            "finalize_campaign",
            payload,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn
class ScenarioStepsWorkflow:
    """
    Child workflow: executes a list of steps with control flow support.

    Used recursively for nested steps (repeat body, if branches, etc.).
    Each nesting level creates a new child workflow instance.
    """

    def __init__(self) -> None:
        self._step_log: list[dict] = []
        self._paused = False
        self._cancelled = False
        self._paused_on_error = False
        self._error_action = ""   # "retry" | "skip"
        self._error_message = ""  # last error message while paused_on_error

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def cancel_scenario(self) -> None:
        self._cancelled = True
        self._paused = False

    @workflow.signal
    async def retry_step(self) -> None:
        """Resume from a paused_on_error state by re-executing the failed step."""
        self._error_action = "retry"
        self._paused_on_error = False

    @workflow.signal
    async def skip_step(self) -> None:
        """Resume from a paused_on_error state by skipping the failed step."""
        self._error_action = "skip"
        self._paused_on_error = False

    @workflow.query
    def get_error_info(self) -> dict:
        return {
            "paused_on_error": self._paused_on_error,
            "error_action": self._error_action,
            "error_message": self._error_message,
        }

    async def _wait_if_paused(self) -> None:
        if self._paused and not self._cancelled:
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)

    @staticmethod
    def _step_result_dict(sr: StepResult, step_index: int) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "index": step_index,
            "type": sr.step_type,
            "ok": sr.ok,
            "message": sr.message or "",
        }
        if sr.details:
            for key, val in sr.details.items():
                if key not in entry:
                    entry[key] = val
        return entry

    @staticmethod
    def _retry_check_payload(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": entry.get("ok", True),
            "reason_code": entry.get("reason_code"),
            "retryable": entry.get("retryable"),
        }

    async def _execute_leaf_with_durable_retry(
        self,
        inp: StepsInput,
        step: dict[str, Any],
        step_index: int,
    ) -> dict[str, Any]:
        """Run one leaf step with DF-T-04-011 retry at workflow level (durable backoff)."""
        policy = parse_step_retry_policy(step)
        if policy is None:
            raise ValueError("_execute_leaf_with_durable_retry requires an explicit retry block")

        step_type = str(step.get("type") or "")
        activity_step = step_for_single_attempt(step)
        attempt_records: list[dict[str, Any]] = []
        wf_random = _get_wf_random()
        final_entry: dict[str, Any] | None = None

        for attempt in range(1, policy.max_attempts + 1):
            await self._wait_if_paused()
            if self._cancelled:
                return {
                    "index": step_index,
                    "type": step_type,
                    "ok": False,
                    "message": "Cancelled during execution",
                    "retry_attempts": attempt_records,
                }

            sr: StepResult = await workflow.execute_activity(
                "execute_device_action",
                DeviceActionInput(
                    device_serial=inp.device_serial,
                    step=activity_step,
                    step_index=step_index,
                    variables=inp.variables,
                    campaign_vars=inp.campaign_vars,
                    scenario_config=getattr(inp, "scenario_config", {}),
                    scenario_registry=inp.scenario_registry,
                    execution_id=inp.execution_id or inp.run_id,
                    campaign_id=inp.campaign_id,
                ),
                result_type=StepResult,
                start_to_close_timeout=_LONG_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
                heartbeat_timeout=timedelta(seconds=30),
            )
            entry = self._step_result_dict(sr, step_index)
            final_entry = entry

            will_retry = (
                is_step_failure_retryable(self._retry_check_payload(entry), policy)
                and attempt < policy.max_attempts
            )
            if not will_retry:
                record_attempt(
                    attempt_records,
                    attempt=attempt,
                    error_reason=str(entry.get("reason_code") or "") if not entry.get("ok", True) else None,
                    wait_ms_before_next=None,
                )
                break

            wait = compute_wait_ms(attempt, policy, rng=wf_random)
            emit_retry_metrics(
                step_type=step_type or "unknown",
                reason_code=entry.get("reason_code"),
                backoff_capped=wait.backoff_capped,
            )
            record_attempt(
                attempt_records,
                attempt=attempt,
                error_reason=str(entry.get("reason_code") or ""),
                wait_ms_before_next=wait.wait_ms,
            )
            await workflow.sleep(timedelta(milliseconds=wait.wait_ms))

        assert final_entry is not None
        if attempt_records:
            final_entry["retry_attempts"] = attempt_records
        return final_entry

    def _cancelled_result(
        self,
        inp: "StepsInput",
        steps_executed: int,
        step_results: list,
        runtime_vars: dict,
        runtime_context: dict,
    ) -> StepsResult:
        return StepsResult(
            success=False,
            steps_executed=steps_executed,
            step_results=step_results,
            runtime_vars=runtime_vars,
            context=runtime_context,
            failed_message="Cancelled during execution",
        )

    async def _apply_error_policy(
        self,
        step: dict,
        step_idx: int,
        msg: str,
        inp: "StepsInput",
        runtime_vars: dict,
        runtime_context: dict,
        steps_executed: int,
        step_results: list,
    ) -> tuple[str, "StepsResult | None"]:
        """Apply error policy for a failed step.

        Returns ('continue', None) — skip step and proceed
             or ('stop', StepsResult) — stop workflow with failure result.

        When policy == 'pause': workflow pauses with status PAUSED_ON_ERROR and
        waits for retry_step or skip_step signal.
          - retry_step: trigger continue_as_new from step_idx (never returns)
          - skip_step: return ('continue', None)
        """
        policy = _error_policy(step, inp.scenario_config or {})
        # Only top-level workflows can pause-on-error; nested child workflows (depth > 0)
        # fall through to "stop" so the parent loop handles the error instead.
        if inp.depth > 0 and policy == "pause":
            policy = "stop"
        if policy == "continue":
            return "continue", None
        if policy == "pause":
            self._error_message = msg
            self._paused_on_error = True
            self._error_action = ""
            await workflow.wait_condition(lambda: not self._paused_on_error)
            self._error_message = ""
            if self._error_action == "retry":
                # Restart from the failed step — continue_as_new resets history
                # while preserving all runtime state. The parent ScenarioWorkflow
                # transparently follows the continuation.
                await workflow.continue_as_new(
                    StepsInput(
                        device_serial=inp.device_serial,
                        steps=inp.steps[step_idx:],
                        variables=inp.variables,
                        campaign_vars=inp.campaign_vars,
                        scenario_registry=inp.scenario_registry,
                        depth=inp.depth,
                        parent_runtime_vars=dict(runtime_vars),
                        scenario_config=inp.scenario_config,
                        context=dict(runtime_context),
                        campaign_id=inp.campaign_id,
                        run_id=inp.run_id,
                        execution_id=inp.execution_id,
                        accumulated_results=list(step_results),
                    ),
                )
            # skip_step or unrecognised action → skip failed step
            return "continue", None
        return "stop", StepsResult(
            success=False,
            steps_executed=steps_executed,
            step_results=step_results,
            runtime_vars=runtime_vars,
            failed_message=msg,
            context=runtime_context,
        )

    @workflow.query
    def get_step_log(self) -> list[dict]:
        """Query accumulated step execution log (works while running or after completion)."""
        return self._step_log

    # Trigger continue_as_new when Temporal history approaches the 50K event limit.
    # Each activity execution = ~3 events (Scheduled + Started + Completed).
    # At 10K events we have ~3.3K activity calls burned — reset early so we never
    # hit the hard limit mid-step.  Only checked at depth=0 (top-level step loop).
    _HISTORY_CONTINUE_THRESHOLD = 10_000

    @workflow.run
    async def run(self, inp: StepsInput) -> StepsResult:
        if inp.depth > MAX_NESTING_DEPTH:
            return StepsResult(
                success=False, steps_executed=0,
                failed_message=f"Max nesting depth {MAX_NESTING_DEPTH} exceeded",
            )

        runtime_vars: dict[str, Any] = dict(inp.parent_runtime_vars)
        # Shared execution context: posts, text_nodes, _no_new_streak, vars (legacy ctx)
        runtime_context: dict[str, Any] = dict(inp.context)
        # Seed from accumulated_results so retry/history-reset continue_as_new calls
        # preserve the results of already-completed steps.
        step_results: list[dict[str, Any]] = list(inp.accumulated_results)
        steps_executed = len(step_results)
        break_requested = False

        def _append(entry: dict) -> None:
            step_results.append(entry)
            self._step_log.append({**entry, "depth": inp.depth})

        def _with_persist_metrics(message: str | None, details: dict[str, Any] | None) -> str:
            """Make persistence counters visible even when UI ignores details."""
            base = str(message or "")
            if not isinstance(details, dict):
                return base

            # extract step: details.auto_save = {saved, duplicate, errors}
            auto = details.get("auto_save")
            if isinstance(auto, dict):
                saved = int(auto.get("saved", 0) or 0)
                dup = int(auto.get("duplicate", 0) or 0)
                err = int(auto.get("errors", 0) or 0)
                marker = f"auto-save: saved={saved}, dup={dup}, err={err}"
                if marker not in base:
                    base = f"{base} | {marker}" if base else marker

            # save_extraction step: details has saved_count/duplicate_count/error_count
            if (
                "saved_count" in details
                or "duplicate_count" in details
                or "error_count" in details
            ):
                saved = int(details.get("saved_count", 0) or 0)
                dup = int(details.get("duplicate_count", 0) or 0)
                err = int(details.get("error_count", 0) or 0)
                marker = f"saved={saved}, duplicate={dup}, errors={err}"
                if marker not in base:
                    base = f"{base} | {marker}" if base else marker

            return base

        # ── Batch accumulator for leaf steps ────────────────────────────────
        # Consecutive non-control-flow steps are grouped into one activity call
        # (3 Temporal history events per batch vs 3N for individual calls).
        # batch_size is configurable via scenario_config; default 10.
        _batch_size = max(1, int((inp.scenario_config or {}).get("batch_size", 10)))
        _pending_steps: list[dict] = []
        _pending_indices: list[int] = []

        async def _flush_batch() -> tuple[bool, str, int]:
            """Dispatch accumulated leaf steps as one batch activity.

            Returns (ok, err_msg, failed_orig_idx) where failed_orig_idx is the
            original index in inp.steps of the first failed step (-1 if all ok).
            """
            nonlocal steps_executed
            if not _pending_steps:
                return True, "", -1
            n = len(_pending_steps)
            batch_result: DeviceActionBatchResult = await workflow.execute_activity(
                "execute_device_action_batch",
                DeviceActionBatchInput(
                    device_serial=inp.device_serial,
                    steps=list(_pending_steps),
                    step_indices=list(_pending_indices),
                    variables=inp.variables,
                    campaign_vars=inp.campaign_vars,
                    scenario_config=getattr(inp, "scenario_config", {}),
                    scenario_registry=inp.scenario_registry,
                    execution_id=inp.execution_id,
                    campaign_id=inp.campaign_id,
                ),
                result_type=DeviceActionBatchResult,
                # 120 s per step, cap at 10 min
                start_to_close_timeout=timedelta(seconds=min(120 * n, 600)),
                retry_policy=_DEVICE_ACTION_RETRY,
                # Extract/comment steps can run minutes; keep margin over 5s heartbeat loop.
                heartbeat_timeout=timedelta(seconds=60),
            )
            orig_indices = list(_pending_indices)  # snapshot before clear
            _pending_steps.clear()
            _pending_indices.clear()
            for r in batch_result.results:
                _append(r)
                steps_executed += 1
            if batch_result.paused_mid_batch:
                await self._wait_if_paused()
                if self._cancelled:
                    return False, "Cancelled during execution", -1
                return True, "", -1
            if batch_result.cancelled_mid_batch or self._cancelled:
                return False, "Cancelled during execution", -1
            if batch_result.first_failure_index >= 0:
                failed = batch_result.results[batch_result.first_failure_index]
                failed_orig_idx = orig_indices[batch_result.first_failure_index]
                return False, failed.get("message", "batch step failed"), failed_orig_idx
            return True, "", -1

        start_step = max(0, int(getattr(inp, "start_step", 0) or 0))

        for idx, raw_step in enumerate(inp.steps):
            if idx < start_step:
                continue
            # ── continue_as_new guard (top-level loop only) ──────────────────
            # Checked every 25 steps to amortise the workflow.info() call cost.
            # continue_as_new resets event history while preserving full state:
            # remaining steps, runtime_vars, context, and all scenario metadata.
            # The parent ScenarioWorkflow transparently follows the continuation.
            if inp.depth == 0 and idx > 0 and idx % 25 == 0:
                history_len = workflow.info().get_current_history_length()
                if history_len >= self._HISTORY_CONTINUE_THRESHOLD:
                    await workflow.continue_as_new(
                        StepsInput(
                            device_serial=inp.device_serial,
                            steps=inp.steps[idx:],       # remaining steps only
                            variables=inp.variables,
                            campaign_vars=inp.campaign_vars,
                            scenario_registry=inp.scenario_registry,
                            depth=0,
                            parent_runtime_vars=runtime_vars,
                            scenario_config=inp.scenario_config,
                            context=runtime_context,
                            campaign_id=inp.campaign_id,
                            run_id=inp.run_id,
                            execution_id=inp.execution_id,
                            accumulated_results=list(step_results),
                        ),
                    )
            await self._wait_if_paused()
            if self._cancelled:
                return self._cancelled_result(
                    inp, steps_executed, step_results, runtime_vars, runtime_context,
                )
            # Resolve variables in step
            step = _resolve_step(raw_step, runtime_vars, inp.variables, inp.campaign_vars, idx)
            step_type = step.get("type", "")

            # ── Flush pending batch before any control-flow step ─────────────
            # Leaf steps accumulate in _pending_steps; control-flow types force
            # a flush so results are appended in execution order.
            if step_type in _CONTROL_FLOW_TYPES:
                ok, msg, failed_idx = await _flush_batch()
                if not ok:
                    failed_step = inp.steps[failed_idx] if 0 <= failed_idx < len(inp.steps) else {}
                    action, early = await self._apply_error_policy(
                        failed_step, failed_idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early

            # ── set_variable (no activity needed) ────────────────────────────
            if step_type == "set_variable":
                result_dict = _handle_set_variable(
                    step, raw_step, runtime_vars, inp.variables, inp.campaign_vars, idx,
                )
                _append(result_dict)
                steps_executed += 1
                continue

            # ── set_var — writes to legacy ctx["vars"] ────────────────────────
            if step_type == "set_var":
                key = str(step.get("key") or step.get("name") or "")
                if not key:
                    _append({
                        "index": idx, "type": "set_var", "ok": False,
                        "message": "set_var: missing key/name",
                    })
                else:
                    value = step.get("value")
                    runtime_context.setdefault("vars", {})[key] = value
                    _append({
                        "index": idx, "type": "set_var", "ok": True,
                        "message": f"set_var: vars[{key!r}] = {value!r}",
                    })
                steps_executed += 1
                continue

            # ── break_if — sets break_requested so enclosing loop exits ──────
            if step_type == "break_if":
                condition = step.get("condition") or {}
                if not condition:
                    _append({
                        "index": idx, "type": "break_if", "ok": False,
                        "message": "break_if: missing condition",
                    })
                else:
                    cond_met: bool = await workflow.execute_activity(
                        "evaluate_legacy_condition",
                        LegacyConditionCheckInput(
                            device_serial=inp.device_serial,
                            condition=condition,
                            runtime_vars=runtime_vars,
                            context=runtime_context,
                            execution_id=inp.execution_id or inp.run_id,
                        ),
                        result_type=bool,
                        start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                        heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                        retry_policy=_ACTIVITY_RETRY,
                    )
                    if cond_met:
                        break_requested = True
                    _append({
                        "index": idx, "type": "break_if", "ok": True,
                        "message": f"break_if: condition={'met — breaking' if cond_met else 'not met'}",
                    })
                steps_executed += 1
                if break_requested:
                    break
                continue

            # ── loop ─────────────────────────────────────────────────────────
            if step_type == "loop":
                ok, msg, sub_results, runtime_context = await self._handle_loop(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({
                    "index": idx, "type": "loop", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                })
                steps_executed += 1
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                continue

            # ── if (generic condition) ────────────────────────────────────────
            if step_type == "if":
                ok, msg, runtime_context, child_break = await self._handle_if(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({"index": idx, "type": "if", "ok": ok, "message": msg})
                steps_executed += 1
                if child_break:
                    break_requested = True
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                if break_requested:
                    break
                continue

            # ── repeat ───────────────────────────────────────────────────────
            if step_type == "repeat":
                ok, msg, sub_results, runtime_context = await self._handle_repeat(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({
                    "index": idx, "type": "repeat", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                })
                steps_executed += 1
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                continue

            # ── repeat_until ─────────────────────────────────────────────────
            if step_type == "repeat_until":
                ok, msg, runtime_context = await self._handle_repeat_until(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({"index": idx, "type": "repeat_until", "ok": ok, "message": msg})
                steps_executed += 1
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                continue

            # ── if_element ───────────────────────────────────────────────────
            if step_type == "if_element":
                ok, msg, runtime_context, child_break = await self._handle_if_element(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({"index": idx, "type": "if_element", "ok": ok, "message": msg})
                steps_executed += 1
                if child_break:
                    break_requested = True
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                if break_requested:
                    break
                continue

            # ── if_variable ──────────────────────────────────────────────────
            if step_type == "if_variable":
                ok, msg, runtime_context, child_break = await self._handle_if_variable(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({"index": idx, "type": "if_variable", "ok": ok, "message": msg})
                steps_executed += 1
                if child_break:
                    break_requested = True
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                if break_requested:
                    break
                continue

            # ── random_pick ──────────────────────────────────────────────────
            if step_type == "random_pick":
                ok, msg, runtime_context, child_break = await self._handle_random_pick(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({"index": idx, "type": "random_pick", "ok": ok, "message": msg})
                steps_executed += 1
                if child_break:
                    break_requested = True
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                if break_requested:
                    break
                continue

            # ── run_scenario ────────────────────────────────────────────────
            if step_type == "run_scenario":
                ok, msg, sub_results, runtime_context = await self._handle_run_scenario(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                _append({
                    "index": idx, "type": "run_scenario", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                })
                steps_executed += 1
                if not ok:
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                continue

            # ── extract — writes to context (posts / text_nodes) ─────────────
            if step_type == "extract":
                extract_result: ExtractResult = await workflow.execute_activity(
                    "execute_extract",
                    ExtractInput(
                        device_serial=inp.device_serial,
                        step=step,
                        step_index=idx,
                        context=runtime_context,
                        scenario_config=inp.scenario_config,
                        campaign_id=inp.campaign_id,
                        run_id=inp.run_id,
                        execution_id=inp.execution_id,
                        user_id=inp.campaign_vars.get("__USER_ID__"),
                    ),
                    result_type=ExtractResult,
                    start_to_close_timeout=_LONG_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY,
                    heartbeat_timeout=timedelta(seconds=30),
                )
                runtime_context = {**runtime_context, **extract_result.context}
                _append({
                    "index": idx, "type": "extract",
                    "ok": extract_result.ok,
                    "message": _with_persist_metrics(extract_result.message, extract_result.details),
                    "details": extract_result.details,
                })
                steps_executed += 1
                if extract_result.break_requested:
                    break_requested = True
                    break
                if not extract_result.ok:
                    action, early = await self._apply_error_policy(
                        step, idx, extract_result.message or "", inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                continue

            # ── save_extraction ──────────────────────────────────────────────
            if step_type == "save_extraction":
                save_result: StepResult = await workflow.execute_activity(
                    "execute_save_extraction",
                    SaveExtractionInput(
                        device_serial=inp.device_serial,
                        step=step,
                        step_index=idx,
                        context=runtime_context,
                        campaign_id=inp.campaign_id,
                        run_id=inp.run_id,
                        execution_id=inp.execution_id,
                        user_id=inp.campaign_vars.get("__USER_ID__"),
                        campaign_vars=dict(inp.campaign_vars or {}),
                    ),
                    result_type=StepResult,
                    start_to_close_timeout=timedelta(seconds=120),
                    retry_policy=_ACTIVITY_RETRY,
                    heartbeat_timeout=timedelta(seconds=60),
                )
                # Apply offset update returned by the activity so retries skip processed items.
                if save_result.details and "updated_offsets" in save_result.details:
                    offsets = dict(runtime_context.get("__save_extraction_offsets__") or {})
                    offsets.update(save_result.details["updated_offsets"])
                    runtime_context = {**runtime_context, "__save_extraction_offsets__": offsets}
                _append({
                    "index": idx, "type": "save_extraction",
                    "ok": save_result.ok,
                    "message": _with_persist_metrics(save_result.message, save_result.details),
                    "details": save_result.details,
                })
                steps_executed += 1
                if not save_result.ok:
                    action, early = await self._apply_error_policy(
                        step, idx, save_result.message or "", inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                continue

            # ── Leaf step: durable workflow retry OR batch dispatch ──────────
            # Steps with explicit retry config run one activity per attempt with
            # workflow.sleep() between attempts (survives worker restart).
            if parse_step_retry_policy(step) is not None:
                ok, msg, failed_idx = await _flush_batch()
                if not ok:
                    failed_step = inp.steps[failed_idx] if 0 <= failed_idx < len(inp.steps) else {}
                    action, early = await self._apply_error_policy(
                        failed_step, failed_idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early

                entry = await self._execute_leaf_with_durable_retry(inp, step, idx)
                _append(entry)
                steps_executed += 1
                if not entry.get("ok", True):
                    action, early = await self._apply_error_policy(
                        step, idx, entry.get("message") or "", inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                continue

            _pending_steps.append(step)
            _pending_indices.append(idx)
            if len(_pending_steps) >= _batch_size:
                ok, msg, failed_idx = await _flush_batch()
                if not ok:
                    failed_step = inp.steps[failed_idx] if 0 <= failed_idx < len(inp.steps) else {}
                    action, early = await self._apply_error_policy(
                        failed_step, failed_idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early

        # Flush any remaining leaf steps accumulated after the last control-flow step.
        ok, msg, failed_idx = await _flush_batch()
        if not ok:
            failed_step = inp.steps[failed_idx] if 0 <= failed_idx < len(inp.steps) else {}
            action, early = await self._apply_error_policy(
                failed_step, failed_idx, msg, inp, runtime_vars, runtime_context,
                steps_executed, step_results,
            )
            if action == "stop":
                return early

        return StepsResult(
            success=True,
            steps_executed=steps_executed,
            step_results=step_results,
            runtime_vars=runtime_vars,
            context=runtime_context,
            break_requested=break_requested,
        )

    async def _handle_loop(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, list, dict]:
        """Handle loop step: count or while condition, supports break_if."""
        count_raw = step.get("count")
        while_cond = step.get("while")
        max_iterations = max(1, min(int(step.get("max_iterations", 100) or 100), 10_000))
        sub_steps = step.get("steps") or []

        if not sub_steps:
            return False, "loop: no nested steps", [], runtime_context

        if count_raw is not None:
            try:
                # count is explicit — max_iterations applies to while-only loops.
                iterations = int(count_raw)
            except (TypeError, ValueError):
                return False, f"loop: invalid count={count_raw!r}", [], runtime_context
            use_while = False
        elif while_cond:
            iterations = max_iterations
            use_while = True
        else:
            return False, "loop: must specify either 'count' or 'while'", [], runtime_context

        sub_results = []
        ctx = dict(runtime_context)

        for i in range(iterations):
            runtime_vars["__LOOP_ITER__"] = i
            ctx["_loop_iter"] = i

            if use_while:
                cond_met: bool = await workflow.execute_activity(
                    "evaluate_legacy_condition",
                    LegacyConditionCheckInput(
                        device_serial=inp.device_serial,
                        condition=while_cond,
                        runtime_vars=runtime_vars,
                        context=ctx,
                        execution_id=inp.execution_id or inp.run_id,
                    ),
                    result_type=bool,
                    start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                    heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                    retry_policy=_ACTIVITY_RETRY,
                )
                if not cond_met:
                    break

            child_result = await self._execute_child_steps(inp, sub_steps, runtime_vars, ctx)
            sub_results.append({"iteration": i, "success": child_result.success})
            runtime_vars.update(child_result.runtime_vars)
            ctx = {**ctx, **child_result.context}

            if child_result.break_requested:
                break

            if not child_result.success:
                ctx.pop("_loop_iter", None)
                return (
                    False,
                    f"loop: iteration {i} failed — {child_result.failed_message}",
                    sub_results,
                    ctx,
                )

        ctx.pop("_loop_iter", None)
        return True, f"loop: {len(sub_results)} iteration(s) completed", sub_results, ctx

    async def _handle_if(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool]:
        """Handle generic 'if' step using _evaluate_condition."""
        condition = step.get("condition") or {}
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not condition:
            return False, "if: missing condition", runtime_context, False

        cond_met: bool = await workflow.execute_activity(
            "evaluate_legacy_condition",
            LegacyConditionCheckInput(
                device_serial=inp.device_serial,
                condition=condition,
                runtime_vars=runtime_vars,
                context=runtime_context,
                execution_id=inp.execution_id or inp.run_id,
            ),
            result_type=bool,
            start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
            heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
            retry_policy=_ACTIVITY_RETRY,
        )

        branch_steps = then_steps if cond_met else else_steps
        branch_name = "then" if cond_met else "else"

        if not branch_steps:
            return True, f"if: no {branch_name} steps, skip", runtime_context, False

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, runtime_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}

        if not child_result.success:
            return False, f"if: {branch_name} branch failed — {child_result.failed_message}", merged_ctx, False

        return True, f"if: executed {branch_name}", merged_ctx, child_result.break_requested

    async def _handle_repeat(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, list, dict]:
        """Handle repeat step: loop N times with optional delay."""
        count_raw = step.get("count")
        delay = float(step.get("delay_between", 0.0) or 0.0)
        sub_steps = step.get("steps") or []

        if count_raw is None:
            return False, "repeat: missing count", [], runtime_context
        if not sub_steps:
            return False, "repeat: no nested steps", [], runtime_context

        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            return False, f"repeat: invalid count={count_raw!r}", [], runtime_context

        count = min(count, 10_000)
        sub_results = []
        ctx = dict(runtime_context)

        for i in range(count):
            runtime_vars["__LOOP_INDEX__"] = i

            child_result = await self._execute_child_steps(inp, sub_steps, runtime_vars, ctx)
            sub_results.append({"iteration": i, "success": child_result.success})

            if not child_result.success:
                return (
                    False,
                    f"repeat: iteration {i} failed — {child_result.failed_message}",
                    sub_results,
                    ctx,
                )

            runtime_vars.update(child_result.runtime_vars)
            ctx = {**ctx, **child_result.context}

            if child_result.break_requested:
                break

            if delay > 0 and i < count - 1:
                await workflow.sleep(min(delay, 300.0))

        return True, f"repeat: {len(sub_results)} iteration(s) completed", sub_results, ctx

    async def _handle_repeat_until(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict]:
        """Handle repeat_until: loop until condition met or max iterations.

        Semantics: CHECK condition → if met, exit immediately (zero body iterations);
        otherwise execute body, then CHECK again. This is a pre-condition check loop
        (while-not), NOT a do-while. If the condition is already satisfied on entry,
        the body never runs.

        Returns success=True when condition is met, success=False when max_iterations
        is exhausted without the condition becoming true.
        """
        condition = step.get("condition") or {}
        max_iter = max(1, min(int(step.get("max_iterations", 100) or 100), 10_000))
        sub_steps = step.get("steps") or []

        if not condition:
            return False, "repeat_until: missing condition", runtime_context
        if not sub_steps:
            return False, "repeat_until: no nested steps", runtime_context

        ctx = dict(runtime_context)

        for i in range(max_iter):
            runtime_vars["__LOOP_INDEX__"] = i

            condition_met: bool = await workflow.execute_activity(
                "evaluate_condition",
                ConditionCheckInput(
                    device_serial=inp.device_serial,
                    condition=condition,
                    runtime_vars=runtime_vars,
                ),
                result_type=bool,
                start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                retry_policy=_ACTIVITY_RETRY,
            )

            if condition_met:
                return True, f"repeat_until: condition met after {i} iteration(s)", ctx

            child_result = await self._execute_child_steps(inp, sub_steps, runtime_vars, ctx)

            if not child_result.success:
                return (
                    False,
                    f"repeat_until: iteration {i} failed — {child_result.failed_message}",
                    ctx,
                )

            runtime_vars.update(child_result.runtime_vars)
            ctx = {**ctx, **child_result.context}

        return False, f"repeat_until: max_iterations ({max_iter}) reached", ctx

    async def _handle_if_element(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool]:
        """Handle if_element: branch based on element existence."""
        by = str(step.get("by") or "")
        value = str(step.get("value") or "").strip()
        timeout = float(step.get("timeout", 3.0) or 3.0)
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not by or not value:
            return False, "if_element: missing by/value", runtime_context, False

        check_result: ElementCheckResult = await workflow.execute_activity(
            "check_element_exists",
            ElementCheckInput(
                device_serial=inp.device_serial,
                by=by, value=value, timeout=timeout,
                execution_id=inp.execution_id or inp.run_id,
            ),
            result_type=ElementCheckResult,
            start_to_close_timeout=timedelta(seconds=timeout + 10),
            heartbeat_timeout=timedelta(seconds=timeout + 10),
            retry_policy=_ACTIVITY_RETRY,
        )

        branch_steps = then_steps if check_result.found else else_steps
        branch_name = "then" if check_result.found else "else"

        if not branch_steps:
            return True, f"if_element(found={check_result.found}): no {branch_name} steps, skip", runtime_context, False

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, runtime_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}

        if not child_result.success:
            return False, f"if_element: {branch_name} branch failed — {child_result.failed_message}", merged_ctx, False

        return True, f"if_element(found={check_result.found}): executed {branch_name}", merged_ctx, child_result.break_requested

    async def _handle_if_variable(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool]:
        """Handle if_variable: branch based on variable value."""
        name = str(step.get("name") or "")
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not name:
            return False, "if_variable: missing name", runtime_context, False

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
            # No comparator specified: treat variable as truthy/falsy.
            # Falsy: None, empty string, "0", "None", "False".
            condition_met = bool(raw_val) and str_val not in ("None", "", "0", "False")

        branch_steps = then_steps if condition_met else else_steps
        branch_name = "then" if condition_met else "else"

        if not branch_steps:
            return True, f"if_variable({name}={str_val!r}): no {branch_name} steps, skip", runtime_context, False

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, runtime_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}

        if not child_result.success:
            return False, f"if_variable: {branch_name} branch failed", merged_ctx, False

        return True, f"if_variable({name}={str_val!r}): executed {branch_name}", merged_ctx, child_result.break_requested

    async def _handle_random_pick(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool]:
        """Handle random_pick: weighted random branch selection."""
        branches = step.get("branches") or []
        if not branches:
            return False, "random_pick: no branches", runtime_context, False

        weights = [max(1, int(b.get("weight", 1))) for b in branches]
        wf_random = _get_wf_random()
        chosen_idx = wf_random.choices(range(len(branches)), weights=weights, k=1)[0]
        chosen = branches[chosen_idx]
        branch_steps = chosen.get("steps") or []

        if not branch_steps:
            return True, f"random_pick: branch {chosen_idx} has no steps, skip", runtime_context, False

        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, runtime_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}

        if not child_result.success:
            return False, f"random_pick: branch {chosen_idx} failed", merged_ctx, False

        return True, f"random_pick: executed branch {chosen_idx}", merged_ctx, child_result.break_requested

    async def _handle_run_scenario(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, list, dict]:
        """Handle run_scenario as in-workflow control flow.

        This keeps campaign-level scenario sequences on one device strictly
        sequential while preserving Temporal step execution for the nested
        scenario, instead of wrapping the whole sub-scenario in one long
        activity call.
        """
        scenario_id = str(step.get("scenario_id") or "").strip()
        scenario_name = str(step.get("scenario_name") or "").strip()
        scenario_ref = scenario_id or scenario_name

        if not scenario_ref:
            return False, "run_scenario: missing scenario_id or scenario_name", [], runtime_context

        stack = list(runtime_context.get("__scenario_call_stack__") or [])
        if scenario_ref in stack:
            return (
                False,
                f"run_scenario: circular reference detected: {scenario_ref!r}",
                [],
                runtime_context,
            )

        registry = inp.scenario_registry or {}
        sub_def: dict[str, Any] | None = None
        if scenario_id:
            sub_def = (registry.get("by_id") or {}).get(scenario_id)
        if sub_def is None and scenario_name:
            sub_def = (registry.get("by_campaign_name") or {}).get(scenario_name)
        if sub_def is None and scenario_name:
            sub_def = (registry.get("by_template_name") or {}).get(scenario_name)
        # Backward-compat: some campaigns store steps only in ScenarioTemplates
        # and keep Scenario.steps empty. If we resolved by_id but the definition
        # has no steps, fall back to template lookup by name.
        if (
            sub_def is not None
            and not (sub_def.get("steps") or [])
            and scenario_name
        ):
            template_def = (registry.get("by_template_name") or {}).get(scenario_name)
            if template_def and (template_def.get("steps") or []):
                sub_def = template_def

        if sub_def is None:
            return (
                False,
                f"run_scenario: sub-scenario not found: {scenario_ref!r}",
                [],
                runtime_context,
            )

        override_vars = step.get("variables") or {}
        if not isinstance(override_vars, dict):
            override_vars = {}
        merged_vars = {**(sub_def.get("variables") or {}), **override_vars}
        child_vars = {**inp.variables, **merged_vars}
        sub_steps = sub_def.get("steps") or []

        child_context = {
            **runtime_context,
            "__scenario_call_stack__": [*stack, scenario_ref],
        }
        child_result = await self._execute_child_steps(
            inp,
            sub_steps,
            runtime_vars,
            child_context,
            variables=child_vars,
        )

        merged_ctx = {**runtime_context, **child_result.context}
        merged_ctx.pop("__scenario_call_stack__", None)

        if not child_result.success:
            return (
                False,
                f"run_scenario: sub-scenario {scenario_ref!r} failed — {child_result.failed_message}",
                child_result.step_results,
                merged_ctx,
            )

        return (
            True,
            f"run_scenario: {scenario_ref!r} completed ({child_result.steps_executed} steps)",
            child_result.step_results,
            merged_ctx,
        )

    # ── Inline step execution (no child workflow spawn) ──────────────────

    async def _execute_child_steps(
        self,
        parent_inp: StepsInput,
        steps: list[dict],
        runtime_vars: dict,
        runtime_context: dict,
        *,
        variables: dict[str, Any] | None = None,
    ) -> StepsResult:
        """Execute a list of steps inline (same workflow, no child spawn).

        Previously this spawned a child workflow per iteration which caused
        N×repeat_count workflows to appear in Temporal UI and wasted resources.
        Now control-flow steps (repeat, if_element, etc.) run in-process.
        Child workflows are only used for truly independent top-level executions
        (one per device per scenario, from ScenarioWorkflow.run).
        """
        if parent_inp.depth >= MAX_NESTING_DEPTH:
            return StepsResult(
                success=False, steps_executed=0,
                failed_message=f"Max nesting depth {MAX_NESTING_DEPTH} exceeded",
            )

        # Copy lists explicitly to prevent shared-reference mutation across nesting levels.
        # dict() is a shallow copy — list values (posts, text_nodes) would be shared otherwise.
        context_copy = {
            k: list(v) if isinstance(v, list) else v
            for k, v in runtime_context.items()
        }
        nested_inp = StepsInput(
            device_serial=parent_inp.device_serial,
            steps=steps,
            variables=parent_inp.variables if variables is None else variables,
            campaign_vars=parent_inp.campaign_vars,
            scenario_registry=parent_inp.scenario_registry,
            depth=parent_inp.depth + 1,
            parent_runtime_vars=dict(runtime_vars),
            scenario_config=parent_inp.scenario_config if hasattr(parent_inp, "scenario_config") else {},
            context=context_copy,
            campaign_id=getattr(parent_inp, "campaign_id", None),
            run_id=getattr(parent_inp, "run_id", None),
            execution_id=getattr(parent_inp, "execution_id", None),
        )
        return await self.run(nested_inp)


# ── Variable resolution (deterministic, no I/O) ─────────────────────────────


def _get_wf_random():
    """Get workflow-safe random instance.

    Uses workflow.random() inside a real Temporal workflow to guarantee replay
    determinism. Falls back to stdlib random ONLY during unit tests where there
    is no Temporal context — the exception type expected is RuntimeError/AttributeError
    from the Temporal sandbox.

    If workflow.random() raises an unexpected exception type during a live workflow
    run, this is logged at ERROR level because using stdlib random would corrupt
    Temporal replay determinism.
    """
    try:
        return workflow.random()
    except Exception as exc:
        # Expected during unit tests: Temporal sandbox not active.
        # Unexpected during real workflow runs: log loudly so the issue is visible.
        _wf_random_log = logging.getLogger(__name__)
        # AttributeError, RuntimeError, NotImplementedError are raised by Temporal SDK
        # internally when workflow.random() is called outside a workflow context (unit tests).
        # Also accept any exception whose class name contains "NotInWorkflow" or "EventLoop"
        # to cover Temporal's internal _NotInWorkflowEventLoopError.
        expected_test_types = (AttributeError, RuntimeError, NotImplementedError)
        is_expected = isinstance(exc, expected_test_types) or any(
            s in type(exc).__name__ for s in ("NotInWorkflow", "EventLoop", "Sandbox")
        )
        if not is_expected:
            _wf_random_log.error(
                "workflow.random() raised unexpected %s: %s — "
                "falling back to stdlib random which BREAKS Temporal replay determinism. "
                "This MUST be investigated.",
                type(exc).__name__, exc,
            )
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
