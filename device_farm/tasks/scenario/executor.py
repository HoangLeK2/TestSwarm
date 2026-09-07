"""ScenarioExecutor — main step loop and result assembly."""
from __future__ import annotations

import asyncio
import logging
import random
import time
import importlib
from datetime import datetime, timezone
from typing import Any, Dict, TYPE_CHECKING

from services.execution.step_runner import execute_step_with_retry
from services.execution.trace_context import (
    TRACE_CONTEXT_KEY,
    step_trace_from_context,
    trace_from_runtime_context,
)


if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)
trace_log = importlib.import_module("structlog").get_logger("scenario_trace")

_MAX_NESTING_DEPTH = 10


def _resolve_step_for_execution(
    sc: "ScenarioContext",
    raw_step: Dict[str, Any],
    *,
    step_index: int,
) -> Dict[str, Any]:
    """Resolve step fields while preserving nested step bodies for control flow."""
    step_type = str(raw_step.get("type") or "")
    nested_keys: set[str] = set()
    if step_type in {"loop", "repeat", "repeat_until"}:
        nested_keys.add("steps")
    elif step_type in {"if", "if_element", "if_variable"}:
        nested_keys.update({"then", "else"})
    elif step_type == "random_pick":
        nested_keys.add("branches")

    if not nested_keys:
        return sc.var_ctx.resolve(raw_step, step_index=step_index)

    resolved = sc.var_ctx.resolve(
        {key: value for key, value in raw_step.items() if key not in nested_keys},
        step_index=step_index,
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
            resolved_branch = sc.var_ctx.resolve(
                {k: v for k, v in branch.items() if k != "steps"},
                step_index=step_index,
            )
            resolved_branch["steps"] = branch.get("steps") or []
            branches.append(resolved_branch)
        resolved[key] = branches
    return resolved


def _error_policy(step: Dict[str, Any], scenario: Dict[str, Any]) -> str:
    """Return parent-owned error policy for a failed step."""
    step_type = str(step.get("type") or "")
    dsl_policy = step.get("error_policy", "")
    if dsl_policy in ("ignore", "continue"):
        return "continue"
    if dsl_policy == "stop":
        return "stop"
    step_policy = step.get("on_error", "")
    if step_policy in ("pause", "continue", "stop"):
        return step_policy
    if step.get("ignore_error"):
        return "continue"
    scenario_policy = scenario.get("on_error", "")
    if scenario_policy in ("pause", "continue", "stop"):
        return scenario_policy
    if scenario.get("continue_on_error"):
        return "continue"
    return "stop"


def _failure_counts_for_result(step_result: Dict[str, Any]) -> bool:
    if step_result.get("ok", True):
        return False
    return not bool(step_result.get("error_ignored"))


def _run_scenario_failure_can_be_ignored(step_result: Dict[str, Any]) -> bool:
    if not step_result.get("sub_result"):
        return False
    message = str(step_result.get("message") or "")
    reason = message.split("—", maxsplit=1)[-1].strip()
    if reason.startswith("run_scenario:"):
        return False
    if reason.startswith("Max nesting depth"):
        return False
    return True


def _schedule_ignored_failure_warning(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    step_result: Dict[str, Any],
) -> None:
    if sc.depth > 0 or not sc.execution_id or not step_result.get("ignored_failure"):
        return
    loop = getattr(sc.device, "_loop", None)
    if loop is None or loop.is_closed():
        return

    execution_id = sc.execution_id
    device_serial = sc.serial
    step_index = step_result.get("index")
    step_type = str(step_result.get("type") or step.get("type") or "unknown")
    message = str(
        step_result.get("ignored_message")
        or step_result.get("message")
        or "step warning"
    )

    async def _do() -> None:
        try:
            from db.database import activity_session
            from db.crud.execution import get_execution
            from services.execution.event_publisher import resolve_execution_org_id
            from services.campaign.events import emit_campaign_step_warning
            from tenancy.context import tenant_context

            async with activity_session() as db:
                execution = await get_execution(db, execution_id)
                campaign_id = getattr(execution, "campaign_id", None) if execution else None
                if not execution or not campaign_id:
                    return
                org_id = await resolve_execution_org_id(db, execution)
                if not org_id:
                    return
                campaign_name = None
                with tenant_context(org_id):
                    try:
                        from db.crud import campaign_entity as campaign_repo

                        campaign = await campaign_repo.get_campaign_entity(db, campaign_id)
                        campaign_name = getattr(campaign, "name", None) if campaign else None
                    except Exception:
                        campaign_name = None
                    await emit_campaign_step_warning(
                        db,
                        org_id=org_id,
                        campaign_id=campaign_id,
                        campaign_name=campaign_name,
                        execution_id=execution_id,
                        device_serial=device_serial,
                        step_index=step_index,
                        step_type=step_type,
                        message=message,
                        user_id=getattr(execution, "user_id", None),
                    )
                    await db.commit()
        except Exception as exc:
            log.debug(
                "campaign step warning schedule failed exec_id=%s step=%s: %s",
                execution_id,
                step_index,
                exc,
            )

    try:
        fut = asyncio.run_coroutine_threadsafe(_do(), loop)
        fut.add_done_callback(
            lambda f: log.warning(
                "campaign step warning future failed exec_id=%s step=%s: %s",
                execution_id,
                step_index,
                f.exception(),
            )
            if f.exception() is not None
            else None
        )
    except Exception as exc:
        log.debug("campaign step warning schedule failed (non-fatal): %s", exc)


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

        if sc.scenario.get("capability_preflight", True) is not False:
            from services.scenario_node_preflight import preflight_scenario_node_capabilities

            preflight = preflight_scenario_node_capabilities(sc.device, sc.scenario)
            if not preflight.ok:
                payload = preflight.to_dict()
                message = preflight.message
                log.warning("[%s] %s", sc.serial, message)
                return {
                    "serial": sc.serial,
                    "success": False,
                    "steps_executed": 0,
                    "step_results": [
                        {
                            "index": -1,
                            "type": "capability_preflight",
                            "ok": False,
                            "message": message,
                            "capability_preflight": payload,
                            "reason_code": "NODE_CAPABILITY_UNAVAILABLE",
                        }
                    ],
                    "failed_message": message,
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

            step: Dict[str, Any] = _resolve_step_for_execution(
                sc,
                raw_step,
                step_index=idx,
            )
            t = step.get("type")
            parent_trace = trace_from_runtime_context(sc.ctx)
            step_trace_context = step_trace_from_context(sc.ctx, step=step, step_index=idx)
            step_trace = trace_from_runtime_context(step_trace_context)
            step["_scenario_parent_trace"] = parent_trace
            step.update(
                {
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
                }
            )
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

            step_start_t = time.monotonic()
            step_started_at = datetime.now(timezone.utc)
            sc.ctx[TRACE_CONTEXT_KEY] = step_trace
            try:
                step_result, attempts_used = execute_step_with_retry(
                    sc, step, idx, trace_log=trace_log,
                )
            finally:
                if parent_trace:
                    sc.ctx[TRACE_CONTEXT_KEY] = parent_trace
                else:
                    sc.ctx.pop(TRACE_CONTEXT_KEY, None)
            step_result.setdefault("trace", step_trace)
            if step_trace.get("step_path") is not None:
                step_result.setdefault("step_path", step_trace.get("step_path"))
            if step_trace.get("loop_iter") is not None:
                step_result.setdefault("loop_iter", step_trace.get("loop_iter"))
            step_dur_ms = (time.monotonic() - step_start_t) * 1000.0
            step_ended_at = datetime.now(timezone.utc)
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

            stop_after_step = False
            if step_result.get("ok", True):
                _persist_checkpoint(sc, idx + 1)
            else:
                policy = _error_policy(step, sc.scenario)
                step_result["error_policy"] = policy
                if policy == "continue":
                    step_result["error_ignored"] = True
                    step_result["marked_ignored"] = True
                    if (
                        str(step.get("type") or "") == "run_scenario"
                        and _run_scenario_failure_can_be_ignored(step_result)
                    ):
                        step_result["ignored_failure"] = True
                        step_result["ignored_message"] = step_result.get("message")
                        step_result["message"] = (
                            f"{step_result.get('message') or 'run_scenario failed'}; "
                            "ignored by parent run_scenario policy"
                        )
                        step_result["ok"] = True
                        _schedule_ignored_failure_warning(sc, step, step_result)
                    _persist_checkpoint(sc, idx + 1)
                else:
                    if policy == "pause":
                        step_result["message"] = (
                            f"{step_result.get('message') or 'step failed'}; "
                            "pause-on-error is only supported by Temporal execution"
                        )
                    stop_after_step = True

            sc.step_results.append(step_result)

            if sc.depth == 0 and sc.execution_id:
                from services.execution.step_store import schedule_persist_step

                schedule_persist_step(
                    sc,
                    step,
                    step_result,
                    started_at=step_started_at,
                    ended_at=step_ended_at,
                    duration_ms=step_dur_ms,
                )

            # Notify caller
            if sc.on_step_done is not None:
                try:
                    sc.on_step_done(step_result)
                except Exception:
                    pass

            if stop_after_step:
                break

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
        if sc.depth == 0:
            from services.execution.capture_service import flush_pending_captures

            flush_pending_captures()
            if sc.execution_id and sc.step_results:
                from services.execution.step_store import schedule_sync_step_artifacts

                schedule_sync_step_artifacts(sc)
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
        failed_steps = [r for r in sc.step_results if _failure_counts_for_result(r)]
        all_ok = not failed_steps
        first_fail_msg = failed_steps[0].get("message", "step failed") if failed_steps else ""
        if failed_steps and failed_steps[0].get("cancelled"):
            failed_index = int(failed_steps[0].get("index", 0)) + 1
            first_fail_msg = f"Cancelled at step {failed_index}"

        result = {
            "serial": sc.serial,
            "success": all_ok,
            "steps_executed": len(sc.step_results),
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
    for key in (
        "_campaign_id",
        "_execution_id",
        "_run_hash_scope",
        "_campaign_vars",
        "execution_id",
        "run_id",
        "name",
        "scenario_name",
        "recovery_policy",
        "_scenario_registry",
    ):
        if key not in child_scenario and key in sc.scenario:
            child_scenario[key] = sc.scenario[key]
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
