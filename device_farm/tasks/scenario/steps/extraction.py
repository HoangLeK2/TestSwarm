"""Step handlers: extract, extract_text_hierarchy, extract_text_ocr, extract_text_ai, extract_screen_data."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)


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

    # Inline auto-save
    _auto_save_coll = step.get("collection")
    if _auto_save_coll and result.get("ok", True):
        _do_inline_auto_save(sc, step, strategy, result, _auto_save_coll)


def _extract_fb_posts(sc, step, idx, result, xml, expand_see_more, completion_retries, _lazy_rounds, _lazy_scroll, stop_if_no_new, no_new_threshold):
    from tasks.fb_extract import parse_fb_posts_from_xml, _dedup, is_fb_post_truncated, expand_see_more_with_lazy_hydration
    from services.content_store import compute_content_hash

    serial = sc.serial
    device = sc.device
    ctx = sc.ctx
    scroll_idx = ctx.get("_loop_iter", 0)
    new_posts = parse_fb_posts_from_xml(xml, source_index=scroll_idx)

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
                new_posts = _dedup(new_posts + parse_fb_posts_from_xml(xml_h, source_index=scroll_idx))
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
                retry_posts = parse_fb_posts_from_xml(xml_retry, source_index=scroll_idx)
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

    if new_posts:
        ctx["_first_new_post_hash"] = compute_content_hash(new_posts[0], dedupe_field="post_key")
        pid_map = {}
        for p in new_posts:
            if p.get("_pid"):
                pid_map[p["_pid"]] = compute_content_hash(p, dedupe_field="post_key")
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
            _base_streak = ctx.get("_no_new_posts_streak", ctx.get("_no_new_streak", 0))
            ctx["_no_new_posts_streak"] = _base_streak + 1
            ctx["_no_new_streak"] = ctx["_no_new_posts_streak"]
            if ctx["_no_new_posts_streak"] >= no_new_threshold:
                ctx["_break"] = True
                result["message"] += f" — breaking (no new for {ctx['_no_new_posts_streak']} scrolls)"
        else:
            ctx["_no_new_posts_streak"] = 0
            ctx["_no_new_streak"] = 0


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
    from tasks.fb_extract import parse_fb_comments_from_xml, _dedup_comments, _is_junk_parsed_comment_row, _post_id_from_ctx

    serial = sc.serial
    ctx = sc.ctx
    ctx["_active_comment_parent_hash"] = None
    parent_post_id_var = step.get("parent_post_id_var")
    max_items = int(step.get("max_items") or 50)
    parent_post_id = _post_id_from_ctx(ctx, parent_post_id_var)
    raw_items = parse_fb_comments_from_xml(xml, parent_post_id=parent_post_id, max_items=max_items)

    post_stats = next((x for x in raw_items if x.get("_type") == "post_stats"), None)
    new_comments = [x for x in raw_items if x.get("_type") != "post_stats" and not _is_junk_parsed_comment_row(x)]

    if post_stats:
        ctx["_comment_view_stats"] = post_stats
        _pid_key = parent_post_id
        parent_hash = ctx.get("_post_id_map", {}).get(_pid_key) or ctx.get("_first_new_post_hash")
        if parent_hash:
            ctx["_active_comment_parent_hash"] = parent_hash
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
                        )
                        if updated:
                            await _db.commit()
                            log.info(f"[{_serial}] post stats updated: hash={_ph[:12]} reactions={_ps.get('reactions')} shares={_ps.get('shares')}")

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(asyncio.run, _do_update_stats()).result(timeout=10)
            except Exception as exc:
                log.warning(f"[{serial}] update_content_stats failed: {exc}")
    else:
        _pid_key = parent_post_id
        parent_hash = ctx.get("_post_id_map", {}).get(_pid_key) or ctx.get("_first_new_post_hash")
        if parent_hash:
            ctx["_active_comment_parent_hash"] = parent_hash

    ctx.setdefault("comments", [])
    prev_count = len(ctx["comments"])
    ctx["comments"] = _dedup_comments(ctx["comments"] + new_comments)
    added = len(ctx["comments"]) - prev_count
    result["extracted"] = added
    result["total_comments"] = len(ctx["comments"])
    result["parent_post_id"] = parent_post_id
    result["post_stats"] = post_stats
    result["message"] = f"extract fb_comments: +{added} new (total {len(ctx['comments'])}, post={parent_post_id})"

    if stop_if_no_new:
        if added == 0:
            ctx["_no_new_comments_streak"] = ctx.get("_no_new_comments_streak", 0) + 1
            ctx["_no_new_streak"] = ctx["_no_new_comments_streak"]
            if ctx["_no_new_comments_streak"] >= no_new_threshold:
                ctx["_break"] = True
                result["message"] += f" — breaking comments loop (no new for {ctx['_no_new_comments_streak']} scrolls)"
        else:
            ctx["_no_new_comments_streak"] = 0
            ctx["_no_new_streak"] = 0
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
        snap = list(batch)

        async def _auto_save_all():
            sv = dp = er = pc = 0
            for it in snap:
                try:
                    r = await save_content_item(
                        data=it, collection=coll, platform=plat, content_type=ctype,
                        dedupe_field=dedup, tags=tags, device_serial=dserial,
                        parent_id=parent_id, item_level=level, user_id=user_id,
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
