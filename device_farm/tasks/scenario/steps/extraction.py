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
    from services.content.legacy_type_map import default_content_type_for_strategy

    return default_content_type_for_strategy(strategy, step)


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


_COMMENT_PARENT_ANCHOR_KEYS = (
    "pid",
    "post_key",
    "stable_post_id",
    "fb_post_id",
    "author",
    "timestamp",
    "text_prefix",
)
_ACTIVE_COMMENT_PARENT_CTX_KEYS = (
    "_active_comment_parent_hash",
    "_first_new_post_hash",
    "_fb_comment_parent_pid",
    "_active_comment_parent_anchor",
    "_active_comment_anchor_verified",
)


def _clean_comment_parent_anchor(source: Dict[str, Any]) -> Dict[str, Any]:
    anchor: Dict[str, Any] = {}
    for key in _COMMENT_PARENT_ANCHOR_KEYS:
        value = source.get(key)
        if value is not None and str(value).strip():
            anchor[key] = value
    return anchor


def _clear_active_comment_parent(ctx: Dict[str, Any]) -> None:
    for key in _ACTIVE_COMMENT_PARENT_CTX_KEYS:
        ctx.pop(key, None)


def _remember_active_comment_parent(ctx: Dict[str, Any], ingest: Dict[str, Any]) -> None:
    active_parent = ingest.get("active_parent_post")
    pid_map = ingest.get("post_id_map") if isinstance(ingest.get("post_id_map"), dict) else None
    if not isinstance(active_parent, dict):
        if not pid_map or len(pid_map) != 1:
            _clear_active_comment_parent(ctx)
            return
        pid, parent_hash = next(iter(pid_map.items()))
        active_parent = {"pid": pid, "parent_id": parent_hash}

    parent_id = (
        active_parent.get("parent_id")
        or active_parent.get("content_hash")
        or active_parent.get("parent_content_hash")
    )
    pid = active_parent.get("pid") or active_parent.get("parent_post_id")
    if parent_id:
        ctx["_active_comment_parent_hash"] = parent_id
        ctx["_first_new_post_hash"] = parent_id
    if pid:
        ctx["_fb_comment_parent_pid"] = pid
    anchor = _clean_comment_parent_anchor(active_parent)
    if anchor:
        ctx["_active_comment_parent_anchor"] = anchor
    if parent_id or pid or anchor:
        ctx["_active_comment_anchor_verified"] = True


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


def _relay_extra_data_available(device: Any) -> bool:
    """PA B: edge extract requires a relay mapping for this device."""
    if not _env_bool("EDGE_EXTRA_RELAY_ENABLED", True):
        return False
    try:
        from runtime.transports.adb_relay_server import get_relay_manager

        relay = get_relay_manager()
        if relay is None:
            return False
        resolve = getattr(device, "_resolve_relay_serial", None)
        relay_serial = resolve() if callable(resolve) else getattr(device, "serial", "")
        return bool(relay.relay_for_serial(str(relay_serial or "")))
    except Exception:
        return False


