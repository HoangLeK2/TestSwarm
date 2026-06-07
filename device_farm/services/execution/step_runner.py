"""Shared step execution with DF-T-04-011 retry policy (executor + Temporal activities)."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, TYPE_CHECKING

from services.execution.retry_policy import (
    compute_wait_ms,
    emit_retry_metrics,
    is_step_failure_retryable,
    parse_step_retry_policy,
    record_attempt,
)
from tasks.scenario.capture import StaleFrameError, capture_fail_step, capture_pre_step, capture_post_step
from tasks.scenario.steps import dispatch_step

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)


def _cancel_event(sc: "ScenarioContext") -> Any:
    ev = getattr(sc, "cancel_event", None)
    if ev is not None and callable(getattr(ev, "is_set", None)):
        try:
            state = ev.is_set()
        except Exception:
            return None
        if not isinstance(state, bool):
            return None
        return ev
    return None


def execute_step_with_retry(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    idx: int,
    *,
    trace_log: Any = None,
) -> tuple[Dict[str, Any], int]:
    """Run one step with optional per-step retry policy. Returns (step_result, attempts_used)."""
    trace = trace_log or log
    t = step.get("type")
    step_result: Dict[str, Any] = {"index": idx, "type": t, "ok": True}

    capture_pre_step(sc, step, idx, step_result, attempt_index=1)
    step_start_t = time.monotonic()

    retry_policy = parse_step_retry_policy(step)
    max_attempts = retry_policy.max_attempts if retry_policy else 1

    attempts_used = 0
    attempt_records: list[Dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        cancel_event = _cancel_event(sc)
        if cancel_event is not None and cancel_event.is_set():
            return {
                "index": idx,
                "type": t,
                "ok": False,
                "message": f"{t}: cancelled by user",
                "cancelled": True,
            }, attempts_used
        attempts_used = attempt
        try:
            handler_result = dispatch_step(sc, step, idx)
        except Exception as exc:
            handler_result = {
                "ok": False,
                "message": f"{t}: handler raised: {exc}",
                "reason_code": "handler_exception",
            }
            log.exception(f"[{sc.serial}] step#{idx + 1} handler raised")

        merged: Dict[str, Any] = {"index": idx, "type": t, "ok": True}
        merged.update(handler_result)

        stale_raised = False
        post_sync = not merged.get("ok", True)
        try:
            capture_post_step(
                sc, step, idx, merged, step_start_t,
                attempt_index=attempt, sync=post_sync,
            )
        except StaleFrameError as sfe:
            stale_raised = True
            merged["ok"] = False
            merged["reason_code"] = "stale_frame"
            merged["retryable"] = True
            merged["message"] = f"{t}: {sfe}"
            log.warning(f"[{sc.serial}] step#{idx + 1}: {sfe}")

        will_retry = (
            retry_policy is not None
            and is_step_failure_retryable(merged, retry_policy)
            and attempt < max_attempts
        )
        if will_retry:
            wait = compute_wait_ms(attempt, retry_policy)
            emit_retry_metrics(
                step_type=str(t or "unknown"),
                reason_code=merged.get("reason_code"),
                backoff_capped=wait.backoff_capped,
            )
            record_attempt(
                attempt_records,
                attempt=attempt,
                error_reason=str(merged.get("reason_code") or ""),
                wait_ms_before_next=wait.wait_ms,
            )
            trace.info(
                "step_retry",
                trace_id=sc.trace_id,
                serial=sc.serial,
                step_index=idx + 1,
                step_type=t,
                attempt=attempt,
                max_attempts=max_attempts,
                reason_code=merged.get("reason_code"),
                backoff_ms=wait.wait_ms,
                stale_frame=stale_raised,
            )
            wait_s = wait.wait_ms / 1000.0
            cancel_event = _cancel_event(sc)
            if cancel_event is not None:
                if cancel_event.wait(wait_s):
                    merged["cancelled"] = True
                    merged["ok"] = False
                    merged["message"] = f"{t}: cancelled by user"
                    step_result = merged
                    if attempt_records:
                        attempt_records[-1]["wait_ms_before_next"] = None
                        attempt_records[-1]["cancelled"] = True
                    if attempt_records:
                        step_result["retry_attempts"] = attempt_records
                    break
            else:
                time.sleep(wait_s)
            step_result = {"index": idx, "type": t, "ok": True}
            capture_pre_step(sc, step, idx, step_result, attempt_index=attempt + 1)
            step_start_t = time.monotonic()
            continue

        record_attempt(
            attempt_records,
            attempt=attempt,
            error_reason=str(merged.get("reason_code") or "") if not merged.get("ok", True) else None,
            wait_ms_before_next=None,
        )
        step_result = merged
        if not step_result.get("ok", True):
            capture_fail_step(sc, step, idx, step_result, attempt_index=attempt)
        if attempt_records:
            step_result["retry_attempts"] = attempt_records
        break

    return step_result, attempts_used
