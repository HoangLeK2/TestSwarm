"""Step handlers: loop, if, break_if, repeat, repeat_until, if_element, if_variable, random_pick, set_variable, set_var."""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import _evaluate_condition, _eval_ru_condition, _wait_for_element

log = logging.getLogger(__name__)


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

    sub_results = []
    actual_iters = 0
    for i in range(iterations):
        if use_while and not _evaluate_condition(sc.device, while_cond, sc.ctx):
            break
        sc.ctx["_loop_iter"] = i
        nested_result = _run_nested(sc, nested_steps)
        sub_results.append({"iteration": i, "result": nested_result})
        actual_iters += 1
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
    by = str(step.get("by") or "")
    value = str(step.get("value") or "").strip()
    timeout = float(step.get("timeout", 3.0) or 3.0)
    then_steps = step.get("then") or []
    else_steps = step.get("else") or []

    if not by or not value:
        result["ok"] = False
        result["message"] = "if_element: missing by/value"
        return

    element_found = False
    try:
        sc.device.ensure_u2_healthy()
        u2 = sc.device.u2
        if u2 is not None:
            eid = _wait_for_element(u2, by, value, timeout=timeout)
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
        condition_met = bool(raw_val) and str_val not in ("None", "", "0")

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
