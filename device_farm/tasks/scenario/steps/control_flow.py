"""Step handlers: loop, if, break_if, repeat, repeat_until, if_element, if_variable, random_pick, set_variable, set_var."""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import _evaluate_condition, _eval_ru_condition, _wait_for_element

log = logging.getLogger(__name__)

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


# ── Facebook comment filter switch (bundled into tap_fb_comment_button) ──────
# When comment sheet opens, FB defaults to "Most relevant" — misses comments.
# Switch to "All comments" (+ spam) to crawl the full volume.
#
# FB stores these as content-desc on the indicator row and option button.
# Known content-desc strings (update here if FB changes wording):
#   Indicator VN: "Đang hiển thị Phù hợp nhất bình luận. Nhấn để thay đổi bộ lọc bình luận."
#   Option VN:    "Tất cả bình luận, Hiển thị tất cả bình luận, bao gồm cả nội dung có thể là spam."
#   Indicator EN: "Showing Most Relevant comments. Tap to change comment filter."
#   Option EN:    "All Comments, Show all comments, including those that may be spam."

# Indicator row — the tappable row showing current filter mode.
# Ordered: most-specific first (exact substring), then fuzzy fallback.
_FB_FILTER_INDICATOR_XPATHS = [
    # VN exact fragments (content-desc)
    "//*[contains(@content-desc,'Phù hợp nhất bình luận') and contains(@content-desc,'thay đổi bộ lọc')]",
    "//*[contains(@content-desc,'Phù hợp nhất') and contains(@content-desc,'bình luận')]",
    # VN text attribute fallback
    "//*[contains(@text,'Phù hợp nhất') and contains(@text,'bình luận')]",
    # EN exact (content-desc)
    "//*[contains(@content-desc,'Most Relevant') and contains(@content-desc,'comment filter')]",
    "//*[contains(@content-desc,'Most Relevant') or contains(@content-desc,'Most relevant')]",
    # EN text fallback
    "//*[contains(@text,'Most Relevant') or contains(@text,'Most relevant')]",
]

# "All comments" option in the filter menu (appears after tapping indicator).
# FB uses a long content-desc including the spam disclaimer — match on key substring.
_FB_ALL_COMMENTS_OPTION_XPATHS = [
    # VN — content-desc contains spam-hint phrase (most specific)
    "//*[contains(@content-desc,'Tất cả bình luận') and contains(@content-desc,'spam')]",
    # VN — content-desc, plain
    "//*[contains(@content-desc,'Tất cả bình luận')]",
    # VN — text attribute
    "//*[contains(@text,'Tất cả') and contains(@text,'bình luận')]",
    # EN — content-desc contains spam phrase
    "//*[contains(@content-desc,'All Comments') and contains(@content-desc,'spam')]",
    "//*[contains(@content-desc,'All comments') and contains(@content-desc,'spam')]",
    # EN — plain
    "//*[contains(@content-desc,'All Comments') or contains(@content-desc,'All comments')]",
    "//*[contains(@text,'All comments') or contains(@text,'All Comments')]",
]


def _find_and_tap_by_xpaths(device, xml: str, xpaths: List[str]) -> Optional[str]:
    """Parse XML once, test xpaths with lxml, tap the first match by bounds.

    Returns the matching xpath string, or None if nothing matched / tap failed.
    Zero u2 round-trips for the search itself.
    """
    import re as _re
    try:
        from lxml import etree as _et
        root = _et.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except Exception:
        return None

    for xp in xpaths:
        try:
            nodes = root.xpath(xp)
        except Exception:
            continue
        if not nodes:
            continue
        node = nodes[0]
        m = _re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
        if not m:
            continue
        x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        try:
            device.tap(cx, cy)
            return xp
        except Exception:
            continue
    return None