def _attach_edge_content_screenshots(
    *,
    device: Any,
    ingest: dict[str, Any],
    collection: str,
    execution_id: str | None,
    user_id: str | None,
) -> None:
    """Attach screenshot to rows from this extract batch (inserted + duplicates missing path).

    Prefer framebuffer captured on agent-boot immediately after the last XML dump.
    When ``screenshot_targets`` include card bounds, crop one JPEG per post on the feed.
    """
    if not _env_bool("DEVICE_FARM_CONTENT_IMAGES_ENABLED", False):
        return

    import base64

    hashes = ingest.get("batch_content_hashes") or ingest.get("inserted_content_hashes") or []
    hashes = [str(h) for h in hashes if h]
    if not hashes or not collection:
        return
    jpeg: bytes | None = None
    b64 = ingest.get("screenshot_b64")
    if isinstance(b64, str) and b64.strip():
        try:
            jpeg = base64.b64decode(b64, validate=False)
        except Exception as exc:
            log.debug("edge extra_data screenshot b64 decode failed: %s", exc)
    if not jpeg:
        capture = getattr(device, "capture_screenshot", None)
        if callable(capture):
            try:
                jpeg = capture(skip_cache=True)
            except TypeError:
                jpeg = capture()
            except Exception as exc:
                log.debug("edge extra_data fresh screencap failed: %s", exc)
    if not jpeg:
        try:
            jpeg = device.take_screenshot()
        except Exception as exc:
            log.debug("edge extra_data screenshot attach skipped: %s", exc)
            return
    if not jpeg:
        return
    per_hash_bytes: dict[str, bytes] = {}
    targets = ingest.get("screenshot_targets")
    if isinstance(targets, list) and jpeg:
        from services.content_store import crop_jpeg_screenshot

        for entry in targets:
            if not isinstance(entry, dict):
                continue
            ch = str(entry.get("content_hash") or "").strip()
            bounds = entry.get("bounds")
            if not ch or not isinstance(bounds, (list, tuple)):
                continue
            cropped = crop_jpeg_screenshot(jpeg, bounds)
            if cropped:
                per_hash_bytes[ch] = cropped
    try:
        from db.database import run_activity_coro
        from services.content_store import attach_screenshot_to_content_hashes

        updated = run_activity_coro(
            attach_screenshot_to_content_hashes(
                content_hashes=hashes,
                collection=collection,
                execution_id=execution_id,
                screenshot_bytes=jpeg,
                user_id=user_id,
                only_if_missing=True,
                per_hash_bytes=per_hash_bytes or None,
            )
        )
        if updated:
            log.info(
                "edge extra_data: attached screenshot to %d content item(s) (cropped=%d)",
                updated,
                len(per_hash_bytes),
            )
    except Exception as exc:
        log.warning("edge extra_data screenshot attach failed: %s", exc)


def _edge_extra_should_return_items(step: Dict[str, Any], collection: Any) -> bool:
    if "return_items" in step:
        return _coerce_bool(step.get("return_items"), default=False)
    if "edge_extra_return_items" in step:
        return _coerce_bool(step.get("edge_extra_return_items"), default=False)
    if step.get("save_as") or step.get("data_var"):
        return True
    return not bool(collection)


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback_endpoint(url: str) -> bool:
    parts = _edge_extra_url_parts(url)
    if parts is None:
        return False
    return parts[1] in _LOOPBACK_HOSTS


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


def _edge_extra_endpoint_for_device(step: Dict[str, Any]) -> str:
    """Endpoint forwarded to the phone APK — must be reachable from the device, not loopback."""
    endpoint = _edge_extra_endpoint(step)
    if not endpoint or not _is_loopback_endpoint(endpoint):
        return endpoint
    public = str(
        step.get("edge_extra_agent_public_url")
        or os.environ.get("EDGE_EXTRA_AGENT_PUBLIC_URL")
        or ""
    ).strip()
    if not public:
        return endpoint
    if not public.rstrip("/").endswith("/extra-data/xml"):
        public = public.rstrip("/") + "/extra-data/xml"
    return public


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
        if any(_edge_extra_endpoint_matches(endpoint, prefix) for prefix in allowlist):
            return True
    else:
        env_endpoint = os.environ.get("EDGE_EXTRA_AGENT_URL", "").strip().rstrip("/")
        if env_endpoint and _edge_extra_endpoint_matches(endpoint, env_endpoint):
            return True
    public = os.environ.get("EDGE_EXTRA_AGENT_PUBLIC_URL", "").strip().rstrip("/")
    if public and _edge_extra_endpoint_matches(endpoint, public):
        loopback = os.environ.get("EDGE_EXTRA_AGENT_URL", "").strip().rstrip("/")
        env_endpoint = os.environ.get("EDGE_EXTRA_AGENT_URL", "").strip().rstrip("/")
        if loopback and (
            (allowlist and any(_edge_extra_endpoint_matches(loopback, prefix) for prefix in allowlist))
            or (not allowlist and env_endpoint and _edge_extra_endpoint_matches(loopback, env_endpoint))
        ):
            return True
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


