

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from temporalio import activity

from temporal.shared import (
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
    """

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
        step = inp.step
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

            # SECURITY: Credentials are resolved here at activity time — never stored in
            # Temporal event history. __ACCOUNT_ID__ is a safe reference passed via workflow
            # input; the actual password is fetched+decrypted only within this activity scope.
            # SECURITY: Credentials resolved here at activity time — never stored in
            # Temporal event history. __ACCOUNT_ID__ is the safe reference from workflow
            # input; the password is fetched+decrypted only within this activity scope
            # and passed via scenario_vars (activity-local), NOT campaign_vars, to
            # prevent it from leaking into serialized workflow state.
            credential_vars: dict[str, Any] = {}
            if "__ACCOUNT_ID__" in resolved_campaign_vars:
                from db.database import activity_session
                from db.crud.account import get_account
                from common.crypto import decrypt_password

                acct_id = resolved_campaign_vars["__ACCOUNT_ID__"]
                async with activity_session() as acct_db:
                    account = await get_account(acct_db, acct_id)
                if account is None:
                    return StepResult(
                        index=idx, step_type=step_type, ok=False,
                        message=(
                            f"Account {acct_id!r} not found — cannot resolve credentials. "
                            "Check that the account still exists in the database."
                        ),
                    )
                credential_vars["__ACCOUNT_PASSWORD__"] = decrypt_password(
                    account.password_encrypted
                )

            var_ctx = VariableContext(
                # Merge credentials into scenario_vars (activity-scoped) so the
                # password is available for variable resolution but never enters
                # campaign_vars, which could be serialized or logged.
                scenario_vars={**inp.variables, **credential_vars},
                campaign_vars=resolved_campaign_vars,
                device_serial=inp.device_serial,
                device_model=getattr(device, "model", ""),
            )

            result = run_scenario_task(
                device,
                mini_scenario,
                _var_ctx=var_ctx,
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
            import asyncio as _asyncio
            try:
                from temporalio.exceptions import CancelledError as _TemporalCancelledError
                if isinstance(exc, (_asyncio.CancelledError, _TemporalCancelledError)):
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

            eid = _wait_for_element(u2, inp.by, inp.value, timeout=inp.timeout)
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

            return _evaluate_condition(device, inp.condition, ctx)
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
        break_requested = False
        details: dict[str, Any] = {}

        try:
            if strategy == "fb_posts" and expand_see_more:
                try:
                    from tasks.fb_extract import _expand_see_more
                    if _expand_see_more(device):
                        import asyncio as _asyncio
                        await _asyncio.sleep(0.5)
                except Exception:
                    pass

            xml = device.hierarchy_xml(force_refresh=True)
            if not xml:
                return ExtractResult(
                    ok=False,
                    message="extract: hierarchy_xml returned None",
                    context=ctx,
                )

            if strategy == "fb_posts":
                from tasks.fb_extract import parse_fb_posts_from_xml, _dedup
                from services.content_store import compute_content_hash
                scroll_idx = ctx.get("_loop_iter", 0)
                new_posts = parse_fb_posts_from_xml(xml, source_index=scroll_idx)
                prev_count = len(ctx["posts"])
                ctx["posts"] = _dedup(ctx["posts"] + new_posts)
                added = len(ctx["posts"]) - prev_count
                details["extracted"] = added
                details["total_posts"] = len(ctx["posts"])
                msg = f"extract fb_posts: +{added} new (total {len(ctx['posts'])})"
                # Track first VISIBLE post for comment linking.
                # Uses new_posts[0] (topmost post on screen), NOT the first "new" post,
                # because tap_selector("Bình luận") taps the topmost button on screen.
                if new_posts:
                    ctx["_first_new_post_hash"] = compute_content_hash(
                        new_posts[0], dedupe_field="text"
                    )
                if stop_if_no_new:
                    if added == 0:
                        ctx["_no_new_streak"] = ctx.get("_no_new_streak", 0) + 1
                        if ctx["_no_new_streak"] >= no_new_threshold:
                            break_requested = True
                            msg += f" — breaking (no new for {ctx['_no_new_streak']} scrolls)"
                    else:
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
                    parse_fb_comments_from_xml, _dedup_comments, _post_id_from_ctx,
                )
                parent_post_id_var = inp.step.get("parent_post_id_var")
                max_items = int(inp.step.get("max_items") or 50)
                parent_post_id = _post_id_from_ctx(ctx, parent_post_id_var)
                raw_items = parse_fb_comments_from_xml(
                    xml, parent_post_id=parent_post_id, max_items=max_items,
                )
                # Separate post_stats sentinel from actual comments
                post_stats = next((x for x in raw_items if x.get("_type") == "post_stats"), None)
                new_comments = [x for x in raw_items if x.get("_type") != "post_stats"]

                # Update parent post reaction/share counts with more accurate comment-view values
                if post_stats:
                    ctx["_comment_view_stats"] = post_stats
                    parent_hash = ctx.get("_first_new_post_hash")
                    if parent_hash:
                        try:
                            from db.database import activity_session
                            from db.crud.content import update_content_stats
                            from services.content_store import _safe_int
                            async with activity_session() as _db:
                                updated = await update_content_stats(
                                    _db,
                                    content_hash=parent_hash,
                                    likes_count=_safe_int(post_stats.get("reactions")),
                                    shares_count=_safe_int(post_stats.get("shares")),
                                )
                                if updated:
                                    await _db.commit()
                        except Exception as exc:
                            log.warning(f"update_content_stats failed: {exc}")

                ctx.setdefault("comments", [])
                prev_count = len(ctx["comments"])
                ctx["comments"] = _dedup_comments(ctx["comments"] + new_comments)
                added = len(ctx["comments"]) - prev_count
                details["extracted"] = added
                details["total_comments"] = len(ctx["comments"])
                details["parent_post_id"] = parent_post_id
                details["post_stats"] = post_stats
                msg = (
                    f"extract fb_comments: +{added} new "
                    f"(total {len(ctx['comments'])}, post={parent_post_id})"
                )
            else:
                return ExtractResult(
                    ok=False,
                    message=f"extract: unknown strategy {strategy!r}",
                    context=ctx,
                )

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
        step = inp.step
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
            from services.content_store import save_content_item

            items: list[dict[str, Any]] = []
            if isinstance(data, str):
                items = [{"text": data}]
            elif isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = [item for item in data if isinstance(item, dict)]
            else:
                return StepResult(
                    index=idx, step_type="save_extraction", ok=False,
                    message=f"save_extraction: unsupported type for '{data_var}': {type(data).__name__}",
                )

            # Offset tracking so repeated calls don't re-save already-saved items
            offsets = ctx.get("__save_extraction_offsets__", {})
            start_idx = int(offsets.get(data_var, 0))
            if start_idx > 0:
                items = items[start_idx:]

            if not items:
                return StepResult(
                    index=idx, step_type="save_extraction", ok=True,
                    message="save_extraction: no new items to save",
                    details={"saved_count": 0, "duplicate_count": 0, "error_count": 0},
                )

            coll = step.get("collection", "default")
            platform = step.get("platform")
            ctype = step.get("content_type", "post")
            dedupe_field = step.get("dedupe_field")
            tags = step.get("tags", "")
            parent_id_var = step.get("parent_id_var")
            parent_id = ctx.get(parent_id_var) if parent_id_var else None
            item_level = int(step.get("item_level") or 0)
            saved = dup = err = 0

            for item in items:
                try:
                    result = await save_content_item(
                        data=item,
                        collection=coll,
                        platform=platform,
                        content_type=ctype,
                        dedupe_field=dedupe_field,
                        tags=tags,
                        device_serial=inp.device_serial,
                        campaign_id=inp.campaign_id,
                        run_id=inp.run_id,
                        parent_id=parent_id,
                        item_level=item_level,
                    )
                    if result.get("saved"):
                        saved += 1
                    else:
                        dup += 1
                except Exception as exc:
                    err += 1
                    log.warning("[%s] save_extraction item failed: %s", inp.device_serial, exc)
                    # Continue processing remaining items — don't bail on first error.

            ok = not (err > 0 and saved == 0 and dup == 0)
            msg = f"save_extraction: saved={saved}, duplicate={dup}, errors={err}"
            if not ok:
                msg = "save_extraction: all items failed"

            # Advance offset only past items that were successfully processed (saved or
            # deduplicated). Items that errored are NOT counted so a Temporal retry
            # will re-attempt them rather than silently skipping them.
            # Design trade-off (at-least-once): if the activity is retried after a partial
            # write (e.g. DB commit succeeded but activity heartbeat was lost), previously
            # saved items will be re-attempted. The `dedupe_field` key prevents duplicate
            # rows — so at-least-once is safe as long as dedupe_field is configured.
            new_offset = start_idx + saved + dup
            updated_offsets = {data_var: new_offset}

            return StepResult(
                index=idx, step_type="save_extraction", ok=ok, message=msg,
                details={
                    "saved_count": saved,
                    "duplicate_count": dup,
                    "error_count": err,
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
        """Update CampaignRun + Campaign DB status when a workflow ends.

        Called at the end of ScenarioWorkflow.run (success, failure, or cancel).
        - Always updates CampaignRun.status to "completed" or "failed".
        - When all workflows for the campaign are done, sets Campaign.status = "idle".

        Accepts a dict: {"campaign_id": str, "run_id": str|None, "success": bool}
        (kept as dict for Temporal serialization simplicity).
        """
        # Support both old str payload (backward compat) and new dict payload.
        if isinstance(inp, str):
            campaign_id: str = inp
            run_id = None
            success = True
        else:
            campaign_id = inp.get("campaign_id", "")
            run_id = inp.get("run_id")
            success = bool(inp.get("success", True))

        activity.heartbeat("finalize_campaign")

        # Always update the CampaignRun status so the UI reflects real outcome.
        if run_id:
            try:
                from db.database import activity_session
                from db.crud.campaign_run import finish_campaign_run
                run_status = "completed" if success else "failed"
                async with activity_session() as db:
                    await finish_campaign_run(db, run_id, status=run_status)
                    await db.commit()
                log.info("finalize_campaign: run %s → %s", run_id, run_status)
            except Exception as exc:
                log.warning("finalize_campaign: run status update failed (%s): %s", run_id, exc)

        if not campaign_id:
            return

        cfg = _temporal_config
        if cfg is None:
            log.warning("finalize_campaign: no temporal config, skipping campaign status update")
            return
        try:
            from temporal.worker import get_temporal_client
            client = await get_temporal_client(cfg)
            wf_query = (
                f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" '
                f'AND ExecutionStatus="Running"'
            )
            still_running = 0
            async for _ in client.list_workflows(wf_query):
                still_running += 1
                break  # one is enough to know we're not done
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
