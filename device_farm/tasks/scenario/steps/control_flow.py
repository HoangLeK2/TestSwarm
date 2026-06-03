"""Step handlers: loop, if, break_if, repeat, repeat_until, if_element, if_variable, random_pick, set_variable, set_var."""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from typing import Any, Dict, List

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import _evaluate_condition, _eval_ru_condition, _wait_for_element

log = logging.getLogger(__name__)


def _cancelled(sc: ScenarioContext) -> bool:
    return sc.cancel_event is not None and sc.cancel_event.is_set()


# Per-execution asyncio.Lock for serializing loop_state writes.
# Keyed by execution_id; leaks are bounded since executions finish.
_LOOP_PERSIST_LOCKS: Dict[str, asyncio.Lock] = {}
_LOOP_PERSIST_LOCKS_GUARD = threading.Lock()


def _loop_persist_lock_for(execution_id: str) -> asyncio.Lock:
    with _LOOP_PERSIST_LOCKS_GUARD:
        lock = _LOOP_PERSIST_LOCKS.get(execution_id)
        if lock is None:
            lock = asyncio.Lock()
            _LOOP_PERSIST_LOCKS[execution_id] = lock
        return lock


def _run_nested(sc: ScenarioContext, nested_steps: list, extra_scenario_keys: dict = None) -> Dict[str, Any]:
    """Run nested steps recursively without importing scenario_task."""
    # Lazy import to avoid circular import during module initialization:
    # executor -> steps -> control_flow -> executor.
    from tasks.scenario.executor import run_nested_scenario

    return run_nested_scenario(
        sc,
        nested_steps,
        variables={},
        isolate_variables=False,
        extra_scenario_keys=extra_scenario_keys,
    )


