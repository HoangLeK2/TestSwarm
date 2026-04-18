"""ScenarioExecutor — main step loop and result assembly."""
from __future__ import annotations

import asyncio
import logging
import random
import time
import importlib
from typing import Any, Dict, TYPE_CHECKING

from tasks.scenario.capture import StaleFrameError, capture_pre_step, capture_post_step
from tasks.scenario.steps import dispatch_step


# F1.5 — reason codes that are considered retryable when a step fails.
# Extraction empty-parse reasons + capture staleness. Other codes (login_screen,
# rate_limited, xml_parse_error) are NOT retryable — they indicate session or
# programming problems that retries won't fix.
_DEFAULT_RETRY_REASONS = frozenset({
    "stale_frame",
    "no_candidates",
    "no_feed_container",
    "all_filtered_junk",
    "empty_cluster",
    "anchor_not_found",
    "no_nodes_in_band",
    "no_text_nodes",
})


def _compute_backoff_s(attempt: int, base_ms: float, cap_ms: float, jitter_ms: float) -> float:
    """Exponential backoff with jitter. attempt is 1-based."""
    expo = base_ms * (2 ** (attempt - 1))
    delay_ms = min(cap_ms, expo) + random.uniform(0, max(0.0, jitter_ms))
    return max(0.0, delay_ms / 1000.0)


def _is_retryable(step_result: Dict[str, Any], retry_on: frozenset) -> bool:
    """True if step result marks as retryable OR has a reason_code in retry_on."""
    if step_result.get("ok", True):
        return False
    if step_result.get("retryable") is True:
        return True
    code = str(step_result.get("reason_code") or "")
    return code in retry_on

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)
trace_log = importlib.import_module("structlog").get_logger("scenario_trace")

_MAX_NESTING_DEPTH = 10


def _persist_checkpoint(sc: "ScenarioContext", next_step: int) -> None:
    """Best-effort async checkpoint write. Never blocks or raises.

    Uses the device's event loop if available; silently skips otherwise.
    Top-level executions only — nested scenarios inherit parent's execution.

    Writes are advance-only: the SQL UPDATE refuses to regress checkpoint_step
    so fire-and-forget calls that land out-of-order cannot overwrite a newer
    checkpoint with an older one.
    """
    if sc.depth > 0 or not sc.execution_id:
        return
    loop = getattr(sc.device, "_loop", None)
    if loop is None or loop.is_closed():
        return

    execution_id = sc.execution_id

    async def _do():
        try:
            from sqlalchemy import update
            from db.database import activity_session
            from db.models.execution import Execution
            async with activity_session() as db:
                stmt = (
                    update(Execution)
                    .where(Execution.id == execution_id)
                    .where(
                        (Execution.checkpoint_step.is_(None))
                        | (Execution.checkpoint_step < next_step)
                    )
                    .values(checkpoint_step=next_step)
                )
                await db.execute(stmt)
                await db.commit()
        except Exception as exc:
            log.debug("checkpoint write failed (non-fatal): %s", exc)

    def _on_done(fut):
        exc = fut.exception()
        if exc is not None:
            log.warning(
                "checkpoint future failed exec_id=%s step=%s: %s",
                execution_id, next_step, exc,
            )

    try:
        fut = asyncio.run_coroutine_threadsafe(_do(), loop)
        fut.add_done_callback(_on_done)
    except Exception as exc:
        log.debug("checkpoint schedule failed (non-fatal): %s", exc)


