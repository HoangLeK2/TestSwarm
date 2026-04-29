"""Step handlers: extract, extract_text_hierarchy, extract_text_ocr, extract_text_ai, extract_screen_data."""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from tasks.scenario.failure_bundle import capture_failure_bundle
from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext
from services.extraction_usecase import resolve_comment_parent_hash

log = logging.getLogger(__name__)

try:
    _trace_log = importlib.import_module("structlog").get_logger("scenario_trace")
except Exception:  # pragma: no cover — structlog optional
    _trace_log = None


def _emit_extraction_event(sc: ScenarioContext, step_idx: int, diagnostic: Dict[str, Any],
                           posts_added: int, bundle_path: Optional[str] = None) -> None:
    """Emit one structlog ``extraction_result`` event per extract step."""
    if _trace_log is None:
        return
    try:
        device = sc.device
        last_frame_t = float(getattr(device, "_last_frame_time", 0.0) or 0.0)
        frame_age_ms = int((time.monotonic() - last_frame_t) * 1000) if last_frame_t > 0 else None
        u2_hb_age = None
        try:
            pool_mod = importlib.import_module("agent_boot.relay.u2_session_pool")
            heartbeat_age_fn = getattr(pool_mod, "heartbeat_age_ms", None)
            if callable(heartbeat_age_fn):
                u2_hb_age = heartbeat_age_fn(sc.serial)
        except Exception:
            u2_hb_age = None
        _trace_log.info(
            "extraction_result",
            serial=sc.serial,
            step_idx=step_idx,
            reason_code=diagnostic.get("reason_code", "unknown"),
            posts_added=posts_added,
            posts_returned=diagnostic.get("posts_returned", 0),
            truncated=diagnostic.get("truncated_post_count", 0),
            candidate_clusters=diagnostic.get("candidate_clusters", 0),
            filtered_junk=diagnostic.get("filtered_junk_count", 0),
            anchor_button_found=diagnostic.get("anchor_button_found"),
            parse_ms=diagnostic.get("elapsed_ms"),
            frame_age_ms=frame_age_ms,
            u2_heartbeat_age_ms=u2_hb_age,
            bundle_path=bundle_path,
        )
    except Exception as exc:  # pragma: no cover
        log.debug("extraction_result event emit failed: %s", exc)