@register_step("loop")
def handle_loop(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    count = step.get("count")
    while_cond = step.get("while")
    max_iterations = int(step.get("max_iterations", 100))
    nested_steps = step.get("steps") or []

    if not nested_steps:
        result["ok"] = False
        result["message"] = "loop: no nested steps"
        return

    if count is not None:
        iterations = min(int(count), max_iterations)
        use_while = False
    elif while_cond:
        iterations = max_iterations
        use_while = True
    else:
        result["ok"] = False
        result["message"] = "loop: must specify either 'count' or 'while'"
        return

    # F4.1 — mid-loop resume. If scenario starts with a saved
    # ``_resume_loop_iter`` in ctx or scenario dict, skip iterations already
    # completed before the crash. Loop step is the most common place for long
    # work (scroll crawls), so mid-loop granularity matters more than
    # step-level.
    resume_from = int(
        sc.ctx.pop("_resume_loop_iter", None)
        or (sc.scenario.get("_loop_state") or {}).get("_loop_iter") or 0
    )
    if resume_from:
        log.info(f"[{sc.serial}] loop: resuming from iter {resume_from}/{iterations}")

    sub_results = []
    actual_iters = 0
    for i in range(resume_from, iterations):
        if _cancelled(sc):
            result["ok"] = False
            result["message"] = "loop: cancelled by user"
            break
        if use_while and not _evaluate_condition(sc.device, while_cond, sc.ctx):
            break
        sc.ctx["_loop_iter"] = i
        nested_result = _run_nested(sc, nested_steps)
        sub_results.append({"iteration": i, "result": nested_result})
        actual_iters += 1
        # F4.1 — persist mid-loop iteration index so resume picks up cleanly.
        _persist_loop_iter(sc, i + 1)
        if not nested_result.get("success"):
            result["ok"] = False
            result["message"] = (
                f"loop: iteration {i} failed — {nested_result.get('failed_message', '')}"
            )
            break
        if sc.ctx.pop("_break", False):
            log.info(f"[{sc.serial}] loop: break at iteration {i}")
            break

    sc.ctx.pop("_loop_iter", None)
    result["iterations"] = actual_iters
    result["sub_results"] = sub_results
    if result.get("ok", True):
        result["message"] = f"loop: {actual_iters} iteration(s)"


def _persist_loop_iter(sc: ScenarioContext, next_iter: int) -> None:
    """Best-effort async write of loop iter to Execution.meta.

    Never blocks or raises. Only fires for top-level scenarios with an
    execution_id. Nested scenarios inherit parent's execution and skip.
    """
    import asyncio

    if sc.depth > 0 or not sc.execution_id:
        return
    loop = getattr(sc.device, "_loop", None)
    if loop is None or loop.is_closed():
        return

    # Per-execution asyncio.Lock serializes read-modify-write on Execution.meta
    # so fire-and-forget schedules can't interleave and race the JSON blob.
    lock = _loop_persist_lock_for(sc.execution_id)
    execution_id = sc.execution_id

    async def _do():
        try:
            from db.database import activity_session
            from db.crud.execution import get_execution, update_execution
            async with lock:
                async with activity_session() as db:
                    ex = await get_execution(db, execution_id)
                    if ex is None:
                        return
                    meta = dict(ex.meta or {})
                    ls = dict(meta.get("_loop_state") or {})
                    prev_iter = ls.get("_loop_iter")
                    # Advance-only: drop stale writes where next_iter would regress.
                    if isinstance(prev_iter, int) and next_iter < prev_iter:
                        return
                    ls["_loop_iter"] = next_iter
                    meta["_loop_state"] = ls
                    await update_execution(db, execution_id, meta=meta)
                    await db.commit()
        except Exception as exc:
            log.debug(f"loop_iter persist failed (non-fatal): {exc}")

    def _on_done(fut):
        exc = fut.exception()
        if exc is not None:
            log.warning(
                "loop_iter future failed exec_id=%s iter=%s: %s",
                execution_id, next_iter, exc,
            )

    try:
        fut = asyncio.run_coroutine_threadsafe(_do(), loop)
        fut.add_done_callback(_on_done)
    except Exception as exc:
        log.debug(f"loop_iter schedule failed (non-fatal): {exc}")


@register_step("if")
def handle_if(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    condition = step.get("condition") or {}
    then_steps = step.get("then") or []
    else_steps = step.get("else") or []

    if not condition:
        result["ok"] = False
        result["message"] = "if: missing condition"
        return

    cond_met = _evaluate_condition(sc.device, condition, sc.ctx)
    branch_steps = then_steps if cond_met else else_steps
    branch_name = "then" if cond_met else "else"

    if branch_steps:
        branch_result = _run_nested(sc, branch_steps)
        result["branch"] = branch_name
        result["condition_met"] = cond_met
        result["sub_result"] = branch_result
        if not branch_result.get("success"):
            result["ok"] = False
            result["message"] = f"if: {branch_name} branch failed"
        else:
            result["message"] = f"if: took {branch_name} branch"
    else:
        result["message"] = f"if: condition={cond_met}, no steps for {branch_name} branch"


@register_step("break_if")
def handle_break_if(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    condition = step.get("condition") or {}
    if not condition:
        result["ok"] = False
        result["message"] = "break_if: missing condition"
        return
    if _evaluate_condition(sc.device, condition, sc.ctx):
        sc.ctx["_break"] = True
        result["message"] = "break_if: condition met — breaking loop"
    else:
        result["message"] = "break_if: condition not met — continuing"


@register_step("repeat")
def handle_repeat(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    count = step.get("count")
    delay = float(step.get("delay_between", 0.0) or 0.0)
    sub_steps = step.get("steps") or []

    if count is None:
        result["ok"] = False
        result["message"] = "repeat: missing count"
        return
    if not sub_steps:
        result["ok"] = False
        result["message"] = "repeat: no nested steps"
        return
    try:
        n = int(count)
    except (TypeError, ValueError):
        result["ok"] = False
        result["message"] = f"repeat: invalid count={count!r}"
        return

    sub_results: List[Dict[str, Any]] = []
    for i in range(n):
        if _cancelled(sc):
            result["ok"] = False
            result["message"] = "repeat: cancelled by user"
            break
        sc.var_ctx.set("__LOOP_INDEX__", i)
        iter_res = _run_nested(sc, sub_steps)
        sub_results.append({"iteration": i, "result": iter_res})
        if not iter_res.get("success"):
            result["ok"] = False
            result["message"] = f"repeat: iteration {i} failed — {iter_res.get('failed_message', '')}"
            break
        if delay > 0 and i < n - 1:
            time.sleep(delay)
    else:
        result["message"] = f"repeat: {n} iteration(s) completed"
    result["iterations"] = len(sub_results)
    result["sub_results"] = sub_results


@register_step("repeat_until")
def handle_repeat_until(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    condition = step.get("condition") or {}
    max_iter = max(1, int(step.get("max_iterations", 100) or 100))
    sub_steps = step.get("steps") or []

    if not condition:
        result["ok"] = False
        result["message"] = "repeat_until: missing condition"
        return
    if not sub_steps:
        result["ok"] = False
        result["message"] = "repeat_until: no nested steps"
        return

    actual_iters = 0
    condition_met = False
    for i in range(max_iter):
        if _cancelled(sc):
            result["ok"] = False
            result["message"] = "repeat_until: cancelled by user"
            break
        sc.var_ctx.set("__LOOP_INDEX__", i)
        if _eval_ru_condition(sc.device, condition, sc.var_ctx):
            condition_met = True
            break
        iter_res = _run_nested(sc, sub_steps)
        actual_iters += 1
        if not iter_res.get("success"):
            result["ok"] = False
            result["message"] = f"repeat_until: iteration {i} failed — {iter_res.get('failed_message', '')}"
            break
    else:
        if not condition_met:
            result["ok"] = False
            result["message"] = f"repeat_until: max_iterations ({max_iter}) reached without condition"

    result["iterations"] = actual_iters
    if condition_met:
        result["message"] = f"repeat_until: condition met after {actual_iters} iteration(s)"


@register_step("if_element")
def handle_if_element(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    from tasks.scenario.utils import resolve_step_selector_fields, _retry_find_element

    spec, by, value, _ = resolve_step_selector_fields(step)
    timeout = float(step.get("timeout", 3.0) or 3.0)
    then_steps = step.get("then") or []
    else_steps = step.get("else") or []

    if spec is None or spec.is_empty():
        result["ok"] = False
        result["message"] = "if_element: missing selector"
        return

    element_found = False
    try:
        sc.device.ensure_u2_healthy()
        u2 = sc.device.u2
        if u2 is not None:
            eid = _retry_find_element(
                u2, by, value, timeout=timeout, poll=0.3, spec=spec, device=sc.device,
            )
            element_found = eid is not None
    except Exception as exc:
        log.debug(f"[{sc.serial}] if_element u2 check error: {exc}")

    branch_steps = then_steps if element_found else else_steps
    branch_name = "then" if element_found else "else"
    result["element_found"] = element_found
    result["branch"] = branch_name

    if branch_steps:
        sub = _run_nested(sc, branch_steps)
        result["sub_result"] = sub
        if not sub.get("success"):
            result["ok"] = False
            result["message"] = f"if_element: {branch_name} branch failed"
        else:
            result["message"] = f"if_element(element_found={element_found}): took {branch_name}"
    else:
        result["message"] = f"if_element(element_found={element_found}): no steps for {branch_name}, skip"


@register_step("tap_fb_comment_button", "fb_tap_comment_button")
def handle_tap_fb_comment_button(
    sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any],
) -> None:
    """Resolve the visible FB comment button via agent-boot, then tap locally."""
    from tasks.scenario.steps.extraction import (
        _clear_active_comment_parent,
        request_edge_comment_target,
    )

    if step.get("pre_scroll"):
        try:
            distance = float(step.get("pre_scroll_distance", 0.24) or 0.24)
            duration_ms = int(step.get("pre_scroll_duration_ms", 520) or 520)
            start_x_ratio = float(step.get("pre_scroll_x_ratio", 0.68) or 0.68)
            start_y_ratio = float(step.get("pre_scroll_start_y_ratio", 0.65) or 0.65)
            end_y_ratio = float(step.get("pre_scroll_end_y_ratio", 0.47) or 0.47)
            pause_s = float(step.get("pre_scroll_pause_s", 0.6) or 0.6)
            start_x_ratio = min(0.95, max(0.05, start_x_ratio))
            start_y_ratio = min(0.95, max(0.55, start_y_ratio))
            end_y_ratio = min(0.75, max(0.1, end_y_ratio))
            if end_y_ratio >= start_y_ratio:
                end_y_ratio = max(0.1, start_y_ratio - distance)
            sx = int(sc.w * start_x_ratio)
            sy1 = int(sc.h * start_y_ratio)
            sy2 = int(sc.h * end_y_ratio)
            sc.device.swipe(sx, sy1, sx, sy2, duration_ms=max(120, duration_ms))
            if pause_s > 0:
                time.sleep(pause_s)
            result["pre_scrolled"] = True
        except Exception as exc:
            log.warning("[%s] tap_fb_comment_button: pre_scroll failed: %s", sc.serial, exc)

    target = request_edge_comment_target(
        device=sc.device,
        serial=sc.serial,
        ctx=sc.ctx,
        scenario=sc.scenario,
        step=step,
        result=result,
    )
    ignore_error = bool(step.get("ignore_error", True))
    then_steps = step.get("then") or []
    else_steps = step.get("else") or []

    tapped = False
    if result.get("reason_code") == "already_on_comment_sheet":
        tapped = True
        _clear_active_comment_parent(sc.ctx)
        result["parent_context_cleared"] = True
        result["message"] = "tap_fb_comment_button: comment sheet already open"
    elif target:
        bounds = target.get("bounds")
        if isinstance(bounds, list) and len(bounds) == 4:
            x1, y1, x2, y2 = [int(v) for v in bounds]
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            try:
                agent_tapped = bool(target.get("_agent_tapped"))
                edge_summary = result.get("edge_extra_summary") if isinstance(result.get("edge_extra_summary"), dict) else None
                diag = edge_summary.get("diagnostic") if isinstance(edge_summary, dict) and isinstance(edge_summary.get("diagnostic"), dict) else None
                verified = bool(diag.get("verified")) if diag else False
                if not agent_tapped:
                    sc.device.tap(cx, cy)
                    verified = bool(diag.get("verified")) if diag else False
                elif verified:
                    pass
                elif not verified:
                    result["target_verified"] = False
                    result["message"] = (
                        "tap_fb_comment_button: comment sheet did not open after tap"
                    )
                if verified:
                    tapped = True
                    parent_base_hash = target.get("parent_base_hash")
                    if parent_base_hash:
                        sc.ctx["_edge_comment_parent_base_hash"] = parent_base_hash
                    if target.get("parent_id"):
                        sc.ctx["_active_comment_parent_hash"] = target.get("parent_id")
                        sc.ctx["_first_new_post_hash"] = target.get("parent_id")
                    if target.get("pid"):
                        sc.ctx["_fb_comment_parent_pid"] = target.get("pid")
                    sc.ctx["_active_comment_parent_anchor"] = {
                        "pid": target.get("pid"),
                        "post_key": target.get("post_key"),
                        "stable_post_id": target.get("stable_post_id"),
                        "fb_post_id": target.get("fb_post_id"),
                        "author": target.get("author"),
                        "timestamp": target.get("timestamp"),
                        "text_prefix": target.get("text_prefix"),
                    }
                    sc.ctx["_active_comment_anchor_verified"] = True
                    result["tapped_at"] = [cx, cy]
                    result["agent_tapped"] = agent_tapped
                    result["_bounds"] = bounds
                    result["_pid"] = target.get("pid")
                    result["parent_id"] = target.get("parent_id")
                    result["target_score"] = target.get("score")
                    result["target_chosen_index"] = diag.get("chosen_index") if diag else None
                    result["target_verified"] = True
                    result["target_candidate_count"] = diag.get("candidate_count") if diag else None
            except Exception as exc:
                result["ok"] = False
                result["message"] = f"tap_fb_comment_button: tap failed: {exc}"
                return

    from tasks.scenario.steps.extraction import (
        resolve_step_comment_filter,
        run_edge_comment_filter_switch,
    )

    if tapped and resolve_step_comment_filter(step):
        try:
            result["filter_switch"] = run_edge_comment_filter_switch(
                device=sc.device,
                serial=sc.serial,
                scenario=sc.scenario,
                step=step,
                result=result,
            )
        except Exception as exc:
            log.warning("[%s] tap_fb_comment_button: filter switch failed: %s", sc.serial, exc)
        settle_s = float(
            step.get("comment_filter_settle_s", step.get("post_tap_wait_s", 0.6)) or 0.6
        )
        if settle_s > 0:
            time.sleep(settle_s)

    branch_steps = then_steps if tapped else else_steps
    branch_name = "then" if tapped else "else"
    result["tapped"] = tapped
    result["branch"] = branch_name

    if not tapped:
        result["message"] = result.get("message") or "tap_fb_comment_button: no visible comment button"
        if not ignore_error:
            result["ok"] = False
            return
        result["ok"] = True

    if branch_steps:
        sub = _run_nested(sc, branch_steps)
        result["sub_result"] = sub
        if not sub.get("success"):
            result["ok"] = False
            result["message"] = f"tap_fb_comment_button: {branch_name} branch failed"
            return
        result["ok"] = True
        result["message"] = f"tap_fb_comment_button(tapped={tapped}): took {branch_name}"
        return

    result["ok"] = True
    result["message"] = (
        f"tap_fb_comment_button(tapped={tapped}): "
        f"{'tapped correct post comment button' if tapped else 'no steps for else, skip'}"
    )


@register_step("if_variable")
def handle_if_variable(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    name = str(step.get("name") or "")
    then_steps = step.get("then") or []
    else_steps = step.get("else") or []

    if not name:
        result["ok"] = False
        result["message"] = "if_variable: missing name"
        return
    if not then_steps and not else_steps:
        result["message"] = "if_variable: no then/else steps, skip"
        return

    raw_val = sc.var_ctx.resolve(f"${{{name}}}", step_index=idx)
    str_val = str(raw_val)

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
        condition_met = (
            bool(raw_val)
            and str_val not in ("None", "", "0")
            and str_val != f"${{{name}}}"
        )

    branch_steps = then_steps if condition_met else else_steps
    branch_name = "then" if condition_met else "else"
    result["condition_met"] = condition_met
    result["branch"] = branch_name

    if branch_steps:
        sub = _run_nested(sc, branch_steps)
        result["sub_result"] = sub
        if not sub.get("success"):
            result["ok"] = False
            result["message"] = f"if_variable: {branch_name} branch failed"
        else:
            result["message"] = f"if_variable({name}={str_val!r}): took {branch_name}"
    else:
        result["message"] = f"if_variable({name}={str_val!r}): no steps for {branch_name}, skip"


@register_step("random_pick")
def handle_random_pick(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    branches = step.get("branches") or []
    if not branches:
        result["ok"] = False
        result["message"] = "random_pick: no branches"
        return

    weights = [max(1, int(b.get("weight", 1))) for b in branches]
    chosen_idx = random.choices(range(len(branches)), weights=weights, k=1)[0]
    chosen = branches[chosen_idx]
    branch_steps = chosen.get("steps") or []
    result["chosen_branch"] = chosen_idx

    if not branch_steps:
        result["message"] = f"random_pick: branch {chosen_idx} has no steps, skip"
        return

    sub = _run_nested(sc, branch_steps)
    result["sub_result"] = sub
    if not sub.get("success"):
        result["ok"] = False
        result["message"] = f"random_pick: branch {chosen_idx} failed"
    else:
        result["message"] = f"random_pick: executed branch {chosen_idx}"


@register_step("set_variable")
def handle_set_variable(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    name = str(step.get("name") or "")
    if not name:
        result["ok"] = False
        result["message"] = "set_variable: missing name"
        return

    # Need raw_step for from_list (before variable resolution)
    raw_step = sc.steps[idx] if idx < len(sc.steps) else step

    if "from_list" in raw_step:
        vals = raw_step.get("from_list")
        if isinstance(vals, str):
            resolved_list = sc.var_ctx.resolve(vals, step_index=idx)
            vals = resolved_list if isinstance(resolved_list, list) else []
        if not isinstance(vals, list) or not vals:
            result["ok"] = False
            result["message"] = "set_variable: from_list phải là list không rỗng"
        else:
            resolved_vals = [sc.var_ctx.resolve(v, step_index=idx) for v in vals]
            chosen = sc.var_ctx.set_from_list(name, resolved_vals)
            result["message"] = f"set_variable: {name} = {chosen!r} (from_list)"
    elif "increment" in step:
        try:
            inc = int(step["increment"])
        except (TypeError, ValueError):
            inc = 1
        val = sc.var_ctx.increment(name, inc)
        result["message"] = f"set_variable: {name} += {inc} → {val}"
    else:
        value = step.get("value")
        sc.var_ctx.set(name, value)
        result["message"] = f"set_variable: {name} = {value!r}"


@register_step("set_var")
def handle_set_var(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    key = str(step.get("key") or "")
    value = step.get("value")
    if not key:
        result["ok"] = False
        result["message"] = "set_var: missing key"
    else:
        sc.ctx["vars"][key] = value
        result["message"] = f"set_var: {key}={value!r}"
