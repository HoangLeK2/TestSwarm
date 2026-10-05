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
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ChildWorkflowError
from temporalio.exceptions import CancelledError as TemporalCancelledError

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
    from services.execution.event_types import (
        STEP_COMPLETED,
        STEP_FAILED,
        STEP_STARTED,
        TEMPORAL_ACTIVITY_COMPLETED,
        TEMPORAL_ACTIVITY_FAILED,
        TEMPORAL_ACTIVITY_RETRYING,
        TEMPORAL_ACTIVITY_SCHEDULED,
        TEMPORAL_ACTIVITY_STALLED,
    )
    from services.execution.reason_codes import (
        BRANCH_FAILED,
        CONDITION_EVAL_FAILED,
        LOOP_HISTORY_LIMIT,
        LOOP_INVALID_COUNT,
        LOOP_ITERATION_FAILED,
        LOOP_NO_NESTED_STEPS,
        LOOP_STALLED,
        SUBSCENARIO_FAILED,
    )
    from services.execution.trace_context import (
        TRACE_CONTEXT_KEY,
        push_step_path,
        step_trace_from_context,
        trace_from_runtime_context,
    )
    from temporal.step_activity_policy import (
        build_batch_activity_policy,
        build_step_activity_policy,
        workflow_activity_id,
    )
    from temporal.shared import (
        MAX_NESTING_DEPTH,
        TASK_QUEUE_NAME,
        control_task_queue,
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
    non_retryable_error_types=[
        "ValueError",
        "CampaignDeviceClaimLostError",
    ],
)

_DEVICE_ACTION_RETRY = RetryPolicy(
    maximum_attempts=1,
)

_CAMPAIGN_CLAIM_KEEPALIVE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=0,
    non_retryable_error_types=[
        "ValueError",
        "CampaignDeviceClaimLostError",
    ],
)


def _is_temporal_cancelled_error(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.CancelledError, TemporalCancelledError)):
        return True
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, (asyncio.CancelledError, TemporalCancelledError)):
            return True
        cause = cause.__cause__
    if isinstance(exc, ChildWorkflowError):
        text = str(exc).lower()
        return "cancelled" in text or "canceled" in text
    return False


_GENERIC_TEMPORAL_FAILURE_MESSAGES = {
    "activity error",
    "activity execution failed",
    "activity task failed",
    "child workflow execution failed",
    "workflow execution failed",
}


def _is_generic_temporal_failure_message(message: str) -> bool:
    lowered = message.lower()
    return (
        lowered in _GENERIC_TEMPORAL_FAILURE_MESSAGES
        or lowered.startswith("child workflow execution failed")
        or lowered.startswith("workflow execution failed")
    )


def _workflow_failure_message(
    exc: BaseException,
    *,
    fallback: str = "Workflow failed before recording step details",
) -> str:
    """Return the most useful deterministic error text from a Temporal exception."""
    messages: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        if text:
            messages.append(text)
        current = current.__cause__ or current.__context__

    for message in reversed(messages):
        if not _is_generic_temporal_failure_message(message):
            return message
    return fallback