@register_step("extract")
def handle_extract(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    serial = sc.serial
    device = sc.device
    ctx = sc.ctx

    strategy = str(step.get("strategy", "fb_posts"))
    stop_if_no_new = bool(step.get("stop_if_no_new", False))
    no_new_threshold = int(step.get("no_new_threshold", 3))
    expand_see_more = bool(step.get("expand_see_more", True))
    _ecr = step.get("expand_completion_retries", 3)
    completion_retries = max(0, int(3 if _ecr is None else _ecr))

    _em_passes = int(step.get("expand_see_more_max_passes", 2))
    _em_scroll = bool(step.get("expand_see_more_scroll", False))
    _em_scroll_dist = float(step.get("expand_see_more_scroll_distance", 0.3))
    _lazy_rounds = int(step.get("expand_lazy_hydration_rounds", 6))
    _prefetch_passes = int(step.get("expand_prefetch_scroll_passes", 0) or 0)
    _lazy_scroll = float(step.get("expand_lazy_scroll_distance", _em_scroll_dist))

    # Pre-expand
    if strategy == "fb_posts" and expand_see_more:
        try:
            from tasks.fb_extract import expand_see_more_with_lazy_hydration
            expand_see_more_with_lazy_hydration(device, max_rounds=max(3, _lazy_rounds), scroll_distance=max(0.12, _lazy_scroll))
            time.sleep(0.35)
        except Exception as exc:
            log.warning("[%s] extract: pre-expand fb_posts failed: %s", serial, exc)

    if strategy == "fb_comments" and expand_see_more:
        try:
            from tasks.fb_extract import _expand_see_more
            _expand_see_more(device, max_passes=_em_passes, scroll_between=_em_scroll, scroll_distance=_em_scroll_dist)
            time.sleep(0.55)
        except Exception as exc:
            log.warning("[%s] extract: pre-expand fb_comments failed: %s", serial, exc)

    if strategy == "fb_posts" and expand_see_more and _prefetch_passes > 0:
        try:
            from tasks.fb_extract import prefetch_viewport_scrolls
            prefetch_viewport_scrolls(device, passes=_prefetch_passes, distance=max(0.15, _em_scroll_dist),
                                      pause_s=float(step.get("expand_prefetch_scroll_pause", 0.7)))
        except Exception as exc:
            log.warning("[%s] extract: prefetch_viewport_scrolls failed: %s", serial, exc)

    xml = device.hierarchy_xml(force_refresh=True)
    if not xml:
        result["ok"] = False
        result["message"] = "extract: hierarchy_xml returned None"
        return

    if strategy == "fb_posts":
        _extract_fb_posts(sc, step, idx, result, xml, expand_see_more, completion_retries,
                          _lazy_rounds, _lazy_scroll, stop_if_no_new, no_new_threshold)
    elif strategy == "text_nodes":
        _extract_text_nodes(sc, result, xml)
    elif strategy == "fb_comments":
        _extract_fb_comments(sc, step, idx, result, xml, stop_if_no_new, no_new_threshold)
    elif strategy in ("ig_posts", "tiktok_posts", "linkedin_posts", "auto_posts"):
        # Phase 3 — multi-platform extraction via BasePlatformParser.
        _extract_multi_platform(sc, step, idx, result, xml, strategy)
    elif strategy in ("ig_comments", "tiktok_comments", "linkedin_comments"):
        _extract_multi_platform(sc, step, idx, result, xml, strategy)
    else:
        result["ok"] = False
        result["message"] = f"extract: unknown strategy {strategy!r}"
        return

    # Inline auto-save (F1.4 save-partial)
    # Originally gated on result.ok=True so failed-step extractions never
    # persisted. Now: save regardless, so partial progress survives scenario
    # aborts (session-death, stale frame, scroll fail). Dedup by content_hash
    # at content_store layer makes re-runs idempotent.
    _auto_save_coll = step.get("collection")
    if _auto_save_coll:
        _do_inline_auto_save(sc, step, strategy, result, _auto_save_coll)


def _parse_posts_with_diag(xml: str, source_index: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
   
    from tasks.fb_extract import (
        _hierarchy_is_fb_comment_sheet,
        _parse_xml,
        parse_fb_posts_from_xml,
        parse_fb_posts_from_xml_with_diagnostic,
        is_fb_post_truncated,
    )
    root = _parse_xml(xml)
    if root is not None and _hierarchy_is_fb_comment_sheet(root):
        return [], {
            "reason_code": "wrong_screen_comment_sheet",
            "posts_returned": 0,
            "truncated_post_count": 0,
            "candidate_clusters": 0,
            "filtered_junk_count": 0,
            "locale_tokens_hit": [],
        }
    posts = parse_fb_posts_from_xml(xml, source_index=source_index)
    if posts:
        return posts, {
            "reason_code": "ok",
            "posts_returned": len(posts),
            "truncated_post_count": sum(1 for p in posts if is_fb_post_truncated(p)),
            "candidate_clusters": len(posts),
            "filtered_junk_count": 0,
            "locale_tokens_hit": [],
        }
    _, diag = parse_fb_posts_from_xml_with_diagnostic(xml, source_index=source_index)
    return posts, diag


def _parse_comments_with_diag(
    xml: str, parent_post_id: Optional[str], max_items: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Same adapter pattern for comments — preserves test mocks."""
    from tasks.fb_extract import (
        parse_fb_comments_from_xml,
        parse_fb_comments_from_xml_with_diagnostic,
    )
    rows = parse_fb_comments_from_xml(xml, parent_post_id=parent_post_id, max_items=max_items)
    if rows:
        body_rows = [r for r in rows if r.get("_type") != "post_stats"]
        return rows, {
            "reason_code": "ok",
            "comments_returned": len(body_rows),
            "anchor_button_found": True,  # best-effort; real diag would confirm
            "nodes_in_band": len(rows),
            "candidate_clusters": len(rows),
            "locale_tokens_hit": [],
            "has_header_stats": any(r.get("_type") == "post_stats" for r in rows),
        }
    _, diag = parse_fb_comments_from_xml_with_diagnostic(
        xml, parent_post_id=parent_post_id, max_items=max_items,
    )
    return rows, diag


def _extract_fb_posts(sc, step, idx, result, xml, expand_see_more, completion_retries, _lazy_rounds, _lazy_scroll, stop_if_no_new, no_new_threshold):
    from tasks.fb_extract import (
        _dedup,
        is_fb_post_truncated,
        expand_see_more_with_lazy_hydration,
    )
    from services.content_store import compute_content_hash

    serial = sc.serial
    device = sc.device
    ctx = sc.ctx
    scroll_idx = ctx.get("_loop_iter", 0)
    new_posts, diagnostic = _parse_posts_with_diag(xml, source_index=scroll_idx)
    reason_code = diagnostic.get("reason_code", "unknown")

    # F1.8 session-death — short-circuit, do NOT treat as retriable empty feed.
    if reason_code in ("login_screen", "rate_limited"):
        ctx["_session_dead_reason"] = reason_code
        ctx["_break"] = True
        result["ok"] = False
        result["reason_code"] = reason_code
        result["message"] = f"extract fb_posts: {reason_code} detected — aborting scenario"
        result["extract_diagnostic"] = diagnostic
        execution_id = (sc.scenario or {}).get("_execution_id")
        bundle = capture_failure_bundle(
            device, ctx, execution_id, idx,
            reason=reason_code, xml=xml, diagnostic=diagnostic,
        )
        if bundle:
            result["failure_bundle"] = bundle
        _emit_extraction_event(sc, idx, diagnostic, posts_added=0, bundle_path=bundle)
        log.warning("[%s] %s", serial, result["message"])
        return

    def _snapshot(posts: List[Dict[str, Any]]) -> Tuple[int, int]:
        unresolved = sum(1 for p in posts if is_fb_post_truncated(p))
        total_len = sum(len(str(p.get("text") or "")) for p in posts)
        return unresolved, total_len

    unresolved_first, total_len_first = _snapshot(new_posts)

    if expand_see_more and any(is_fb_post_truncated(p) for p in new_posts):
        try:
            expand_see_more_with_lazy_hydration(device, max_rounds=max(2, min(_lazy_rounds, 5)), scroll_distance=max(0.12, _lazy_scroll))
            xml_h = device.hierarchy_xml(force_refresh=True)
            if xml_h:
                retry_posts, _ = _parse_posts_with_diag(xml_h, source_index=scroll_idx)
                new_posts = _dedup(new_posts + retry_posts)
        except Exception as exc:
            log.warning("[%s] extract: mid-parse expand failed: %s", serial, exc)

    unresolved_before, total_len_before = _snapshot(new_posts)
    retries_done = 0
    plateau = 0
    if expand_see_more and unresolved_before > 0:
        max_retries = max(1, min(4, completion_retries))
        prev_unresolved, prev_total_len = unresolved_before, total_len_before
        for _ in range(max_retries):
            retries_done += 1
            try:
                expand_see_more_with_lazy_hydration(device, max_rounds=max(3, min(_lazy_rounds, 8)), scroll_distance=max(0.12, _lazy_scroll))
                time.sleep(0.6)
                xml_retry = device.hierarchy_xml(force_refresh=True)
                if not xml_retry:
                    break
                retry_posts, _ = _parse_posts_with_diag(xml_retry, source_index=scroll_idx)
                candidate_posts = _dedup(new_posts + (retry_posts or []))
                curr_unresolved, curr_total_len = _snapshot(candidate_posts)
                improved = curr_unresolved < prev_unresolved or curr_total_len > prev_total_len + 20
                new_posts = candidate_posts
                if improved:
                    plateau = 0
                else:
                    plateau += 1
                prev_unresolved, prev_total_len = curr_unresolved, curr_total_len
                if curr_unresolved == 0 or plateau >= 2:
                    break
            except Exception as exc:
                log.warning("[%s] extract: expand_completion retry failed: %s", serial, exc)
                break

    unresolved_after, total_len_after = _snapshot(new_posts)
    result["extract_diagnostics"] = {
        "unresolved_first_parse": unresolved_first, "total_len_first_parse": total_len_first,
        "unresolved_before": unresolved_before, "unresolved_after": unresolved_after,
        "total_len_before": total_len_before, "total_len_after": total_len_after,
        "completion_retries": retries_done, "plateau_count": plateau,
    }
    prev_count = len(ctx["posts"])
    ctx["posts"] = _dedup(ctx["posts"] + new_posts)
    added = len(ctx["posts"]) - prev_count
    result["extracted"] = added
    result["total_posts"] = len(ctx["posts"])
    result["message"] = f"extract fb_posts: +{added} new (total {len(ctx['posts'])})"
    log.info(f"[{serial}] {result['message']}")

    dedupe_field = str(step.get("dedupe_field") or "post_key")
    ctx["_fb_posts_dedupe_field"] = dedupe_field
    if new_posts:
        ctx["_first_new_post_hash"] = compute_content_hash(new_posts[0], dedupe_field=dedupe_field)
        # Accumulate pid→hash across batches so tap_fb_comment_button (or a
        # late tap on a cached post) can still resolve the parent hash.
        pid_map = ctx.setdefault("_post_id_map", {})
        for p in new_posts:
            _pid = p.get("_pid")
            if _pid:
                pid_map[_pid] = compute_content_hash(p, dedupe_field=dedupe_field)
        _tpid = new_posts[0].get("_pid")
        if _tpid:
            ctx["_fb_comment_parent_pid"] = _tpid
        else:
            ctx.pop("_fb_comment_parent_pid", None)
    else:
        ctx.pop("_fb_comment_parent_pid", None)

    # F1.7 — only count "parser OK but feed returned nothing" toward no-new
    # streak. If parser failed (anchor_not_found, no_candidates, etc), we
    # should NOT exit the loop — those are retriable/diagnostic failures, not
    # end-of-feed.
    if stop_if_no_new:
        if added == 0 and reason_code == "ok":
            _base_streak = ctx.get("_no_new_posts_streak", ctx.get("_no_new_streak", 0))
            ctx["_no_new_posts_streak"] = _base_streak + 1
            ctx["_no_new_streak"] = ctx["_no_new_posts_streak"]
            if ctx["_no_new_posts_streak"] >= no_new_threshold:
                ctx["_break"] = True
                result["message"] += f" — breaking (no new for {ctx['_no_new_posts_streak']} scrolls)"
        elif added > 0:
            ctx["_no_new_posts_streak"] = 0
            ctx["_no_new_streak"] = 0
        # reason_code != "ok" and added == 0: do not touch streak.

    # Failure bundle: any non-ok reason_code that didn't already capture above.
    bundle_path: Optional[str] = None
    if reason_code not in ("ok", "comment_sheet_no_posts_expected"):
        execution_id = (sc.scenario or {}).get("_execution_id")
        bundle_path = capture_failure_bundle(
            device, ctx, execution_id, idx,
            reason=reason_code, xml=xml, diagnostic=diagnostic,
        )
        if bundle_path:
            result["failure_bundle"] = bundle_path

    result["extract_diagnostic"] = diagnostic
    result["reason_code"] = reason_code
    _emit_extraction_event(sc, idx, diagnostic, posts_added=added, bundle_path=bundle_path)


def _extract_text_nodes(sc, result, xml):
    try:
        root = ET.fromstring(xml)
        texts = []
        for node in root.iter():
            t2 = (node.get("text") or "").strip()
            if t2 and len(t2) > 2:
                texts.append(t2)
        sc.ctx.setdefault("text_nodes", [])
        sc.ctx["text_nodes"].extend(texts)
        result["extracted"] = len(texts)
        result["message"] = f"extract text_nodes: {len(texts)} texts"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"extract text_nodes failed: {exc}"


def _extract_fb_comments(sc, step, idx, result, xml, stop_if_no_new, no_new_threshold):
    from tasks.fb_extract import (
        _dedup_comments,
        _is_junk_parsed_comment_row,
        _post_id_from_ctx,
    )
    from services.content_store import compute_content_hash

    serial = sc.serial
    ctx = sc.ctx
    ctx["_active_comment_parent_hash"] = None
    parent_post_id_var = step.get("parent_post_id_var")
    max_items = int(step.get("max_items") or 50)
    comment_scroll_passes = max(0, int(step.get("comment_scroll_passes", 0) or 0))
    min_comment_scan_passes = max(0, int(step.get("min_comment_scan_passes", 0) or 0))
    comment_no_growth_break = max(0, int(step.get("comment_no_growth_break", 0) or 0))
    comment_scroll_distance = max(0.12, min(0.45, float(step.get("comment_scroll_distance", 0.28) or 0.28)))
    comment_scroll_pause_s = max(0.1, float(step.get("comment_scroll_pause_s", 0.4) or 0.4))
    comment_scroll_duration_ms = max(220, min(900, int(step.get("comment_scroll_duration_ms", 360) or 360)))
    parent_post_id = _post_id_from_ctx(ctx, parent_post_id_var)
    raw_items, cdiag = _parse_comments_with_diag(
        xml, parent_post_id=parent_post_id, max_items=max_items,
    )
    creason = cdiag.get("reason_code", "unknown")
    if creason in {"no_nodes_in_band", "empty_cluster"}:
        # Transitional frame after comment-tap can still look like feed for a
        # short moment. Retry a couple of fresh snapshots before giving up.
        for _ in range(2):
            time.sleep(0.35)
            xml_retry = sc.device.hierarchy_xml(force_refresh=True)
            if not xml_retry:
                continue
            rows_retry, diag_retry = _parse_comments_with_diag(
                xml_retry, parent_post_id=parent_post_id, max_items=max_items,
            )
            reason_retry = diag_retry.get("reason_code", "unknown")
            if reason_retry == "ok":
                raw_items, cdiag, creason = rows_retry, diag_retry, reason_retry
                break

    # F1.8 session-death — short-circuit on comment screen too.
    if creason in ("login_screen", "rate_limited"):
        ctx["_session_dead_reason"] = creason
        ctx["_break"] = True
        result["ok"] = False
        result["reason_code"] = creason
        result["message"] = f"extract fb_comments: {creason} detected — aborting scenario"
        result["extract_diagnostic"] = cdiag
        execution_id = (sc.scenario or {}).get("_execution_id")
        bundle = capture_failure_bundle(
            sc.device, ctx, execution_id, idx,
            reason=creason, xml=xml, diagnostic=cdiag,
        )
        if bundle:
            result["failure_bundle"] = bundle
        log.warning("[%s] %s", serial, result["message"])
        return

    post_stats = next((x for x in raw_items if x.get("_type") == "post_stats"), None)
    new_comments = [x for x in raw_items if x.get("_type") != "post_stats" and not _is_junk_parsed_comment_row(x)]
    # Progressive comment scan: pull more comments by scrolling in-sheet and
    # merging snapshots. This uses template knobs that were previously ignored.
    all_comments = list(new_comments)
    no_growth_streak = 0
    scan_passes_done = 0
    if comment_scroll_passes > 0:
        for _ in range(comment_scroll_passes):
            if len(all_comments) >= max_items:
                break
            try:
                sx = int(sc.w * 0.55)
                sy1_ratio = 0.74
                sy2_ratio = max(0.2, sy1_ratio - comment_scroll_distance)
                sy1 = int(sc.h * sy1_ratio)
                sy2 = int(sc.h * sy2_ratio)
                sc.device.swipe(sx, sy1, sx, sy2, duration_ms=comment_scroll_duration_ms)
                time.sleep(comment_scroll_pause_s)
                xml_next = sc.device.hierarchy_xml(force_refresh=True)
                if not xml_next:
                    no_growth_streak += 1
                else:
                    rows_next, _diag_next = _parse_comments_with_diag(
                        xml_next, parent_post_id=parent_post_id, max_items=max_items,
                    )
                    if _diag_next.get("reason_code") == "ok":
                        ps_next = next((x for x in rows_next if x.get("_type") == "post_stats"), None)
                        if ps_next and post_stats is None:
                            post_stats = ps_next
                    comments_next = [
                        x for x in rows_next
                        if x.get("_type") != "post_stats" and not _is_junk_parsed_comment_row(x)
                    ]
                    before = len(all_comments)
                    all_comments = _dedup_comments(all_comments + comments_next)
                    grew = len(all_comments) > before
                    no_growth_streak = 0 if grew else (no_growth_streak + 1)
                scan_passes_done += 1
                if comment_no_growth_break > 0 and scan_passes_done >= min_comment_scan_passes:
                    if no_growth_streak >= comment_no_growth_break:
                        break
            except Exception:
                no_growth_streak += 1
                scan_passes_done += 1
                if comment_no_growth_break > 0 and scan_passes_done >= min_comment_scan_passes:
                    if no_growth_streak >= comment_no_growth_break:
                        break

    parent_hash = resolve_comment_parent_hash(ctx, parent_post_id)
    result["parent_hash_source"] = ctx.get("_comment_parent_resolve_source")
    if parent_hash:
        ctx["_active_comment_parent_hash"] = parent_hash

    # In many FB layouts, comment sheet omits like/share text. Fallback to
    # the already-extracted parent post stats from feed context.
    post_stats_source = "comment_sheet"
    if post_stats is None and parent_hash:
        dedupe_field = str(ctx.get("_fb_posts_dedupe_field") or step.get("dedupe_field") or "post_key")
        for post in (ctx.get("posts") or []):
            try:
                if compute_content_hash(post, dedupe_field=dedupe_field) != parent_hash:
                    continue
            except Exception:
                continue
            post_stats = {
                "_type": "post_stats",
                "reactions": post.get("reactions"),
                "shares": post.get("shares"),
                "comments": post.get("comments"),
            }
            post_stats_source = "feed_parent_fallback"
            break

    if post_stats:
        if post_stats_source == "comment_sheet" and parent_hash:
            dedupe_field = str(ctx.get("_fb_posts_dedupe_field") or step.get("dedupe_field") or "post_key")
            for post in (ctx.get("posts") or []):
                try:
                    if compute_content_hash(post, dedupe_field=dedupe_field) != parent_hash:
                        continue
                except Exception:
                    continue
                post_stats["reactions"] = post_stats.get("reactions") or post.get("reactions")
                post_stats["shares"] = post_stats.get("shares") or post.get("shares")
                post_stats["comments"] = post_stats.get("comments") or post.get("comments")
                break
        ctx["_comment_view_stats"] = post_stats
        result["post_stats_source"] = post_stats_source
        if parent_hash:
            try:
                from db.database import activity_session
                from db.crud.content import update_content_stats
                from services.content_store import _safe_int
                _ph, _ps, _serial = parent_hash, post_stats, serial

                async def _do_update_stats():
                    async with activity_session() as _db:
                        updated = await update_content_stats(
                            _db, content_hash=_ph,
                            likes_count=_safe_int(_ps.get("reactions")),
                            shares_count=_safe_int(_ps.get("shares")),
                            comments_count=_safe_int(_ps.get("comments")),
                        )
                        if updated:
                            await _db.commit()
                            log.info(
                                f"[{_serial}] post stats updated: hash={_ph[:12]} "
                                f"reactions={_ps.get('reactions')} "
                                f"shares={_ps.get('shares')} "
                                f"comments={_ps.get('comments')} source={post_stats_source}"
                            )

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(asyncio.run, _do_update_stats()).result(timeout=10)
            except Exception as exc:
                log.warning(f"[{serial}] update_content_stats failed: {exc}")

    ctx.setdefault("comments", [])
    prev_count = len(ctx["comments"])
    ctx["comments"] = _dedup_comments(ctx["comments"] + all_comments)
    added = len(ctx["comments"]) - prev_count
    result["extracted"] = added
    result["total_comments"] = len(ctx["comments"])
    result["parent_post_id"] = parent_post_id
    result["post_stats"] = post_stats
    result["comment_scan_passes"] = scan_passes_done
    result["message"] = f"extract fb_comments: +{added} new (total {len(ctx['comments'])}, post={parent_post_id})"

    if stop_if_no_new:
        if added == 0 and creason == "ok":
            ctx["_no_new_comments_streak"] = ctx.get("_no_new_comments_streak", 0) + 1
            ctx["_no_new_streak"] = ctx["_no_new_comments_streak"]
            if ctx["_no_new_comments_streak"] >= no_new_threshold:
                ctx["_break"] = True
                result["message"] += f" — breaking comments loop (no new for {ctx['_no_new_comments_streak']} scrolls)"
        elif added > 0:
            ctx["_no_new_comments_streak"] = 0
            ctx["_no_new_streak"] = 0

    # Failure bundle for non-OK parse reasons.
    if creason not in ("ok",):
        execution_id = (sc.scenario or {}).get("_execution_id")
        bundle_path = capture_failure_bundle(
            sc.device, ctx, execution_id, idx,
            reason=creason, xml=xml, diagnostic=cdiag,
        )
        if bundle_path:
            result["failure_bundle"] = bundle_path
    result["extract_diagnostic"] = cdiag
    result["reason_code"] = creason
    log.info(f"[{serial}] {result['message']}")


def _do_inline_auto_save(sc, step, strategy, result, collection):
    try:
        from services.content_store import save_content_item

        data_var = "comments" if strategy == "fb_comments" else ("text_nodes" if strategy == "text_nodes" else "posts")
        data = sc.ctx.get(data_var, [])
        items = [it for it in data if isinstance(it, dict)] if isinstance(data, list) else ([data] if isinstance(data, dict) else [])

        if not items:
            return

        offsets = sc.ctx.setdefault("__save_extraction_offsets__", {})
        start = int(offsets.get(data_var, 0) or 0)
        batch = items[start:]
        if not batch:
            return

        coll = collection
        plat = step.get("platform")
        ctype = step.get("content_type", "post")
        dedup = step.get("dedupe_field")
        tags = step.get("tags", "")
        parent_var = step.get("save_parent_id_var")
        parent_id = sc.ctx.get(parent_var) if parent_var else None
        level = int(step.get("item_level") or 0)
        dserial = sc.device.serial
        user_id = (sc.scenario.get("_campaign_vars") or {}).get("__USER_ID__")
        execution_id = sc.scenario.get("_execution_id")   # real DB FK — only set by Temporal
        run_hash_scope = sc.scenario.get("_run_hash_scope") or execution_id  # per-run dedup scope, no FK
        campaign_id = sc.scenario.get("_campaign_id")
        snap = list(batch)

        async def _resolve_user_id() -> str | None:
            """Fallback to device owner when no auth context, to avoid orphaned data."""
            if user_id:
                return user_id
            try:
                from db.database import activity_session
                from db.crud.device import get_device_by_serial
                async with activity_session() as db:
                    dev = await get_device_by_serial(db, dserial)
                    return dev.user_id if dev else None
            except Exception:
                return None

        async def _auto_save_all():
            resolved_uid = await _resolve_user_id()
            sv = dp = er = pc = 0
            for it in snap:
                try:
                    r = await save_content_item(
                        data=it, collection=coll, platform=plat, content_type=ctype,
                        dedupe_field=dedup, tags=tags, device_serial=dserial,
                        parent_id=parent_id, item_level=level, user_id=resolved_uid,
                        campaign_id=campaign_id, execution_id=execution_id,
                        hash_scope=run_hash_scope,
                    )
                    if r.get("saved"):
                        sv += 1
                    else:
                        dp += 1
                    pc += 1
                except Exception as exc:
                    er += 1
                    log.warning("[%s] extract auto-save failed: %s", dserial, exc)
                    break
            return sv, dp, er, pc

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            saved, dup, err, proc = pool.submit(asyncio.run, _auto_save_all()).result(timeout=120)

        offsets[data_var] = start + proc
        result["auto_save"] = {"saved": saved, "duplicate": dup, "errors": err}
        result["message"] += f" | auto-save: saved={saved}, dup={dup}, err={err}"
        log.info(f"[{sc.serial}] extract auto-save: saved={saved}, dup={dup}, err={err}")
    except Exception as exc:
        log.warning("[%s] extract auto-save failed: %s", sc.serial, exc)
        result["auto_save_error"] = str(exc)


@register_step("extract_text_hierarchy")
def handle_extract_text_hierarchy(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    save_as = step.get("save_as", "")
    if not save_as:
        result["ok"] = False
        result["message"] = "extract_text_hierarchy: missing save_as"
        return
    try:
        from runtime.extraction.hierarchy_extractor import HierarchyExtractor
        xml = sc.device.hierarchy_xml(force_refresh=True)
        if not xml:
            result["ok"] = False
            result["message"] = "No hierarchy XML available"
            return
        fmt = step.get("format", "text")
        items = HierarchyExtractor.extract_texts(xml, filter_class=step.get("filter_class"), exclude_empty=step.get("exclude_empty", True))
        if fmt == "json":
            sc.var_ctx.set(save_as, items)
        else:
            sc.var_ctx.set(save_as, "\n".join(i["text"] for i in items if i.get("text")))
        result["message"] = f"Extracted {len(items)} text elements"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"extract_text_hierarchy failed: {exc}"


@register_step("extract_text_ocr")
def handle_extract_text_ocr(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    save_as = step.get("save_as", "")
    if not save_as:
        result["ok"] = False
        result["message"] = "extract_text_ocr: missing save_as"
        return
    try:
        from runtime.extraction.ocr_engine import OCREngine
        frame = sc.device.take_screenshot()
        if not frame:
            result["ok"] = False
            result["message"] = "No screenshot available for OCR"
            return
        ocr = OCREngine()
        text = ocr.extract_text(frame, language=step.get("language", "eng"), region=step.get("region"),
                                psm=int(step.get("psm", 11)), preprocess=step.get("preprocess", True),
                                scale_factor=float(step.get("scale_factor", 2.0)))
        sc.var_ctx.set(save_as, text)
        result["message"] = f"OCR extracted {len(text)} chars"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"extract_text_ocr failed: {exc}"


@register_step("extract_text_ai")
def handle_extract_text_ai(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    save_as = step.get("save_as", "")
    prompt = step.get("prompt", "")
    if not save_as or not prompt:
        result["ok"] = False
        result["message"] = "extract_text_ai: missing save_as or prompt"
        return
    try:
        from runtime.extraction.ai_vision import AIVisionExtractor
        frame = sc.device.take_screenshot()
        if not frame:
            result["ok"] = False
            result["message"] = "No screenshot available for AI extraction"
            return
        ai = AIVisionExtractor()
        ai_result = ai.extract(frame, prompt=prompt, provider=step.get("provider", "openai"),
                               output_format=step.get("format", "json"), model=step.get("model"),
                               region=step.get("region"))
        sc.var_ctx.set(save_as, ai_result)
        result["message"] = f"AI extracted {type(ai_result).__name__}"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"extract_text_ai failed: {exc}"


@register_step("extract_screen_data")
def handle_extract_screen_data(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    save_as = step.get("save_as", "")
    if not save_as:
        result["ok"] = False
        result["message"] = "extract_screen_data: missing save_as"
        return
    strategy = step.get("strategy", "auto")
    extracted = None
    source = ""
    try:
        if strategy in ("auto", "hierarchy"):
            from runtime.extraction.hierarchy_extractor import HierarchyExtractor
            xml = sc.device.hierarchy_xml(force_refresh=True)
            if xml:
                items = HierarchyExtractor.extract_texts(xml, exclude_empty=True)
                if items:
                    extracted = "\n".join(i["text"] for i in items if i.get("text"))
                    source = "hierarchy"
        if extracted is None and strategy in ("auto", "ocr"):
            from runtime.extraction.ocr_engine import OCREngine
            frame = sc.device.take_screenshot()
            if frame:
                ocr = OCREngine()
                if ocr.available:
                    text = ocr.extract_text(frame, language=step.get("language", "eng"), psm=11)
                    if text and len(text) > 3:
                        extracted = text
                        source = "ocr"
        if extracted is None and strategy in ("auto", "ai"):
            from runtime.extraction.ai_vision import AIVisionExtractor
            frame = sc.device.take_screenshot()
            if frame:
                schema = step.get("schema")
                prompt = "Extract all visible text from this mobile screenshot."
                if schema:
                    prompt = f"Extract the following fields from this screenshot: {json.dumps(schema)}. Return as JSON."
                ai = AIVisionExtractor()
                extracted = ai.extract(frame, prompt=prompt, output_format="json" if schema else "text")
                source = "ai"
        if extracted is not None:
            sc.var_ctx.set(save_as, extracted)
            result["message"] = f"Extracted via {source}"
            result["source"] = source
        else:
            result["ok"] = False
            result["message"] = "extract_screen_data: no data extracted"
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"extract_screen_data failed: {exc}"


@register_step("llm_extract")
def handle_llm_extract(sc: "ScenarioContext", step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    """Phase 4 — universal schema-driven LLM extraction.

    Step config:
      {
        "type": "llm_extract",
        "schema": {                       # inline schema
          "name": "social_post",
          "multiple": true,
          "fields": [{"name": "author", "required": true, "hint": "..."}]
        },
        "provider": "gemini",             # or "openai"
        "model": null,                    # override default
        "max_cost_usd": 5.0,              # per-session cap
        "include_hierarchy": true,        # pass a text summary of XML to the LLM
        "save_as": "posts"                # ctx var name to store result (optional)
      }
    """
    schema = step.get("schema")
    if not isinstance(schema, dict) or not schema.get("fields"):
        result["ok"] = False
        result["message"] = "llm_extract: missing or invalid 'schema' (need 'fields')"
        return

    provider = str(step.get("provider", "gemini"))
    model = step.get("model")
    max_cost_usd = float(step.get("max_cost_usd", 5.0))
    include_hierarchy = bool(step.get("include_hierarchy", True))
    save_as = step.get("save_as")

    try:
        frame = sc.device.take_screenshot()
        if not frame:
            result["ok"] = False
            result["message"] = "llm_extract: screenshot failed"
            return

        hierarchy_summary = None
        if include_hierarchy:
            try:
                xml = sc.device.hierarchy_xml(force_refresh=False)
                hierarchy_summary = _summarize_hierarchy_for_llm(xml, max_nodes=50) if xml else None
            except Exception:
                hierarchy_summary = None

        from runtime.extraction.ai_vision import AIVisionExtractor
        ai = AIVisionExtractor()
        items = ai.extract_with_schema(
            frame,
            schema,
            provider=provider,
            model=model,
            hierarchy_summary=hierarchy_summary,
            max_cost_usd=max_cost_usd,
        )

        # Track LLM fallback usage on the execution record.
        meta_bucket = sc.ctx.setdefault("_llm_extract", {"calls": 0, "items": 0})
        meta_bucket["calls"] = int(meta_bucket.get("calls", 0)) + 1
        item_count = len(items) if isinstance(items, list) else (1 if items else 0)
        meta_bucket["items"] = int(meta_bucket.get("items", 0)) + item_count

        if save_as:
            sc.var_ctx.set(save_as, items)
        # Also push into ctx.posts for downstream save_content steps.
        posts_bucket = sc.ctx.setdefault("posts", [])
        if isinstance(items, list):
            posts_bucket.extend(items)
        elif items:
            posts_bucket.append(items)

        result["items"] = item_count
        result["provider"] = provider
        result["session_cost_usd"] = round(AIVisionExtractor.session_cost_usd(), 6)
        result["message"] = f"llm_extract: {item_count} item(s) via {provider}"
    except Exception as exc:
        log.exception("llm_extract failed")
        result["ok"] = False
        result["message"] = f"llm_extract: {exc}"


def _summarize_hierarchy_for_llm(xml: str, max_nodes: int = 50) -> str:
    """Reduce XML hierarchy to text-bearing nodes only (cut token cost ~10x)."""
    try:
        import xml.etree.ElementTree as _ET
        root = _ET.fromstring(xml) if isinstance(xml, str) else xml
    except Exception:
        return ""
    lines: List[str] = []
    for node in root.iter():
        text = (node.get("text") or node.get("content-desc") or "").strip()
        if not text or len(text) < 3:
            continue
        cls = (node.get("class") or "").split(".")[-1]
        lines.append(f"[{cls}] {text[:120]}")
        if len(lines) >= max_nodes:
            break
    return "\n".join(lines)


def _extract_multi_platform(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    idx: int,
    result: Dict[str, Any],
    xml: str,
    strategy: str,
) -> None:
    """Phase 3 — platform-agnostic post/comment extraction via BasePlatformParser.

    Strategies: ig_posts, tiktok_posts, linkedin_posts, auto_posts (detect from
    current app package), ig_comments, tiktok_comments, linkedin_comments.
    """
    from lxml import etree as _etree
    from tasks.platform_detector import detect_parser, detect_from_hierarchy

    try:
        xml_root = _etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"extract_multi: XML parse failed: {exc}"
        return

    parser = None
    is_comments = "_comments" in strategy
    if strategy.startswith("auto_"):
        pkg = getattr(sc.device, "current_package", None) or ""
        parser = detect_parser(pkg) if pkg else None
        if parser is None:
            parser = detect_from_hierarchy(xml_root)
    else:
        platform_code = strategy.split("_", 1)[0]  # "ig", "tiktok", "linkedin"
        pkg_map = {
            "ig": "com.instagram.android",
            "tiktok": "com.zhiliaoapp.musically",
            "linkedin": "com.linkedin.android",
        }
        parser = detect_parser(pkg_map.get(platform_code, ""))

    if parser is None:
        result["ok"] = False
        result["message"] = f"extract_multi: no parser for strategy {strategy!r}"
        return

    try:
        if is_comments:
            post_key = str(step.get("post_key") or sc.var_ctx.get("last_post_key") or "")
            items = parser.parse_comments(xml_root, post_key)
        else:
            items = parser.parse_posts(xml_root)
    except Exception as exc:
        log.exception("extract_multi: parser %s failed", parser.__class__.__name__)
        result["ok"] = False
        result["message"] = f"extract_multi: parser failed: {exc}"
        return

    # Push into scenario ctx.posts for downstream save steps.
    posts_bucket = sc.ctx.setdefault("posts", [])
    for item in items:
        posts_bucket.append(item.to_dict())

    result["items"] = len(items)
    result["platform"] = parser.platform
    result["message"] = f"extract_multi: {len(items)} {parser.platform} items"