def _fb_switch_to_all_comments(
    sc: ScenarioContext,
    *,
    wait_stable_s: float = 0.5,
    indicator_timeout: float = 3.0,
    option_wait_s: float = 0.4,
) -> Dict[str, Any]:
    """Switch FB comment filter from "Most Relevant" to "All Comments".

    Fast path: get XML once → test all xpaths in Python (lxml, no round-trips)
    → tap by bounds. Two XML fetches total (one per step).
    Best-effort: any failure returns report with switched=False.
    """
    report: Dict[str, Any] = {"indicator": None, "option": None, "switched": False}
    device = sc.device

    # Wait for comment sheet animation before probing.
    time.sleep(wait_stable_s)

    # Step 1 — find indicator row in XML, tap it.
    deadline = time.monotonic() + indicator_timeout
    indicator_hit = None
    while time.monotonic() < deadline:
        xml = device.hierarchy_xml(force_refresh=True)
        if xml:
            hit = _find_and_tap_by_xpaths(device, xml, _FB_FILTER_INDICATOR_XPATHS)
            if hit:
                indicator_hit = hit
                log.debug(f"[filter-switch] indicator tapped: {hit}")
                break
        time.sleep(0.3)

    report["indicator"] = indicator_hit
    if not indicator_hit:
        log.debug("[filter-switch] no indicator — already All, or too few comments")
        return report

    # Step 2 — option menu appears; get fresh XML and tap "All comments".
    time.sleep(option_wait_s)
    xml = device.hierarchy_xml(force_refresh=True)
    if xml:
        hit = _find_and_tap_by_xpaths(device, xml, _FB_ALL_COMMENTS_OPTION_XPATHS)
        if hit:
            report["option"] = hit
            report["switched"] = True
            log.debug(f"[filter-switch] option tapped: {hit}")
            # Brief settle for comment list to repaint under new filter.
            time.sleep(0.5)
            return report

    log.debug("[filter-switch] indicator tapped but option not found")
    return report