def _activity_failure_suggests_stall(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        token in lowered
        for token in (
            "heartbeat",
            "schedule_to_start",
            "schedule to start",
            "start_to_close",
            "start to close",
            "timed out",
            "timeout",
        )
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
_BATCH_STEP_TIMEOUT_SECONDS = 120
_BATCH_TIMEOUT_CAP_SECONDS = 600
_BATCH_RECOVERY_MARGIN_SECONDS = 30
_BATCH_TIMEOUT_HARD_CAP_SECONDS = 3600
_MAX_RETAINED_SUB_RESULTS = 50
# Cap on the in-memory step log a workflow keeps for its query handler. The
# durable record is execution_steps in the database; this is only for live
# progress, so there is no reason to hold an unbounded copy per cached workflow.
_STEP_LOG_MAX = 500
# Flushing step results to the database before continue_as_new adds an activity
# call, which changes the commands a workflow emits — old runs must keep their
# original shape on replay.
_STEP_CHECKPOINT_PATCH = "step-checkpoint-before-continue-as-new-v1"
# The retry-on-pause path has the same index-restart flaw, but it is a separate
# continuation with its own history, so it gets its own patch id.
_RETRY_ABSOLUTE_INDEX_PATCH = "retry-absolute-step-index-v1"
_CAMPAIGN_CLAIM_KEEPALIVE_PATCH = "campaign-device-claim-keepalive-v1"
_CAMPAIGN_CLAIM_KEEPALIVE_MAX_SECONDS = 600
_CONTROL_FLOW_EVENT_PATCH = "control-flow-boundary-events-v1"
_STEP_ACTIVITY_POLICY_PATCH = "step-activity-policy-v1"
_TEMPORAL_ACTIVITY_EVENT_PATCH = "temporal-activity-events-v1"
# Ask the server when to continue-as-new instead of comparing event count to a
# constant. The constant ignored history *size*: payload_guard allows 64KB per
# field, so the 50MB limit is reached long before 10,000 events.
_CAN_SUGGESTED_PATCH = "continue-as-new-suggested-v1"
# Buffer telemetry events in the workflow and ship them in one activity instead
# of awaiting an activity per emit. Changes the commands the workflow emits, so
# in-flight runs must keep the per-event shape.
_BUFFERED_EVENTS_PATCH = "buffered-execution-events-v1"
# How many buffered events force an early flush. A crash loses at most this many
# telemetry records — acceptable, they are observation, not state.
_EVENT_BUFFER_FLUSH_AT = 50
# ...and how long one may sit unshipped. Without this a short scenario shows no
# telemetry at all until it ends. workflow.now() is deterministic on replay, so
# the flush decision replays identically.
_EVENT_BUFFER_MAX_AGE = timedelta(seconds=15)

# Step types that require individual activity calls (cannot be batched).
# All other step types are "leaf" steps dispatched via execute_device_action_batch.
#
# Every entry here flushes the pending batch, so the set is also the main source
# of activity fan-out. It has been checked for entries that only sit here for
# historical reasons; there are none:
#   - `extract` returns ExtractResult.break_requested, which is how
#     stop_if_no_new ends a crawl loop. DeviceActionBatchResult has no channel
#     for it, so batching extract would make crawl loops run to their iteration
#     cap instead of stopping. It also needs _LONG_TIMEOUT, which the batch
#     timeout (sized per step count) does not give it.
#   - `save_extraction` writes to the DB on the worker and feeds
#     __save_extraction_offsets__ back into runtime_context so a retry skips
#     what it already saved.
# `run_scenario` is the most frequent step in practice (450 occurrences in one
# measured campaign) and flushes the batch every time. Batching it means
# changing where nested scenarios execute — an execution-model change, not a
# list edit. Note that editing this set at all changes the commands a workflow
# emits and so needs a patch id for in-flight runs (see _STEP_CHECKPOINT_PATCH).
_CONTROL_FLOW_TYPES = frozenset({
    "set_variable", "set_var", "break_if",
    "loop", "if", "repeat", "repeat_until",
    "if_element", "if_variable", "random_pick",
    "run_scenario",
    "extract", "save_extraction",
})


def _step_id(step: dict[str, Any], idx: int) -> str:
    return str(step.get("id") or step.get("_id") or step.get("step_id") or idx)


def _branch_weight(branch: dict[str, Any]) -> int:
    """random_pick branch weight, tolerant of null/blank/float from stored JSON."""
    try:
        return max(1, int(float(branch.get("weight") or 1)))
    except (TypeError, ValueError):
        return 1


def _loop_random_range(low: Any, high: Any, cast) -> tuple:
    """Twin of control_flow.py:_resolve_random_range — keep the two identical.

    Half a range is a typo, not a shorthand: guessing which half the author
    meant is how a loop quietly runs once instead of forty times.

    Returns ``(bounds, error)``; both are ``None`` when the range is unset.
    """
    unset = (None, "")
    if low in unset and high in unset:
        return None, None
    if low in unset or high in unset:
        return None, "needs both min and max"
    try:
        lo, hi = cast(low), cast(high)
    except (TypeError, ValueError):
        return None, f"invalid bounds {low!r}..{high!r}"
    if lo < 0 or hi < lo:
        return None, f"invalid range {lo}..{hi}"
    return (lo, hi), None


def _error_policy(step: dict, cfg: dict) -> str:
    """Return error handling policy: 'pause' | 'continue' | 'stop'.

    Priority: step-level on_error → step-level ignore_error → scenario-level on_error
    → scenario-level continue_on_error → default 'stop'.

    Usage in scenario JSON:
        Step-level:     {"type": "tap", ..., "on_error": "pause"}
        Scenario-level: {"continue_on_error": true, "steps": [...]}
        Pause all:      {"on_error": "pause", "steps": [...]}
    """
    # Same precedence as tasks/scenario/executor.py: the editor's fields win
    # over the error_policy="stop" that normalize_step stamps on save.
    step_policy = step.get("on_error", "")
    if step_policy in ("pause", "continue", "stop"):
        return step_policy
    if step.get("ignore_error"):
        return "continue"
    dsl_policy = step.get("error_policy", "")
    if dsl_policy in ("ignore", "continue"):
        return "continue"
    if dsl_policy == "stop":
        return "stop"
    cfg_policy = cfg.get("on_error", "")
    if cfg_policy in ("pause", "continue", "stop"):
        return cfg_policy
    if cfg.get("continue_on_error"):
        return "continue"
    return "stop"


def _step_results_have_failure(step_results: list) -> bool:
    return any(
        isinstance(entry, dict) and not entry.get("ok", True)
        for entry in step_results or []
    )


def _first_failed_step_message(step_results: list) -> str:
    for entry in step_results or []:
        if isinstance(entry, dict) and not entry.get("ok", True):
            return str(entry.get("message") or "step failed")
    return ""


def _first_failed_step(step_results: list) -> dict[str, Any] | None:
    for entry in step_results or []:
        if isinstance(entry, dict) and not entry.get("ok", True):
            return {
                key: value
                for key, value in entry.items()
                if key in {"index", "type", "step_id", "step_path", "message", "reason_code"}
                and value is not None
            }
    return None


def _run_scenario_failure_can_be_ignored(
    message: str,
    sub_results: list,
) -> bool:
    if not sub_results:
        return False
    reason = str(message or "").split("—", maxsplit=1)[-1].strip()
    if reason.startswith("run_scenario:"):
        return False
    if reason.startswith("Max nesting depth"):
        return False
    return True


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _max_recovery_timeout_seconds(scenario_config: dict[str, Any] | None) -> int:
    policy = (scenario_config or {}).get("recovery_policy")
    if not isinstance(policy, dict) or not policy.get("enabled"):
        return 0
    rules = policy.get("rules")
    if not isinstance(rules, list):
        return 0

    saw_rule = False
    max_timeout = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        saw_rule = True
        timeout_ms = _positive_int(rule.get("timeout_ms"))
        if timeout_ms > 0:
            max_timeout = max(max_timeout, (timeout_ms + 999) // 1000)

    if saw_rule and max_timeout == 0:
        return 60
    return max_timeout


def _batch_start_to_close_timeout(
    step_count: int,
    scenario_config: dict[str, Any] | None,
) -> timedelta:
    n = max(1, _positive_int(step_count))
    base_seconds = min(_BATCH_STEP_TIMEOUT_SECONDS * n, _BATCH_TIMEOUT_CAP_SECONDS)
    recovery_seconds = _max_recovery_timeout_seconds(scenario_config)
    if recovery_seconds <= 0:
        return timedelta(seconds=base_seconds)
    total_seconds = min(
        base_seconds + recovery_seconds + _BATCH_RECOVERY_MARGIN_SECONDS,
        _BATCH_TIMEOUT_HARD_CAP_SECONDS,
    )
    return timedelta(seconds=total_seconds)


def _step_activity_options(
    inp: "StepsInput",
    step: dict[str, Any],
    step_index: int,
    *,
    activity_step_type: str | None = None,
    default_start_to_close_timeout: timedelta,
    default_retry_policy: RetryPolicy,
    default_heartbeat_timeout: timedelta,
) -> dict[str, Any]:
    if not workflow.patched(_STEP_ACTIVITY_POLICY_PATCH):
        return {
            "start_to_close_timeout": default_start_to_close_timeout,
            "retry_policy": default_retry_policy,
            "heartbeat_timeout": default_heartbeat_timeout,
        }
    policy_step = dict(step)
    if activity_step_type:
        policy_step["type"] = activity_step_type
    policy = build_step_activity_policy(
        execution_id=inp.execution_id or inp.run_id,
        step=policy_step,
        step_index=step_index,
        default_start_to_close_timeout=default_start_to_close_timeout,
    )
    return {
        "start_to_close_timeout": policy.start_to_close_timeout,
        "retry_policy": policy.retry_policy,
        "heartbeat_timeout": policy.heartbeat_timeout,
        "activity_id": policy.activity_id,
    }


# Outcomes meaning "this step chose not to act", as opposed to "this step could
# not find anything". A throttled account is the rate limiter working; calling
# that a stall would fail every correctly-paced campaign the moment it reached
# its hourly budget.
_DELIBERATE_NO_ACTION_OUTCOMES = frozenset({"rate_limited", "paced", "cooldown"})


def _walk_loop_step_results(step_results: list[Any]):
    """Every step result in an iteration, however deeply branches nest it.

    ``if_variable`` hangs its branch off ``sub_result``, and in the friend flow
    ``connection_request`` sits two levels down — a shallow read sees only the
    wrappers and would call a working iteration idle.
    """
    stack: list[Any] = list(step_results or [])
    seen = 0
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        seen += 1
        if seen > 5000:  # pathological nesting; stop walking rather than hang
            return
        yield node
        for key in ("step_results", "sub_results"):
            value = node.get(key)
            if isinstance(value, list):
                stack.extend(value)
        for key in ("sub_result", "result"):
            value = node.get(key)
            if isinstance(value, dict):
                stack.append(value)


def _loop_performed_action(step_results: list[Any]) -> bool:
    """Did this iteration actually touch the device? Rate-limited counts as no."""
    return any(
        node.get("action_performed") is True
        for node in _walk_loop_step_results(step_results)
    )


def _loop_made_progress(step_results: list[Any]) -> bool:
    """Did this iteration act, or deliberately decline to act?"""
    return any(
        node.get("action_performed") is True
        or str(node.get("outcome") or "") in _DELIBERATE_NO_ACTION_OUTCOMES
        for node in _walk_loop_step_results(step_results)
    )


def _append_sub_result(
    sub_results: list[dict[str, Any]],
    state: dict[str, Any],
    item: dict[str, Any],
) -> None:
    state["last"] = item
    if len(sub_results) < _MAX_RETAINED_SUB_RESULTS:
        sub_results.append(item)
        return
    state["omitted"] = int(state.get("omitted", 0) or 0) + 1


def _finish_sub_results(
    sub_results: list[dict[str, Any]],
    state: dict[str, Any],
) -> None:
    omitted = int(state.get("omitted", 0) or 0)
    if omitted <= 0:
        return
    sub_results.append(
        {
            "truncated": True,
            "omitted": omitted,
            "last": state.get("last"),
        }
    )


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

        result: StepsResult | None = None
        try:
            # Wait if paused before starting. Keep this inside the terminal
            # error boundary so claim loss during an initial pause is finalized.
            await self._wait_if_paused(inp)

            if self._cancelled:
                self._progress.status = WorkflowStatus.CANCELLED.value
                await self._finalize(
                    inp.campaign_id,
                    inp.run_id,
                    success=False,
                    execution_id=inp.execution_id,
                    device_serial=inp.device_serial,
                    failed_message="Cancelled before start",
                )
                return StepsResult(
                    success=False,
                    steps_executed=0,
                    failed_message="Cancelled before start",
                )

            # Merge capture_steps from ScenarioInput into scenario_config so activities
            # can access it via inp.scenario_config["capture_steps"].
            merged_config = dict(inp.scenario_config or {})
            if inp.capture_steps:
                merged_config["capture_steps"] = True
            elif inp.execution_id or inp.run_id:
                merged_config.setdefault("capture_steps", True)
            steps_input = StepsInput(
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
            )
            result = await self._execute_steps_with_claim_keepalive(inp, steps_input)

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

        except (asyncio.CancelledError, TemporalCancelledError):
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
            if _is_temporal_cancelled_error(exc):
                self._progress.status = WorkflowStatus.CANCELLED.value
                await self._finalize(
                    inp.campaign_id, inp.run_id, success=False,
                    execution_id=inp.execution_id, device_serial=inp.device_serial,
                    failed_message="Cancelled by Temporal",
                )
                return StepsResult(
                    success=False,
                    steps_executed=result.steps_executed if result else 0,
                    failed_message="Cancelled by Temporal",
                )
            self._progress.status = WorkflowStatus.FAILED.value
            failed_message = _workflow_failure_message(
                exc,
                fallback="Child workflow failed before recording step details",
            )
            await self._finalize(
                inp.campaign_id, inp.run_id, success=False,
                execution_id=inp.execution_id, device_serial=inp.device_serial,
                failed_message=failed_message,
            )
            return StepsResult(
                success=False,
                steps_executed=result.steps_executed if result else 0,
                failed_message=failed_message,
            )

    async def _execute_steps_with_claim_keepalive(
        self,
        inp: ScenarioInput,
        steps_input: StepsInput,
    ) -> StepsResult:
        child_execution = workflow.execute_child_workflow(
            ScenarioStepsWorkflow.run,
            steps_input,
            id=f"{workflow.info().workflow_id}:steps",
            task_queue=TASK_QUEUE_NAME,
        )
        execution_id = inp.execution_id or inp.run_id
        keepalive_enabled = (
            bool(inp.campaign_id and execution_id and inp.device_serial)
            and workflow.patched(_CAMPAIGN_CLAIM_KEEPALIVE_PATCH)
        )
        if not keepalive_enabled:
            return await child_execution

        child_task = asyncio.create_task(child_execution)
        keepalive_task = asyncio.create_task(
            self._keep_campaign_claim_alive(
                campaign_id=inp.campaign_id,
                execution_id=execution_id,
                device_serial=inp.device_serial,
            )
        )
        try:
            done, _pending = await workflow.wait(
                {child_task, keepalive_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if keepalive_task in done:
                keepalive_error = keepalive_task.exception()
                child_task.cancel()
                await asyncio.gather(child_task, return_exceptions=True)
                if keepalive_error is not None:
                    raise keepalive_error
                raise RuntimeError("campaign device claim keepalive stopped unexpectedly")
            return await child_task
        except (asyncio.CancelledError, TemporalCancelledError):
            child_task.cancel()
            await asyncio.gather(child_task, return_exceptions=True)
            raise
        finally:
            keepalive_task.cancel()
            await asyncio.gather(keepalive_task, return_exceptions=True)

    async def _keep_campaign_claim_alive(
        self,
        *,
        campaign_id: str,
        execution_id: str,
        device_serial: str,
    ) -> None:
        delay_seconds = 0
        while True:
            if delay_seconds > 0:
                await workflow.sleep(timedelta(seconds=delay_seconds))
            recommended_delay: int = await workflow.execute_activity(
                "heartbeat_campaign_device_claim",
                {
                    "campaign_id": campaign_id,
                    "execution_id": execution_id,
                    "device_serial": device_serial,
                },
                result_type=int,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_CAMPAIGN_CLAIM_KEEPALIVE_RETRY,
            )
            delay_seconds = max(
                1,
                min(
                    int(recommended_delay),
                    _CAMPAIGN_CLAIM_KEEPALIVE_MAX_SECONDS,
                ),
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

    async def _wait_if_paused(self, inp: ScenarioInput | None = None) -> None:
        """Block until unpaused or cancelled."""
        if not self._paused or self._cancelled:
            return
        execution_id = (inp.execution_id or inp.run_id) if inp is not None else None
        keepalive_enabled = (
            inp is not None
            and bool(inp.campaign_id and execution_id and inp.device_serial)
            and workflow.patched(_CAMPAIGN_CLAIM_KEEPALIVE_PATCH)
        )
        if not keepalive_enabled:
            await workflow.wait_condition(
                lambda: not self._paused or self._cancelled,
            )
            return

        keepalive_task = asyncio.create_task(
            self._keep_campaign_claim_alive(
                campaign_id=inp.campaign_id,
                execution_id=execution_id,
                device_serial=inp.device_serial,
            )
        )
        pause_wait_task = asyncio.create_task(
            workflow.wait_condition(
                lambda: not self._paused or self._cancelled,
            )
        )
        try:
            done, _pending = await workflow.wait(
                {pause_wait_task, keepalive_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if keepalive_task in done:
                keepalive_error = keepalive_task.exception()
                pause_wait_task.cancel()
                await asyncio.gather(pause_wait_task, return_exceptions=True)
                if keepalive_error is not None:
                    raise keepalive_error
                raise RuntimeError("campaign device claim keepalive stopped unexpectedly")
            await pause_wait_task
        finally:
            keepalive_task.cancel()
            pause_wait_task.cancel()
            await asyncio.gather(
                keepalive_task,
                pause_wait_task,
                return_exceptions=True,
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
        # Keyed on "is there anything to finalize", not on "is this a campaign".
        # Scenario previews run with campaign_id="" (preview_runtime builds the
        # ScenarioInput that way), so gating on campaign_id alone skipped
        # finalization entirely for them: the execution row stayed RUNNING
        # forever and its device claim was only freed by the 1800s TTL sweeper,
        # locking the phone for 30 minutes after every preview.
        # finalize_campaign itself already guards its campaign-only work behind
        # `if not campaign_id: return`, so an empty campaign_id is safe here.
        if not campaign_id and not execution_id:
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
            # 34ms of work, but it is what releases the device claim: every
            # second it spends queued is a second the phone stays marked busy
            # after it has already finished. Measured on the shared queue with
            # every slot taken, that wait was 20.5s — an 8.5s run lost 70% of
            # its capacity to it, and the effect worsens as the fleet fills.
            #
            # Only this call is routed. The claim keepalive stays put: it runs
            # inside a cancellable coroutine that broke when routed, and it can
            # afford to wait anyway (campaign claims expire after 1800s per
            # DEFAULT_SESSION_IDLE_THRESHOLDS), whereas this one cannot.
            #
            # This makes a control worker a hard dependency: with nobody polling
            # device-control the activity is never picked up, and start_to_close
            # does not run until an activity starts, so it waits rather than
            # failing. Keep TEMPORAL_CONTROL_WORKER_COUNT >= 1.
            task_queue=control_task_queue(),
            # start_to_close only starts counting once an activity *begins*, so
            # with nobody polling device-control this would wait forever instead
            # of failing — the phone stays claimed and nothing says why. A
            # schedule_to_start bound turns a missing control worker into a
            # visible error that retries.
            schedule_to_start_timeout=timedelta(seconds=60),
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
        # Bounded: this list lives for as long as the workflow stays in the
        # worker's sticky cache, and a long crawl appends a ~1KB entry per step
        # forever. Keeping the newest _STEP_LOG_MAX and counting the rest gives
        # the query what it is actually used for — recent progress — without
        # letting one long run pin megabytes in every cached workflow.
        self._step_log: list[dict] = []
        self._step_log_dropped = 0
        self._paused = False
        self._cancelled = False
        self._paused_on_error = False
        self._error_action = ""   # "retry" | "skip"
        self._error_message = ""  # last error message while paused_on_error
        self._resume_generation = 0
        self._cancel_generation = 0
        self._total_steps = 0
        self._current_step = 0
        self._current_step_type = ""
        self._current_step_id = None
        self._current_step_path = None
        self._current_loop_iter = None
        self._current_step_started_at = None
        self._current_activity_id = None
        self._current_step_activity_id = None
        self._current_phase = None
        self._current_side_effect_class = None
        self._current_activity_attempt = 0
        self._current_message = ""
        self._running_step = False
        # Telemetry events waiting to ship. Two awaited activities per step were
        # ~2/3 of this workflow's event history; batching them trades at most
        # _EVENT_BUFFER_FLUSH_AT lost log records on a crash for a history that
        # does not reach the server's termination threshold. Each entry carries
        # its own workflow.now() stamp, so batching cannot reorder the timeline
        # relative to the activity-side events already being written.
        self._pending_events: list[dict[str, Any]] = []
        self._event_flush_seq = 0
        self._last_flush_at: datetime | None = None

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._resume_generation += 1
        self._paused = False

    @workflow.signal
    async def cancel_scenario(self) -> None:
        self._cancel_generation += 1
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

    @workflow.query
    def get_control_state(self) -> dict:
        return {
            "paused": self._paused,
            "cancelled": self._cancelled,
            "resume_generation": self._resume_generation,
            "cancel_generation": self._cancel_generation,
        }

    @workflow.query
    def get_live_progress(self) -> dict:
        elapsed_ms = 0
        if self._running_step and self._current_step_started_at is not None:
            elapsed_ms = int(
                (workflow.now() - self._current_step_started_at).total_seconds() * 1000
            )
        status = WorkflowStatus.RUNNING.value
        if self._cancelled:
            status = WorkflowStatus.CANCELLED.value
        elif self._paused_on_error:
            status = WorkflowStatus.PAUSED_ON_ERROR.value
        elif self._paused:
            status = WorkflowStatus.PAUSED.value
        return {
            "status": status,
            "current_step": self._current_step,
            "total_steps": self._total_steps,
            "current_step_type": self._current_step_type,
            "current_step_id": self._current_step_id,
            "current_step_path": self._current_step_path,
            "current_loop_iter": self._current_loop_iter,
            "current_activity_id": self._current_activity_id,
            "current_step_activity_id": self._current_step_activity_id,
            "current_phase": self._current_phase,
            "side_effect_class": self._current_side_effect_class,
            "activity_attempt": self._current_activity_attempt,
            "current_step_started_at": (
                self._current_step_started_at.isoformat()
                if self._current_step_started_at is not None
                else None
            ),
            "current_step_elapsed_ms": elapsed_ms,
            "running_step": self._running_step,
            "message": self._error_message or self._current_message,
        }

    @workflow.query
    def get_activity_progress(self) -> dict:
        return {
            "current_activity_id": self._current_activity_id,
            "current_step_activity_id": self._current_step_activity_id,
            "current_phase": self._current_phase,
            "side_effect_class": self._current_side_effect_class,
            "activity_attempt": self._current_activity_attempt,
            "current_step": self._current_step,
            "current_step_type": self._current_step_type,
            "current_step_id": self._current_step_id,
            "current_step_path": self._current_step_path,
            "current_loop_iter": self._current_loop_iter,
            "running_step": self._running_step,
        }

    async def _wait_if_paused(self) -> None:
        if self._paused and not self._cancelled:
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)

    def _mark_step_started(
        self,
        step_index: int,
        step_type: str,
        message: str = "",
        *,
        step_id: str | None = None,
        step_path: str | None = None,
        loop_iter: int | None = None,
    ) -> None:
        self._current_step = max(0, step_index)
        self._current_step_type = step_type
        self._current_step_id = step_id
        self._current_step_path = step_path
        self._current_loop_iter = loop_iter
        self._current_step_started_at = workflow.now()
        self._current_message = message
        self._running_step = True

    def _mark_activity_progress(
        self,
        *,
        activity_id: str | None,
        step_activity_id: str | None = None,
        phase: str | None = None,
        side_effect_class: str | None = None,
        activity_attempt: int = 0,
    ) -> None:
        self._current_activity_id = activity_id
        self._current_step_activity_id = step_activity_id
        self._current_phase = phase
        self._current_side_effect_class = side_effect_class
        self._current_activity_attempt = max(0, int(activity_attempt or 0))

    def _clear_activity_progress(self) -> None:
        self._current_activity_id = None
        self._current_step_activity_id = None
        self._current_phase = None
        self._current_side_effect_class = None
        self._current_activity_attempt = 0

    def _mark_step_finished(self, entry: dict[str, Any]) -> None:
        try:
            idx = int(entry.get("index", self._current_step))
        except Exception:
            idx = self._current_step
        self._current_step = max(self._current_step, idx + 1)
        self._current_step_type = str(entry.get("type") or self._current_step_type)
        self._current_step_id = str(entry.get("step_id") or entry.get("id") or self._current_step_id or "")
        self._current_step_path = str(entry.get("step_path") or self._current_step_path or "")
        self._current_loop_iter = entry.get("loop_iter", self._current_loop_iter)
        self._current_message = str(entry.get("message") or "")
        self._clear_activity_progress()
        self._running_step = False

    async def _buffer_event(
        self,
        inp: StepsInput,
        event_kind: str,
        event: dict[str, Any],
    ) -> None:
        """Queue one telemetry event; ship the batch once it is worth an activity.

        The workflow stamps occurred_at here rather than letting the flush
        activity do it, so a batched event keeps the ordering it had relative to
        the activity-side events emitted from activities.py.
        """
        now = workflow.now()
        event["event_kind"] = event_kind
        event["occurred_at"] = now.isoformat()
        self._pending_events.append(event)
        if self._last_flush_at is None:
            self._last_flush_at = now
        if (
            len(self._pending_events) >= _EVENT_BUFFER_FLUSH_AT
            or now - self._last_flush_at >= _EVENT_BUFFER_MAX_AGE
        ):
            await self._flush_events(inp)

    async def _flush_events(self, inp: StepsInput) -> None:
        if not self._pending_events:
            return
        batch = self._pending_events
        self._pending_events = []
        self._last_flush_at = workflow.now()
        self._event_flush_seq += 1
        try:
            await workflow.execute_activity(
                "emit_execution_events_batch",
                {"execution_id": inp.execution_id, "events": batch},
                start_to_close_timeout=timedelta(seconds=60),
                schedule_to_start_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
                task_queue=control_task_queue(),
                activity_id=workflow_activity_id(
                    execution_id=inp.execution_id,
                    activity_name="emit_execution_events_batch",
                    qualifier=self._event_flush_seq,
                ),
            )
        except Exception as exc:
            if _is_temporal_cancelled_error(exc):
                # Cancellation takes the flush with it. These are observation
                # records, not state — the real outcome still rides the normal
                # path (_cancelled_result, execution_steps).
                raise
            # workflow.logger, not logging.getLogger: this runs inside workflow
            # code, and a plain logger re-emits the line on every replay — the
            # same failure appearing three times looks like three failures.
            workflow.logger.warning(
                "emit_execution_events_batch failed for execution %s (%s events): %s",
                inp.execution_id,
                len(batch),
                _workflow_failure_message(exc),
            )

    async def _emit_control_flow_event(
        self,
        inp: StepsInput,
        *,
        event_type: str,
        step: dict[str, Any],
        step_index: int,
        trace: dict[str, Any] | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not inp.execution_id or not workflow.patched(_CONTROL_FLOW_EVENT_PATCH):
            return
        event = {
            "execution_id": inp.execution_id,
            "campaign_id": inp.campaign_id,
            "event_type": event_type,
            "step_id": _step_id(step, step_index),
            "step_index": step_index,
            "step_type": str(step.get("type") or ""),
            "depth": inp.depth,
            "trace": trace or {},
            "payload": payload or {},
        }
        if workflow.patched(_BUFFERED_EVENTS_PATCH):
            await self._buffer_event(inp, "control_flow", event)
            return
        try:
            await workflow.execute_activity(
                "emit_control_flow_event",
                event,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                task_queue=control_task_queue(),
                activity_id=(
                    workflow_activity_id(
                        execution_id=inp.execution_id,
                        activity_name="emit_control_flow_event",
                        step=step,
                        step_index=step_index,
                        qualifier=event_type,
                    )
                    if workflow.patched(_STEP_ACTIVITY_POLICY_PATCH)
                    else None
                ),
            )
        except Exception as exc:
            if _is_temporal_cancelled_error(exc):
                raise
            workflow.logger.warning(
                "emit_control_flow_event failed for execution %s step %s: %s",
                inp.execution_id,
                _step_id(step, step_index),
                _workflow_failure_message(exc),
            )

    async def _emit_temporal_activity_event(
        self,
        inp: StepsInput,
        *,
        event_type: str,
        step: dict[str, Any],
        step_index: int,
        trace: dict[str, Any] | None,
        activity_id: str | None,
        step_activity_id: str | None = None,
        phase: str,
        side_effect_class: str | None,
        activity_attempt: int,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not inp.execution_id or not workflow.patched(_TEMPORAL_ACTIVITY_EVENT_PATCH):
            return
        step_id = _step_id(step, step_index)
        event_payload: dict[str, Any] = {
            "activity_id": activity_id,
            "step_activity_id": step_activity_id or activity_id,
            "side_effect_class": side_effect_class,
            "activity_attempt": activity_attempt,
            "phase": phase,
        }
        for key, value in (payload or {}).items():
            if value is not None:
                event_payload[key] = value
        event = {
            "execution_id": inp.execution_id,
            "campaign_id": inp.campaign_id,
            "event_type": event_type,
            "step_id": step_id,
            "step_index": step_index,
            "step_type": str(step.get("type") or ""),
            "depth": inp.depth,
            "trace": trace or {},
            "payload": event_payload,
        }
        if workflow.patched(_BUFFERED_EVENTS_PATCH):
            await self._buffer_event(inp, "temporal_activity", event)
            return
        try:
            await workflow.execute_activity(
                "emit_temporal_activity_event",
                event,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_start_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=2),
                task_queue=control_task_queue(),
                activity_id=workflow_activity_id(
                    execution_id=inp.execution_id,
                    activity_name="emit_temporal_activity_event",
                    step=step,
                    step_index=step_index,
                    qualifier=f"{event_type}:{activity_attempt}:{activity_id or step_id}",
                ),
            )
        except Exception as exc:
            if _is_temporal_cancelled_error(exc):
                raise
            workflow.logger.warning(
                "emit_temporal_activity_event failed for execution %s activity %s: %s",
                inp.execution_id,
                activity_id,
                _workflow_failure_message(exc),
            )

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
        runtime_context: dict[str, Any] | None = None,
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
        temporal_step_policy_enabled = workflow.patched(_STEP_ACTIVITY_POLICY_PATCH)

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

            attempt_step = dict(activity_step)
            attempt_step["_account_action_outer_retry"] = {
                "attempt": attempt,
                "retry": dict(step.get("retry") or {}),
            }
            activity_id = None
            activity_attempt = attempt
            side_effect_class = None
            start_to_close_timeout = _LONG_TIMEOUT
            heartbeat_timeout = timedelta(seconds=30)
            retry_policy = _ACTIVITY_RETRY
            if temporal_step_policy_enabled:
                activity_policy = build_step_activity_policy(
                    execution_id=inp.execution_id or inp.run_id,
                    step=attempt_step,
                    step_index=step_index,
                    attempt=attempt,
                    default_start_to_close_timeout=_LONG_TIMEOUT,
                )
                activity_id = activity_policy.activity_id
                activity_attempt = activity_policy.attempt
                side_effect_class = activity_policy.side_effect_class
                start_to_close_timeout = activity_policy.start_to_close_timeout
                heartbeat_timeout = activity_policy.heartbeat_timeout
                retry_policy = activity_policy.retry_policy
            self._mark_activity_progress(
                activity_id=activity_id,
                step_activity_id=activity_id,
                phase="scheduled",
                side_effect_class=side_effect_class,
                activity_attempt=activity_attempt,
            )
            activity_started_at = workflow.now()
            await self._emit_temporal_activity_event(
                inp,
                event_type=(
                    TEMPORAL_ACTIVITY_RETRYING
                    if activity_attempt > 1
                    else TEMPORAL_ACTIVITY_SCHEDULED
                ),
                step=attempt_step,
                step_index=step_index,
                trace=trace_from_runtime_context(runtime_context or {}),
                activity_id=activity_id,
                step_activity_id=activity_id,
                phase="scheduled",
                side_effect_class=side_effect_class,
                activity_attempt=activity_attempt,
            )
            try:
                sr: StepResult = await workflow.execute_activity(
                    "execute_device_action",
                    DeviceActionInput(
                        device_serial=inp.device_serial,
                        step=attempt_step,
                        step_index=step_index,
                        variables=inp.variables,
                        campaign_vars=inp.campaign_vars,
                        scenario_config=getattr(inp, "scenario_config", {}),
                        scenario_registry=inp.scenario_registry,
                        execution_id=inp.execution_id or inp.run_id,
                        campaign_id=inp.campaign_id,
                        depth=inp.depth,
                        context=dict(runtime_context or {}),
                        activity_id=activity_id,
                        activity_attempt=activity_attempt,
                        side_effect_class=side_effect_class,
                    ),
                    result_type=StepResult,
                    start_to_close_timeout=start_to_close_timeout,
                    retry_policy=retry_policy,
                    heartbeat_timeout=heartbeat_timeout,
                    activity_id=activity_id,
                )
            except Exception as exc:
                if _is_temporal_cancelled_error(exc):
                    raise
                failure_message = _workflow_failure_message(exc)
                failure_duration_ms = int(
                    (workflow.now() - activity_started_at).total_seconds() * 1000
                )
                if _activity_failure_suggests_stall(failure_message):
                    await self._emit_temporal_activity_event(
                        inp,
                        event_type=TEMPORAL_ACTIVITY_STALLED,
                        step=attempt_step,
                        step_index=step_index,
                        trace=trace_from_runtime_context(runtime_context or {}),
                        activity_id=activity_id,
                        step_activity_id=activity_id,
                        phase="stalled",
                        side_effect_class=side_effect_class,
                        activity_attempt=activity_attempt,
                        payload={
                            "ok": False,
                            "message": failure_message,
                            "stalled_reason": "temporal_activity_timeout",
                            "duration_ms": failure_duration_ms,
                        },
                    )
                await self._emit_temporal_activity_event(
                    inp,
                    event_type=TEMPORAL_ACTIVITY_FAILED,
                    step=attempt_step,
                    step_index=step_index,
                    trace=trace_from_runtime_context(runtime_context or {}),
                    activity_id=activity_id,
                    step_activity_id=activity_id,
                    phase="failed",
                    side_effect_class=side_effect_class,
                    activity_attempt=activity_attempt,
                    payload={
                        "ok": False,
                        "message": failure_message,
                        "duration_ms": failure_duration_ms,
                    },
                )
                raise
            entry = self._step_result_dict(sr, step_index)
            final_entry = entry
            await self._emit_temporal_activity_event(
                inp,
                event_type=(
                    TEMPORAL_ACTIVITY_COMPLETED
                    if entry.get("ok", True)
                    else TEMPORAL_ACTIVITY_FAILED
                ),
                step=attempt_step,
                step_index=step_index,
                trace=trace_from_runtime_context(runtime_context or {}),
                activity_id=activity_id,
                step_activity_id=activity_id,
                phase="completed" if entry.get("ok", True) else "failed",
                side_effect_class=side_effect_class,
                activity_attempt=activity_attempt,
                payload={
                    "ok": bool(entry.get("ok", True)),
                    "message": entry.get("message"),
                    "reason_code": entry.get("reason_code"),
                    "duration_ms": int(
                        (workflow.now() - activity_started_at).total_seconds() * 1000
                    ),
                },
            )

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
                #
                # Carry the whole list and resume via start_step rather than
                # slicing. Slicing makes the continuation re-enumerate from 0,
                # and execution_steps is keyed on (execution_id, step_index), so
                # every step after a retry would overwrite the rows written
                # before it. Measured on the sibling history-threshold path: 60
                # step executions collapsed into 35 distinct indices.
                retry_steps, retry_start = inp.steps[step_idx:], 0
                if workflow.patched(_RETRY_ABSOLUTE_INDEX_PATCH):
                    retry_steps, retry_start = inp.steps, step_idx
                await workflow.continue_as_new(
                    StepsInput(
                        device_serial=inp.device_serial,
                        steps=retry_steps,
                        start_step=retry_start,
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

    def _append_step_log(self, entry: dict) -> None:
        self._step_log.append(entry)
        overflow = len(self._step_log) - _STEP_LOG_MAX
        if overflow > 0:
            del self._step_log[:overflow]
            self._step_log_dropped += overflow

    @workflow.query
    def get_step_log(self) -> list[dict]:
        """Query accumulated step execution log (works while running or after completion).

        Returns the most recent _STEP_LOG_MAX entries. When older ones were
        dropped, a marker entry says so rather than silently presenting a
        truncated log as if it were complete.
        """
        if not self._step_log_dropped:
            return self._step_log
        marker = {
            "type": "_truncated",
            "dropped": self._step_log_dropped,
            "message": (
                f"{self._step_log_dropped} earlier step(s) dropped from this "
                f"in-memory log; execution_steps in the database has them all"
            ),
        }
        return [marker, *self._step_log]

    # Legacy threshold, kept for runs that started before _CAN_SUGGESTED_PATCH.
    # Each activity execution = ~3 events (Scheduled + Started + Completed), so
    # 10K events is ~3.3K activity calls. It counts events only, which is the
    # flaw: Temporal also refuses at 50MB of history, and payload_guard allows
    # 64KB per field, so size hits the wall first on result-heavy scenarios.
    _HISTORY_CONTINUE_THRESHOLD = 10_000

    @staticmethod
    def _history_limit_reached() -> bool:
        """True when this run should stop growing its event history.

        The server decides, weighing both event count and history size; the
        constant below could only see count.
        """
        info = workflow.info()
        if workflow.patched(_CAN_SUGGESTED_PATCH):
            return bool(info.is_continue_as_new_suggested()) or (
                info.get_current_history_length()
                >= ScenarioStepsWorkflow._HISTORY_CONTINUE_THRESHOLD
            )
        return info.get_current_history_length() >= (
            ScenarioStepsWorkflow._HISTORY_CONTINUE_THRESHOLD
        )

    @workflow.run
    async def run(self, inp: StepsInput) -> StepsResult:
        # Thin wrapper so the buffered telemetry gets one guaranteed flush.
        # _run_steps has 13 return statements; patching each would be a standing
        # invitation to miss the fourteenth.
        #
        # _execute_child_steps re-enters run() at depth+1, so nested invocations
        # pass through here without flushing — only the root ships the buffer,
        # which is where it lives.
        try:
            return await self._run_steps(inp)
        finally:
            if inp.depth == 0 and self._pending_events:
                try:
                    await self._flush_events(inp)
                except BaseException:  # noqa: BLE001 — telemetry never decides the outcome
                    # A cancel that lands here would otherwise replace the real
                    # result with a flush error. The workflow ends immediately
                    # after, so swallowing cannot make it uncancellable.
                    pass

    async def _run_steps(self, inp: StepsInput) -> StepsResult:
        if inp.depth > MAX_NESTING_DEPTH:
            return StepsResult(
                success=False, steps_executed=0,
                failed_message=f"Max nesting depth {MAX_NESTING_DEPTH} exceeded",
            )

        # Shared execution context: posts, text_nodes, _no_new_streak, vars (legacy ctx)
        runtime_context: dict[str, Any] = dict(inp.context)
        context_vars = runtime_context.get("vars")
        runtime_vars: dict[str, Any] = {
            **(context_vars if isinstance(context_vars, dict) else {}),
            **inp.variables,
            **inp.parent_runtime_vars,
        }
        # Seed from accumulated_results so retry/history-reset continue_as_new calls
        # preserve the results of already-completed steps.
        #
        # checkpointed_steps counts steps whose results were flushed to
        # execution_steps and then dropped from the payload, so the running
        # totals stay right even though the list itself no longer holds them.
        step_results: list[dict[str, Any]] = list(inp.accumulated_results)
        checkpointed_steps = max(0, int(getattr(inp, "checkpointed_steps", 0) or 0))
        steps_executed = checkpointed_steps + len(step_results)
        if int(getattr(inp, "start_step", 0) or 0) > 0:
            # Absolute-index continuation: inp.steps is the whole scenario and
            # start_step says where to resume, so it already is the total.
            self._total_steps = len(inp.steps)
        else:
            self._total_steps = max(len(inp.steps), steps_executed + len(inp.steps))
        self._current_step = max(self._current_step, steps_executed)
        break_requested = False

        def _append(entry: dict) -> None:
            step_results.append(entry)
            self._append_step_log({**entry, "depth": inp.depth})
            self._mark_step_finished(entry)

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
            nonlocal steps_executed, runtime_context
            if not _pending_steps:
                return True, "", -1
            n = len(_pending_steps)
            orig_steps = list(_pending_steps)      # snapshot before clear
            orig_indices = list(_pending_indices)  # snapshot before clear
            batch_start_to_close_timeout = _batch_start_to_close_timeout(
                n,
                getattr(inp, "scenario_config", {}),
            )
            batch_activity_id = None
            batch_step_activity_ids: list[str] = []
            batch_side_effect_class = None
            if workflow.patched(_STEP_ACTIVITY_POLICY_PATCH):
                batch_policy = build_batch_activity_policy(
                    execution_id=inp.execution_id or inp.run_id,
                    steps=orig_steps,
                    step_indices=orig_indices,
                    start_to_close_timeout=batch_start_to_close_timeout,
                )
                batch_activity_id = batch_policy.activity_id
                batch_step_activity_ids = batch_policy.step_activity_ids
                batch_side_effect_class = batch_policy.side_effect_class
            batch_trace = trace_from_runtime_context(runtime_context)
            batch_started_at = workflow.now()
            if orig_steps and orig_indices:
                first_step = orig_steps[0]
                self._mark_step_started(
                    orig_indices[0],
                    str(first_step.get("type") or ""),
                    f"running batch {len(orig_steps)} step(s)",
                )
                self._mark_activity_progress(
                    activity_id=batch_activity_id,
                    step_activity_id=(
                        batch_step_activity_ids[0]
                        if batch_step_activity_ids
                        else None
                    ),
                    phase="scheduled_batch",
                    side_effect_class=batch_side_effect_class,
                    activity_attempt=1,
                )
                await self._emit_temporal_activity_event(
                    inp,
                    event_type=TEMPORAL_ACTIVITY_SCHEDULED,
                    step=first_step,
                    step_index=orig_indices[0],
                    trace=batch_trace,
                    activity_id=batch_activity_id,
                    step_activity_id=(
                        batch_step_activity_ids[0]
                        if batch_step_activity_ids
                        else None
                    ),
                    phase="scheduled_batch",
                    side_effect_class=batch_side_effect_class,
                    activity_attempt=1,
                    payload={
                        "batch_size": len(orig_steps),
                        "batch_first_step_index": orig_indices[0],
                        "batch_last_step_index": orig_indices[-1],
                        "batch_step_activity_ids": batch_step_activity_ids,
                    },
                )
            try:
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
                        run_id=inp.run_id,
                        execution_id=inp.execution_id,
                        campaign_id=inp.campaign_id,
                        depth=inp.depth,
                        context=dict(runtime_context),
                        activity_id=batch_activity_id,
                        step_activity_ids=batch_step_activity_ids,
                        side_effect_class=batch_side_effect_class,
                    ),
                    result_type=DeviceActionBatchResult,
                    start_to_close_timeout=batch_start_to_close_timeout,
                    retry_policy=_DEVICE_ACTION_RETRY,
                    # Extract/comment steps can run minutes; keep margin over 5s heartbeat loop.
                    heartbeat_timeout=timedelta(seconds=60),
                    activity_id=batch_activity_id,
                )
            except Exception as exc:
                if _is_temporal_cancelled_error(exc):
                    raise
                failed_orig_idx = orig_indices[0] if orig_indices else -1
                failed_step = orig_steps[0] if orig_steps else {}
                failed_type = str(failed_step.get("type") or "batch")
                failed_message = _workflow_failure_message(
                    exc,
                    fallback=f"{failed_type}: activity failed before returning a step result",
                )
                failed_duration_ms = int(
                    (workflow.now() - batch_started_at).total_seconds() * 1000
                )
                if _activity_failure_suggests_stall(failed_message):
                    await self._emit_temporal_activity_event(
                        inp,
                        event_type=TEMPORAL_ACTIVITY_STALLED,
                        step=failed_step,
                        step_index=failed_orig_idx if failed_orig_idx >= 0 else 0,
                        trace=batch_trace,
                        activity_id=batch_activity_id,
                        step_activity_id=(
                            batch_step_activity_ids[0]
                            if batch_step_activity_ids
                            else None
                        ),
                        phase="stalled_batch",
                        side_effect_class=batch_side_effect_class,
                        activity_attempt=1,
                        payload={
                            "ok": False,
                            "message": failed_message,
                            "stalled_reason": "temporal_activity_timeout",
                            "duration_ms": failed_duration_ms,
                            "batch_size": len(orig_steps),
                            "batch_first_step_index": failed_orig_idx,
                            "batch_last_step_index": orig_indices[-1]
                            if orig_indices
                            else failed_orig_idx,
                            "batch_step_activity_ids": batch_step_activity_ids,
                        },
                    )
                await self._emit_temporal_activity_event(
                    inp,
                    event_type=TEMPORAL_ACTIVITY_FAILED,
                    step=failed_step,
                    step_index=failed_orig_idx if failed_orig_idx >= 0 else 0,
                    trace=batch_trace,
                    activity_id=batch_activity_id,
                    step_activity_id=(
                        batch_step_activity_ids[0]
                        if batch_step_activity_ids
                        else None
                    ),
                    phase="failed_batch",
                    side_effect_class=batch_side_effect_class,
                    activity_attempt=1,
                    payload={
                        "ok": False,
                        "message": failed_message,
                        "duration_ms": failed_duration_ms,
                        "batch_size": len(orig_steps),
                        "batch_first_step_index": failed_orig_idx,
                        "batch_last_step_index": orig_indices[-1]
                        if orig_indices
                        else failed_orig_idx,
                        "batch_step_activity_ids": batch_step_activity_ids,
                    },
                )
                self._clear_activity_progress()
                _pending_steps.clear()
                _pending_indices.clear()
                if len(orig_steps) > 1:
                    _pending_steps[:0] = orig_steps[1:]
                    _pending_indices[:0] = orig_indices[1:]
                _append({
                    "index": failed_orig_idx if failed_orig_idx >= 0 else 0,
                    "type": failed_type,
                    "ok": False,
                    "message": failed_message,
                })
                steps_executed += 1
                return False, failed_message, failed_orig_idx
            batch_failure_index = batch_result.first_failure_index
            if batch_failure_index < 0:
                for rel_idx, result in enumerate(batch_result.results):
                    if isinstance(result, dict) and not bool(result.get("ok", True)):
                        batch_failure_index = rel_idx
                        break
            batch_event_ok = (
                batch_failure_index < 0
                and not batch_result.cancelled_mid_batch
            )
            if orig_steps and orig_indices:
                await self._emit_temporal_activity_event(
                    inp,
                    event_type=(
                        TEMPORAL_ACTIVITY_COMPLETED
                        if batch_event_ok
                        else TEMPORAL_ACTIVITY_FAILED
                    ),
                    step=orig_steps[0],
                    step_index=orig_indices[0],
                    trace=batch_trace,
                    activity_id=batch_activity_id,
                    step_activity_id=(
                        batch_step_activity_ids[0]
                        if batch_step_activity_ids
                        else None
                    ),
                    phase="completed_batch" if batch_event_ok else "failed_batch",
                    side_effect_class=batch_side_effect_class,
                    activity_attempt=1,
                    payload={
                        "ok": batch_event_ok,
                        "duration_ms": int(
                            (workflow.now() - batch_started_at).total_seconds()
                            * 1000
                        ),
                        "batch_size": len(orig_steps),
                        "batch_first_step_index": orig_indices[0],
                        "batch_last_step_index": orig_indices[-1],
                        "batch_step_activity_ids": batch_step_activity_ids,
                        "paused_mid_batch": batch_result.paused_mid_batch,
                        "cancelled_mid_batch": batch_result.cancelled_mid_batch,
                    },
                )
            _pending_steps.clear()
            _pending_indices.clear()
            if batch_result.context:
                previous_context_vars = runtime_context.get("vars")
                parent_trace = trace_from_runtime_context(runtime_context)
                runtime_context = {**runtime_context, **batch_result.context}
                if parent_trace:
                    runtime_context[TRACE_CONTEXT_KEY] = parent_trace
                else:
                    runtime_context.pop(TRACE_CONTEXT_KEY, None)
                context_vars = batch_result.context.get("vars")
                if isinstance(context_vars, dict):
                    previous = (
                        previous_context_vars
                        if isinstance(previous_context_vars, dict)
                        else {}
                    )
                    runtime_vars.update(
                        {
                            key: value
                            for key, value in context_vars.items()
                            if key not in previous or previous[key] != value
                        }
                    )
            for r in batch_result.results:
                _append(r)
                steps_executed += 1
            failed_rel_idx = batch_result.first_failure_index
            if failed_rel_idx < 0:
                for rel_idx, result in enumerate(batch_result.results):
                    if isinstance(result, dict) and not bool(result.get("ok", True)):
                        failed_rel_idx = rel_idx
                        break
            if failed_rel_idx >= 0:
                failed_rel_idx = min(failed_rel_idx, max(0, len(orig_steps) - 1))
                if failed_rel_idx + 1 < len(orig_steps):
                    _pending_steps[:0] = orig_steps[failed_rel_idx + 1:]
                    _pending_indices[:0] = orig_indices[failed_rel_idx + 1:]
                failed = (
                    batch_result.results[failed_rel_idx]
                    if failed_rel_idx < len(batch_result.results)
                    else {}
                )
                failed_message = (
                    failed.get("message", "batch step failed")
                    if isinstance(failed, dict)
                    else "batch step failed"
                )
                failed_orig_idx = (
                    orig_indices[failed_rel_idx]
                    if failed_rel_idx < len(orig_indices)
                    else -1
                )
                return False, failed_message, failed_orig_idx
            if batch_result.paused_mid_batch:
                consumed = min(len(batch_result.results), len(orig_steps))
                _pending_steps[:0] = orig_steps[consumed:]
                _pending_indices[:0] = orig_indices[consumed:]
                resume_generation = self._resume_generation
                cancel_generation = self._cancel_generation
                self._paused = True
                await workflow.wait_condition(
                    lambda: self._cancelled
                    or self._cancel_generation > cancel_generation
                    or (
                        not self._paused
                        and self._resume_generation > resume_generation
                    )
                )
                if self._cancelled or self._cancel_generation > cancel_generation:
                    return False, "Cancelled during execution", -1
                if _pending_steps:
                    return await _flush_batch()
                return True, "", -1
            if batch_result.cancelled_mid_batch or self._cancelled:
                return False, "Cancelled during execution", -1
            return True, "", -1

        async def _drain_pending_batch() -> StepsResult | None:
            while _pending_steps:
                ok, msg, failed_idx = await _flush_batch()
                if ok:
                    continue
                if self._cancelled or failed_idx < 0:
                    return self._cancelled_result(
                        inp, steps_executed, step_results, runtime_vars, runtime_context
                    )
                failed_step = inp.steps[failed_idx] if 0 <= failed_idx < len(inp.steps) else {}
                action, early = await self._apply_error_policy(
                    failed_step, failed_idx, msg, inp, runtime_vars, runtime_context,
                    steps_executed, step_results,
                )
                if action == "stop":
                    return early
            return None

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
                if self._history_limit_reached():
                    # Kept in the log next to the server's verdict so the two
                    # can be compared on a real run.
                    workflow.logger.info(
                        "continue_as_new at %s events (step %s)",
                        workflow.info().get_current_history_length(),
                        idx,
                    )
                    carried = list(step_results)
                    carried_count = checkpointed_steps
                    # Flush the results to execution_steps and continue with an
                    # empty payload. Without this, continue_as_new resets history
                    # but drags every past step result along at ~1KB each, so a
                    # long scenario walks toward the 2MB blob limit — the one
                    # thing continue_as_new was supposed to prevent.
                    # Legacy shape: slice the steps, so the continuation
                    # re-enumerates from 0 and step indices restart.
                    next_steps, next_start = inp.steps[idx:], 0
                    if carried and inp.execution_id and workflow.patched(_STEP_CHECKPOINT_PATCH):
                        # Keep the full list and resume via start_step so indices
                        # stay absolute. This is not cosmetic: execution_steps is
                        # keyed on (execution_id, step_index), so restarting the
                        # numbering would make the steps after this point
                        # overwrite the rows we are about to write — destroying
                        # the very audit trail the checkpoint exists to keep.
                        # It is also what lets finalize recognise a trimmed
                        # payload, which no longer begins at index 0.
                        next_steps, next_start = inp.steps, idx
                        await workflow.execute_activity(
                            "persist_step_checkpoint",
                            {
                                "execution_id": inp.execution_id,
                                "device_serial": inp.device_serial,
                                "step_results": carried,
                            },
                            start_to_close_timeout=timedelta(seconds=60),
                            retry_policy=RetryPolicy(maximum_attempts=3),
                            activity_id=(
                                workflow_activity_id(
                                    execution_id=inp.execution_id,
                                    activity_name="persist_step_checkpoint",
                                    qualifier=idx,
                                )
                                if workflow.patched(_STEP_ACTIVITY_POLICY_PATCH)
                                else None
                            ),
                        )
                        carried_count = checkpointed_steps + len(carried)
                        carried = []
                    # Explicit, not via the run() finally: continue_as_new is
                    # driven by an SDK-internal exception, and awaiting an
                    # activity while that unwinds is undefined territory. Flush
                    # here and the finally finds an empty buffer.
                    await self._flush_events(inp)
                    await workflow.continue_as_new(
                        StepsInput(
                            device_serial=inp.device_serial,
                            steps=next_steps,
                            start_step=next_start,
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
                            accumulated_results=carried,
                            checkpointed_steps=carried_count,
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
            step_trace_context = step_trace_from_context(runtime_context, step=step, step_index=idx)
            step_trace = trace_from_runtime_context(step_trace_context)
            step = {
                **step,
                **{
                    key: value
                    for key, value in step_trace.items()
                    if key in {
                        "step_path",
                        "loop_iter",
                        "loop_id",
                        "branch",
                        "step_id",
                        "step_type",
                        "depth",
                    }
                },
            }
            step_path = step_trace.get("step_path")
            step_loop_iter = step_trace.get("loop_iter")
            self._mark_step_started(
                idx,
                str(step_type or ""),
                step_id=_step_id(step, idx),
                step_path=str(step_path) if step_path is not None else None,
                loop_iter=step_loop_iter if isinstance(step_loop_iter, int) else None,
            )

            # ── Flush pending batch before any control-flow step ─────────────
            # Leaf steps accumulate in _pending_steps; control-flow types force
            # a flush so results are appended in execution order.
            if step_type in _CONTROL_FLOW_TYPES:
                early = await _drain_pending_batch()
                if early is not None:
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
                            campaign_id=inp.campaign_id,
                        ),
                        result_type=bool,
                        **_step_activity_options(
                            inp,
                            step,
                            idx,
                            activity_step_type="evaluate_legacy_condition",
                            default_start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                            default_retry_policy=_ACTIVITY_RETRY,
                            default_heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                        ),
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, sub_results, runtime_context, control_payload = await self._handle_loop(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {
                    "index": idx, "type": "loop", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                    "trace": step_trace,
                    **control_payload,
                }
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={k: v for k, v in entry.items() if k != "sub_results"},
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, runtime_context, child_break, control_payload = await self._handle_if(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {"index": idx, "type": "if", "ok": ok, "message": msg, "trace": step_trace, **control_payload}
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload=entry,
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, sub_results, runtime_context, control_payload = await self._handle_repeat(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {
                    "index": idx, "type": "repeat", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                    "trace": step_trace,
                    **control_payload,
                }
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={k: v for k, v in entry.items() if k != "sub_results"},
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, runtime_context, control_payload = await self._handle_repeat_until(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {"index": idx, "type": "repeat_until", "ok": ok, "message": msg, "trace": step_trace, **control_payload}
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload=entry,
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, runtime_context, child_break, control_payload = await self._handle_if_element(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {"index": idx, "type": "if_element", "ok": ok, "message": msg, "trace": step_trace, **control_payload}
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload=entry,
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, runtime_context, child_break, control_payload = await self._handle_if_variable(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {"index": idx, "type": "if_variable", "ok": ok, "message": msg, "trace": step_trace, **control_payload}
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload=entry,
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, runtime_context, child_break, control_payload = await self._handle_random_pick(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {"index": idx, "type": "random_pick", "ok": ok, "message": msg, "trace": step_trace, **control_payload}
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload=entry,
                )
                _append(entry)
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
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_STARTED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={"ok": True},
                )
                ok, msg, sub_results, runtime_context, control_payload = await self._handle_run_scenario(
                    inp, step, runtime_vars, runtime_context, idx,
                )
                entry = {
                    "index": idx, "type": "run_scenario", "ok": ok,
                    "message": msg, "sub_results": sub_results,
                    "trace": step_trace,
                    **control_payload,
                }
                await self._emit_control_flow_event(
                    inp,
                    event_type=STEP_COMPLETED if ok else STEP_FAILED,
                    step=step,
                    step_index=idx,
                    trace=step_trace,
                    payload={k: v for k, v in entry.items() if k != "sub_results"},
                )
                steps_executed += 1
                if not ok:
                    policy = _error_policy(step, inp.scenario_config or {})
                    if (
                        policy == "continue"
                        and _run_scenario_failure_can_be_ignored(msg, sub_results)
                    ):
                        entry["error_policy"] = policy
                        entry["error_ignored"] = True
                        entry["marked_ignored"] = True
                        entry["ignored_failure"] = True
                        entry["ignored_message"] = msg
                        entry["message"] = f"{msg}; ignored by parent run_scenario policy"
                        entry["ok"] = True
                        _append(entry)
                        continue
                    _append(entry)
                    action, early = await self._apply_error_policy(
                        step, idx, msg, inp, runtime_vars, runtime_context,
                        steps_executed, step_results,
                    )
                    if action == "stop":
                        return early
                    continue
                _append(entry)
                continue

            # ── extract — writes to context (posts / text_nodes) ─────────────
            if step_type == "extract":
                extract_activity_policy = None
                if workflow.patched(_STEP_ACTIVITY_POLICY_PATCH):
                    extract_activity_policy = build_step_activity_policy(
                        execution_id=inp.execution_id or inp.run_id,
                        step=step,
                        step_index=idx,
                        default_start_to_close_timeout=_LONG_TIMEOUT,
                    )
                extract_result: ExtractResult = await workflow.execute_activity(
                    "execute_extract",
                    ExtractInput(
                        device_serial=inp.device_serial,
                        step=step,
                        step_index=idx,
                        context=step_trace_context,
                        scenario_config=inp.scenario_config,
                        campaign_id=inp.campaign_id,
                        run_id=inp.run_id,
                        execution_id=inp.execution_id or inp.run_id,
                        user_id=inp.campaign_vars.get("__USER_ID__"),
                    ),
                    result_type=ExtractResult,
                    start_to_close_timeout=(
                        extract_activity_policy.start_to_close_timeout
                        if extract_activity_policy is not None
                        else _LONG_TIMEOUT
                    ),
                    retry_policy=(
                        extract_activity_policy.retry_policy
                        if extract_activity_policy is not None
                        else _ACTIVITY_RETRY
                    ),
                    heartbeat_timeout=(
                        extract_activity_policy.heartbeat_timeout
                        if extract_activity_policy is not None
                        else timedelta(seconds=30)
                    ),
                    activity_id=(
                        extract_activity_policy.activity_id
                        if extract_activity_policy is not None
                        else None
                    ),
                )
                parent_trace = trace_from_runtime_context(runtime_context)
                runtime_context = {**runtime_context, **extract_result.context}
                if parent_trace:
                    runtime_context[TRACE_CONTEXT_KEY] = parent_trace
                else:
                    runtime_context.pop(TRACE_CONTEXT_KEY, None)
                _append({
                    "index": idx, "type": "extract",
                    "ok": extract_result.ok,
                    "message": _with_persist_metrics(extract_result.message, extract_result.details),
                    "details": extract_result.details,
                    "trace": step_trace,
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
                save_activity_policy = None
                if workflow.patched(_STEP_ACTIVITY_POLICY_PATCH):
                    save_activity_policy = build_step_activity_policy(
                        execution_id=inp.execution_id or inp.run_id,
                        step=step,
                        step_index=idx,
                        default_start_to_close_timeout=timedelta(seconds=120),
                    )
                save_result: StepResult = await workflow.execute_activity(
                    "execute_save_extraction",
                    SaveExtractionInput(
                        device_serial=inp.device_serial,
                        step=step,
                        step_index=idx,
                        context=step_trace_context,
                        campaign_id=inp.campaign_id,
                        run_id=inp.run_id,
                        execution_id=inp.execution_id,
                        account_id=(
                            runtime_context.get("__ACCOUNT_ID__")
                            or inp.variables.get("__ACCOUNT_ID__")
                            or inp.campaign_vars.get("__ACCOUNT_ID__")
                        ),
                        user_id=inp.campaign_vars.get("__USER_ID__"),
                        campaign_vars=dict(inp.campaign_vars or {}),
                    ),
                    result_type=StepResult,
                    start_to_close_timeout=(
                        save_activity_policy.start_to_close_timeout
                        if save_activity_policy is not None
                        else timedelta(seconds=120)
                    ),
                    retry_policy=(
                        save_activity_policy.retry_policy
                        if save_activity_policy is not None
                        else _ACTIVITY_RETRY
                    ),
                    heartbeat_timeout=(
                        save_activity_policy.heartbeat_timeout
                        if save_activity_policy is not None
                        else timedelta(seconds=60)
                    ),
                    activity_id=(
                        save_activity_policy.activity_id
                        if save_activity_policy is not None
                        else None
                    ),
                )
                # Apply offset update returned by the activity so retries skip processed items.
                parent_trace = trace_from_runtime_context(runtime_context)
                if save_result.details and "updated_offsets" in save_result.details:
                    offsets = dict(runtime_context.get("__save_extraction_offsets__") or {})
                    offsets.update(save_result.details["updated_offsets"])
                    runtime_context = {**runtime_context, "__save_extraction_offsets__": offsets}
                if parent_trace:
                    runtime_context[TRACE_CONTEXT_KEY] = parent_trace
                else:
                    runtime_context.pop(TRACE_CONTEXT_KEY, None)
                _append({
                    "index": idx, "type": "save_extraction",
                    "ok": save_result.ok,
                    "message": _with_persist_metrics(save_result.message, save_result.details),
                    "details": save_result.details,
                    "trace": step_trace,
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
                early = await _drain_pending_batch()
                if early is not None:
                    return early

                entry = await self._execute_leaf_with_durable_retry(
                    inp,
                    step,
                    idx,
                    runtime_context=step_trace_context,
                )
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
                early = await _drain_pending_batch()
                if early is not None:
                    return early

        # Flush any remaining leaf steps accumulated after the last control-flow step.
        early = await _drain_pending_batch()
        if early is not None:
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
    ) -> tuple[bool, str, list, dict, dict[str, Any]]:
        """Handle loop step: count or while condition, supports break_if."""
        count_raw = step.get("count")
        while_cond = step.get("while")
        max_iterations = max(1, min(int(step.get("max_iterations", 100) or 100), 10_000))
        sub_steps = step.get("steps") or []

        if not sub_steps:
            return (
                False,
                "loop: no nested steps",
                [],
                runtime_context,
                {"reason_code": LOOP_NO_NESTED_STEPS, "stopped_by": "config"},
            )

        # Random ranges. Same contract as the executor copy: count_min/count_max
        # win over `count` because the editor's loop form always writes a count,
        # and wf_random keeps the pick replay-deterministic.
        count_range, count_range_err = _loop_random_range(
            step.get("count_min"), step.get("count_max"), int,
        )
        delay_range, delay_range_err = _loop_random_range(
            step.get("delay_between_min"), step.get("delay_between_max"), float,
        )
        range_err = count_range_err or delay_range_err
        if range_err:
            return (
                False,
                f"loop: {range_err}",
                [],
                runtime_context,
                {"reason_code": LOOP_INVALID_COUNT, "stopped_by": "config"},
            )
        if delay_range is not None:
            delay_range = (min(delay_range[0], 300.0), min(delay_range[1], 300.0))
        wf_random = _get_wf_random()

        if count_range is not None:
            # Picked once: every iteration of this run shares one budget.
            iterations = wf_random.randint(*count_range)
            runtime_vars["__LOOP_COUNT__"] = iterations
            use_while = False
        elif count_raw is not None:
            try:
                # count is explicit — max_iterations applies to while-only loops.
                iterations = int(count_raw)
            except (TypeError, ValueError):
                return (
                    False,
                    f"loop: invalid count={count_raw!r}",
                    [],
                    runtime_context,
                    {"reason_code": LOOP_INVALID_COUNT, "stopped_by": "config"},
                )
            use_while = False
        elif while_cond:
            iterations = max_iterations
            use_while = True
        else:
            return (
                False,
                "loop: must specify either 'count' or 'while'",
                [],
                runtime_context,
                {"reason_code": LOOP_INVALID_COUNT, "stopped_by": "config"},
            )

        sub_results: list[dict[str, Any]] = []
        sub_result_state: dict[str, Any] = {}
        actual_iters = 0
        parent_ctx = dict(runtime_context)
        parent_trace = trace_from_runtime_context(runtime_context)
        ctx = dict(parent_ctx)
        loop_var = str(step.get("loop_var") or "").strip()

        # Campaigns run their loops here, not in tasks/scenario/steps/control_flow.py
        # — that one only drives directly-run and nested scenarios. Both need the
        # same two properties, so both carry them; a measured campaign run span
        # 204 iterations in 8.5 minutes on a screen it could not act on because
        # only the other copy had been taught to stop.
        try:
            stall_after = int(step.get("stall_after", 0) or 0)
        except (TypeError, ValueError):
            stall_after = 0
        try:
            idle_delay_s = float(step.get("idle_delay_seconds", 0) or 0)
        except (TypeError, ValueError):
            idle_delay_s = 0.0
        idle_delay_s = max(0.0, min(idle_delay_s, 300.0))
        idle_streak = 0

        for i in range(iterations):
            # continue_as_new cannot be called from here: _execute_child_steps
            # recurses into self.run() at depth+1, inside the same workflow, and
            # the guard at depth 0 never runs again once a loop is entered. So a
            # long loop grows history until the server terminates the run and
            # the whole trace is lost. Stopping deliberately keeps every
            # iteration that already completed — refuse the action when the
            # ground is not solid.
            if self._history_limit_reached():
                ctx.pop("_loop_iter", None)
                _finish_sub_results(sub_results, sub_result_state)
                return (
                    False,
                    f"loop stopped at iteration {i}: {LOOP_HISTORY_LIMIT}",
                    sub_results,
                    parent_ctx,
                    {
                        "reason_code": LOOP_HISTORY_LIMIT,
                        "iterations_run": actual_iters,
                        "stopped_by": "history_limit",
                        # Not a failure of the work: every iteration that ran
                        # succeeded. The run hit its event-history budget.
                        "partial": True,
                        "history_length": workflow.info().get_current_history_length(),
                        "idle_streak": idle_streak,
                    },
                )
            runtime_vars["__LOOP_ITER__"] = i
            if loop_var:
                runtime_vars[loop_var] = i
            ctx = push_step_path(
                parent_ctx,
                step_id=_step_id(step, idx),
                loop_iter=i,
                step_type="loop",
                step_index=idx,
            )
            self._mark_step_started(
                idx,
                "loop",
                f"loop iteration {i}",
                step_id=_step_id(step, idx),
                step_path=trace_from_runtime_context(ctx).get("step_path"),
                loop_iter=i,
            )
            ctx["_loop_iter"] = i

            if use_while:
                try:
                    cond_met: bool = await workflow.execute_activity(
                        "evaluate_legacy_condition",
                        LegacyConditionCheckInput(
                            device_serial=inp.device_serial,
                            condition=while_cond,
                            runtime_vars=runtime_vars,
                            context=ctx,
                            execution_id=inp.execution_id or inp.run_id,
                            campaign_id=inp.campaign_id,
                        ),
                        result_type=bool,
                        **_step_activity_options(
                            inp,
                            step,
                            idx,
                            activity_step_type="evaluate_legacy_condition",
                            default_start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                            default_retry_policy=_ACTIVITY_RETRY,
                            default_heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                        ),
                    )
                except Exception as exc:
                    if _is_temporal_cancelled_error(exc):
                        raise
                    ctx.pop("_loop_iter", None)
                    _finish_sub_results(sub_results, sub_result_state)
                    return (
                        False,
                        f"loop: condition evaluation failed — {_workflow_failure_message(exc)}",
                        sub_results,
                        parent_ctx,
                        {
                            "reason_code": CONDITION_EVAL_FAILED,
                            "iterations_run": actual_iters,
                            "stopped_by": "condition_error",
                            "idle_streak": idle_streak,
                        },
                    )
                if not cond_met:
                    ctx.pop("_loop_iter", None)
                    _finish_sub_results(sub_results, sub_result_state)
                    return (
                        True,
                        f"loop: {actual_iters} iteration(s) completed",
                        sub_results,
                        parent_ctx,
                        {
                            "iterations_run": actual_iters,
                            "stopped_by": "condition",
                            "idle_streak": idle_streak,
                        },
                    )

            child_result = await self._execute_child_steps(inp, sub_steps, runtime_vars, ctx)
            _append_sub_result(
                sub_results,
                sub_result_state,
                {"iteration": i, "success": child_result.success},
            )
            actual_iters += 1
            runtime_vars.update(child_result.runtime_vars)
            parent_ctx = {**parent_ctx, **child_result.context}
            parent_ctx.pop("_loop_iter", None)
            if parent_trace:
                parent_ctx[TRACE_CONTEXT_KEY] = parent_trace
            else:
                parent_ctx.pop(TRACE_CONTEXT_KEY, None)
            ctx = {**parent_ctx, TRACE_CONTEXT_KEY: trace_from_runtime_context(ctx)}

            if child_result.break_requested:
                ctx.pop("_loop_iter", None)
                _finish_sub_results(sub_results, sub_result_state)
                return (
                    True,
                    f"loop: {actual_iters} iteration(s) completed",
                    sub_results,
                    parent_ctx,
                    {
                        "iterations_run": actual_iters,
                        "stopped_by": "break",
                        "idle_streak": idle_streak,
                    },
                )

            if not child_result.success:
                ctx.pop("_loop_iter", None)
                _finish_sub_results(sub_results, sub_result_state)
                return (
                    False,
                    f"loop: iteration {i} failed — {child_result.failed_message}",
                    sub_results,
                    parent_ctx,
                    {
                        "reason_code": LOOP_ITERATION_FAILED,
                        "iterations_run": actual_iters,
                        "failed_iteration": i,
                        "stopped_by": "child_failure",
                        "idle_streak": idle_streak,
                        "nested_failure": _first_failed_step(child_result.step_results),
                    },
                )

            # Back off after an iteration that touched nothing. workflow.sleep,
            # not time.sleep: this is workflow code, and a blocking sleep would
            # stall the whole worker rather than this one run.
            step_results = getattr(child_result, "step_results", None) or []
            if idle_delay_s > 0 and not _loop_performed_action(step_results):
                await workflow.sleep(timedelta(seconds=idle_delay_s))

            if stall_after > 0:
                if _loop_made_progress(step_results):
                    idle_streak = 0
                else:
                    idle_streak += 1
                    if idle_streak >= stall_after:
                        ctx.pop("_loop_iter", None)
                        _finish_sub_results(sub_results, sub_result_state)
                        return (
                            False,
                            (
                                f"loop: stopped after {idle_streak} consecutive "
                                f"iteration(s) that performed no action — the "
                                f"screen is probably not the one this loop expects"
                            ),
                            sub_results,
                            parent_ctx,
                            {
                                "reason_code": LOOP_STALLED,
                                "iterations_run": actual_iters,
                                "stopped_by": "stall",
                                "idle_streak": idle_streak,
                            },
                        )

            # Re-picked every iteration: one value reused for the whole loop is
            # just a fixed delay with extra fields. workflow.sleep, not
            # time.sleep — a blocking sleep here stalls the whole worker.
            if delay_range is not None and i < iterations - 1:
                await workflow.sleep(
                    timedelta(seconds=wf_random.uniform(*delay_range))
                )

        ctx.pop("_loop_iter", None)
        _finish_sub_results(sub_results, sub_result_state)
        return (
            True,
            f"loop: {actual_iters} iteration(s) completed",
            sub_results,
            parent_ctx,
            {
                "iterations_run": actual_iters,
                "stopped_by": "count" if not use_while else "condition",
                "idle_streak": idle_streak,
                **({"count_chosen": iterations} if count_range is not None else {}),
            },
        )

    async def _handle_if(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool, dict[str, Any]]:
        """Handle generic 'if' step using _evaluate_condition."""
        condition = step.get("condition") or {}
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not condition:
            return (
                False,
                "if: missing condition",
                runtime_context,
                False,
                {"reason_code": CONDITION_EVAL_FAILED},
            )

        try:
            cond_met: bool = await workflow.execute_activity(
                "evaluate_legacy_condition",
                LegacyConditionCheckInput(
                    device_serial=inp.device_serial,
                    condition=condition,
                    runtime_vars=runtime_vars,
                    context=runtime_context,
                    execution_id=inp.execution_id or inp.run_id,
                    campaign_id=inp.campaign_id,
                ),
                result_type=bool,
                **_step_activity_options(
                    inp,
                    step,
                    idx,
                    activity_step_type="evaluate_legacy_condition",
                    default_start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                    default_retry_policy=_ACTIVITY_RETRY,
                    default_heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                ),
            )
        except Exception as exc:
            if _is_temporal_cancelled_error(exc):
                raise
            return (
                False,
                f"if: condition evaluation failed — {_workflow_failure_message(exc)}",
                runtime_context,
                False,
                {"reason_code": CONDITION_EVAL_FAILED},
            )

        branch_steps = then_steps if cond_met else else_steps
        branch_name = "then" if cond_met else "else"
        payload = {"branch": branch_name, "condition_met": cond_met}

        if not branch_steps:
            return True, f"if: no {branch_name} steps, skip", runtime_context, False, payload

        branch_context = push_step_path(
            runtime_context,
            step_id=_step_id(step, idx),
            branch=branch_name,
            step_type="if",
            step_index=idx,
        )
        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, branch_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}
        parent_trace = trace_from_runtime_context(runtime_context)
        if parent_trace:
            merged_ctx[TRACE_CONTEXT_KEY] = parent_trace
        else:
            merged_ctx.pop(TRACE_CONTEXT_KEY, None)

        if not child_result.success:
            return (
                False,
                f"if: {branch_name} branch failed — {child_result.failed_message}",
                merged_ctx,
                False,
                {
                    **payload,
                    "reason_code": BRANCH_FAILED,
                    "nested_failure": _first_failed_step(child_result.step_results),
                },
            )

        return True, f"if: executed {branch_name}", merged_ctx, child_result.break_requested, payload

    async def _handle_repeat(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, list, dict, dict[str, Any]]:
        """Handle repeat step: loop N times with optional delay."""
        count_raw = step.get("count")
        delay = float(step.get("delay_between", 0.0) or 0.0)
        sub_steps = step.get("steps") or []

        if count_raw is None:
            return False, "repeat: missing count", [], runtime_context, {"reason_code": LOOP_INVALID_COUNT, "stopped_by": "config"}
        if not sub_steps:
            return False, "repeat: no nested steps", [], runtime_context, {"reason_code": LOOP_NO_NESTED_STEPS, "stopped_by": "config"}

        try:
            count = int(count_raw)
        except (TypeError, ValueError):
            return False, f"repeat: invalid count={count_raw!r}", [], runtime_context, {"reason_code": LOOP_INVALID_COUNT, "stopped_by": "config"}

        count = min(count, 10_000)
        sub_results: list[dict[str, Any]] = []
        sub_result_state: dict[str, Any] = {}
        actual_iters = 0
        parent_ctx = dict(runtime_context)
        parent_trace = trace_from_runtime_context(runtime_context)
        ctx = dict(parent_ctx)

        for i in range(count):
            # See _handle_loop: continue_as_new is unreachable from inside a
            # loop body, so a long repeat would otherwise run until the server
            # terminates it.
            if self._history_limit_reached():
                _finish_sub_results(sub_results, sub_result_state)
                return (
                    False,
                    f"repeat stopped at iteration {i}: {LOOP_HISTORY_LIMIT}",
                    sub_results,
                    parent_ctx,
                    {
                        "reason_code": LOOP_HISTORY_LIMIT,
                        "iterations_run": actual_iters,
                        "stopped_by": "history_limit",
                        "partial": True,
                        "history_length": workflow.info().get_current_history_length(),
                    },
                )
            runtime_vars["__LOOP_INDEX__"] = i
            ctx = push_step_path(
                parent_ctx,
                step_id=_step_id(step, idx),
                loop_iter=i,
                step_type="repeat",
                step_index=idx,
            )
            self._mark_step_started(
                idx,
                "repeat",
                f"repeat iteration {i}",
                step_id=_step_id(step, idx),
                step_path=trace_from_runtime_context(ctx).get("step_path"),
                loop_iter=i,
            )

            child_result = await self._execute_child_steps(inp, sub_steps, runtime_vars, ctx)
            actual_iters += 1
            _append_sub_result(
                sub_results,
                sub_result_state,
                {"iteration": i, "success": child_result.success},
            )

            if not child_result.success:
                _finish_sub_results(sub_results, sub_result_state)
                return (
                    False,
                    f"repeat: iteration {i} failed — {child_result.failed_message}",
                    sub_results,
                    parent_ctx,
                    {
                        "reason_code": LOOP_ITERATION_FAILED,
                        "iterations_run": actual_iters,
                        "failed_iteration": i,
                        "stopped_by": "child_failure",
                        "nested_failure": _first_failed_step(child_result.step_results),
                    },
                )

            runtime_vars.update(child_result.runtime_vars)
            parent_ctx = {**parent_ctx, **child_result.context}
            parent_ctx.pop("_loop_iter", None)
            if parent_trace:
                parent_ctx[TRACE_CONTEXT_KEY] = parent_trace
            else:
                parent_ctx.pop(TRACE_CONTEXT_KEY, None)

            if child_result.break_requested:
                _finish_sub_results(sub_results, sub_result_state)
                return (
                    True,
                    f"repeat: {actual_iters} iteration(s) completed",
                    sub_results,
                    parent_ctx,
                    {"iterations_run": actual_iters, "stopped_by": "break"},
                )
                break

            if delay > 0 and i < count - 1:
                await workflow.sleep(min(delay, 300.0))

        _finish_sub_results(sub_results, sub_result_state)
        return (
            True,
            f"repeat: {actual_iters} iteration(s) completed",
            sub_results,
            parent_ctx,
            {"iterations_run": actual_iters, "stopped_by": "count"},
        )

    async def _handle_repeat_until(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, dict[str, Any]]:
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
            return False, "repeat_until: missing condition", runtime_context, {"reason_code": CONDITION_EVAL_FAILED}
        if not sub_steps:
            return False, "repeat_until: no nested steps", runtime_context, {"reason_code": LOOP_NO_NESTED_STEPS, "stopped_by": "config"}

        parent_ctx = dict(runtime_context)
        parent_trace = trace_from_runtime_context(runtime_context)
        ctx = dict(parent_ctx)
        actual_iters = 0

        for i in range(max_iter):
            # See _handle_loop: continue_as_new is unreachable from inside a
            # loop body, so a long repeat_until would otherwise run until the
            # server terminates it.
            if self._history_limit_reached():
                return (
                    False,
                    f"repeat_until stopped at iteration {i}: {LOOP_HISTORY_LIMIT}",
                    parent_ctx,
                    {
                        "reason_code": LOOP_HISTORY_LIMIT,
                        "iterations_run": actual_iters,
                        "stopped_by": "history_limit",
                        "partial": True,
                        "history_length": workflow.info().get_current_history_length(),
                    },
                )
            runtime_vars["__LOOP_INDEX__"] = i
            ctx = push_step_path(
                parent_ctx,
                step_id=_step_id(step, idx),
                loop_iter=i,
                step_type="repeat_until",
                step_index=idx,
            )
            self._mark_step_started(
                idx,
                "repeat_until",
                f"repeat_until iteration {i}",
                step_id=_step_id(step, idx),
                step_path=trace_from_runtime_context(ctx).get("step_path"),
                loop_iter=i,
            )

            try:
                condition_met: bool = await workflow.execute_activity(
                    "evaluate_condition",
                    ConditionCheckInput(
                        device_serial=inp.device_serial,
                        condition=condition,
                        runtime_vars=runtime_vars,
                        execution_id=inp.execution_id or inp.run_id,
                        campaign_id=inp.campaign_id,
                    ),
                    result_type=bool,
                    **_step_activity_options(
                        inp,
                        step,
                        idx,
                        activity_step_type="evaluate_condition",
                        default_start_to_close_timeout=_ELEMENT_CHECK_TIMEOUT,
                        default_retry_policy=_ACTIVITY_RETRY,
                        default_heartbeat_timeout=_ELEMENT_CHECK_TIMEOUT,
                    ),
                )
            except Exception as exc:
                if _is_temporal_cancelled_error(exc):
                    raise
                return (
                    False,
                    f"repeat_until: condition evaluation failed — {_workflow_failure_message(exc)}",
                    parent_ctx,
                    {
                        "reason_code": CONDITION_EVAL_FAILED,
                        "iterations_run": actual_iters,
                        "stopped_by": "condition_error",
                    },
                )

            if condition_met:
                return (
                    True,
                    f"repeat_until: condition met after {i} iteration(s)",
                    parent_ctx,
                    {"iterations_run": actual_iters, "stopped_by": "condition"},
                )

            child_result = await self._execute_child_steps(inp, sub_steps, runtime_vars, ctx)
            actual_iters += 1

            if not child_result.success:
                return (
                    False,
                    f"repeat_until: iteration {i} failed — {child_result.failed_message}",
                    parent_ctx,
                    {
                        "reason_code": LOOP_ITERATION_FAILED,
                        "iterations_run": actual_iters,
                        "failed_iteration": i,
                        "stopped_by": "child_failure",
                        "nested_failure": _first_failed_step(child_result.step_results),
                    },
                )

            runtime_vars.update(child_result.runtime_vars)
            parent_ctx = {**parent_ctx, **child_result.context}
            parent_ctx.pop("_loop_iter", None)
            if parent_trace:
                parent_ctx[TRACE_CONTEXT_KEY] = parent_trace
            else:
                parent_ctx.pop(TRACE_CONTEXT_KEY, None)

        return (
            False,
            f"repeat_until: max_iterations ({max_iter}) reached",
            parent_ctx,
            {
                "reason_code": LOOP_STALLED,
                "iterations_run": actual_iters,
                "stopped_by": "max_iterations",
            },
        )

    async def _handle_if_element(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool, dict[str, Any]]:
        """Handle if_element: branch based on element existence."""
        by = str(step.get("by") or "")
        value = str(step.get("value") or "").strip()
        timeout = float(step.get("timeout", 3.0) or 3.0)
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not by or not value:
            return False, "if_element: missing by/value", runtime_context, False, {"reason_code": CONDITION_EVAL_FAILED}

        try:
            check_result: ElementCheckResult = await workflow.execute_activity(
                "check_element_exists",
                ElementCheckInput(
                    device_serial=inp.device_serial,
                    by=by, value=value, timeout=timeout,
                    execution_id=inp.execution_id or inp.run_id,
                    campaign_id=inp.campaign_id,
                ),
                result_type=ElementCheckResult,
                **_step_activity_options(
                    inp,
                    step,
                    idx,
                    activity_step_type="check_element_exists",
                    default_start_to_close_timeout=timedelta(seconds=timeout + 10),
                    default_retry_policy=_ACTIVITY_RETRY,
                    default_heartbeat_timeout=timedelta(seconds=timeout + 10),
                ),
            )
        except Exception as exc:
            if _is_temporal_cancelled_error(exc):
                raise
            return (
                False,
                f"if_element: condition evaluation failed — {_workflow_failure_message(exc)}",
                runtime_context,
                False,
                {"reason_code": CONDITION_EVAL_FAILED},
            )

        branch_steps = then_steps if check_result.found else else_steps
        branch_name = "then" if check_result.found else "else"
        payload = {"branch": branch_name, "condition_met": bool(check_result.found)}

        if not branch_steps:
            return True, f"if_element(found={check_result.found}): no {branch_name} steps, skip", runtime_context, False, payload

        branch_context = push_step_path(
            runtime_context,
            step_id=_step_id(step, idx),
            branch=branch_name,
            step_type="if_element",
            step_index=idx,
        )
        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, branch_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}
        parent_trace = trace_from_runtime_context(runtime_context)
        if parent_trace:
            merged_ctx[TRACE_CONTEXT_KEY] = parent_trace
        else:
            merged_ctx.pop(TRACE_CONTEXT_KEY, None)

        if not child_result.success:
            return (
                False,
                f"if_element: {branch_name} branch failed — {child_result.failed_message}",
                merged_ctx,
                False,
                {
                    **payload,
                    "reason_code": BRANCH_FAILED,
                    "nested_failure": _first_failed_step(child_result.step_results),
                },
            )

        return True, f"if_element(found={check_result.found}): executed {branch_name}", merged_ctx, child_result.break_requested, payload

    async def _handle_if_variable(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool, dict[str, Any]]:
        """Handle if_variable: branch based on variable value."""
        name = str(step.get("name") or "")
        then_steps = step.get("then") or []
        else_steps = step.get("else") or []

        if not name:
            return False, "if_variable: missing name", runtime_context, False, {"reason_code": CONDITION_EVAL_FAILED}

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
        payload = {"branch": branch_name, "condition_met": condition_met}

        if not branch_steps:
            return True, f"if_variable({name}={str_val!r}): no {branch_name} steps, skip", runtime_context, False, payload

        branch_context = push_step_path(
            runtime_context,
            step_id=_step_id(step, idx),
            branch=branch_name,
            step_type="if_variable",
            step_index=idx,
        )
        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, branch_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}
        parent_trace = trace_from_runtime_context(runtime_context)
        if parent_trace:
            merged_ctx[TRACE_CONTEXT_KEY] = parent_trace
        else:
            merged_ctx.pop(TRACE_CONTEXT_KEY, None)

        if not child_result.success:
            return (
                False,
                f"if_variable: {branch_name} branch failed",
                merged_ctx,
                False,
                {
                    **payload,
                    "reason_code": BRANCH_FAILED,
                    "nested_failure": _first_failed_step(child_result.step_results),
                },
            )

        return True, f"if_variable({name}={str_val!r}): executed {branch_name}", merged_ctx, child_result.break_requested, payload

    async def _handle_random_pick(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, dict, bool, dict[str, Any]]:
        """Handle random_pick: weighted random branch selection."""
        branches = step.get("branches") or []
        if not branches:
            return False, "random_pick: no branches", runtime_context, False, {"reason_code": BRANCH_FAILED}

        weights = [_branch_weight(b) for b in branches]
        wf_random = _get_wf_random()
        chosen_idx = wf_random.choices(range(len(branches)), weights=weights, k=1)[0]
        chosen = branches[chosen_idx]
        branch_steps = chosen.get("steps") or []
        branch_name = f"branch{chosen_idx}"
        payload = {"branch": branch_name, "branch_index": chosen_idx}

        if not branch_steps:
            return True, f"random_pick: branch {chosen_idx} has no steps, skip", runtime_context, False, payload

        branch_context = push_step_path(
            runtime_context,
            step_id=_step_id(step, idx),
            branch=branch_name,
            step_type="random_pick",
            step_index=idx,
        )
        child_result = await self._execute_child_steps(
            inp, branch_steps, runtime_vars, branch_context,
        )
        runtime_vars.update(child_result.runtime_vars)
        merged_ctx = {**runtime_context, **child_result.context}
        parent_trace = trace_from_runtime_context(runtime_context)
        if parent_trace:
            merged_ctx[TRACE_CONTEXT_KEY] = parent_trace
        else:
            merged_ctx.pop(TRACE_CONTEXT_KEY, None)

        if not child_result.success:
            return (
                False,
                f"random_pick: branch {chosen_idx} failed",
                merged_ctx,
                False,
                {
                    **payload,
                    "reason_code": BRANCH_FAILED,
                    "nested_failure": _first_failed_step(child_result.step_results),
                },
            )

        return True, f"random_pick: executed branch {chosen_idx}", merged_ctx, child_result.break_requested, payload

    async def _handle_run_scenario(
        self,
        inp: StepsInput,
        step: dict,
        runtime_vars: dict,
        runtime_context: dict,
        idx: int,
    ) -> tuple[bool, str, list, dict, dict[str, Any]]:
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
            return (
                False,
                "run_scenario: missing scenario_id or scenario_name",
                [],
                runtime_context,
                {"reason_code": SUBSCENARIO_FAILED},
            )

        stack = list(runtime_context.get("__scenario_call_stack__") or [])
        if scenario_ref in stack:
            return (
                False,
                f"run_scenario: circular reference detected: {scenario_ref!r}",
                [],
                runtime_context,
                {"reason_code": SUBSCENARIO_FAILED},
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
                {"reason_code": SUBSCENARIO_FAILED},
            )

        override_vars = step.get("variables") or {}
        if not isinstance(override_vars, dict):
            override_vars = {}
        merged_vars = {**(sub_def.get("variables") or {}), **override_vars}
        child_vars = {**inp.variables, **merged_vars}
        sub_steps = sub_def.get("steps") or []
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
        traced_context = push_step_path(
            runtime_context,
            step_id=_step_id(step, idx),
            step_type="run_scenario",
            step_index=idx,
            scenario_updates=scenario_updates,
        )

        child_context = {
            **traced_context,
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
        parent_trace = trace_from_runtime_context(runtime_context)
        if parent_trace:
            merged_ctx[TRACE_CONTEXT_KEY] = parent_trace
        else:
            merged_ctx.pop(TRACE_CONTEXT_KEY, None)
        merged_ctx.pop("__scenario_call_stack__", None)

        child_failed = (not child_result.success) or _step_results_have_failure(
            child_result.step_results
        )
        if child_failed:
            failed_message = (
                child_result.failed_message
                or _first_failed_step_message(child_result.step_results)
            )
            return (
                False,
                f"run_scenario: sub-scenario {scenario_ref!r} failed — {failed_message}",
                child_result.step_results,
                merged_ctx,
                {
                    "reason_code": SUBSCENARIO_FAILED,
                    "nested_failure": _first_failed_step(child_result.step_results),
                    **{
                        key: value
                        for key, value in scenario_updates.items()
                        if value not in (None, "", [], {})
                    },
                },
            )

        return (
            True,
            f"run_scenario: {scenario_ref!r} completed ({child_result.steps_executed} steps)",
            child_result.step_results,
            merged_ctx,
            {
                "sub_steps_executed": child_result.steps_executed,
                **{
                    key: value
                    for key, value in scenario_updates.items()
                    if value not in (None, "", [], {})
                },
            },
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
    step_type = str(raw_step.get("type") or "")
    nested_keys: set[str] = set()
    if step_type in {"loop", "repeat", "repeat_until"}:
        nested_keys.add("steps")
    elif step_type in {"if", "if_element", "if_variable"}:
        nested_keys.update({"then", "else"})
    elif step_type == "random_pick":
        nested_keys.add("branches")

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

    if not nested_keys:
        return _resolve_value(raw_step)

    resolved = _resolve_value(
        {key: value for key, value in raw_step.items() if key not in nested_keys}
    )
    for key in nested_keys:
        if key not in raw_step:
            continue
        if key != "branches":
            resolved[key] = raw_step[key]
            continue
        branches = []
        for branch in raw_step.get("branches") or []:
            if not isinstance(branch, dict):
                branches.append(branch)
                continue
            resolved_branch = _resolve_value(
                {k: v for k, v in branch.items() if k != "steps"}
            )
            resolved_branch["steps"] = branch.get("steps") or []
            branches.append(resolved_branch)
        resolved[key] = branches
    return resolved


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

    if "from_list" in step:
        vals = step["from_list"]
        if not isinstance(vals, list) or not vals:
            return {"index": idx, "type": "set_variable", "ok": False,
                    "message": "set_variable: from_list must be non-empty list"}
        if "from_list_index" in step:
            try:
                list_index = int(step["from_list_index"])
            except (TypeError, ValueError):
                return {"index": idx, "type": "set_variable", "ok": False,
                        "message": "set_variable: from_list_index must be an integer"}
            if list_index < 0 or list_index >= len(vals):
                return {"index": idx, "type": "set_variable", "ok": False,
                        "message": (
                            f"set_variable: from_list_index {list_index} out of range "
                            f"0..{len(vals) - 1}"
                        )}
            chosen = vals[list_index]
            runtime_vars[name] = chosen
            return {"index": idx, "type": "set_variable", "ok": True,
                    "message": f"set_variable: {name} = {chosen!r} (from_list_index={list_index})"}

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
