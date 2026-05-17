"""Step handlers: extract, extract_text_hierarchy, extract_text_ocr, extract_text_ai, extract_screen_data."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from tasks.scenario.steps import register_step
from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

EDGE_CONTENT_STRATEGIES = {
    "fb_posts",
    "fb_comments",
    "text_nodes",
    "ig_posts",
    "tiktok_posts",
    "linkedin_posts",
    "auto_posts",
    "ig_comments",
    "tiktok_comments",
    "linkedin_comments",
    "auto_comments",
}

COMMENT_STRATEGIES = {
    "fb_comments",
    "ig_comments",
    "tiktok_comments",
    "linkedin_comments",
    "auto_comments",
}


def _platform_for_strategy(strategy: str, step: Dict[str, Any]) -> str:
    if step.get("platform"):
        return str(step["platform"])
    if strategy.startswith("ig_"):
        return "instagram"
    if strategy.startswith("tiktok_"):
        return "tiktok"
    if strategy.startswith("linkedin_"):
        return "linkedin"
    if strategy.startswith("auto_"):
        return "auto"
    if strategy == "text_nodes":
        return str(step.get("platform") or "ui")
    return "facebook"


def _content_type_for_strategy(strategy: str, step: Dict[str, Any]) -> str:
    if step.get("content_type"):
        return str(step["content_type"])
    if strategy in COMMENT_STRATEGIES:
        return "comment"
    if strategy == "text_nodes":
        return "text"
    if strategy.startswith("tiktok_"):
        return "video"
    return "post"


def _data_var_for_edge_strategy(strategy: str, step: Dict[str, Any]) -> str:
    explicit = step.get("data_var") or step.get("save_as")
    if explicit:
        return str(explicit)
    if strategy == "text_nodes":
        return "text_nodes"
    if strategy in COMMENT_STRATEGIES:
        return "comments"
    return "posts"


def _store_returned_items(ctx: Dict[str, Any], strategy: str, step: Dict[str, Any], items: list[Any]) -> None:
    data_var = _data_var_for_edge_strategy(strategy, step)
    if strategy == "text_nodes":
        values = [
            str(item.get("text") or item.get("body") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("text") or item.get("body") or "").strip()
        ]
    else:
        values = [item for item in items if isinstance(item, dict)]
    if not values:
        ctx.setdefault(data_var, [])
        return
    bucket = ctx.setdefault(data_var, [])
    if isinstance(bucket, list):
        bucket.extend(values)
    else:
        ctx[data_var] = values


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _edge_extra_should_return_items(step: Dict[str, Any], collection: Any) -> bool:
    if "return_items" in step:
        return _coerce_bool(step.get("return_items"), default=False)
    if "edge_extra_return_items" in step:
        return _coerce_bool(step.get("edge_extra_return_items"), default=False)
    if step.get("save_as") or step.get("data_var"):
        return True
    return not bool(collection)


def _edge_extra_endpoint(step: Dict[str, Any]) -> str:
    endpoint = str(
        step.get("edge_extra_agent_url")
        or step.get("extra_data_agent_url")
        or os.environ.get("EDGE_EXTRA_AGENT_URL")
        or ""
    ).strip()
    if endpoint and not endpoint.rstrip("/").endswith("/extra-data/xml"):
        endpoint = endpoint.rstrip("/") + "/extra-data/xml"
    return endpoint


def _edge_extra_url_parts(url: str) -> tuple[str, str, int, str] | None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), port, parsed.path.rstrip("/") or "/"


def _edge_extra_endpoint_matches(endpoint: str, allowed: str) -> bool:
    ep = _edge_extra_url_parts(endpoint)
    al = _edge_extra_url_parts(allowed)
    if ep is None or al is None:
        return False
    ep_scheme, ep_host, ep_port, ep_path = ep
    al_scheme, al_host, al_port, al_path = al
    if (ep_scheme, ep_host, ep_port) != (al_scheme, al_host, al_port):
        return False
    if al_path in {"", "/"}:
        return True
    return ep_path == al_path or ep_path.startswith(al_path.rstrip("/") + "/")


def _edge_extra_endpoint_allowed(endpoint: str) -> bool:
    allowlist = [p.strip().rstrip("/") for p in os.environ.get("EDGE_EXTRA_AGENT_URL_ALLOWLIST", "").split(",") if p.strip()]
    if _edge_extra_url_parts(endpoint) is None:
        return False
    if allowlist:
        return any(_edge_extra_endpoint_matches(endpoint, prefix) for prefix in allowlist)
    env_endpoint = os.environ.get("EDGE_EXTRA_AGENT_URL", "").strip().rstrip("/")
    if env_endpoint:
        return _edge_extra_endpoint_matches(endpoint, env_endpoint)
    return _env_bool("EDGE_EXTRA_ALLOW_STEP_ENDPOINT", False)


def _resolve_user_id_for_edge(serial: str, scenario: Dict[str, Any]) -> str | None:
    user_id = (scenario.get("_campaign_vars") or {}).get("__USER_ID__")
    if user_id:
        return str(user_id)
    direct_uid = scenario.get("user_id") or scenario.get("__USER_ID__")
    if direct_uid:
        s = str(direct_uid).strip()
        if s:
            return s
    try:
        from db.database import run_activity_coro, activity_session
        from db.crud.device import get_device_by_serial

        async def _resolve():
            async with activity_session() as db:
                dev = await get_device_by_serial(db, serial)
                return dev.user_id if dev else None

        return run_activity_coro(_resolve())
    except Exception:
        return None


def request_edge_extra_data(
    *,
    device: Any,
    serial: str,
    ctx: Dict[str, Any],
    scenario: Dict[str, Any],
    step: Dict[str, Any],
    strategy: str,
    result: Dict[str, Any],
) -> bool:
    has_edge_flag = "edge_extra_data" in step
    explicit_enabled = (
        _coerce_bool(step.get("edge_extra_data"), default=False)
        if has_edge_flag
        else strategy in EDGE_CONTENT_STRATEGIES
    )
    enabled = explicit_enabled or _env_bool("EDGE_EXTRA_DATA_ENABLED", False)
    if not enabled:
        return False
    if not explicit_enabled and not _env_bool("EDGE_EXTRA_APPLY_GLOBALLY", False):
        return False
    if strategy not in EDGE_CONTENT_STRATEGIES:
        return False
    collection = step.get("collection")
    endpoint = _edge_extra_endpoint(step)
    if not endpoint:
        result["ok"] = False
        result["message"] = (
            f"edge extra_data {strategy}: missing EDGE_EXTRA_AGENT_URL "
            "or step.edge_extra_agent_url"
        )
        return True
    if not _edge_extra_endpoint_allowed(endpoint):
        log.warning("[%s] edge extra_data endpoint not allowlisted: %s", serial, endpoint)
        result["ok"] = False
        result["message"] = (
            f"edge extra_data {strategy}: endpoint not allowlisted: {endpoint}"
        )
        return True
    token = str(step.get("edge_extra_token") or os.environ.get("EDGE_EXTRA_TOKEN") or "").strip()
    if not token and not _env_bool("EDGE_EXTRA_ALLOW_UNAUTH", False):
        log.warning("[%s] edge extra_data token missing; device_farm content XML parser is disabled", serial)
        result["ok"] = False
        result["message"] = f"edge extra_data {strategy}: missing EDGE_EXTRA_TOKEN"
        return True
    if step.get("edge_extra_requires_context"):
        log.info("[%s] edge extra_data skipped because step requires in-memory extraction context", serial)
        result["ok"] = False
        result["message"] = f"edge extra_data {strategy}: step requires in-memory extraction context"
        return True

    parent_post_id_var = step.get("parent_post_id_var")
    parent_post_id = ctx.get(parent_post_id_var) if parent_post_id_var else ctx.get("_fb_comment_parent_pid")
    parent_var = step.get("save_parent_id_var") or step.get("parent_id_var")
    parent_id = ctx.get("_edge_comment_parent_base_hash") if strategy == "fb_comments" else None
    if parent_id is None and parent_var:
        parent_id = ctx.get(parent_var)
    return_items = _edge_extra_should_return_items(step, collection)
    context = {
        "schema_version": 1,
        "context_id": scenario.get("_execution_id") or scenario.get("_run_hash_scope") or serial,
        "execution_id": scenario.get("_execution_id"),
        "campaign_id": scenario.get("_campaign_id"),
        "user_id": _resolve_user_id_for_edge(serial, scenario),
        "device_serial": serial,
        "collection": collection,
        "platform": _platform_for_strategy(strategy, step),
        "content_type": _content_type_for_strategy(strategy, step),
        "scenario_name": scenario.get("name") or scenario.get("scenario_name"),
        "hash_scope": scenario.get("_run_hash_scope") or scenario.get("_execution_id"),
        "dedupe_field": step.get("dedupe_field"),
        "tags": step.get("tags", ""),
        "item_level": int(step.get("item_level") or (1 if strategy in COMMENT_STRATEGIES else 0)),
        "parent_id": parent_id,
        "parent_post_id": parent_post_id,
        "post_key": step.get("post_key") or ctx.get("last_post_key"),
        "max_items": int(step.get("max_items") or 50),
        "source_index": int(ctx.get("_loop_iter", 0) or 0),
        "persist": bool(collection),
        "return_items": return_items,
        "package_name": step.get("package_name") or step.get("current_package") or "",
    }
    for key in (
        "comment_scroll_passes",
        "comment_scroll_distance",
        "comment_scroll_duration_ms",
        "comment_scroll_pause_s",
        "comment_no_growth_break",
        "min_comment_scan_passes",
        "expand_see_more",
        "expand_see_more_max_passes",
        "expand_see_more_scroll",
        "expand_see_more_scroll_distance",
        "expand_completion_retries",
        "allow_a11y_xml_fallback",
    ):
        if key in step:
            context[key] = step[key]
    timeout = float(step.get("edge_extra_timeout_s") or os.environ.get("EDGE_EXTRA_TIMEOUT_S", "45"))
    try:
        summary = device.request_extra_data_xml(
            endpoint=endpoint,
            strategy=strategy,
            context=context,
            token=token,
            timeout=timeout,
        )
    except Exception as exc:
        log.warning("[%s] edge extra_data failed before request: %s", serial, exc)
        return False
    if not summary.get("ok"):
        log.warning("[%s] edge extra_data failed: %s", serial, summary.get("error") or summary)
        result["ok"] = False
        result["message"] = f"edge extra_data failed: {summary.get('error') or 'unknown'}"
        result["edge_extra_summary"] = summary
        return True
    ingest = summary.get("ingest") if isinstance(summary.get("ingest"), dict) else summary
    parsed_count = int(ingest.get("parsed_count", 0) or 0)
    inserted_count = int(ingest.get("inserted_count", 0) or 0)
    duplicate_count = int(ingest.get("duplicate_count", 0) or 0)
    result["extracted"] = inserted_count if collection else parsed_count
    result["duplicate_count"] = duplicate_count
    edge_extra_summary = ingest
    if not return_items and isinstance(ingest.get("items"), list):
        edge_extra_summary = {k: v for k, v in ingest.items() if k != "items"}
        edge_extra_summary["items_omitted"] = len(ingest["items"])
    result["edge_extra_summary"] = edge_extra_summary
    result["reason_code"] = ((ingest.get("diagnostic") or {}) if isinstance(ingest.get("diagnostic"), dict) else {}).get("reason_code", "ok")
    items = ingest.get("items") if return_items and isinstance(ingest.get("items"), list) else []
    if items:
        _store_returned_items(ctx, strategy, step, items)
        result["items"] = len(items)
    result["message"] = (
        f"edge extra_data {strategy}: parsed={parsed_count} "
        f"inserted={inserted_count} duplicate={duplicate_count}"
    )
    log.info("[%s] %s", serial, result["message"])
    return True


_COMMENT_FILTER_MODES = frozenset({"most_relevant", "newest", "all_comments"})


def resolve_step_comment_filter(step: Dict[str, Any]) -> Optional[str]:
    """Target FB comment sort: most_relevant | newest | all_comments, or None to skip."""
    raw = step.get("comment_filter")
    if raw is not None and str(raw).strip():
        mode = str(raw).strip().lower()
        if mode in ("none", "skip", "off", "no", "default", "keep"):
            return None
        if mode in _COMMENT_FILTER_MODES:
            return mode
    if step.get("switch_to_all_comments") is False:
        return None
    return "all_comments"


def request_edge_comment_target(
    *,
    device: Any,
    serial: str,
    ctx: Dict[str, Any],
    scenario: Dict[str, Any],
    step: Dict[str, Any],
    result: Dict[str, Any],
) -> dict[str, Any] | None:
    endpoint = _edge_extra_endpoint(step)
    if not endpoint:
        result["ok"] = False
        result["message"] = "tap_fb_comment_button: edge extra_data endpoint missing"
        return None
    if not _edge_extra_endpoint_allowed(endpoint):
        result["ok"] = False
        result["message"] = f"tap_fb_comment_button: endpoint not allowlisted: {endpoint}"
        return None
    token = str(step.get("edge_extra_token") or os.environ.get("EDGE_EXTRA_TOKEN") or "").strip()
    if not token and not _env_bool("EDGE_EXTRA_ALLOW_UNAUTH", False):
        result["ok"] = False
        result["message"] = "tap_fb_comment_button: edge extra_data token missing"
        return None
    context = {
        "schema_version": 1,
        "context_id": scenario.get("_execution_id") or scenario.get("_run_hash_scope") or serial,
        "execution_id": scenario.get("_execution_id"),
        "campaign_id": scenario.get("_campaign_id"),
        "user_id": _resolve_user_id_for_edge(serial, scenario),
        "device_serial": serial,
        "hash_scope": scenario.get("_run_hash_scope") or scenario.get("_execution_id"),
        "dedupe_field": step.get("dedupe_field") or "post_key",
        "source_index": int(ctx.get("_loop_iter", 0) or 0),
        "switch_to_all_comments": bool(step.get("switch_to_all_comments", True)),
        "post_tap_wait_s": float(step.get("post_tap_wait_s", 0.8) or 0.8),
        "comment_filter_step_pause_s": float(step.get("comment_filter_step_pause_s", 0.45) or 0.45),
    }
    timeout = float(step.get("edge_extra_timeout_s") or os.environ.get("EDGE_EXTRA_TIMEOUT_S", "45"))
    try:
        strategy = "fb_comment_target_tap" if _env_bool("EDGE_COMMENT_TARGET_AGENT_TAP", True) else "fb_comment_target"
        summary = device.request_extra_data_xml(
            endpoint=endpoint,
            strategy=strategy,
            context=context,
            token=token,
            timeout=timeout,
        )
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"tap_fb_comment_button: edge target request failed: {exc}"
        return None
    if not summary.get("ok"):
        result["ok"] = False
        result["edge_extra_summary"] = summary
        result["message"] = f"tap_fb_comment_button: edge target failed: {summary.get('error') or 'unknown'}"
        return None
    ingest = summary.get("ingest") if isinstance(summary.get("ingest"), dict) else summary
    diagnostic = ingest.get("diagnostic") if isinstance(ingest.get("diagnostic"), dict) else {}
    target = diagnostic.get("target") if isinstance(diagnostic.get("target"), dict) else None
    if target is not None:
        target["_agent_tapped"] = bool(summary.get("agent_tapped"))
    result["edge_extra_summary"] = ingest
    result["agent_tapped"] = bool(summary.get("agent_tapped"))
    result["reason_code"] = diagnostic.get("reason_code", "unknown")
    return target


def run_edge_comment_filter_switch(
    *,
    device: Any,
    serial: str,
    scenario: Dict[str, Any],
    step: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Drive FB comment sort sheet via agent-boot (open sheet, tap chosen option)."""
    target_filter = resolve_step_comment_filter(step)
    report: Dict[str, Any] = {
        "enabled": target_filter is not None,
        "target_filter": target_filter,
        "switched": False,
        "steps": [],
    }
    if not target_filter:
        report["reason_code"] = "disabled"
        return report

    endpoint = _edge_extra_endpoint(step)
    if not endpoint or not _edge_extra_endpoint_allowed(endpoint):
        report["reason_code"] = "endpoint_unavailable"
        return report
    token = str(step.get("edge_extra_token") or os.environ.get("EDGE_EXTRA_TOKEN") or "").strip()
    if not token and not _env_bool("EDGE_EXTRA_ALLOW_UNAUTH", False):
        report["reason_code"] = "token_missing"
        return report

    wait_s = float(step.get("post_tap_wait_s", 0.8) or 0.8)
    if wait_s > 0:
        time.sleep(wait_s)

    context = {
        "schema_version": 1,
        "context_id": scenario.get("_execution_id") or scenario.get("_run_hash_scope") or serial,
        "execution_id": scenario.get("_execution_id"),
        "campaign_id": scenario.get("_campaign_id"),
        "user_id": _resolve_user_id_for_edge(serial, scenario),
        "device_serial": serial,
        "comment_filter": target_filter,
        "switch_to_all_comments": True,
        "post_tap_wait_s": wait_s,
        "comment_filter_step_pause_s": float(step.get("comment_filter_step_pause_s", 0.45) or 0.45),
    }
    timeout = float(step.get("edge_extra_timeout_s") or os.environ.get("EDGE_EXTRA_TIMEOUT_S", "45"))
    step_pause = float(step.get("comment_filter_step_pause_s", 0.45) or 0.45)

    for _ in range(4):
        try:
            summary = device.request_extra_data_xml(
                endpoint=endpoint,
                strategy="fb_comment_filter_next",
                context=context,
                token=token,
                timeout=timeout,
            )
        except Exception as exc:
            report["reason_code"] = "request_failed"
            report["error"] = str(exc)
            break
        if not summary.get("ok"):
            report["reason_code"] = "ingest_failed"
            report["error"] = summary.get("error")
            break
        ingest = summary.get("ingest") if isinstance(summary.get("ingest"), dict) else summary
        diagnostic = ingest.get("diagnostic") if isinstance(ingest.get("diagnostic"), dict) else {}
        phase = str(diagnostic.get("phase") or "done")
        reason = str(diagnostic.get("reason_code") or "")
        step_info = {"phase": phase, "reason_code": reason}
        report["steps"].append(step_info)
        if phase in {"done", "error"}:
            if reason in {"already_on_filter", "already_all_comments"}:
                report["switched"] = True
            report["reason_code"] = reason or phase
            break
        tap = diagnostic.get("tap") if isinstance(diagnostic.get("tap"), dict) else None
        bounds = tap.get("bounds") if tap else None
        if not isinstance(bounds, list) or len(bounds) != 4:
            report["reason_code"] = reason or "tap_missing"
            break
        x1, y1, x2, y2 = [int(v) for v in bounds]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        try:
            device.tap(cx, cy)
            step_info["tapped_at"] = [cx, cy]
        except Exception as exc:
            report["reason_code"] = "tap_failed"
            report["error"] = str(exc)
            break
        if phase in {"select_option", "select_all"}:
            report["switched"] = True
            report["reason_code"] = reason or "ok"
            break
        if step_pause > 0:
            time.sleep(step_pause)
    else:
        if "reason_code" not in report:
            report["reason_code"] = "max_steps"
    result["edge_filter_summary"] = report
    return report


def _try_edge_extra_data(sc: ScenarioContext, step: Dict[str, Any], strategy: str, result: Dict[str, Any]) -> bool:
    return request_edge_extra_data(
        device=sc.device,
        serial=sc.serial,
        ctx=sc.ctx,
        scenario=sc.scenario,
        step=step,
        strategy=strategy,
        result=result,
    )

@register_step("extract")
def handle_extract(sc: ScenarioContext, step: Dict[str, Any], idx: int, result: Dict[str, Any]) -> None:
    from services.scenario_step_contract import normalize_extract_step

    step = normalize_extract_step(step)
    strategy = str(step.get("strategy", "fb_posts"))
    if strategy in EDGE_CONTENT_STRATEGIES:
        if _try_edge_extra_data(sc, step, strategy, result):
            return
        result["ok"] = False
        result["message"] = (
            f"extract {strategy}: device_farm content XML parser was removed; "
            "enable edge_extra_data so phone/APK sends XML to agent-boot"
        )
        return

    result["ok"] = False
    result["message"] = f"extract: unknown strategy {strategy!r}"


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