def _resolve_org_id_for_edge(serial: str, scenario: Dict[str, Any]) -> str | None:
    raw = scenario.get("_org_id") or scenario.get("org_id")
    if raw:
        text = str(raw).strip()
        if text:
            return text
    campaign_vars = scenario.get("_campaign_vars") or {}
    if isinstance(campaign_vars, dict):
        cv_org = campaign_vars.get("__ORG_ID__") or campaign_vars.get("org_id")
        if cv_org:
            text = str(cv_org).strip()
            if text:
                return text
    user_id = _resolve_user_id_for_edge(serial, scenario)
    if user_id:
        try:
            from db.database import run_activity_coro, activity_session
            from db.crud.content import resolve_org_id

            async def _resolve_from_user():
                async with activity_session() as db:
                    return await resolve_org_id(db, user_id=user_id)

            org = run_activity_coro(_resolve_from_user())
            if org:
                return str(org)
        except Exception:
            pass
    return None


def _edge_persist_fk_context(scenario: Dict[str, Any], serial: str) -> dict[str, Any]:
    """FK-safe fields forwarded to agent-boot for direct content_items writes."""
    execution_id = scenario.get("_execution_id") or scenario.get("execution_id") or scenario.get("run_id")
    exec_text = str(execution_id).strip() if execution_id else None
    return {
        "execution_id": exec_text,
        "campaign_id": _resolve_campaign_id_for_edge(scenario),
        "user_id": _resolve_user_id_for_edge(serial, scenario),
        "org_id": _resolve_org_id_for_edge(serial, scenario),
    }


