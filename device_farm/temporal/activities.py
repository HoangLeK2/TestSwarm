

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Callable

from temporalio import activity

from temporal.shared import (
    DeviceActionBatchInput,
    DeviceActionBatchResult,
    DeviceActionInput,
    ElementCheckInput,
    ElementCheckResult,
    ConditionCheckInput,
    LegacyConditionCheckInput,
    ExtractInput,
    ExtractResult,
    SaveExtractionInput,
    StepResult,
)
from services.extraction_usecase import (
    persist_data_items,
    resolve_comment_parent_hash,
    update_parent_stats_if_available,
)
from services.scenario_step_contract import (
    extract_data_var_for_strategy,
    normalize_extract_step,
    normalize_save_extraction_step,
)

log = logging.getLogger(__name__)

_SERIAL_RE = re.compile(r"^[\w.:_-]{1,128}$")

# Global device registry reference — set by worker at startup (before any activity runs).
_device_registry = None
_temporal_config = None


def set_device_registry(registry) -> None:
    """Called by worker startup to inject DeviceManager reference."""
    global _device_registry
    _device_registry = registry


def set_temporal_config(cfg) -> None:
    """Called by worker startup to inject TemporalConfig for finalize_campaign."""
    global _temporal_config
    _temporal_config = cfg


async def _to_thread_with_heartbeat(
    fn: Callable,
    *args: Any,
    heartbeat_interval: float = 20.0,
    **kwargs: Any,
) -> Any:
    """Run a sync blocking function in the thread pool while sending Temporal heartbeats.

    Without this, an activity with heartbeat_timeout=30s that blocks for >30s in a
    thread (waiting for UI elements, scrolling, etc.) will be cancelled by Temporal
    with CancelledError because no heartbeat arrives within the timeout window.

    heartbeat_interval should be < heartbeat_timeout (default 20s vs 30s timeout).
    """
    async def _heartbeat_loop() -> None:
        n = 0
        while True:
            await asyncio.sleep(heartbeat_interval)
            with contextlib.suppress(Exception):
                activity.heartbeat(f"running:{n}")
            n += 1

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    try:
        return await asyncio.to_thread(functools.partial(fn, *args, **kwargs))
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


def _validate_serial(serial: str) -> None:
    """Validate device serial to prevent injection attacks."""
    if not serial or not _SERIAL_RE.match(serial):
        raise ValueError(f"Invalid device serial: {serial!r}")


def _get_device(serial: str):
    """Get DeviceClient from the global device registry."""
    _validate_serial(serial)
    registry = _device_registry
    if registry is None:
        raise RuntimeError("Device registry not initialized — worker not started")
    device = registry.get_device(serial)
    if device is None:
        raise RuntimeError(f"Device {serial!r} not found in registry")
    return device