@register_step("tap_fb_comment_button")
def handle_tap_fb_comment_button(
    sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any],
) -> None:
    """Atomic resolve+tap of topmost visible FB feed ``Bình luận`` button.

    Control-flow shape (like ``if_element``):
      - ``then`` / ``else``: nested step lists. ``then`` runs only after a
        successful resolve+tap; ``else`` runs when no button was found / tap
        failed. Users do not need an auxiliary flag variable.

    Built-in post-tap behavior:
      - ``switch_to_all_comments`` (default True): automatically switch the
        comment filter from "Most relevant" to "All comments" (VN + EN
        locales) BEFORE running ``then``. Removes the manual if_element
        chain previously required in every template.

    On success, ctx is updated so downstream ``extract fb_comments`` links
    comments to the correct post:
      - ``_fb_comment_parent_pid``   = _pid of the tapped row
      - ``_post_id_map[_pid]``       = sha256 content_hash (accumulated)
      - ``_active_comment_parent_hash`` = same hash

    Step params (all optional):
      - ``timeout`` (default 6.0): seconds to poll for a visible button.
      - ``poll`` (default 0.4): polling interval.
      - ``dedupe_field`` (default "post_key"): hash field for the post.
      - ``ignore_error`` (default True): miss does NOT fail scenario — the
        ``else`` branch runs (or nothing runs if ``else`` is empty).
      - ``post_tap_wait_s`` (default 0.8): settle delay after tap before the
        auto filter switch peeks at the XML.
    """
    from tasks.fb_extract import resolve_topmost_comment_target_from_xml
    from services.content_store import compute_content_hash

    timeout = float(step.get("timeout", 6.0) or 6.0)
    poll = max(0.1, float(step.get("poll", 0.4) or 0.4))
    dedupe_field = str(step.get("dedupe_field") or sc.ctx.get("_fb_posts_dedupe_field") or "post_key")
    enter_comment_sheet_timeout = float(step.get("enter_comment_sheet_timeout", 1.8) or 1.8)
    ignore_error = bool(step.get("ignore_error", True))
    switch_filter = bool(step.get("switch_to_all_comments", True))
    post_tap_wait_s = float(step.get("post_tap_wait_s", 0.8) or 0.8)
    pre_scroll = bool(step.get("pre_scroll", False))
    pre_scroll_distance = float(step.get("pre_scroll_distance", 0.24) or 0.24)
    then_steps = step.get("then") or []
    else_steps = step.get("else") or []

    device = sc.device
    ctx = sc.ctx

    # Optional light scroll to expose the action bar when the topmost post is tall.
    if pre_scroll:
        try:
            device.swipe_ratio(0.5, 0.72, 0.5, 0.72 - pre_scroll_distance)
            time.sleep(0.4)
        except Exception:
            pass

    deadline = time.monotonic() + timeout
    post = None
    btn = None
    while True:
        xml = device.hierarchy_xml(force_refresh=True)
        if xml:
            post, btn = resolve_topmost_comment_target_from_xml(xml)
            if post and btn:
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(poll)

    tapped = False
    pid = None
    post_hash = None
    if post and btn and post.get("_pid"):
        pid = post["_pid"]
        post_hash = compute_content_hash(post, dedupe_field=dedupe_field)
        x1, y1, x2, y2 = btn
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        try:
            device.tap(cx, cy)
            # Confirm we actually entered the comment sheet; in real devices
            # the tap may hit but transition can fail/lag and we remain on feed.
            try:
                from tasks.fb_extract import _hierarchy_is_fb_comment_sheet, _parse_xml

                deadline_enter = time.monotonic() + max(0.5, enter_comment_sheet_timeout)
                while time.monotonic() < deadline_enter:
                    _xml = device.hierarchy_xml(force_refresh=True)
                    _root = _parse_xml(_xml) if _xml else None
                    if _root is not None and _hierarchy_is_fb_comment_sheet(_root):
                        tapped = True
                        break
                    time.sleep(0.15)
            except Exception:
                # Fallback to previous behavior if classifier fails.
                tapped = True
            if tapped:
                pid_map = ctx.setdefault("_post_id_map", {})
                pid_map[pid] = post_hash
                ctx["_fb_comment_parent_pid"] = pid
                ctx["_active_comment_parent_hash"] = post_hash
                ctx["_first_new_post_hash"] = post_hash
                # Keep a richer post anchor so downstream comment extraction can
                # still map parent hash when pid-based linkage is missing.
                ctx["_active_comment_parent_anchor"] = {
                    "post_key": post.get("post_key"),
                    "stable_post_id": post.get("stable_post_id"),
                    "fb_post_id": post.get("fb_post_id"),
                    "author": post.get("author"),
                    "timestamp": post.get("timestamp"),
                    "text_prefix": str(post.get("text") or "")[:220],
                }
            result["_pid"] = pid
            result["_bounds"] = [x1, y1, x2, y2]
            result["tapped_at"] = [cx, cy]
            log.info(
                f"[{sc.serial}] tap_fb_comment_button: pid={pid} "
                f"hash={post_hash[:12]} at ({cx},{cy}) entered_sheet={tapped}"
            )
            time.sleep(0.3)
        except Exception as exc:
            log.warning(f"[{sc.serial}] tap_fb_comment_button: tap failed: {exc}")

    # Auto filter switch — only when tap succeeded and user didn't opt out.
    if tapped and switch_filter:
        try:
            fsw = _fb_switch_to_all_comments(sc, wait_stable_s=post_tap_wait_s)
            result["filter_switch"] = fsw
            if fsw.get("switched"):
                log.info(
                    f"[{sc.serial}] tap_fb_comment_button: switched to All comments "
                    f"(option={fsw.get('option')})"
                )
        except Exception as exc:
            log.warning(
                f"[{sc.serial}] tap_fb_comment_button: filter switch failed: {exc}"
            )

    branch_steps = then_steps if tapped else else_steps
    branch_name = "then" if tapped else "else"
    result["tapped"] = tapped
    result["branch"] = branch_name

    if not tapped and not ignore_error:
        result["ok"] = False
        result["message"] = "tap_fb_comment_button: no visible Bình luận button"
        return

    if branch_steps:
        sub = _run_nested(sc, branch_steps)
        result["sub_result"] = sub
        if not sub.get("success"):
            result["ok"] = False
            result["message"] = f"tap_fb_comment_button: {branch_name} branch failed"
        else:
            result["message"] = (
                f"tap_fb_comment_button(tapped={tapped}): took {branch_name}"
                + (f" pid={pid}" if pid else "")
            )
    else:
        result["message"] = (
            f"tap_fb_comment_button(tapped={tapped}): no steps for {branch_name}, skip"
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