def _resolve_campaign_id_for_edge(scenario: Dict[str, Any]) -> str | None:
    execution_id = (
        scenario.get("_execution_id")
        or scenario.get("execution_id")
        or scenario.get("run_id")
    )
    exec_id = str(execution_id).strip() if execution_id else None

    # When upstream already resolved FK-safe campaign (e.g. Temporal execute_extract),
    # honor explicit None — do not fall back to stale workflow campaign_id.
    if "_campaign_id" in scenario:
        pre = scenario.get("_campaign_id")
        if not pre:
            return None
        campaign_id = str(pre).strip() or None
    else:
        raw = scenario.get("campaign_id")
        campaign_id = str(raw).strip() if raw else None

    if not campaign_id and not exec_id:
        return None

    try:
        from db.database import run_activity_coro, activity_session
        from services.content.campaign_ref import resolve_persist_campaign_id

        async def _resolve():
            async with activity_session() as db:
                return await resolve_persist_campaign_id(
                    db,
                    campaign_id=campaign_id,
                    execution_id=exec_id,
                )

        return run_activity_coro(_resolve())
    except Exception as exc:
        log.warning("edge extra_data: campaign_id resolve failed: %s", exc)
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
    if not _relay_extra_data_available(device):
        result["ok"] = False
        result["message"] = (
            f"edge extra_data {strategy}: no relay for device "
            "(start agent-boot relay and ensure device is registered)"
        )
        return True
    if step.get("edge_extra_requires_context"):
        log.info("[%s] edge extra_data skipped because step requires in-memory extraction context", serial)
        result["ok"] = False
        result["message"] = f"edge extra_data {strategy}: step requires in-memory extraction context"
        return True

    parent_post_id_var = step.get("parent_post_id_var")
    parent_post_id = ctx.get(parent_post_id_var) if parent_post_id_var else ctx.get("_fb_comment_parent_pid")
    parent_var = step.get("save_parent_id_var") or step.get("parent_id_var")
    parent_id_already_scoped = False
    parent_id = None
    if strategy == "fb_comments":
        # Prefer tap-scoped hash (matches persisted fb_post row). Base hash uses
        # comment-target dedupe and must not override the scoped parent_id.
        parent_id = ctx.get("_active_comment_parent_hash")
        parent_id_already_scoped = bool(parent_id)
        if parent_id is None:
            parent_id = ctx.get("_edge_comment_parent_base_hash")
            parent_id_already_scoped = False
        if parent_id is None and parent_var:
            parent_id = ctx.get(parent_var)
            parent_id_already_scoped = bool(parent_id)
    if strategy == "fb_posts" and step.get("dedupe_field"):
        ctx["_fb_posts_dedupe_field"] = step.get("dedupe_field")
    return_items = _edge_extra_should_return_items(step, collection)
    comment_defaults: dict[str, Any] = {}
    if strategy in COMMENT_STRATEGIES:
        from services.extract_profiles import DEFAULT_EXTRACT_PROFILE, get_profile_defaults
        from services.scenario_step_contract import resolve_extract_profile

        comment_defaults = get_profile_defaults(resolve_extract_profile(step), strategy)
    context = {
        "schema_version": 1,
        "context_id": scenario.get("_execution_id") or scenario.get("_run_hash_scope") or serial,
        **_edge_persist_fk_context(scenario, serial),
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
        "parent_id_already_scoped": parent_id_already_scoped,
        "parent_post_id": parent_post_id,
        "post_key": step.get("post_key") or ctx.get("last_post_key"),
        "_post_id_map": ctx.get("_post_id_map"),
        "_fb_posts_dedupe_field": ctx.get("_fb_posts_dedupe_field"),
        "posts_dedupe_field": ctx.get("_fb_posts_dedupe_field")
        or step.get("posts_dedupe_field"),
        "posts": ctx.get("posts"),
        "_active_comment_parent_anchor": ctx.get("_active_comment_parent_anchor"),
        "max_items": int(
            step.get("max_items")
            or comment_defaults.get("max_items")
            or (400 if strategy in COMMENT_STRATEGIES else 50)
        ),
        "source_index": int(ctx.get("_loop_iter", 0) or 0),
        "persist": bool(collection),
        "return_items": return_items,
        "package_name": step.get("package_name") or step.get("current_package") or "",
    }
    for key, val in comment_defaults.items():
        context.setdefault(key, val)
    for key in (
        "comment_scroll_passes",
        "comment_swipes_per_dump",
        "comment_scroll_distance",
        "comment_scroll_duration_ms",
        "comment_scroll_pause_s",
        "comment_no_growth_break",
        "min_comment_scan_passes",
        "comment_max_snapshots",
        "comment_xml_max_bytes",
        "hierarchy_compressed",
        "hierarchy_dump_timeout_s",
        "expand_see_more_max_passes",
        "expand_see_more_scroll",
        "expand_see_more_scroll_distance",
        "expand_completion_retries",
        "expand_see_more_wall_s",
        "expand_see_more_fast",
        "expand_see_more_xml_probe",
        "expand_see_more_xml_probe_first",
        "expand_selector_max_s",
        "expand_see_more_xml_fallback",
        "expand_selector_timeout_s",
        "hierarchy_compressed",
        "open_post_before_extract",
        "open_post_press_back_after_extract",
        "open_post_tap_settle_s",
        "open_post_max_attempts",
        "open_post_verify",
        "allow_a11y_xml_fallback",
    ):
        if key in step:
            context[key] = step[key]
    if strategy in COMMENT_STRATEGIES:
        context["expand_see_more"] = False
    elif "expand_see_more" in step:
        context["expand_see_more"] = step["expand_see_more"]
    if strategy not in COMMENT_STRATEGIES:
        from services.extract_profiles import DEFAULT_EXTRACT_PROFILE, get_profile_defaults
        from services.scenario_step_contract import resolve_extract_profile

        profile_name = resolve_extract_profile(step)
        profile_defaults = get_profile_defaults(profile_name, strategy)
        if not profile_defaults and strategy.endswith("_posts"):
            profile_defaults = get_profile_defaults(profile_name, "fb_posts")
        for ek, ev in (profile_defaults or {}).items():
            context.setdefault(ek, ev)
        if "expand_see_more" not in context:
            context.setdefault("expand_see_more", True)
            context.setdefault("expand_see_more_fast", True)
            context.setdefault("expand_completion_retries", 1)
            context.setdefault("expand_see_more_wall_s", 18)
    timeout = float(step.get("edge_extra_timeout_s") or os.environ.get("EDGE_EXTRA_TIMEOUT_S", "60"))
    try:
        summary = device.request_extra_data_xml(
            strategy=strategy,
            context=context,
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
    if collection and parsed_count > 0 and (
        ingest.get("screenshot_b64") or ingest.get("batch_content_hashes")
    ):
        _attach_edge_content_screenshots(
            device=device,
            ingest=ingest,
            collection=str(collection),
            execution_id=scenario.get("_execution_id") or scenario.get("_run_hash_scope"),
            user_id=(scenario.get("_campaign_vars") or {}).get("__USER_ID__") or scenario.get("user_id"),
        )
    result["extracted"] = inserted_count if collection else parsed_count
    result["duplicate_count"] = duplicate_count
    edge_extra_summary = ingest
    if not return_items and isinstance(ingest.get("items"), list):
        edge_extra_summary = {
            k: v
            for k, v in ingest.items()
            if k not in ("items", "screenshot_b64")
        }
        edge_extra_summary["items_omitted"] = len(ingest["items"])
    elif isinstance(edge_extra_summary, dict):
        edge_extra_summary = {
            k: v for k, v in edge_extra_summary.items() if k != "screenshot_b64"
        }
    result["edge_extra_summary"] = edge_extra_summary
    result["reason_code"] = ((ingest.get("diagnostic") or {}) if isinstance(ingest.get("diagnostic"), dict) else {}).get("reason_code", "ok")
    if strategy == "fb_posts":
        pid_map = ingest.get("post_id_map") if isinstance(ingest.get("post_id_map"), dict) else None
        if pid_map:
            merged = ctx.setdefault("_post_id_map", {})
            if isinstance(merged, dict):
                merged.update(pid_map)
        _remember_active_comment_parent(ctx, ingest)
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
    if not _relay_extra_data_available(device):
        result["ok"] = False
        result["message"] = "tap_fb_comment_button: no relay for device"
        return None
    context = {
        "schema_version": 1,
        "context_id": scenario.get("_execution_id") or scenario.get("_run_hash_scope") or serial,
        **_edge_persist_fk_context(scenario, serial),
        "device_serial": serial,
        "hash_scope": scenario.get("_run_hash_scope") or scenario.get("_execution_id"),
        "dedupe_field": step.get("dedupe_field") or "post_key",
        "posts_dedupe_field": ctx.get("_fb_posts_dedupe_field")
        or step.get("posts_dedupe_field")
        or "text",
        "source_index": int(ctx.get("_loop_iter", 0) or 0),
        "switch_to_all_comments": bool(step.get("switch_to_all_comments", True)),
        "post_tap_wait_s": float(step.get("post_tap_wait_s", 0.8) or 0.8),
        "comment_filter_step_pause_s": float(step.get("comment_filter_step_pause_s", 0.45) or 0.45),
        "comment_filter_post_select_s": float(step.get("comment_filter_post_select_s", 0.85) or 0.85),
    }
    for ctx_key in (
        "comment_target_verify",
        "comment_recover_chrome",
        "comment_target_verify_max_retries",
        "comment_target_center_y_ratio",
        "comment_target_band_low",
        "comment_target_band_high",
        "comment_target_u2_click",
        "comment_sheet_u2_wait",
        "comment_sheet_wait_s",
        "comment_target_click_timeout_s",
    ):
        if ctx_key in step:
            context[ctx_key] = step[ctx_key]
    timeout = float(
        step.get("edge_extra_timeout_s")
        or os.environ.get("EDGE_COMMENT_TARGET_TIMEOUT_S", "12")
    )
    try:
        strategy = "fb_comment_target_tap" if _env_bool("EDGE_COMMENT_TARGET_AGENT_TAP", True) else "fb_comment_target"
        summary = device.request_extra_data_xml(
            strategy=strategy,
            context=context,
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

    if not _relay_extra_data_available(device):
        report["reason_code"] = "no_relay"
        return report

    wait_s = float(step.get("post_tap_wait_s", 0.8) or 0.8)
    context = {
        "schema_version": 1,
        "context_id": scenario.get("_execution_id") or scenario.get("_run_hash_scope") or serial,
        **_edge_persist_fk_context(scenario, serial),
        "device_serial": serial,
        "comment_filter": target_filter,
        "switch_to_all_comments": True,
        "post_tap_wait_s": wait_s,
        "comment_filter_step_pause_s": float(step.get("comment_filter_step_pause_s", 0.45) or 0.45),
        "comment_filter_post_select_s": float(step.get("comment_filter_post_select_s", 0.85) or 0.85),
    }
    timeout = float(
        step.get("edge_extra_timeout_s")
        or os.environ.get("EDGE_COMMENT_FILTER_TIMEOUT_S", "10")
    )
    step_pause = float(step.get("comment_filter_step_pause_s", 0.35) or 0.35)

    if _env_bool("EDGE_COMMENT_FILTER_AGENT_APPLY", True):
        apply_timeout = float(
            step.get("edge_extra_timeout_s")
            or os.environ.get("EDGE_COMMENT_FILTER_APPLY_TIMEOUT_S", "18")
        )
        try:
            summary = device.request_extra_data_xml(
                strategy="fb_comment_filter_apply",
                context=context,
                timeout=apply_timeout,
            )
        except Exception as exc:
            report["reason_code"] = "request_failed"
            report["error"] = str(exc)
            result["edge_filter_summary"] = report
            return report
        if not summary.get("ok"):
            report["reason_code"] = "ingest_failed"
            report["error"] = summary.get("error")
            result["edge_filter_summary"] = report
            return report
        ingest = summary.get("ingest") if isinstance(summary.get("ingest"), dict) else summary
        diagnostic = ingest.get("diagnostic") if isinstance(ingest.get("diagnostic"), dict) else {}
        report["steps"] = list(diagnostic.get("steps") or [])
        report["switched"] = bool(diagnostic.get("switched"))
        report["reason_code"] = str(diagnostic.get("reason_code") or "ok")
        result["edge_filter_summary"] = report
        return report

    for _ in range(3):
        try:
            summary = device.request_extra_data_xml(
                strategy="fb_comment_filter_next",
                context=context,
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
        from services.content.extraction.capture_service import ExtractionCaptureService
        from services.content.extraction.hierarchy.service import HierarchyService
        from services.content.extraction.models import CaptureError, StrategyMismatchError
        from services.content.extraction.scenario_bridge import (
            execution_capture_ctx,
            run_extraction_async,
            should_persist_artifact,
        )

        exec_ctx = execution_capture_ctx(sc, idx, "hierarchy_snapshot")
        persist = should_persist_artifact(sc, step) and exec_ctx is not None

        async def _run():
            svc = HierarchyService(ExtractionCaptureService())
            return await svc.extract(
                sc.device,
                "screen_data",
                config={
                    "filter_class": step.get("filter_class"),
                    "exclude_empty": step.get("exclude_empty", True),
                },
                persist=persist,
                execution_ctx=exec_ctx,
            )

        hr = run_extraction_async(_run())
        items = hr.data if isinstance(hr.data, list) else [hr.data]
        fmt = step.get("format", "text")
        if fmt == "json":
            sc.var_ctx.set(save_as, items)
        else:
            sc.var_ctx.set(
                save_as,
                "\n".join(i["text"] for i in items if isinstance(i, dict) and i.get("text")),
            )
        result["message"] = f"Extracted {len(items)} text elements"
        if hr.raw_data.get("artifact_id"):
            result["artifact_id"] = hr.raw_data["artifact_id"]
    except (CaptureError, StrategyMismatchError) as exc:
        result["ok"] = False
        result["message"] = f"extract_text_hierarchy failed: {exc}"
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
        from services.content.extraction.capture_service import ExtractionCaptureService
        from services.content.extraction.models import CaptureError, OCRError
        from services.content.extraction.ocr_service import OCRService
        from services.content.extraction.scenario_bridge import (
            capture_screenshot_async,
            execution_capture_ctx,
            map_ocr_languages,
            run_extraction_async,
            should_persist_artifact,
        )

        exec_ctx = execution_capture_ctx(sc, idx, "screenshot_ocr")
        persist = should_persist_artifact(sc, step) and exec_ctx is not None
        region = step.get("region")

        async def _run():
            capture = ExtractionCaptureService()
            handle = await capture_screenshot_async(
                capture,
                sc.device,
                region=region,
                persist=persist,
                execution_ctx=exec_ctx,
            )
            ocr = OCRService(confidence_threshold=float(step.get("confidence_threshold", 0.5)))
            langs = map_ocr_languages(step.get("languages") or step.get("language", "eng"))
            ocr_result = await ocr.extract(
                handle.image_bytes,
                lang=langs,
                region=region,
                confidence_threshold=float(step.get("confidence_threshold", 0.5)),
            )
            return ocr_result, handle.artifact_id

        ocr_result, artifact_id = run_extraction_async(_run())
        text = "\n".join(r["text"] for r in ocr_result.results if r.get("text"))
        sc.var_ctx.set(save_as, text)
        result["message"] = f"OCR extracted {len(text)} chars"
        if artifact_id:
            result["artifact_id"] = artifact_id
    except (CaptureError, OCRError) as exc:
        result["ok"] = False
        result["message"] = f"extract_text_ocr failed: {exc}"
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
        from services.content.extraction.capture_service import ExtractionCaptureService
        from services.content.extraction.hierarchy.service import HierarchyService
        from services.content.extraction.models import CaptureError, OCRError, StrategyMismatchError
        from services.content.extraction.ocr_service import OCRService
        from services.content.extraction.scenario_bridge import (
            capture_screenshot_async,
            execution_capture_ctx,
            map_ocr_languages,
            run_extraction_async,
            should_persist_artifact,
        )

        persist = should_persist_artifact(sc, step)

        if strategy in ("auto", "hierarchy"):
            exec_ctx = execution_capture_ctx(sc, idx, "hierarchy_snapshot")
            hierarchy_persist = persist and exec_ctx is not None

            async def _hierarchy():
                svc = HierarchyService(ExtractionCaptureService())
                return await svc.extract(
                    sc.device,
                    "screen_data",
                    config={"exclude_empty": True},
                    persist=hierarchy_persist,
                    execution_ctx=exec_ctx,
                )

            try:
                hr = run_extraction_async(_hierarchy())
                items = hr.data if isinstance(hr.data, list) else []
                if items:
                    extracted = "\n".join(
                        i["text"] for i in items if isinstance(i, dict) and i.get("text")
                    )
                    source = "hierarchy"
                    if hr.raw_data.get("artifact_id"):
                        result["artifact_id"] = hr.raw_data["artifact_id"]
            except StrategyMismatchError:
                pass

        if extracted is None and strategy in ("auto", "ocr"):
            ocr_ctx = execution_capture_ctx(sc, idx, "screenshot_ocr")
            ocr_persist = persist and ocr_ctx is not None

            async def _ocr():
                capture = ExtractionCaptureService()
                handle = await capture_screenshot_async(
                    capture,
                    sc.device,
                    region=None,
                    persist=ocr_persist,
                    execution_ctx=ocr_ctx,
                )
                ocr = OCRService()
                langs = map_ocr_languages(step.get("language", "eng"))
                ocr_result = await ocr.extract(handle.image_bytes, lang=langs)
                text = "\n".join(r["text"] for r in ocr_result.results if r.get("text"))
                return text, handle.artifact_id

            try:
                text, artifact_id = run_extraction_async(_ocr())
                if text and len(text) > 3:
                    extracted = text
                    source = "ocr"
                    if artifact_id:
                        result["artifact_id"] = artifact_id
            except (CaptureError, OCRError):
                pass

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