class ScenarioExecutor:
    def __init__(self, sc: "ScenarioContext"):
        self.sc = sc

    def run(self) -> Dict[str, Any]:
        sc = self.sc
        scenario_started_at = time.monotonic()
        total_steps = len(sc.steps)
        trace_log.info(
            "scenario_start",
            trace_id=sc.trace_id,
            serial=sc.serial,
            depth=sc.depth,
            source=sc.trace_source,
            total_steps=total_steps,
            capture_enabled=bool(sc.capture_enabled),
            visual_anchor_enabled=bool(sc.visual_anchor_enabled),
        )

        # Check nesting depth
        if sc.depth > _MAX_NESTING_DEPTH:
            log.warning(f"[{sc.serial}] run_scenario_task: max nesting depth {_MAX_NESTING_DEPTH} exceeded")
            return {
                "serial": sc.serial,
                "success": False,
                "steps_executed": 0,
                "step_results": [{"type": "error", "ok": False, "message": f"Max nesting depth {_MAX_NESTING_DEPTH} exceeded"}],
                "failed_message": f"Max nesting depth {_MAX_NESTING_DEPTH} exceeded",
                "context": sc.ctx,
            }

        if sc.visual_anchor_enabled:
            log.info(f"[{sc.serial}] Visual Anchoring ON (SSIM≥{sc.va_ssim_threshold}, image≥{sc.va_image_threshold})")
        if sc.capture_enabled and sc.capture_dir:
            log.info(f"[{sc.serial}] Step capture enabled → {sc.capture_dir} settle={sc.capture_settle_ms}ms")
            if sc.capture_pre_step:
                log.info(f"[{sc.serial}] Step pre-capture enabled (CAPTURE_PRE_STEP=1)")

        if sc.start_step and sc.start_step > 0:
            log.info(f"[{sc.serial}] resume from checkpoint step #{sc.start_step}")
            trace_log.info(
                "scenario_resume", trace_id=sc.trace_id, serial=sc.serial,
                start_step=sc.start_step, total_steps=total_steps,
            )
            # Mark skipped steps so step_results length stays consistent with step indices.
            for skip_idx in range(sc.start_step):
                sc.step_results.append({"index": skip_idx, "type": "resumed", "ok": True, "message": "skipped — resumed from checkpoint"})

        for idx, raw_step in enumerate(sc.steps):
            if idx < sc.start_step:
                continue  # already executed pre-checkpoint
            # Cancellation checkpoint
            if sc.cancel_event is not None and sc.cancel_event.is_set():
                log.info(f"[{sc.serial}] scenario CANCELLED at step#{idx + 1}")
                sc.step_results.append({"index": idx, "type": "cancelled", "ok": False, "message": "Cancelled by user"})
                return {
                    "serial": sc.serial,
                    "success": False,
                    "steps_executed": idx,
                    "step_results": sc.step_results,
                    "failed_message": f"Cancelled at step {idx + 1}",
                    "context": sc.ctx,
                }

            step: Dict[str, Any] = sc.var_ctx.resolve(raw_step, step_index=idx)
            t = step.get("type")
            trace_log.info(
                "step_start",
                trace_id=sc.trace_id,
                serial=sc.serial,
                step_index=idx + 1,
                total_steps=total_steps,
                step_type=t,
                step_id=step.get("id") or step.get("_id") or "-",
            )

            step_result: Dict[str, Any] = {"index": idx, "type": t, "ok": True}

            # Pre-step capture
            capture_pre_step(sc, step, idx, step_result)

            # Record timestamp before action
            step_start_t = time.monotonic()

            # F1.5 — per-step retry config (optional per step):
            #   "retry": {"attempts": 3, "backoff_ms": 500, "jitter_ms": 300,
            #             "backoff_cap_ms": 5000, "on": ["stale_frame", "no_candidates"]}
            retry_cfg = step.get("retry") if isinstance(step.get("retry"), dict) else {}
            max_attempts = max(1, int(retry_cfg.get("attempts") or 1))
            backoff_ms = float(retry_cfg.get("backoff_ms") or 500)
            jitter_ms = float(retry_cfg.get("jitter_ms") or 250)
            backoff_cap_ms = float(retry_cfg.get("backoff_cap_ms") or 5000)
            retry_on_cfg = retry_cfg.get("on")
            if retry_on_cfg:
                retry_on = frozenset(str(r) for r in retry_on_cfg)
            else:
                retry_on = _DEFAULT_RETRY_REASONS

            attempts_used = 0
            handler_result: Dict[str, Any] = {}
            for attempt in range(1, max_attempts + 1):
                attempts_used = attempt
                # Re-dispatch (handler may be called multiple times; handlers
                # should be idempotent — extract is by virtue of dedupe).
                try:
                    handler_result = dispatch_step(sc, step, idx)
                except Exception as exc:
                    handler_result = {
                        "ok": False,
                        "message": f"{t}: handler raised: {exc}",
                        "reason_code": "handler_exception",
                    }
                    log.exception(f"[{sc.serial}] step#{idx + 1} handler raised")

                merged = {"index": idx, "type": t, "ok": True}
                merged.update(handler_result)

                # Also catch StaleFrameError from capture_post_step so retry
                # treats it like any other retryable condition.
                stale_raised = False
                try:
                    capture_post_step(sc, step, idx, merged, step_start_t)
                except StaleFrameError as sfe:
                    stale_raised = True
                    merged["ok"] = False
                    merged["reason_code"] = "stale_frame"
                    merged["retryable"] = True
                    merged["message"] = f"{t}: {sfe}"
                    log.warning(f"[{sc.serial}] step#{idx + 1}: {sfe}")

                if _is_retryable(merged, retry_on) and attempt < max_attempts:
                    delay = _compute_backoff_s(attempt, backoff_ms, backoff_cap_ms, jitter_ms)
                    trace_log.info(
                        "step_retry",
                        trace_id=sc.trace_id,
                        serial=sc.serial,
                        step_index=idx + 1,
                        step_type=t,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        reason_code=merged.get("reason_code"),
                        backoff_ms=round(delay * 1000, 1),
                        stale_frame=stale_raised,
                    )
                    time.sleep(delay)
                    step_result = {"index": idx, "type": t, "ok": True}
                    capture_pre_step(sc, step, idx, step_result)
                    step_start_t = time.monotonic()
                    continue

                step_result = merged
                break

            step_dur_ms = (time.monotonic() - step_start_t) * 1000.0
            trace_log.info(
                "step_end",
                trace_id=sc.trace_id,
                serial=sc.serial,
                step_index=idx + 1,
                total_steps=total_steps,
                step_type=t,
                ok=bool(step_result.get("ok", True)),
                duration_ms=round(step_dur_ms, 1),
                message=str(step_result.get("message") or "-"),
                attempts=attempts_used,
            )

            sc.step_results.append(step_result)

            if step_result.get("ok", True):
                _persist_checkpoint(sc, idx + 1)

            # Notify caller
            if sc.on_step_done is not None:
                try:
                    sc.on_step_done(step_result)
                except Exception:
                    pass

            # Phase 2 — anti-detection jitter between steps. Applied only at
            # top-level scenarios (nested scenarios inherit pacing from parent)
            # and never after the last step.
            if (
                sc.depth == 0
                and sc.jitter_max_ms > 0
                and idx + 1 < total_steps
                and step_result.get("ok", True)
            ):
                delay_ms = random.uniform(sc.jitter_min_ms, sc.jitter_max_ms)
                time.sleep(delay_ms / 1000.0)

        result = self._build_result()
        total_dur_ms = (time.monotonic() - scenario_started_at) * 1000.0
        failed_step = next((r for r in sc.step_results if not r.get("ok", True)), None)
        trace_log.info(
            "scenario_end",
            trace_id=sc.trace_id,
            serial=sc.serial,
            depth=sc.depth,
            success=bool(result.get("success")),
            executed_steps=result.get("steps_executed"),
            total_steps=total_steps,
            duration_ms=round(total_dur_ms, 1),
            failed_step=(failed_step.get("index") + 1) if failed_step else None,
            failed_message=str(result.get("failed_message") or ""),
        )
        return result

    def _build_result(self) -> Dict[str, Any]:
        sc = self.sc
        all_ok = all(r.get("ok", True) for r in sc.step_results)
        failed_steps = [r for r in sc.step_results if not r.get("ok", True)]
        first_fail_msg = failed_steps[0].get("message", "step failed") if failed_steps else ""

        result = {
            "serial": sc.serial,
            "success": all_ok,
            "steps_executed": len(sc.steps),
            "step_results": sc.step_results,
            "failed_message": first_fail_msg if not all_ok else None,
            "context": sc.ctx,
        }
        if sc.capture_dir:
            result["capture_dir"] = sc.capture_dir
        return result


def run_nested_scenario(
    sc: "ScenarioContext",
    nested_steps: list,
    *,
    variables: dict | None = None,
    isolate_variables: bool = True,
    call_stack_add: str | None = None,
    extra_scenario_keys: dict | None = None,
) -> Dict[str, Any]:
    """
    Execute nested steps without importing tasks.scenario_task.

    Used by composition/control-flow handlers to avoid reverse imports.
    """
    child_var_ctx = (
        sc.var_ctx.child_scope(variables or {})
        if isolate_variables
        else sc.var_ctx
    )
    child_scenario: Dict[str, Any] = {"steps": nested_steps, "variables": variables or {}}
    if extra_scenario_keys:
        child_scenario.update(extra_scenario_keys)
    child_call_stack = sc.call_stack | ({call_stack_add} if call_stack_add else set())
    child = sc.__class__.from_args(
        sc.device,
        child_scenario,
        context=sc.ctx,
        _var_ctx=child_var_ctx,
        _depth=sc.depth + 1,
        _call_stack=frozenset(child_call_stack),
        cancel_event=sc.cancel_event,
    )
    return ScenarioExecutor(child).run()