class DeviceActivities:
    """
    Temporal activity methods for device interaction.

    execute_device_action delegates to the original run_scenario_task()
    which has the full, battle-tested execution pipeline:
    - pre_hash → auto_dismiss_popup → _execute_tap(retries=2) → _wait_ui_change
    - Smart waits, fallback logic, container class skip, wrong element detection

    Credential cache: account passwords are fetched once per account_id and
    cached for the lifetime of this Worker instance. activity_session() creates
    a new async engine per call (NullPool), so caching avoids repeated
    engine-create/dispose on every step of a multi-step campaign.
    """

    def __init__(self) -> None:
        # account_id -> decrypted password; populated lazily, never evicted
        # (passwords don't change mid-campaign; Worker restarts clear the cache).
        self._cred_cache: dict[str, str] = {}
        # Prevents duplicate DB fetches when two coroutines miss the cache
        # simultaneously for the same account_id.
        self._cred_lock: asyncio.Lock = asyncio.Lock()

    async def _resolve_password(self, account_id: str) -> str | None:
        """Fetch and cache the decrypted password for account_id.

        The lock prevents the check-then-act race: without it, two coroutines
        could both miss the cache and issue duplicate DB queries for the same
        account. The fast path (cache hit) does not acquire the lock.
        """
        if account_id in self._cred_cache:
            return self._cred_cache[account_id]
        async with self._cred_lock:
            # Re-check after acquiring lock — another coroutine may have
            # populated the cache while we waited.
            if account_id in self._cred_cache:
                return self._cred_cache[account_id]
            from db.database import activity_session
            from db.crud.account import get_account
            from common.crypto import decrypt_password
            async with activity_session() as acct_db:
                account = await get_account(acct_db, account_id)
            if account is None:
                return None
            pwd = decrypt_password(account.password_encrypted)
            self._cred_cache[account_id] = pwd
            return pwd

    @activity.defn
    async def execute_device_action(self, inp: DeviceActionInput) -> StepResult:
        """
        Execute a single device action step using the original scenario executor.

        Wraps run_scenario_task() with a 1-step scenario so we get the full
        pipeline: popup dismiss, smart waits, selector fallback, UI change
        detection — exactly as described in flow.md.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        step = normalize_extract_step(inp.step)
        step_type = step.get("type", "")
        idx = inp.step_index

        activity.heartbeat(f"step:{idx}:{step_type}")

        try:
            # Import here to avoid circular imports at module level
            from tasks.scenario_task import run_scenario_task
            from common.variable_resolver import VariableContext

            # Build a 1-step scenario and run it through the ORIGINAL executor.
            # Merge scenario-level config (visual_anchor, implicit_wait, etc.)
            # so each mini-scenario inherits the parent's settings.
            mini_scenario: dict[str, Any] = {"steps": [step]}
            if inp.scenario_config:
                for key in ("visual_anchor", "implicit_wait", "capture_steps"):
                    if key in inp.scenario_config:
                        mini_scenario[key] = inp.scenario_config[key]
            # Pass scenario registry so run_scenario sub-steps can resolve
            if inp.scenario_registry:
                mini_scenario["_scenario_registry"] = inp.scenario_registry

            # Create VariableContext with all variable layers
            resolved_campaign_vars = dict(inp.campaign_vars)

            # SECURITY: Credentials resolved at activity time — never stored in Temporal
            # event history. __ACCOUNT_ID__ is a safe reference; password is fetched+decrypted
            # inside _resolve_password() (activity-local) and passed via scenario_vars,
            # NOT campaign_vars, to prevent leaking into serialized workflow state.
            credential_vars: dict[str, Any] = {}
            if "__ACCOUNT_ID__" in resolved_campaign_vars:
                acct_id = resolved_campaign_vars["__ACCOUNT_ID__"]
                pwd = await self._resolve_password(acct_id)
                if pwd is None:
                    return StepResult(
                        index=idx, step_type=step_type, ok=False,
                        message=(
                            f"Account {acct_id!r} not found — cannot resolve credentials. "
                            "Check that the account still exists in the database."
                        ),
                    )
                credential_vars["__ACCOUNT_PASSWORD__"] = pwd

            var_ctx = VariableContext(
                # Merge credentials into scenario_vars (activity-scoped) so the
                # password is available for variable resolution but never enters
                # campaign_vars, which could be serialized or logged.
                scenario_vars={**inp.variables, **credential_vars},
                campaign_vars=resolved_campaign_vars,
                device_serial=inp.device_serial,
                device_model=getattr(device, "model", ""),
            )

            result = await _to_thread_with_heartbeat(
                run_scenario_task, device, mini_scenario, _var_ctx=var_ctx,
            )

            # Extract the single step result
            step_results = result.get("step_results", [])
            if step_results:
                sr = step_results[0]

                # Self-healing hook: if selector healed during image-match,
                # include the healed selector in details for the caller to persist.
                details = {
                    k: v for k, v in sr.items()
                    if k not in ("index", "type", "ok", "message")
                }

                return StepResult(
                    index=idx,
                    step_type=step_type,
                    ok=sr.get("ok", False),
                    message=sr.get("message") or "",
                    details=details,
                )

            # No step results — check overall success
            return StepResult(
                index=idx,
                step_type=step_type,
                ok=result.get("success", False),
                message=result.get("failed_message") or "",
            )

        except BaseException as exc:
            # Re-raise cancellation signals so Temporal can propagate them correctly.
            # temporalio.exceptions.CancelledError inherits from Exception, so it must
            # be explicitly re-raised before the generic handler converts it to StepResult.
            try:
                from temporalio.exceptions import CancelledError as _TemporalCancelledError
                if isinstance(exc, (asyncio.CancelledError, _TemporalCancelledError)):
                    raise
            except ImportError:
                if isinstance(exc, _asyncio.CancelledError):
                    raise
            if not isinstance(exc, Exception):
                raise  # re-raise other BaseException (KeyboardInterrupt, SystemExit, etc.)
            log.error(
                "[%s] activity error step#%d (%s): %s",
                inp.device_serial, idx, step_type, exc,
            )
            return StepResult(
                index=idx, step_type=step_type, ok=False,
                message=f"Activity error: {exc}",
            )

    @activity.defn
    async def execute_device_action_batch(
        self, inp: DeviceActionBatchInput,
    ) -> DeviceActionBatchResult:
        """Run N consecutive leaf steps as one activity call.

        History cost: 3 events regardless of batch size (vs 3N for individual calls).
        Steps are executed sequentially; stops on the first failure unless
        the step has ignore_error=True.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        activity.heartbeat(f"batch:0/{len(inp.steps)}")

        from tasks.scenario_task import run_scenario_task
        from common.variable_resolver import VariableContext

        results: list[dict[str, Any]] = []
        first_failure_index = -1

        # Resolve credentials once for the whole batch.
        credential_vars: dict[str, Any] = {}
        acct_id = inp.campaign_vars.get("__ACCOUNT_ID__")
        if acct_id:
            pwd = await self._resolve_password(acct_id)
            if pwd is None:
                return DeviceActionBatchResult(
                    results=[{
                        "index": inp.step_indices[0] if inp.step_indices else 0,
                        "type": "batch",
                        "ok": False,
                        "message": f"Account {acct_id!r} not found",
                    }],
                    first_failure_index=0,
                )
            credential_vars["__ACCOUNT_PASSWORD__"] = pwd

        var_ctx = VariableContext(
            scenario_vars={**inp.variables, **credential_vars},
            campaign_vars=inp.campaign_vars,
            device_serial=inp.device_serial,
            device_model=getattr(device, "model", ""),
        )

        for batch_pos, (step, step_idx) in enumerate(zip(inp.steps, inp.step_indices)):
            activity.heartbeat(f"batch:{batch_pos}/{len(inp.steps)}")
            step_type = step.get("type", "")
            mini_scenario: dict[str, Any] = {"steps": [step]}
            if inp.scenario_config:
                for key in ("visual_anchor", "implicit_wait", "capture_steps"):
                    if key in inp.scenario_config:
                        mini_scenario[key] = inp.scenario_config[key]
            if inp.scenario_registry:
                mini_scenario["_scenario_registry"] = inp.scenario_registry

            try:
                result = await _to_thread_with_heartbeat(
                    run_scenario_task, device, mini_scenario, _var_ctx=var_ctx,
                )
                step_results = result.get("step_results", [])
                if step_results:
                    sr = step_results[0]
                    entry = {
                        "index": step_idx, "type": step_type,
                        "ok": sr.get("ok", False),
                        "message": sr.get("message") or "",
                        "details": {k: v for k, v in sr.items()
                                    if k not in ("index", "type", "ok", "message")},
                    }
                else:
                    entry = {
                        "index": step_idx, "type": step_type,
                        "ok": result.get("success", False),
                        "message": result.get("failed_message") or "",
                    }
            except Exception as exc:
                log.error("[%s] batch step#%d (%s): %s", inp.device_serial, step_idx, step_type, exc)
                entry = {"index": step_idx, "type": step_type, "ok": False, "message": str(exc)}

            results.append(entry)
            if not entry["ok"] and not step.get("ignore_error"):
                first_failure_index = batch_pos
                break

        return DeviceActionBatchResult(results=results, first_failure_index=first_failure_index)

    @activity.defn
    async def check_element_exists(self, inp: ElementCheckInput) -> ElementCheckResult:
        """
        Check if a UI element exists on the device screen.

        Uses the same _wait_for_element from scenario_task.py for consistency.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        activity.heartbeat(f"check_element:{inp.by}={inp.value}")

        try:
            from tasks.scenario_task import _wait_for_element

            u2 = device.u2
            if u2 is None:
                device.ensure_u2_healthy()
                u2 = device.u2

            if u2 is None:
                return ElementCheckResult(found=False, message="u2 not available")

            eid = await _to_thread_with_heartbeat(_wait_for_element, u2, inp.by, inp.value, timeout=inp.timeout)
            found = eid is not None
            return ElementCheckResult(
                found=found,
                message=f"element {inp.by}={inp.value!r}: {'found' if found else 'not found'}",
            )
        except Exception as exc:
            log.debug("[%s] check_element error: %s", inp.device_serial, exc)
            return ElementCheckResult(found=False, message=f"check error: {exc}")

    @activity.defn
    async def evaluate_legacy_condition(self, inp: LegacyConditionCheckInput) -> bool:
        """
        Evaluate a generic condition dict (if / loop while / break_if steps).

        Supports: element_exists, element_not_exists, posts_count_gte,
        posts_count_lt, no_new_posts. Delegates to _evaluate_condition from
        scenario_task.py so condition semantics stay in one place.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        activity.heartbeat("evaluate_legacy_condition")

        try:
            from tasks.scenario_task import _evaluate_condition

            # Reconstruct a ctx dict that _evaluate_condition expects.
            # Merge: runtime_vars under "vars" key + flat context keys (posts, etc.)
            ctx: dict[str, Any] = dict(inp.context)
            if inp.runtime_vars:
                ctx.setdefault("vars", {}).update(inp.runtime_vars)

            return await _to_thread_with_heartbeat(_evaluate_condition, device, inp.condition, ctx)
        except Exception as exc:
            log.error("[%s] evaluate_legacy_condition error: %s", inp.device_serial, exc)
            return False

    @activity.defn
    async def execute_extract(self, inp: ExtractInput) -> ExtractResult:
        """
        Execute an 'extract' step (fb_posts / text_nodes / fb_comments strategies).

        Returns updated context (posts, text_nodes, comments, _no_new_streak) and
        break_requested flag when stop_if_no_new triggers.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        step = inp.step
        idx = inp.step_index
        activity.heartbeat(f"extract:{idx}:{step.get('strategy', 'fb_posts')}")

        # Work on a deep-enough copy so we never mutate the input.
        # Lists (posts, text_nodes) are copied explicitly to prevent shared-reference mutation.
        ctx: dict[str, Any] = {}
        for _k, _v in inp.context.items():
            ctx[_k] = list(_v) if isinstance(_v, list) else _v
        ctx.setdefault("posts", [])
        ctx.setdefault("comments", [])

        strategy = str(step.get("strategy", "fb_posts"))
        stop_if_no_new = bool(step.get("stop_if_no_new", False))
        no_new_threshold = int(step.get("no_new_threshold", 3))
        expand_see_more = bool(step.get("expand_see_more", True))
        _ecr = step.get("expand_completion_retries", 3)
        completion_retries = max(0, int(3 if _ecr is None else _ecr))
        em_passes = int(step.get("expand_see_more_max_passes", 2))
        em_scroll = bool(step.get("expand_see_more_scroll", False))
        em_scroll_distance = float(step.get("expand_see_more_scroll_distance", 0.3))
        lazy_rounds = int(step.get("expand_lazy_hydration_rounds", 6))
        lazy_scroll = float(step.get("expand_lazy_scroll_distance", em_scroll_distance))
        prefetch_passes = int(step.get("expand_prefetch_scroll_passes", 0) or 0)
        break_requested = False
        details: dict[str, Any] = {}

        try:
            # Always pre-expand fb_posts when enabled (see scenario_task extract notes).
            do_pre_expand = expand_see_more and strategy in ("fb_posts", "fb_comments")
            if do_pre_expand:
                try:
                    if strategy == "fb_posts":
                        from tasks.fb_extract import expand_see_more_with_lazy_hydration

                        expanded = await _to_thread_with_heartbeat(
                            expand_see_more_with_lazy_hydration,
                            device,
                            max_rounds=max(3, lazy_rounds),
                            scroll_distance=max(0.12, lazy_scroll),
                        )
                    else:
                        from tasks.fb_extract import _expand_see_more

                        expanded = await _to_thread_with_heartbeat(
                            _expand_see_more,
                            device,
                            max_passes=em_passes,
                            scroll_between=em_scroll,
                            scroll_distance=em_scroll_distance,
                        )
                    if expanded:
                        await asyncio.sleep(0.55 if strategy == "fb_comments" else 0.35)
                except Exception:
                    pass

            if strategy == "fb_posts" and expand_see_more and prefetch_passes > 0:
                try:
                    from tasks.fb_extract import prefetch_viewport_scrolls

                    await _to_thread_with_heartbeat(
                        prefetch_viewport_scrolls,
                        device,
                        passes=prefetch_passes,
                        distance=max(0.15, em_scroll_distance),
                        pause_s=float(step.get("expand_prefetch_scroll_pause", 0.7)),
                    )
                except Exception:
                    pass

            xml = await _to_thread_with_heartbeat(device.hierarchy_xml, force_refresh=True)
            if not xml:
                return ExtractResult(
                    ok=False,
                    message="extract: hierarchy_xml returned None",
                    context=ctx,
                )

            if strategy == "fb_posts":
                from tasks.fb_extract import (
                    parse_fb_posts_from_xml,
                    _dedup,
                    is_fb_post_truncated,
                    expand_see_more_with_lazy_hydration,
                )
                from services.content_store import compute_content_hash, scope_content_hash
                scroll_idx = ctx.get("_loop_iter", 0)
                new_posts = parse_fb_posts_from_xml(xml, source_index=scroll_idx)

                def _snapshot(posts: list[dict[str, Any]]) -> tuple[int, int]:
                    unresolved = sum(1 for _p in posts if is_fb_post_truncated(_p))
                    total_len = sum(len(str(_p.get("text") or "")) for _p in posts)
                    return unresolved, total_len

                unresolved_first, total_len_first = _snapshot(new_posts)

                if expand_see_more and any(is_fb_post_truncated(p) for p in new_posts):
                    try:
                        await _to_thread_with_heartbeat(
                            expand_see_more_with_lazy_hydration,
                            device,
                            max_rounds=max(2, min(lazy_rounds, 5)),
                            scroll_distance=max(0.12, lazy_scroll),
                        )
                        xml_h = await _to_thread_with_heartbeat(device.hierarchy_xml, force_refresh=True)
                        if xml_h:
                            new_posts = _dedup(
                                new_posts
                                + parse_fb_posts_from_xml(xml_h, source_index=scroll_idx)
                            )
                    except Exception:
                        pass

                unresolved_before, total_len_before = _snapshot(new_posts)
                retries_done = 0
                plateau = 0
                if expand_see_more and unresolved_before > 0:
                    max_retries = max(1, min(4, completion_retries))
                    prev_unresolved, prev_total_len = unresolved_before, total_len_before
                    for _ in range(max_retries):
                        retries_done += 1
                        try:
                            await _to_thread_with_heartbeat(
                                expand_see_more_with_lazy_hydration,
                                device,
                                max_rounds=max(3, min(lazy_rounds, 8)),
                                scroll_distance=max(0.12, lazy_scroll),
                            )
                            await asyncio.sleep(0.6)
                            xml_retry = await _to_thread_with_heartbeat(device.hierarchy_xml, force_refresh=True)
                            if not xml_retry:
                                break
                            retry_posts = parse_fb_posts_from_xml(xml_retry, source_index=scroll_idx)
                            # Merge instead of replacing to prevent viewport-drift data loss.
                            candidate_posts = _dedup(new_posts + (retry_posts or []))
                            curr_unresolved, curr_total_len = _snapshot(candidate_posts)
                            improved = (
                                (curr_unresolved < prev_unresolved)
                                or (curr_total_len > prev_total_len + 20)
                            )
                            new_posts = candidate_posts
                            if improved:
                                plateau = 0
                            else:
                                plateau += 1
                            prev_unresolved, prev_total_len = curr_unresolved, curr_total_len
                            if curr_unresolved == 0 or plateau >= 2:
                                break
                        except Exception:
                            break

                unresolved_after, total_len_after = _snapshot(new_posts)
                prev_count = len(ctx["posts"])
                ctx["posts"] = _dedup(ctx["posts"] + new_posts)
                added = len(ctx["posts"]) - prev_count
                details["extracted"] = added
                details["total_posts"] = len(ctx["posts"])
                details["extract_diagnostics"] = {
                    "unresolved_first_parse": unresolved_first,
                    "total_len_first_parse": total_len_first,
                    "unresolved_before": unresolved_before,
                    "unresolved_after": unresolved_after,
                    "total_len_before": total_len_before,
                    "total_len_after": total_len_after,
                    "completion_retries": retries_done,
                    "plateau_count": plateau,
                }
                msg = f"extract fb_posts: +{added} new (total {len(ctx['posts'])})"
                log.info(
                    "[%s] extract fb_posts diagnostics: unresolved %s->%s, len %s->%s, retries=%s, plateau=%s",
                    inp.device_serial,
                    unresolved_before,
                    unresolved_after,
                    total_len_before,
                    total_len_after,
                    retries_done,
                    plateau,
                )
                # Track first VISIBLE post for comment linking.
                # Uses new_posts[0] (topmost post on screen), NOT the first "new" post,
                # because tap_selector("Bình luận") taps the topmost button on screen.
                if new_posts:
                    ctx["_first_new_post_hash"] = scope_content_hash(
                        compute_content_hash(new_posts[0], dedupe_field="post_key"),
                        inp.execution_id or inp.run_id,
                    )
                    pid_map = {}
                    for _p in new_posts:
                        if _p.get("_pid"):
                            pid_map[_p["_pid"]] = scope_content_hash(
                                compute_content_hash(_p, dedupe_field="post_key"),
                                inp.execution_id or inp.run_id,
                            )
                    ctx["_post_id_map"] = pid_map
                    _tpid = new_posts[0].get("_pid")
                    if _tpid:
                        ctx["_fb_comment_parent_pid"] = _tpid
                    else:
                        ctx.pop("_fb_comment_parent_pid", None)
                else:
                    ctx.pop("_fb_comment_parent_pid", None)
                if stop_if_no_new:
                    if added == 0:
                        base_streak = ctx.get("_no_new_posts_streak", ctx.get("_no_new_streak", 0))
                        ctx["_no_new_posts_streak"] = base_streak + 1
                        # Backward compatibility for any condition using legacy key.
                        ctx["_no_new_streak"] = ctx["_no_new_posts_streak"]
                        if ctx["_no_new_posts_streak"] >= no_new_threshold:
                            break_requested = True
                            msg += f" — breaking (no new for {ctx['_no_new_posts_streak']} scrolls)"
                    else:
                        ctx["_no_new_posts_streak"] = 0
                        ctx["_no_new_streak"] = 0

            elif strategy == "text_nodes":
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml)
                texts = [
                    (node.get("text") or "").strip()
                    for node in root.iter()
                    if len((node.get("text") or "").strip()) > 2
                ]
                # Ensure we have our own list (not shared with inp.context)
                ctx["text_nodes"] = list(ctx.get("text_nodes") or [])
                ctx["text_nodes"].extend(texts)
                details["extracted"] = len(texts)
                msg = f"extract text_nodes: {len(texts)} texts"

            elif strategy == "fb_comments":
                from tasks.fb_extract import (
                    parse_fb_comments_from_xml,
                    _dedup_comments,
                    _is_junk_parsed_comment_row,
                    _post_id_from_ctx,
                )
                ctx["_active_comment_parent_hash"] = None
                parent_post_id_var = step.get("parent_post_id_var")
                max_items = int(step.get("max_items") or 400)
                comment_scroll_passes = int(
                    step.get("comment_scroll_passes")
                    or step.get("scroll_passes")
                    or 0
                )
                comment_scroll_distance = float(
                    step.get("comment_scroll_distance")
                    or step.get("scroll_distance")
                    or 0.45
                )
                comment_scroll_pause_s = float(
                    step.get("comment_scroll_pause_s")
                    or step.get("scroll_pause_s")
                    or 0.45
                )
                no_growth_break = int(step.get("comment_no_growth_break") or 2)
                min_comment_scan_passes = int(step.get("min_comment_scan_passes") or 0)
                parent_post_id = _post_id_from_ctx(ctx, parent_post_id_var)

                def _parse_comment_frame(frame_xml: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
                    raw_items = parse_fb_comments_from_xml(
                        frame_xml,
                        parent_post_id=parent_post_id,
                        max_items=max_items,
                    )
                    frame_post_stats = next((x for x in raw_items if x.get("_type") == "post_stats"), None)
                    frame_comments = [
                        x
                        for x in raw_items
                        if x.get("_type") != "post_stats"
                        and not _is_junk_parsed_comment_row(x)
                    ]
                    return frame_post_stats, frame_comments

                # Parse current viewport first, then scroll several passes to collect more comments.
                post_stats, new_comments = _parse_comment_frame(xml)
                def _comment_identity(row: dict[str, Any]) -> str:
                    return str(
                        row.get("comment_key")
                        or f"{row.get('author','')}|{row.get('text','')}|{row.get('timestamp','')}"
                    )
                seen_comment_keys = {_comment_identity(c) for c in new_comments}
                scanned_frames = 1
                growthless_streak = 0
                for pass_idx in range(max(0, comment_scroll_passes)):
                    if len(new_comments) >= max_items:
                        break
                    await _to_thread_with_heartbeat(
                        device.scroll,
                        "down",
                        max(0.1, min(0.9, comment_scroll_distance)),
                    )
                    await asyncio.sleep(max(0.1, comment_scroll_pause_s))
                    xml_next = await _to_thread_with_heartbeat(device.hierarchy_xml, force_refresh=True)
                    if not xml_next:
                        break
                    scanned_frames += 1
                    frame_stats, frame_comments = _parse_comment_frame(xml_next)
                    if frame_stats:
                        post_stats = frame_stats
                    prev_len = len(new_comments)
                    for c in frame_comments:
                        key = _comment_identity(c)
                        if key in seen_comment_keys:
                            continue
                        seen_comment_keys.add(key)
                        new_comments.append(c)
                    if len(new_comments) == prev_len:
                        growthless_streak += 1
                        # Don't terminate too early: first passes often only warm up/lazy-load.
                        if (
                            pass_idx + 1 >= max(0, min_comment_scan_passes)
                            and growthless_streak >= max(1, no_growth_break)
                        ):
                            break
                    else:
                        growthless_streak = 0
                # Final safety dedup (single pass), avoids repeated N^2-ish dedup per frame.
                new_comments = _dedup_comments(new_comments)

                # Update parent post reaction/share counts with more accurate comment-view values
                if post_stats:
                    ctx["_comment_view_stats"] = post_stats
                    parent_hash = resolve_comment_parent_hash(ctx, parent_post_id)
                    if parent_hash:
                        ctx["_active_comment_parent_hash"] = parent_hash
                        try:
                            await update_parent_stats_if_available(
                                content_hash=parent_hash,
                                post_stats=post_stats,
                            )
                        except Exception as exc:
                            log.warning(f"update_content_stats failed: {exc}")
                else:
                    parent_hash = resolve_comment_parent_hash(ctx, parent_post_id)
                    if parent_hash:
                        ctx["_active_comment_parent_hash"] = parent_hash

                ctx.setdefault("comments", [])
                prev_count = len(ctx["comments"])
                ctx["comments"] = _dedup_comments(ctx["comments"] + new_comments)
                added = len(ctx["comments"]) - prev_count
                details["extracted"] = added
                details["total_comments"] = len(ctx["comments"])
                details["parent_post_id"] = parent_post_id
                details["post_stats"] = post_stats
                details["comment_scan"] = {
                    "frames": scanned_frames,
                    "scroll_passes": comment_scroll_passes,
                    "max_items": max_items,
                    "growthless_streak": growthless_streak,
                    "min_scan_passes": min_comment_scan_passes,
                }
                msg = (
                    f"extract fb_comments: +{added} new "
                    f"(total {len(ctx['comments'])}, post={parent_post_id})"
                )
                if stop_if_no_new:
                    if added == 0:
                        ctx["_no_new_comments_streak"] = ctx.get("_no_new_comments_streak", 0) + 1
                        # Backward compatibility for legacy condition key.
                        ctx["_no_new_streak"] = ctx["_no_new_comments_streak"]
                        if ctx["_no_new_comments_streak"] >= no_new_threshold:
                            break_requested = True
                            msg += (
                                f" — breaking comments loop (no new for {ctx['_no_new_comments_streak']} scrolls)"
                            )
                    else:
                        ctx["_no_new_comments_streak"] = 0
                        ctx["_no_new_streak"] = 0
            else:
                return ExtractResult(
                    ok=False,
                    message=f"extract: unknown strategy {strategy!r}",
                    context=ctx,
                )

            # Temporal path parity with task-queue path: optional inline autosave.
            # If `collection` exists on extract step, persist newly extracted records now.
            collection = str(step.get("collection") or "").strip()
            if collection:
                offsets = ctx.get("__save_extraction_offsets__", ctx.get("__extract_save_offsets__", {}))
                extracted_var = extract_data_var_for_strategy(step)
                source_data = ctx.get(extracted_var)
                parent_hash = ctx.get("_active_comment_parent_hash")
                item_level = 1 if strategy == "fb_comments" else 0
                report, updated_offsets = await persist_data_items(
                    data=source_data,
                    data_var=extracted_var,
                    offsets=offsets,
                    collection=collection,
                    platform=step.get("platform"),
                    content_type=step.get("content_type", "comment" if strategy == "fb_comments" else "post"),
                    dedupe_field=step.get("dedupe_field"),
                    tags=step.get("tags"),
                    device_serial=inp.device_serial,
                    campaign_id=inp.campaign_id,
                    execution_id=inp.execution_id or inp.run_id,
                    parent_id=parent_hash if strategy == "fb_comments" else None,
                    item_level=item_level,
                    user_id=inp.user_id,
                )
                # Use one shared namespace so extract inline-save and explicit save_extraction
                # coordinate offsets for the same data_var.
                ctx["__save_extraction_offsets__"] = updated_offsets
                details["auto_save"] = {
                    "saved": report.saved_count,
                    "duplicate": report.duplicate_count,
                    "errors": report.error_count,
                    "saved_count": report.saved_count,
                    "duplicate_count": report.duplicate_count,
                    "error_count": report.error_count,
                }

            return ExtractResult(
                ok=True,
                message=msg,
                context=ctx,
                break_requested=break_requested,
                details=details,
            )

        except Exception as exc:
            log.error("[%s] execute_extract error: %s", inp.device_serial, exc)
            return ExtractResult(ok=False, message=f"extract failed: {exc}", context=ctx)

    @activity.defn
    async def execute_save_extraction(self, inp: SaveExtractionInput) -> StepResult:
        """
        Execute a 'save_extraction' step as a native async activity.

        Unlike the TaskQueue path (which uses asyncio.run in a thread),
        this activity is fully async and safe with the asyncpg connection pool.
        """
        _validate_serial(inp.device_serial)
        step = normalize_save_extraction_step(inp.step)
        idx = inp.step_index
        activity.heartbeat(f"save_extraction:{idx}")

        data_var = step.get("data_var", "")
        if not data_var:
            return StepResult(
                index=idx, step_type="save_extraction", ok=False,
                message="save_extraction: missing data_var",
            )

        ctx = dict(inp.context)
        data = ctx.get(data_var)

        if data is None:
            return StepResult(
                index=idx, step_type="save_extraction", ok=False,
                message=f"save_extraction: variable '{data_var}' not found in context",
            )

        try:
            if not isinstance(data, (str, dict, list)):
                return StepResult(
                    index=idx, step_type="save_extraction", ok=False,
                    message=f"save_extraction: unsupported type for '{data_var}': {type(data).__name__}",
                )
            if isinstance(data, list) and data and not any(isinstance(item, dict) for item in data):
                return StepResult(
                    index=idx,
                    step_type="save_extraction",
                    ok=False,
                    message=f"save_extraction: variable '{data_var}' is a list but has no object items",
                )

            offsets = ctx.get("__save_extraction_offsets__", {})
            coll = step.get("collection", "default")
            platform = step.get("platform")
            ctype = step.get("content_type", "post")
            dedupe_field = step.get("dedupe_field")
            tags = step.get("tags", "")
            parent_id_var = step.get("parent_id_var")
            parent_id = ctx.get(parent_id_var) if parent_id_var else None
            item_level = int(step.get("item_level") or 0)
            report, updated_offsets = await persist_data_items(
                data=data,
                data_var=data_var,
                offsets=offsets,
                collection=coll,
                platform=platform,
                content_type=ctype,
                dedupe_field=dedupe_field,
                tags=tags,
                device_serial=inp.device_serial,
                campaign_id=inp.campaign_id,
                execution_id=inp.execution_id,
                parent_id=parent_id,
                item_level=item_level,
                user_id=inp.user_id,
            )
            ok = not (
                report.error_count > 0
                and report.saved_count == 0
                and report.duplicate_count == 0
            )
            msg = (
                f"save_extraction: saved={report.saved_count}, "
                f"duplicate={report.duplicate_count}, errors={report.error_count}"
            )
            if not ok:
                msg = "save_extraction: all items failed"

            return StepResult(
                index=idx, step_type="save_extraction", ok=ok, message=msg,
                details={
                    "saved_count": report.saved_count,
                    "duplicate_count": report.duplicate_count,
                    "error_count": report.error_count,
                    "updated_offsets": updated_offsets,
                },
            )

        except Exception as exc:
            log.error("[%s] execute_save_extraction error: %s", inp.device_serial, exc)
            return StepResult(
                index=idx, step_type="save_extraction", ok=False,
                message=f"save_extraction failed: {exc}",
            )

    @activity.defn
    async def evaluate_condition(self, inp: ConditionCheckInput) -> bool:
        """
        Evaluate a repeat_until stop condition.

        Uses _eval_ru_condition from scenario_task.py for consistency.
        """
        _validate_serial(inp.device_serial)
        device = _get_device(inp.device_serial)
        activity.heartbeat("evaluate_condition")

        try:
            from tasks.scenario_task import _eval_ru_condition
            from common.variable_resolver import VariableContext

            # Build a VariableContext with runtime vars for condition evaluation
            var_ctx = VariableContext(
                device_serial=inp.device_serial,
                device_model=getattr(device, "model", ""),
            )
            # Inject runtime vars
            for name, value in inp.runtime_vars.items():
                var_ctx.set(name, value)

            return _eval_ru_condition(device, inp.condition, var_ctx)
        except Exception as exc:
            log.warning("evaluate_condition error: %s", exc)
            return False

    @activity.defn
    async def finalize_campaign(self, inp: dict) -> None:
        """Update Execution + Campaign DB status when a workflow ends.

        Called at the end of ScenarioWorkflow.run (success, failure, or cancel).
        - When all workflows for the campaign are done, sets Campaign.status = "idle".

        Accepts a dict: {"campaign_id": str, "execution_id": str|None, "success": bool}
        (kept as dict for Temporal serialization simplicity).
        """
        # Support both old str payload (backward compat) and new dict payload.
        if isinstance(inp, str):
            campaign_id: str = inp
            success = True
            execution_id = None
            device_serial = None
            step_results: list = []
        else:
            campaign_id = inp.get("campaign_id", "")
            success = bool(inp.get("success", True))
            # run_id is legacy alias for execution_id
            execution_id = inp.get("execution_id") or inp.get("run_id")
            device_serial = inp.get("device_serial")
            step_results = inp.get("step_results") or []

        activity.heartbeat("finalize_campaign")

        # Persist per-device execution result
        if execution_id and device_serial:
            try:
                from datetime import datetime, timezone as _tz
                from db.database import activity_session
                from db.crud.execution import upsert_execution_result
                from db.crud.device import get_device_by_serial
                er_status = "passed" if success else "failed"
                passed_steps = [s for s in step_results if s.get("ok")]
                failed_steps = [s for s in step_results if not s.get("ok")]
                _device_id = None
                async with activity_session() as db:
                    device = await get_device_by_serial(db, device_serial)
                    if device:
                        _device_id = device.id
                        await upsert_execution_result(
                            db,
                            execution_id=execution_id,
                            device_id=device.id,
                            status=er_status,
                            passed_steps=passed_steps,
                            failed_steps=failed_steps,
                            finished_at=datetime.now(_tz.utc),
                        )
                        # DLQ: create entry when run fails
                        if not success:
                            from db.crud.execution_dlq import create_dlq_entry
                            error_msg = (failed_steps[-1].get("message") if failed_steps else None)
                            await create_dlq_entry(
                                db,
                                execution_id=execution_id,
                                device_serial=device_serial,
                                error=error_msg,
                            )
                        await db.commit()
                log.info(
                    "finalize_campaign: execution_result %s/%s → %s",
                    execution_id, device_serial, er_status,
                )
                # Webhook: fire-and-forget notification
                org_id = inp.get("org_id") if isinstance(inp, dict) else None
                if org_id:
                    from services.webhook_dispatcher import dispatch_webhook
                    event = "task.complete" if success else "task.failed"
                    await dispatch_webhook(org_id, event, {
                        "execution_id": execution_id,
                        "device_serial": device_serial,
                        "status": er_status,
                        "passed_steps": len(passed_steps),
                        "failed_steps": len(failed_steps),
                    })
            except Exception as exc:
                log.warning(
                    "finalize_campaign: execution_result update failed (%s/%s): %s",
                    execution_id, device_serial, exc,
                )

        if not campaign_id:
            return

        cfg = _temporal_config
        if cfg is None:
            log.warning("finalize_campaign: no temporal config, skipping campaign status update")
            return
        try:
            from temporal.worker import get_temporal_client
            client = await get_temporal_client(cfg)
            # This activity runs *while* the parent ScenarioWorkflow is still in
            # ExecutionStatus=Running (it awaits this activity before return).
            # Without excluding the caller, list_workflows always sees ≥1 match
            # and the campaign never flips back to idle in the DB.
            try:
                caller_wf_id = activity.info().workflow_id or ""
            except Exception:
                caller_wf_id = ""
            wf_query = (
                f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" '
                f'AND ExecutionStatus="Running"'
            )
            still_running = 0
            async for wf_exec in client.list_workflows(wf_query):
                if caller_wf_id and wf_exec.id == caller_wf_id:
                    continue
                still_running += 1
                break  # one other running workflow is enough
            if still_running == 0:
                from db.database import activity_session
                from db.crud.campaign import update_campaign_status
                async with activity_session() as db:
                    await update_campaign_status(db, campaign_id, "idle")
                    await db.commit()
                log.info("finalize_campaign: campaign %s → idle", campaign_id)
        except Exception as exc:
            log.warning("finalize_campaign error (campaign %s): %s", campaign_id, exc)


def _xml_has_element(xml: str, by: str, value: str) -> bool:
    """Check if XML hierarchy contains element matching (by, value).

    Uses attribute iteration instead of XPath f-string interpolation
    to prevent XPath injection when value contains quotes.
    """
    if not xml or not value:
        return False
    try:
        root = ET.fromstring(xml)
        attr_map = {
            "text": "text",
            "resource-id": "resource-id",
            "content-desc": "content-desc",
            "accessibility id": "content-desc",
            "class name": "class",
        }
        attr = attr_map.get(by)
        if attr:
            return any(node.get(attr) == value for node in root.iter())
        for node in root.iter():
            if node.get("text") == value or node.get("resource-id") == value:
                return True
        return False
    except Exception:
        return False
