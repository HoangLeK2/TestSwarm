"""Collect UI hierarchy XML via relay u2 for edge extra_data (PA B)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("relay.extra_data.collector")

_collect_locks: dict[str, asyncio.Lock] = {}
_CANCEL_EVENT_CONTEXT_KEY = "_cancel_event"
_PREPARSED_FB_COMMENT_ITEMS_KEY = "_preparsed_fb_comment_items"
_PREPARSED_FB_COMMENT_DIAGNOSTIC_KEY = "_preparsed_fb_comment_diagnostic"
_PREPARSED_FB_COMMENT_SNAPSHOT_COUNT_KEY = "_preparsed_fb_comment_snapshot_count"
_PREPARSED_FB_COMMENT_XML_BYTES_KEY = "_preparsed_fb_comment_xml_bytes"
_COMMENT_SCROLL_MAX_SWIPES = 4
_COMMENT_SWIPES_PER_DUMP = 1
_COMMENT_NO_GROWTH_BREAK = 1
_COMMENT_MIN_SCAN_PASSES = 1
_COMMENT_SCROLL_DURATION_MS = 80
_COMMENT_SCROLL_PAUSE_S = 0.0
_COMMENT_DEEP_SCROLL_MAX_SWIPES = 10_000
_COMMENT_DEEP_SWIPES_PER_DUMP = 6
_COMMENT_DEEP_NO_GROWTH_BREAK = 24
_COMMENT_STALL_SWIPES_PER_DUMP = 2
_COMMENT_DEEP_MAX_SNAPSHOTS = 2_000
_COMMENT_MIN_SCROLL_DURATION_S = 0.06
_COMMENT_SCROLL_SETTLE_S = 0.0
_POST_OPEN_TAP_SETTLE_S = 0.10


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _collect_lock(serial: str) -> asyncio.Lock:
    lock = _collect_locks.get(serial)
    if lock is None:
        lock = asyncio.Lock()
        _collect_locks[serial] = lock
    return lock


def _cancel_event_from_context(context: dict[str, Any] | None) -> asyncio.Event | None:
    if not isinstance(context, dict):
        return None
    event = context.get(_CANCEL_EVENT_CONTEXT_KEY)
    if isinstance(event, asyncio.Event):
        return event
    return None


def _raise_if_cancelled(context: dict[str, Any] | None) -> None:
    event = _cancel_event_from_context(context)
    if event is not None and event.is_set():
        raise asyncio.CancelledError("extra_data_cancelled")


async def _sleep_cancelable(context: dict[str, Any] | None, seconds: float) -> None:
    if seconds <= 0:
        return
    event = _cancel_event_from_context(context)
    if event is None:
        await asyncio.sleep(seconds)
        return
    if event.is_set():
        raise asyncio.CancelledError("extra_data_cancelled")
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return
    raise asyncio.CancelledError("extra_data_cancelled")


def strip_private_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe context for parser/ingest payloads."""
    return {key: value for key, value in context.items() if not str(key).startswith("_cancel_")}


def release_collect_lock(serial: str) -> None:
    """Drop the per-serial collect lock if it is idle.

    Called from the device-offline cascade in the relay agent so phones that
    are cycled (cradle / USB replug) do not slowly grow this map. Safe to
    call when a lock is held — in that case we leave it in place and the
    holder will finish normally; the next OFFLINE event will free it.
    """
    lock = _collect_locks.get(serial)
    if lock is None:
        return
    if lock.locked():
        return
    _collect_locks.pop(serial, None)


_COMMENT_STRATEGIES = frozenset({
    "fb_comments",
    "ig_comments",
    "tiktok_comments",
    "linkedin_comments",
    "auto_comments",
})

_POST_STRATEGIES = frozenset({
    "fb_posts",
    "ig_posts",
    "tiktok_posts",
    "linkedin_posts",
    "auto_posts",
})

# Single hierarchy dump — no expand/scroll (tap-target + filter wizard).
_PROBE_ONLY_STRATEGIES = frozenset({
    "fb_comment_target",
    "fb_comment_target_tap",
    "fb_comment_filter_next",
})


def _looks_like_hierarchy_xml(xml: str) -> bool:
    s = (xml or "").strip()
    if not s or "<hierarchy" not in s:
        return False
    return not (
        s == "<hierarchy />"
        or s == '<?xml version="1.0" encoding="UTF-8"?><hierarchy />'
        or s.endswith("<hierarchy />")
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _comment_item_dedupe_key(item: dict[str, Any]) -> str:
    explicit = str(item.get("comment_key") or item.get("id") or item.get("content_hash") or "").strip()
    if explicit:
        return explicit
    author = str(item.get("author") or "").strip().casefold()
    text = str(item.get("text") or item.get("body") or "").strip().casefold()
    parent = str(item.get("parent_post_id") or item.get("parent_id") or "").strip()
    return _sha256_hex(f"{parent}\x00{author}\x00{text}") if text else ""


def _int_context(context: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(context.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _float_context(context: dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(context.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _bool_context(context: dict[str, Any], key: str, default: bool = False) -> bool:
    value = context.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def should_capture_screenshot(context: dict[str, Any]) -> bool:
    return _bool_context(
        context,
        "capture_screenshot",
        _env_bool("AGENT_BOOT_CAPTURE_SCREENSHOT", False),
    )


def _preparse_fb_comments_enabled(context: dict[str, Any]) -> bool:
    return _bool_context(
        context,
        "preparse_fb_comments",
        _env_bool("AGENT_BOOT_PREPARSE_FB_COMMENTS", False),
    )


def _include_debug_xml_snapshots(context: dict[str, Any]) -> bool:
    return _bool_context(
        context,
        "debug_xml_snapshots",
        _env_bool("AGENT_BOOT_DEBUG_XML_SNAPSHOTS", False),
    )


def _clear_preparsed_fb_comments(context: dict[str, Any]) -> None:
    for key in (
        _PREPARSED_FB_COMMENT_ITEMS_KEY,
        _PREPARSED_FB_COMMENT_DIAGNOSTIC_KEY,
        _PREPARSED_FB_COMMENT_SNAPSHOT_COUNT_KEY,
        _PREPARSED_FB_COMMENT_XML_BYTES_KEY,
        "agent_boot_preparsed_comments",
    ):
        context.pop(key, None)


def _attach_preparsed_fb_comment_snapshots(
    context: dict[str, Any],
    snapshots: list[str],
) -> None:
    _clear_preparsed_fb_comments(context)
    if not snapshots or not _preparse_fb_comments_enabled(context):
        return
    _raise_if_cancelled(context)
    started = time.perf_counter()
    try:
        from relay.extra_data.ingest import _parse_items, merge_fb_comment_frames

        max_items = _int_context(context, "max_items", 400, 1, 10_000)
        frame_results: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
        for idx, snapshot in enumerate(snapshots):
            _raise_if_cancelled(context)
            items, diagnostic = _parse_items(
                "fb_comments",
                snapshot,
                {**context, "source_index": idx},
            )
            frame_results.append((items, diagnostic))
        _raise_if_cancelled(context)
        items, diagnostic = merge_fb_comment_frames(frame_results, max_items=max_items)
    except asyncio.CancelledError:
        _clear_preparsed_fb_comments(context)
        raise
    except Exception as exc:
        context["preparse_fb_comments_error"] = str(exc)[:200]
        logger.debug("fb_comments preparsed snapshot parse failed: %s", exc)
        return

    _raise_if_cancelled(context)
    xml_bytes = sum(len(snapshot.encode("utf-8")) for snapshot in snapshots)
    diagnostic = dict(diagnostic)
    diagnostic["snapshot_count"] = len(snapshots)
    diagnostic["xml_bytes"] = xml_bytes
    diagnostic["preparse_ms"] = int((time.perf_counter() - started) * 1000)
    context[_PREPARSED_FB_COMMENT_ITEMS_KEY] = items
    context[_PREPARSED_FB_COMMENT_DIAGNOSTIC_KEY] = diagnostic
    context[_PREPARSED_FB_COMMENT_SNAPSHOT_COUNT_KEY] = len(snapshots)
    context[_PREPARSED_FB_COMMENT_XML_BYTES_KEY] = xml_bytes
    context["agent_boot_preparsed_comments"] = True


def _open_post_debug_dump_enabled(context: dict[str, Any]) -> bool:
    if _bool_context(context, "open_post_debug_dump", False):
        return True
    return os.environ.get("OPEN_POST_DEBUG_DUMP", "").strip().lower() in {"1", "true", "yes", "on"}


def _save_open_post_debug_xml(serial: str, xml: str, tag: str) -> str | None:
    """Persist hierarchy for offline post-open diagnosis (OPEN_POST_DEBUG_DUMP=1)."""
    if not xml or not _looks_like_hierarchy_xml(xml):
        return None
    out_dir = Path(__file__).resolve().parents[2] / "debug" / "traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_serial = "".join(c if c.isalnum() else "_" for c in serial)[:32] or "device"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"open_post_{safe_serial}_{tag}_{ts}.xml"
    path.write_text(xml, encoding="utf-8")
    logger.info("[%s] open_post debug xml saved: %s", serial, path)
    return str(path)


async def _u2_click(executor: Any, serial: str, x: int, y: int) -> bool:
    result = await executor.run_batch(
        serial,
        [{"op": "click", "x": int(x), "y": int(y)}],
        early_exit=True,
    )
    if not result.get("ok"):
        return False
    results = result.get("results") or []
    return bool(results and results[0].get("ok"))


async def _u2_click_selector(
    executor: Any,
    serial: str,
    selector: dict[str, Any],
    *,
    timeout: float = 1.2,
) -> bool:
    result = await executor.run_batch(
        serial,
        [{"op": "click_selector", "selector": selector, "timeout": timeout}],
        early_exit=True,
    )
    if not result.get("ok"):
        return False
    results = result.get("results") or []
    return bool(results and results[0].get("ok") and results[0].get("value"))


async def _u2_click_spec(
    executor: Any,
    serial: str,
    spec: dict[str, Any],
    *,
    timeout: float = 1.2,
) -> bool:
    result = await executor.run_batch(
        serial,
        [{"op": "click_spec", "spec": spec, "timeout": timeout}],
        early_exit=True,
    )
    if not result.get("ok"):
        return False
    results = result.get("results") or []
    return bool(results and results[0].get("ok") and results[0].get("value"))


async def _u2_wait_selector(
    executor: Any,
    serial: str,
    selector: dict[str, Any],
    *,
    timeout: float = 1.0,
) -> bool:
    result = await executor.run_batch(
        serial,
        [{"op": "wait_exists", "selector": selector, "timeout": timeout}],
        early_exit=True,
    )
    if not result.get("ok"):
        return False
    results = result.get("results") or []
    return bool(results and results[0].get("ok") and results[0].get("value"))


async def _u2_click_comment_target(
    executor: Any,
    serial: str,
    cand: dict[str, Any],
    context: dict[str, Any],
) -> tuple[bool, str]:
    """Prefer bounds-pinned U2 node click; fall back to coordinate tap."""
    from relay.extra_data.parsers.facebook.comment_pipeline import comment_tap_point

    use_u2 = _bool_context(context, "comment_target_u2_click", True)
    timeout = _float_context(context, "comment_target_click_timeout_s", 0.35, 0.1, 4.0)
    u2_click = cand.get("u2_click") if isinstance(cand.get("u2_click"), dict) else {}

    if use_u2:
        spec = u2_click.get("spec") if isinstance(u2_click.get("spec"), dict) else None
        if spec and await _u2_click_spec(executor, serial, spec, timeout=timeout):
            return True, "click_spec"
        xpath = u2_click.get("xpath")
        if xpath and await _u2_click_spec(executor, serial, {"xpath": xpath}, timeout=timeout):
            return True, "click_spec_xpath"
        allow_selector = _bool_context(context, "comment_target_selector_fallback", False)
        selector = u2_click.get("selector") if isinstance(u2_click.get("selector"), dict) else None
        if allow_selector and selector and await _u2_click_selector(executor, serial, selector, timeout=timeout):
            return True, "click_selector"

    bounds = cand.get("bounds")
    if not (isinstance(bounds, list) and len(bounds) == 4):
        return False, "invalid_bounds"
    x1, y1, x2, y2 = [int(v) for v in bounds]
    screen_w = 1080
    cx, cy = comment_tap_point((x1, y1, x2, y2), screen_w=screen_w)
    if await _u2_click(executor, serial, cx, cy):
        return True, "click_coord"
    return False, "tap_failed"


def _profile_tab_min_y_from_target(target: dict[str, Any]) -> int | None:
    raw = target.get("profile_tab_min_y")
    if isinstance(raw, (int, float)) and int(raw) > 0:
        return int(raw)
    return None


async def _u2_click_post_open_target(
    executor: Any,
    serial: str,
    target: dict[str, Any],
    context: dict[str, Any],
) -> tuple[bool, str]:
    """Tap post header metadata (timestamp / badge row / geometric fallback)."""
    from relay.extra_data.parsers.facebook.post_open_pipeline import post_header_tap_point

    bounds = target.get("bounds")
    if not (isinstance(bounds, list) and len(bounds) == 4):
        return False, "invalid_bounds"
    x1, y1, x2, y2 = [int(v) for v in bounds]
    tap_kind = str(target.get("tap_kind") or "")
    gradient_wallpaper = bool(target.get("gradient_wallpaper"))
    screen_w, _screen_h = await _window_size(executor, serial)
    timeout = _float_context(context, "post_open_click_timeout_s", 0.35, 0.1, 4.0)
    cx, cy = post_header_tap_point(
        (x1, y1, x2, y2),
        tap_kind=tap_kind,
        screen_w=screen_w,
        gradient_wallpaper=gradient_wallpaper,
        profile_tab_min_y=_profile_tab_min_y_from_target(target),
    )
    logger.info(
        "[%s] open_post tap kind=%s at (%d,%d) bounds=%s wallpaper=%s",
        serial,
        tap_kind,
        cx,
        cy,
        bounds,
        bool(target.get("gradient_wallpaper")),
    )
    if await _u2_click(executor, serial, cx, cy):
        return True, "click_coord"

    use_u2 = _bool_context(context, "post_open_u2_click", False)
    timeout = _float_context(context, "post_open_click_timeout_s", 0.25, 0.1, 4.0)
    u2_click = target.get("u2_click") if isinstance(target.get("u2_click"), dict) else {}

    if use_u2 and u2_click:
        spec = u2_click.get("spec") if isinstance(u2_click.get("spec"), dict) else None
        if spec and await _u2_click_spec(executor, serial, spec, timeout=timeout):
            return True, "click_spec"
        xpath = u2_click.get("xpath")
        if xpath and await _u2_click_spec(executor, serial, {"xpath": xpath}, timeout=timeout):
            return True, "click_spec_xpath"
        allow_selector = _bool_context(context, "post_open_selector_fallback", False)
        selector = u2_click.get("selector") if isinstance(u2_click.get("selector"), dict) else None
        if allow_selector and selector and await _u2_click_selector(executor, serial, selector, timeout=timeout):
            return True, "click_selector"
    return False, "tap_failed"


async def _u2_click_post_open_target_and_dump(
    executor: Any,
    serial: str,
    target: dict[str, Any],
    context: dict[str, Any],
    *,
    settle_s: float,
) -> tuple[bool, str, str | None]:
    """Coordinate tap and post-tap dump in one executor batch."""
    from relay.extra_data.parsers.facebook.post_open_pipeline import post_header_tap_point

    bounds = target.get("bounds")
    if not (isinstance(bounds, list) and len(bounds) == 4):
        return False, "invalid_bounds", None
    x1, y1, x2, y2 = [int(v) for v in bounds]
    tap_kind = str(target.get("tap_kind") or "")
    screen_w, _screen_h = await _window_size(executor, serial)
    cx, cy = post_header_tap_point(
        (x1, y1, x2, y2),
        tap_kind=tap_kind,
        screen_w=screen_w,
        gradient_wallpaper=bool(target.get("gradient_wallpaper")),
        profile_tab_min_y=_profile_tab_min_y_from_target(target),
    )
    logger.info(
        "[%s] open_post batched tap kind=%s at (%d,%d) bounds=%s",
        serial,
        tap_kind,
        cx,
        cy,
        bounds,
    )
    compressed = _bool_context(context, "hierarchy_compressed", False)
    dump_timeout = _float_context(context, "hierarchy_dump_timeout_s", 5.0, 2.0, 15.0)
    batch = await executor.run_batch(
        serial,
        [
            {"op": "click", "x": cx, "y": cy},
            {"op": "sleep", "seconds": settle_s},
            {"op": "dump_hierarchy", "compressed": compressed, "timeout": dump_timeout},
        ],
        early_exit=True,
    )
    if not batch.get("ok"):
        return False, "click_dump_batch_failed", None
    results = batch.get("results") or []
    clicked = bool(results and results[0].get("ok"))
    if not clicked:
        return False, "tap_failed", None
    xml = None
    if len(results) >= 3 and results[2].get("ok"):
        value = results[2].get("value")
        if isinstance(value, str) and _looks_like_hierarchy_xml(value):
            xml = value
    return True, "click_coord_batch_dump", xml


def _opened_post_payload_from_post(post: dict[str, Any]) -> dict[str, Any] | None:
    if not post:
        return None
    text_prefix = (
        post.get("text")
        or post.get("body")
        or post.get("content")
        or post.get("message")
        or post.get("caption")
        or post.get("description")
        or post.get("image_desc")
        or ""
    )
    payload = {
        "pid": post.get("_pid"),
        "post_key": post.get("post_key"),
        "stable_post_id": post.get("stable_post_id"),
        "fb_post_id": post.get("fb_post_id"),
        "author": post.get("author"),
        "timestamp": post.get("timestamp"),
        "text_prefix": str(text_prefix)[:220],
    }
    return {key: value for key, value in payload.items() if value is not None and str(value).strip()}


def _opened_post_payload_from_target(target: dict[str, Any]) -> dict[str, Any] | None:
    post = target.get("post") if isinstance(target.get("post"), dict) else {}
    return _opened_post_payload_from_post(post)


async def _maybe_open_fb_post_detail(
    executor: Any,
    serial: str,
    context: dict[str, Any],
    feed_xml: str,
) -> tuple[str | None, dict[str, Any]]:
    """Open post detail from feed header tap; return detail XML or None to keep feed."""
    from relay.extra_data.parsers.facebook.post_open_pipeline import (
        hierarchy_is_fb_post_detail_from_xml,
        resolve_post_open_targets_from_xml,
    )

    if not _bool_context(context, "open_post_before_extract", False):
        return None, {"skipped": True}

    if hierarchy_is_fb_post_detail_from_xml(feed_xml):
        probe_posts: list[dict[str, Any]] = []
        try:
            from relay.extra_data.parsers.facebook.feed_pipeline import (
                parse_fb_posts_from_xml_with_diagnostic,
            )

            probe_posts, _ = parse_fb_posts_from_xml_with_diagnostic(feed_xml)
        except Exception:
            probe_posts = []
        if len(probe_posts) >= 2:
            logger.info(
                "[%s] open_post_before_extract: post-detail heuristic false positive (%d feed posts)",
                serial,
                len(probe_posts),
            )
        else:
            logger.info("[%s] open_post_before_extract: already on post detail", serial)
            context["open_post_detail"] = True
            diagnostic: dict[str, Any] = {"reason_code": "already_on_post_detail"}
            if len(probe_posts) == 1:
                opened_post = _opened_post_payload_from_post(probe_posts[0])
                if opened_post:
                    diagnostic["opened_post"] = opened_post
            return feed_xml, diagnostic

    locked_post_key = str(context.get("post_key") or "").strip() or None
    primary, alternates = resolve_post_open_targets_from_xml(
        feed_xml,
        locked_post_key=locked_post_key,
        center_y_ratio=float(context.get("post_open_center_y_ratio") or 0.5),
    )
    candidates = ([primary] if primary else []) + [
        t for t in alternates if isinstance(t, dict)
    ]
    attempt_targets: list[dict[str, Any]] = []
    if primary:
        attempt_targets.append(primary)
        for alt_tap in primary.get("tap_alternates") or []:
            if isinstance(alt_tap, dict):
                attempt_targets.append({**primary, **alt_tap})
    for alt in alternates:
        if isinstance(alt, dict) and alt.get("post_key") != (primary or {}).get("post_key"):
            attempt_targets.append(alt)
    if not attempt_targets:
        attempt_targets = candidates
    if not candidates:
        from relay.extra_data.parsers.facebook.post_open_pipeline import (
            diagnose_post_open_resolution,
        )

        diag = diagnose_post_open_resolution(feed_xml)
        debug_path = None
        if _open_post_debug_dump_enabled(context):
            debug_path = _save_open_post_debug_xml(serial, feed_xml, "no_target")
        logger.info(
            "[%s] open_post_before_extract: no header tap target on feed diag=%s debug_xml=%s",
            serial,
            diag,
            debug_path,
        )
        return None, {"reason_code": "post_open_target_not_found", "diagnostic": diag, "debug_xml": debug_path}

    profile_tab_min_y = _profile_tab_min_y_from_target(primary or {})
    if profile_tab_min_y is not None:
        context["profile_tab_min_y"] = profile_tab_min_y

    settle_s = _float_context(
        context,
        "post_open_tap_settle_s",
        _POST_OPEN_TAP_SETTLE_S,
        0.0,
        3.0,
    )
    verify = _bool_context(context, "post_open_verify", True)
    max_attempts = _int_context(context, "post_open_max_attempts", 2, 1, 4)
    back_settle_s = _float_context(context, "post_open_back_settle_s", 0.5, 0.0, 3.0)
    attempts: list[dict[str, Any]] = []

    for idx, target in enumerate(attempt_targets[:max_attempts]):
        detail_xml: str | None = None
        use_batch_dump = _bool_context(
            context,
            "post_open_batch_dump",
            True,
        )
        if use_batch_dump:
            click_ok, route, detail_xml = await _u2_click_post_open_target_and_dump(
                executor,
                serial,
                target,
                context,
                settle_s=settle_s,
            )
            if click_ok and not detail_xml:
                detail_xml = await _dump_hierarchy(executor, serial, context)
        else:
            click_ok, route = await _u2_click_post_open_target(executor, serial, target, context)
        if not click_ok:
            attempts.append({"index": idx, "tapped": False, "reason": "tap_failed", "route": route})
            continue
        logger.info(
            "[%s] open_post_before_extract tap #%d kind=%s route=%s label=%r",
            serial,
            idx,
            target.get("tap_kind"),
            route,
            (target.get("tap_label") or "")[:60],
        )
        if not use_batch_dump and settle_s > 0:
            await asyncio.sleep(settle_s)
        if detail_xml is None:
            detail_xml = await _dump_hierarchy(executor, serial, context)
        opened = bool(detail_xml and hierarchy_is_fb_post_detail_from_xml(detail_xml))
        comment_sheet_opened = bool(detail_xml and _diag_sheet_opened(detail_xml))
        attempts.append(
            {
                "index": idx,
                "tapped": True,
                "verified": opened if verify else "skipped",
                "route": route,
                "tap_kind": target.get("tap_kind"),
                "comment_sheet_opened": comment_sheet_opened,
            }
        )
        if opened or not verify:
            context["open_post_detail"] = True
            context["open_post_detail_tap_kind"] = target.get("tap_kind")
            diagnostic = {
                "reason_code": "ok" if opened else "unverified",
                "attempts": attempts,
                "tap_kind": target.get("tap_kind"),
            }
            opened_post = _opened_post_payload_from_target(target)
            if opened_post:
                diagnostic["opened_post"] = opened_post
            return (detail_xml or feed_xml), diagnostic
        if comment_sheet_opened:
            # Timestamp/metadata taps on vivo often open the comment sheet directly.
            # Keep the sheet for extract; backing would drop parent/comment context.
            context["open_post_detail"] = True
            context["open_post_detail_tap_kind"] = target.get("tap_kind")
            diagnostic = {
                "reason_code": "comment_sheet",
                "attempts": attempts,
                "tap_kind": target.get("tap_kind"),
            }
            opened_post = _opened_post_payload_from_target(target)
            if opened_post:
                diagnostic["opened_post"] = opened_post
            logger.info(
                "[%s] open_post_before_extract tap #%d opened comment sheet — using for extract",
                serial,
                idx,
            )
            return (detail_xml or feed_xml), diagnostic
        # Verify heuristic missed detail chrome but tap may still have navigated — keep post-tap XML.
        wallpaper_body_miss = bool(
            target.get("gradient_wallpaper") and target.get("tap_kind") == "post_body"
        )
        if detail_xml and detail_xml != feed_xml and not wallpaper_body_miss:
            logger.info(
                "[%s] open_post_before_extract: verify miss but hierarchy changed — using post-tap xml",
                serial,
            )
            context["open_post_detail"] = True
            context["open_post_detail_tap_kind"] = target.get("tap_kind")
            diagnostic = {
                "reason_code": "unverified_hierarchy_changed",
                "attempts": attempts,
                "tap_kind": target.get("tap_kind"),
            }
            opened_post = _opened_post_payload_from_target(target)
            if opened_post:
                diagnostic["opened_post"] = opened_post
            return detail_xml, diagnostic
        if wallpaper_body_miss:
            attempts[-1]["verified"] = False
            attempts[-1]["reason"] = "wallpaper_body_no_detail"
            logger.info(
                "[%s] open_post_before_extract tap #%d wallpaper shell miss — try timestamp",
                serial,
                idx,
            )
        # Same rule as comment-target retries: never BACK on group feed (exits the
        # group). Only dismiss transient overlays (profile viewer, photo lightbox).
        from relay.extra_data.parsers.facebook.comment_pipeline import (
            should_press_back_after_failed_tap,
        )

        if detail_xml and should_press_back_after_failed_tap(detail_xml, context):
            backed = await _press_back_unless_group_locked(
                executor, serial, context, xml=detail_xml, reason="post_open_verify_overlay"
            )
            attempts[-1]["back_pressed"] = backed
            if back_settle_s > 0:
                await asyncio.sleep(back_settle_s)
            logger.info(
                "[%s] open_post_before_extract tap #%d verify_failed overlay back=%s",
                serial,
                idx,
                backed,
            )
        else:
            attempts[-1]["back_pressed"] = False
            logger.info(
                "[%s] open_post_before_extract tap #%d verify_failed no_back — next alternate",
                serial,
                idx,
            )

    logger.info("[%s] open_post_before_extract: verify failed after %d attempt(s)", serial, len(attempts))
    debug_path = None
    if _open_post_debug_dump_enabled(context):
        last_xml = await _dump_hierarchy(executor, serial, context)
        if last_xml:
            debug_path = _save_open_post_debug_xml(serial, last_xml, "verify_failed")
    return None, {"reason_code": "post_open_verify_failed", "attempts": attempts, "debug_xml": debug_path}


async def _wait_comment_sheet_opened(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[bool, str]:
    """Verify comment sheet via U2 wait on sheet chrome nodes (no full XML dump)."""
    from relay.extra_data.parsers.facebook.comment_pipeline import FB_COMMENT_SHEET_WAIT_SELECTORS

    if not _bool_context(context, "comment_sheet_u2_wait", True):
        return False, "skipped"
    timeout = _float_context(context, "comment_sheet_wait_s", 2.0, 0.5, 6.0)
    per_sel = max(0.25, timeout / max(1, len(FB_COMMENT_SHEET_WAIT_SELECTORS)))
    for selector in FB_COMMENT_SHEET_WAIT_SELECTORS:
        if await _u2_wait_selector(executor, serial, selector, timeout=per_sel):
            return True, "wait_exists"
    return False, "wait_miss"


async def _u2_swipe_vertical(
    executor: Any,
    serial: str,
    *,
    distance_ratio: float,
    duration_s: float,
    context: dict[str, Any] | None = None,
    start_x_ratio: float = 0.5,
) -> bool:
    width, height = await _window_size(executor, serial)
    cx = int(width * start_x_ratio)
    y1 = int(height * 0.65)
    y2 = int(height * max(0.2, 0.65 - distance_ratio))
    if context is not None:
        try:
            from relay.extra_data.parsers.facebook.scroll_swipe import (
                resolve_feed_scroll_swipe_from_xml,
            )

            xml = context.get("_last_hierarchy_xml")
            if not isinstance(xml, str) or not xml.strip():
                dump = await executor.run_batch(
                    serial,
                    [{"op": "dump_hierarchy", "timeout": 3.0}],
                    early_exit=True,
                )
                results = dump.get("results") or []
                if results and results[0].get("ok"):
                    xml = results[0].get("value")
            if isinstance(xml, str) and xml.strip():
                context["_last_hierarchy_xml"] = xml
                end_y_ratio = max(0.2, 0.65 - distance_ratio)
                resolved = resolve_feed_scroll_swipe_from_xml(
                    xml,
                    screen_w=width,
                    screen_h=height,
                    start_x_ratio=start_x_ratio,
                    start_y_ratio=0.65,
                    end_y_ratio=end_y_ratio,
                )
                if resolved is not None:
                    cx, y1, _, y2 = resolved
        except Exception:
            pass
    result = await executor.run_batch(
        serial,
        [{
            "op": "swipe",
            "fx": cx,
            "fy": y1,
            "tx": cx,
            "ty": y2,
            "duration": max(0.12, duration_s),
        }],
        early_exit=True,
    )
    return bool(result.get("ok"))


# Caption "xem thêm" only — avoid profile tab strip "Xem thêm" (capital X, trong số).
_SEE_MORE_U2_SELECTORS: tuple[dict[str, str], ...] = (
    {"text": "xem thêm"},
    {"text": "see more"},
)


async def _click_see_more_selector(executor: Any, serial: str, context: dict[str, Any]) -> bool:
    timeout = _float_context(context, "expand_selector_timeout_s", 0.35, 0.15, 2.0)
    for selector in _SEE_MORE_U2_SELECTORS:
        result = await executor.run_batch(
            serial,
            [{"op": "click_selector", "selector": selector, "timeout": timeout}],
            early_exit=True,
        )
        if not result.get("ok"):
            continue
        results = result.get("results") or []
        if results and results[0].get("ok") and results[0].get("value"):
            return True
    return False


async def _expand_see_more_via_selectors(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> int:
    wall_s = _float_context(context, "expand_see_more_wall_s", 18.0, 3.0, 120.0)
    deadline = time.monotonic() + wall_s
    selector_cap_s = _float_context(context, "expand_selector_max_s", 2.5, 0.5, 15.0)
    selector_deadline = time.monotonic() + selector_cap_s

    def _timed_out() -> bool:
        return time.monotonic() >= deadline

    def _selector_timed_out() -> bool:
        return time.monotonic() >= selector_deadline

    max_passes = min(2, _int_context(context, "expand_see_more_max_passes", 2, 1, 12))
    scroll_between = _bool_context(context, "expand_see_more_scroll", False)
    scroll_distance = _float_context(context, "expand_see_more_scroll_distance", 0.3, 0.1, 0.9)
    max_total_taps = min(40, _int_context(context, "expand_see_more_max_taps", 24, 1, 40))

    logger.info(
        "[%s] expand_see_more selector phase (max %.1fs, %d passes)",
        serial,
        selector_cap_s,
        max_passes,
    )
    total_taps = 0
    for pass_num in range(max_passes):
        if total_taps >= max_total_taps or _timed_out() or _selector_timed_out():
            break
        if pass_num > 0 and scroll_between:
            await _u2_swipe_vertical(
                executor,
                serial,
                distance_ratio=scroll_distance,
                duration_s=0.78,
                context=context,
                start_x_ratio=_float_context(context, "scroll_x_ratio", 0.18, 0.05, 0.95),
            )
            await asyncio.sleep(0.5)
        pass_taps = 0
        while total_taps < max_total_taps and not _timed_out() and not _selector_timed_out():
            if not await _click_see_more_selector(executor, serial, context):
                break
            pass_taps += 1
            total_taps += 1
            logger.info("[%s] expand_see_more tap #%d (selector)", serial, total_taps)
            await asyncio.sleep(0.35)
        if not pass_taps:
            break
    if _selector_timed_out() and not total_taps:
        logger.info("[%s] expand_see_more selector phase timed out (0 taps)", serial)
    return total_taps


async def _try_u2_see_more_selectors(executor: Any, serial: str, context: dict[str, Any]) -> bool:
    """Quick u2 text tap without dump_hierarchy (one batch, early exit on first hit)."""
    timeout = _float_context(context, "expand_selector_timeout_s", 0.35, 0.15, 2.0)
    actions = [
        {"op": "click_selector", "selector": sel, "timeout": timeout}
        for sel in _SEE_MORE_U2_SELECTORS[:4]
    ]
    result = await executor.run_batch(serial, actions, early_exit=True)
    if not result.get("ok"):
        return False
    for entry in result.get("results") or []:
        if entry.get("op") == "click_selector" and entry.get("ok") and entry.get("value"):
            return True
    return False


async def _expand_see_more_xml_probe_tap(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[int, str | None]:
    """One dump (+ post-tap dump when tapped). Returns (taps, xml_for_parse)."""
    from relay.extra_data.parsers.facebook.parser import _parse_xml
    from relay.extra_data.parsers.facebook.ui_expansion import _bounds_center, _collect_see_more_tap_plan

    if _bool_context(context, "expand_see_more_fast", True):
        if not context.get("profile_tab_min_y") and await _try_u2_see_more_selectors(
            executor, serial, context
        ):
            settle_s = _float_context(context, "expand_post_tap_settle_s", 0.35, 0.15, 2.0)
            await asyncio.sleep(settle_s)
            final_xml = await _dump_hierarchy(executor, serial, context)
            if final_xml and _looks_like_hierarchy_xml(final_xml):
                logger.info("[%s] expand_see_more tap via u2 selector (no probe dump)", serial)
                return 1, final_xml

    xml = await _dump_hierarchy(executor, serial, context)
    if not xml:
        return 0, None
    root = _parse_xml(xml)
    if root is None:
        return 0, xml if _looks_like_hierarchy_xml(xml) else None
    plan = _collect_see_more_tap_plan(root)
    if not plan:
        logger.info("[%s] expand_see_more xml_probe: no see-more in hierarchy", serial)
        return 0, xml
    bounds = min(plan, key=lambda bb: (_bounds_center(bb)[1], _bounds_center(bb)[0]))
    cx, cy = _bounds_center(bounds)
    compressed = _bool_context(context, "hierarchy_compressed", False)
    dump_timeout = _float_context(context, "hierarchy_dump_timeout_s", 5.0, 2.0, 15.0)
    settle_s = _float_context(context, "expand_post_tap_settle_s", 0.35, 0.15, 2.0)
    batch = await executor.run_batch(
        serial,
        [
            {"op": "click", "x": cx, "y": cy},
            {"op": "dump_hierarchy", "compressed": compressed, "timeout": dump_timeout},
        ],
        early_exit=True,
    )
    if not batch.get("ok"):
        logger.warning("[%s] expand_see_more xml_probe: click+dump batch failed at %s,%s", serial, cx, cy)
        return 0, xml
    results = batch.get("results") or []
    clicked = bool(results and results[0].get("ok"))
    if not clicked:
        logger.warning("[%s] expand_see_more xml_probe: click failed at %s,%s", serial, cx, cy)
        return 0, xml
    logger.info("[%s] expand_see_more tap #1 at (%d,%d) (xml_probe)", serial, cx, cy)
    await asyncio.sleep(settle_s)
    final_xml = None
    if len(results) > 1 and results[1].get("ok"):
        value = results[1].get("value")
        if isinstance(value, str) and _looks_like_hierarchy_xml(value):
            final_xml = value
            logger.info(
                "[%s] dump_hierarchy ok in-batch bytes=%d",
                serial,
                len(final_xml.encode("utf-8")),
            )
    if final_xml:
        return 1, final_xml
    return 1, xml


async def _expand_see_more_via_xml_dump(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[int, str | None]:
    """Legacy: probe/loop dump_hierarchy to locate See more bounds (slow; opt-in fallback)."""
    from relay.extra_data.parsers.facebook.expansion_runtime import _xml_has_actionable_see_more_expand
    from relay.extra_data.parsers.facebook.parser import _parse_xml
    from relay.extra_data.parsers.facebook.ui_expansion import _bounds_center, _collect_see_more_tap_plan

    wall_s = _float_context(context, "expand_see_more_wall_s", 18.0, 3.0, 120.0)
    deadline = time.monotonic() + wall_s

    def _timed_out() -> bool:
        return time.monotonic() >= deadline

    max_passes = _int_context(context, "expand_see_more_max_passes", 3, 1, 12)
    scroll_between = _bool_context(context, "expand_see_more_scroll", False)
    scroll_distance = _float_context(context, "expand_see_more_scroll_distance", 0.3, 0.1, 0.9)
    max_rounds = _int_context(context, "expand_completion_retries", 1, 1, 6)
    max_total_taps = min(40, _int_context(context, "expand_see_more_max_taps", 24, 1, 40))

    probe_xml = await _dump_hierarchy(executor, serial, context) or ""
    if not _xml_has_actionable_see_more_expand(probe_xml):
        logger.info("[%s] expand_see_more xml: no see-more in viewport (0 taps)", serial)
        return 0, probe_xml if _looks_like_hierarchy_xml(probe_xml) else None

    total_taps = 0
    pending_xml: str | None = probe_xml
    for _round in range(max_rounds):
        if total_taps >= max_total_taps or _timed_out():
            break
        round_taps = 0
        for pass_num in range(max_passes):
            if total_taps >= max_total_taps or _timed_out():
                break
            if pass_num > 0 and scroll_between:
                await _u2_swipe_vertical(
                    executor,
                    serial,
                    distance_ratio=scroll_distance,
                    duration_s=0.78,
                )
                await asyncio.sleep(0.6)
                pending_xml = None
            expanded_this_pass = 0
            while total_taps < max_total_taps and not _timed_out():
                xml = pending_xml
                pending_xml = None
                if not xml:
                    xml = await _dump_hierarchy(executor, serial, context)
                if not xml:
                    break
                root = _parse_xml(xml)
                if root is None:
                    break
                plan = _collect_see_more_tap_plan(root)
                if not plan:
                    break
                bounds = min(plan, key=lambda bb: (_bounds_center(bb)[1], _bounds_center(bb)[0]))
                cx, cy = _bounds_center(bounds)
                if not await _u2_click(executor, serial, cx, cy):
                    logger.warning("[%s] expand_see_more xml: click failed at %s,%s", serial, cx, cy)
                    break
                expanded_this_pass += 1
                total_taps += 1
                round_taps += 1
                logger.info("[%s] expand_see_more tap #%d at (%d,%d) (xml)", serial, total_taps, cx, cy)
                await asyncio.sleep(0.35)
            if not expanded_this_pass:
                break
            await asyncio.sleep(0.8 + expanded_this_pass * 0.15)
        if not round_taps:
            break
        if scroll_between:
            await _u2_swipe_vertical(
                executor,
                serial,
                distance_ratio=max(0.15, scroll_distance / 2),
                duration_s=0.72,
                context=context,
                start_x_ratio=_float_context(context, "scroll_x_ratio", 0.18, 0.05, 0.95),
            )
            await asyncio.sleep(0.5)
    return total_taps, None


async def expand_see_more_via_u2(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[int, str | None]:
    """Tap See more / Xem thêm. Fast path: u2 selectors (no dump). Returns (tap_count, cached_xml)."""
    if not _bool_context(context, "expand_see_more", False):
        return 0, None

    use_fast = _bool_context(context, "expand_see_more_fast", True)
    xml_fallback = _bool_context(context, "expand_see_more_xml_fallback", False)
    xml_probe = _bool_context(context, "expand_see_more_xml_probe", True)
    probe_first = _bool_context(context, "expand_see_more_xml_probe_first", False)

    if probe_first:
        logger.info("[%s] expand_see_more: xml_probe_first (Facebook-friendly)", serial)
        probe_context = {**context, "expand_see_more_fast": False}
        total_taps, cached = await _expand_see_more_xml_probe_tap(executor, serial, probe_context)
        if total_taps:
            logger.info(
                "[%s] extra_data expand_see_more done taps=%d route=xml_probe_first",
                serial,
                total_taps,
            )
        else:
            logger.info("[%s] expand_see_more xml_probe_first: no tap (skip selector storm)", serial)
        return total_taps, cached

    if use_fast:
        total_taps = await _expand_see_more_via_selectors(executor, serial, context)
        if total_taps == 0 and xml_probe:
            logger.info("[%s] expand_see_more: selector 0 taps, trying xml_probe (1 dump)", serial)
            total_taps, cached = await _expand_see_more_xml_probe_tap(executor, serial, context)
            if total_taps:
                logger.info(
                    "[%s] extra_data expand_see_more done taps=%d route=xml_probe",
                    serial,
                    total_taps,
                )
                return total_taps, cached
            if cached:
                return 0, cached
        if total_taps == 0 and xml_fallback:
            logger.info("[%s] expand_see_more: trying full xml_fallback", serial)
            total_taps, cached = await _expand_see_more_via_xml_dump(executor, serial, context)
            if total_taps:
                logger.info("[%s] extra_data expand_see_more done taps=%d route=xml_fallback", serial, total_taps)
            return total_taps, cached
        if total_taps:
            logger.info("[%s] extra_data expand_see_more done taps=%d route=selector", serial, total_taps)
        elif not xml_probe:
            logger.info("[%s] expand_see_more: 0 taps (selector miss, xml_probe disabled)", serial)
        return total_taps, None

    total_taps, cached = await _expand_see_more_via_xml_dump(executor, serial, context)
    if total_taps:
        logger.info("[%s] extra_data expand_see_more done taps=%d route=xml", serial, total_taps)
    else:
        logger.info("[%s] expand_see_more xml: 0 taps", serial)
    return total_taps, cached


async def _capture_screenshot_b64(
    executor: Any,
    serial: str,
) -> str | None:
    """Capture device framebuffer as base64 PNG/JPEG via u2 (for ingest evidence)."""
    if not hasattr(executor, "run_batch"):
        return None
    try:
        batch = await executor.run_batch(serial, [{"op": "screenshot"}], early_exit=True)
    except Exception:
        return None
    if not batch.get("ok"):
        return None
    results = batch.get("results") or []
    if not results or not results[0].get("ok"):
        return None
    value = results[0].get("value")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _dump_hierarchy(
    executor: Any,
    serial: str,
    context: dict[str, Any] | None = None,
) -> str | None:
    ctx = context or {}
    _raise_if_cancelled(ctx)
    compressed = _bool_context(ctx, "hierarchy_compressed", False)
    dump_timeout = _float_context(ctx, "hierarchy_dump_timeout_s", 5.0, 2.0, 15.0)
    started = time.monotonic()
    result = await executor.run_batch(
        serial,
        [{
            "op": "dump_hierarchy",
            "compressed": compressed,
            "timeout": dump_timeout,
        }],
        early_exit=True,
    )
    _raise_if_cancelled(ctx)
    elapsed = time.monotonic() - started
    if not result.get("ok"):
        logger.warning(
            "[%s] dump_hierarchy failed in %.2fs: %s",
            serial,
            elapsed,
            result.get("error") or "batch_not_ok",
        )
        return None
    results = result.get("results") or []
    if not results or not results[0].get("ok"):
        logger.warning("[%s] dump_hierarchy empty in %.2fs", serial, elapsed)
        return None
    xml = results[0].get("value")
    if not isinstance(xml, str) or not _looks_like_hierarchy_xml(xml):
        logger.warning("[%s] dump_hierarchy invalid xml in %.2fs", serial, elapsed)
        return None
    logger.info("[%s] dump_hierarchy ok in %.2fs bytes=%d", serial, elapsed, len(xml.encode("utf-8")))
    return xml


async def _window_size(executor: Any, serial: str) -> tuple[int, int]:
    if hasattr(executor, "window_size"):
        size = await executor.window_size(serial)
        if size and len(size) == 2:
            w, h = int(size[0]), int(size[1])
            if w > 0 and h > 0:
                return w, h
    return 1080, 2340


async def _collect_comment_snapshots(
    executor: Any,
    serial: str,
    context: dict[str, Any],
    initial_xml: str,
) -> list[str]:
    """Swipe through the comment list, dumping hierarchy every N swipes (not every swipe)."""
    _raise_if_cancelled(context)
    explicit_scroll_budget = "comment_scroll_passes" in context
    explicit_item_target = "max_items" in context
    explicit_target_budget = explicit_scroll_budget or explicit_item_target
    swipe_budget = _int_context(
        context,
        "comment_scroll_passes",
        _COMMENT_SCROLL_MAX_SWIPES,
        0,
        _COMMENT_DEEP_SCROLL_MAX_SWIPES if explicit_scroll_budget else _COMMENT_SCROLL_MAX_SWIPES,
    )
    if swipe_budget <= 0:
        return [initial_xml]

    explicit_swipes_per_dump = "comment_swipes_per_dump" in context
    swipes_per_dump = _int_context(
        context,
        "comment_swipes_per_dump",
        _COMMENT_SWIPES_PER_DUMP,
        1,
        _COMMENT_DEEP_SWIPES_PER_DUMP if explicit_swipes_per_dump else _COMMENT_SWIPES_PER_DUMP,
    )
    def _dump_cycle_count(swipes: int, per_dump: int) -> int:
        return max(1, (swipes + per_dump - 1) // per_dump)

    def _adaptive_dump_cycle_count(swipes: int, per_dump: int) -> int:
        return 1 + max(
            0,
            (
                max(0, swipes - per_dump)
                + _COMMENT_STALL_SWIPES_PER_DUMP
                - 1
            )
            // _COMMENT_STALL_SWIPES_PER_DUMP,
        )

    dump_cycles = _dump_cycle_count(swipe_budget, swipes_per_dump)
    adaptive_dump_cycles = _adaptive_dump_cycle_count(swipe_budget, swipes_per_dump)
    min_dumps = _int_context(
        context,
        "min_comment_scan_passes",
        _COMMENT_MIN_SCAN_PASSES,
        0,
        adaptive_dump_cycles,
    )
    explicit_no_growth = "comment_no_growth_break" in context
    no_growth_break = _int_context(
        context,
        "comment_no_growth_break",
        _COMMENT_NO_GROWTH_BREAK if explicit_no_growth else 0,
        0,
        _COMMENT_DEEP_NO_GROWTH_BREAK if explicit_no_growth else _COMMENT_NO_GROWTH_BREAK,
    )
    explicit_stop_if_no_new = (
        "comment_stop_if_no_new" in context
        or "stop_if_no_new" in context
    )
    stop_if_no_new_default = _bool_context(context, "stop_if_no_new", False)
    stop_if_no_new_comments = (
        _bool_context(
            context,
            "comment_stop_if_no_new",
            stop_if_no_new_default,
        )
        if explicit_stop_if_no_new
        else False
    )
    no_new_comment_threshold = _int_context(
        context,
        "comment_no_new_threshold",
        _int_context(context, "no_new_threshold", 4, 1, 1000),
        1,
        1000,
    )
    initial_xml_bytes = len(initial_xml.encode("utf-8"))
    snapshot_cap = (
        _COMMENT_DEEP_MAX_SNAPSHOTS
        if explicit_target_budget or "comment_max_snapshots" in context
        else 50
    )
    max_snapshots = _int_context(
        context,
        "comment_max_snapshots",
        min(snapshot_cap, max(20, adaptive_dump_cycles + 1)),
        1,
        snapshot_cap,
    )
    if explicit_target_budget:
        max_snapshots = max(
            max_snapshots,
            min(snapshot_cap, adaptive_dump_cycles + 1),
        )
    explicit_xml_byte_cap = "comment_xml_max_bytes" in context
    xml_byte_hi = 512 * 1024 * 1024 if explicit_xml_byte_cap or explicit_target_budget else 7 * 1024 * 1024
    xml_byte_default = 6 * 1024 * 1024
    if not explicit_xml_byte_cap and explicit_target_budget:
        projected_xml_bytes = max_snapshots * max(initial_xml_bytes, 512 * 1024)
        xml_byte_default = min(xml_byte_hi, max(xml_byte_default, projected_xml_bytes))
    max_xml_bytes = _int_context(
        context,
        "comment_xml_max_bytes",
        xml_byte_default,
        512 * 1024,
        xml_byte_hi,
    )
    # Fast defaults, but explicit crawl profiles keep their requested scroll tuning.
    distance = _float_context(context, "comment_scroll_distance", 0.28, 0.08, 0.85)
    explicit_duration = "comment_scroll_duration_ms" in context
    duration_ms = _int_context(
        context,
        "comment_scroll_duration_ms",
        _COMMENT_SCROLL_DURATION_MS,
        int(_COMMENT_MIN_SCROLL_DURATION_S * 1000),
        800 if explicit_duration else _COMMENT_SCROLL_DURATION_MS,
    )
    explicit_pause = "comment_scroll_pause_s" in context
    swipe_pause_s = _float_context(
        context,
        "comment_scroll_pause_s",
        _COMMENT_SCROLL_PAUSE_S,
        0.0,
        4.0 if explicit_pause else _COMMENT_SCROLL_PAUSE_S,
    )
    settle_default = max(swipe_pause_s, _COMMENT_SCROLL_SETTLE_S)
    explicit_settle = "comment_scroll_settle_s" in context
    settle_after_batch_s = _float_context(
        context,
        "comment_scroll_settle_s",
        settle_default,
        0.0,
        2.0 if explicit_settle else _COMMENT_SCROLL_SETTLE_S,
    )
    recover_chrome = _bool_context(context, "comment_recover_chrome", True)
    retry_screen_swipe_on_stuck = _bool_context(context, "comment_screen_swipe_retry_on_stuck", False)
    # Wall-clock safety cap for extremely long threads (0 = disabled). This bounds
    # the comment phase independently of the swipe budget so a single huge post
    # cannot stall the crawl loop indefinitely. Early-stop (no-new / no-growth)
    # still ends short threads well before this cap.
    configured_comment_scroll_wall_s = _float_context(
        context, "comment_scroll_wall_s", 0.0, 0.0, 600.0
    )
    comment_scroll_wall_s = configured_comment_scroll_wall_s
    max_items = _int_context(context, "max_items", 400, 1, 10_000)
    respect_post_count = _bool_context(context, "comment_respect_post_count", True)
    post_comment_count: int | None = None
    effective_comment_target = max_items
    if respect_post_count:
        from relay.extra_data.parsers.facebook.feed_pipeline import (
            extract_post_comment_count_from_xml,
            resolve_comment_crawl_target,
        )

        post_comment_count = extract_post_comment_count_from_xml(initial_xml)
        effective_comment_target = resolve_comment_crawl_target(max_items, post_comment_count)
        if post_comment_count == 0:
            context["post_comment_count"] = post_comment_count
            context["comment_target_effective"] = 0
            context["comment_scroll_skipped_reason"] = "post_comment_count_zero"
            logger.info(
                "[%s] extra_data comment scroll skipped: post comment count is zero",
                serial,
            )
            return [initial_xml]
        if (
            post_comment_count is not None
            and post_comment_count > 0
            and effective_comment_target < max_items
        ):
            logger.info(
                "[%s] extra_data comment target capped by post count: "
                "max_items=%d post_comments=%d effective=%d",
                serial,
                max_items,
                post_comment_count,
                effective_comment_target,
            )
        context["post_comment_count"] = post_comment_count
        context["comment_target_effective"] = effective_comment_target
    large_comment_target = explicit_target_budget and effective_comment_target >= 100
    if large_comment_target:
        context["comment_target_source"] = (
            "post_count" if post_comment_count is not None else "max_items"
        )
    target_budget_unknown_count = _bool_context(
        context,
        "comment_target_budget_unknown_count",
        False,
    )
    hard_comment_budget = _bool_context(context, "comment_hard_budget", False) or _bool_context(
        context,
        "lock_comment_crawl_profile",
        False,
    )
    large_target_fast_scroll = (
        large_comment_target
        and post_comment_count is not None
        and _bool_context(context, "comment_large_target_fast_scroll", False)
    )
    if large_target_fast_scroll:
        fast_swipes_per_dump = _int_context(
            context,
            "comment_large_target_swipes_per_dump",
            _COMMENT_DEEP_SWIPES_PER_DUMP,
            1,
            _COMMENT_DEEP_SWIPES_PER_DUMP,
        )
        if swipes_per_dump < fast_swipes_per_dump:
            configured_swipes_per_dump = swipes_per_dump
            swipes_per_dump = fast_swipes_per_dump
            context["comment_swipes_per_dump_configured"] = configured_swipes_per_dump
            context["comment_swipes_per_dump_effective"] = swipes_per_dump
            logger.info(
                "[%s] extra_data comment swipe batch lifted %d -> %d "
                "(target=%d post=%s)",
                serial,
                configured_swipes_per_dump,
                swipes_per_dump,
                effective_comment_target,
                post_comment_count,
            )
        fast_distance_floor = _float_context(
            context,
            "comment_large_target_scroll_distance",
            0.68,
            0.08,
            0.85,
        )
        if distance < fast_distance_floor:
            context["comment_scroll_distance_configured"] = distance
            distance = fast_distance_floor
            context["comment_scroll_distance_effective"] = distance
        fast_duration_cap_ms = _int_context(
            context,
            "comment_large_target_duration_ms",
            80,
            int(_COMMENT_MIN_SCROLL_DURATION_S * 1000),
            240,
        )
        if duration_ms > fast_duration_cap_ms:
            context["comment_scroll_duration_ms_configured"] = duration_ms
            duration_ms = fast_duration_cap_ms
            context["comment_scroll_duration_ms_effective"] = duration_ms
        dump_cycles = _dump_cycle_count(swipe_budget, swipes_per_dump)
        adaptive_dump_cycles = _adaptive_dump_cycle_count(swipe_budget, swipes_per_dump)
        max_snapshots = max(
            max_snapshots,
            min(snapshot_cap, adaptive_dump_cycles + 1),
        )

    if (
        large_comment_target
        and not hard_comment_budget
        and (post_comment_count is not None or target_budget_unknown_count)
        and _bool_context(context, "comment_target_budget", True)
    ):
        comments_per_swipe = _int_context(
            context,
            "comment_target_comments_per_swipe",
            1,
            1,
            20,
        )
        target_swipe_budget = min(
            _COMMENT_DEEP_SCROLL_MAX_SWIPES,
            max(
                swipe_budget,
                (effective_comment_target + comments_per_swipe - 1)
                // comments_per_swipe,
            ),
        )
        if target_swipe_budget > swipe_budget:
            configured_swipe_budget = swipe_budget
            swipe_budget = target_swipe_budget
            dump_cycles = _dump_cycle_count(swipe_budget, swipes_per_dump)
            adaptive_dump_cycles = _adaptive_dump_cycle_count(swipe_budget, swipes_per_dump)
            max_snapshots = max(
                max_snapshots,
                min(snapshot_cap, adaptive_dump_cycles + 1),
            )
            if not explicit_xml_byte_cap:
                projected_xml_bytes = max_snapshots * max(initial_xml_bytes, 512 * 1024)
                max_xml_bytes = max(
                    max_xml_bytes,
                    min(xml_byte_hi, projected_xml_bytes),
                )
            context["comment_scroll_passes_configured"] = configured_swipe_budget
            logger.info(
                "[%s] extra_data comment swipe budget lifted %d -> %d "
                "(target=%d post=%s comments_per_swipe=%d)",
                serial,
                configured_swipe_budget,
                swipe_budget,
                effective_comment_target,
                post_comment_count,
                comments_per_swipe,
            )
    context["comment_scroll_passes_effective"] = swipe_budget
    context.setdefault("comment_swipes_per_dump_effective", swipes_per_dump)

    from relay.extra_data.parsers.facebook.comment_pipeline import (
        detect_comment_sheet_interrupt_from_xml,
        interrupt_reason_allows_back,
        note_fb_group_navigation,
        resolve_comment_scroll_swipe_from_xml,
    )

    note_fb_group_navigation(context, initial_xml)
    from relay.extra_data.parsers.facebook.comment_filter import _is_sort_bottom_sheet_open
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        parse_fb_comments_from_xml_with_diagnostic,
    )
    from relay.extra_data.parsers.facebook.parser import _parse_xml

    def _visible_comment_keys(xml: str) -> set[str]:
        try:
            items, _diag = parse_fb_comments_from_xml_with_diagnostic(
                xml,
                parent_post_id=str(context.get("parent_post_id") or "") or None,
                max_items=120,
            )
        except Exception as exc:
            logger.debug("[%s] comment no-new probe parse failed: %s", serial, exc)
            return set()
        keys: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or item.get("_type") == "post_stats":
                continue
            key = _comment_item_dedupe_key(item)
            if key:
                keys.add(key)
        return keys

    async def _wait_sort_sheet_closed(xml: str) -> str:
        _raise_if_cancelled(context)
        wait_s = _float_context(context, "comment_filter_sheet_wait_s", 2.5, 0.0, 8.0)
        if wait_s <= 0:
            return xml
        deadline = time.monotonic() + wait_s
        current = xml
        while time.monotonic() < deadline:
            _raise_if_cancelled(context)
            root = _parse_xml(current)
            if root is None or not _is_sort_bottom_sheet_open(root):
                return current
            await _sleep_cancelable(context, 0.28)
            fresh = await _dump_hierarchy(executor, serial, context)
            if fresh:
                current = fresh
        return current

    initial_xml = await _wait_sort_sheet_closed(initial_xml)

    async def _recover_comment_chrome(xml: str) -> tuple[str, bool]:
        _raise_if_cancelled(context)
        if not recover_chrome:
            return xml, False
        reason = detect_comment_sheet_interrupt_from_xml(xml)
        if not reason:
            return xml, False
        if not interrupt_reason_allows_back(reason, context):
            logger.info(
                "[%s] extra_data comment recovery: %s — skip BACK (group/sheet safe)",
                serial,
                reason,
            )
            return xml, reason == "left_comment_sheet"
        logger.info("[%s] extra_data comment recovery: %s — press BACK", serial, reason)
        await _press_back_unless_group_locked(
            executor, serial, context, xml=xml, reason=f"comment_recovery:{reason}"
        )
        await _sleep_cancelable(context, 0.22)
        fresh = await _dump_hierarchy(executor, serial, context)
        return (fresh if fresh else xml), False

    initial_xml, abort_scroll = await _recover_comment_chrome(initial_xml)
    if abort_scroll:
        logger.warning(
            "[%s] extra_data comment scroll aborted: not on comment sheet",
            serial,
        )
        return [initial_xml]
    snapshots: list[str] = [initial_xml]
    seen_xml: set[str] = {_sha256_hex(initial_xml)}
    target_from_max_items = large_comment_target and post_comment_count is None
    track_comment_keys = stop_if_no_new_comments or target_from_max_items or (
        post_comment_count is not None and post_comment_count > 0
    )
    seen_comment_keys: set[str] = (
        _visible_comment_keys(initial_xml) if track_comment_keys else set()
    )
    no_new_probe_ready = bool(seen_comment_keys)

    def _comment_target_reached() -> bool:
        if not track_comment_keys:
            return False
        if post_comment_count is None:
            return target_from_max_items and len(seen_comment_keys) >= effective_comment_target
        if post_comment_count <= 0:
            return False
        return len(seen_comment_keys) >= effective_comment_target

    if _comment_target_reached():
        logger.info(
            "[%s] extra_data comment target already visible: collected=%d target=%d "
            "(post=%s max_items=%d)",
            serial,
            len(seen_comment_keys),
            effective_comment_target,
            post_comment_count,
            max_items,
        )
        return snapshots

    total_xml_bytes = initial_xml_bytes
    # Stop after N consecutive dumps with identical hierarchy (end of list / scroll stuck).
    unchanged_dumps = 0
    no_new_comment_dumps = 0
    scroll_xml = initial_xml
    # Keep enough press time for Android to treat the gesture as scroll, not tap.
    duration_s = max(_COMMENT_MIN_SCROLL_DURATION_S, duration_ms / 1000.0)
    if (
        configured_comment_scroll_wall_s > 0
        and large_comment_target
        and (post_comment_count is not None or target_budget_unknown_count)
    ):
        dump_timeout_s = _float_context(context, "hierarchy_dump_timeout_s", 5.0, 2.0, 15.0)
        estimated_dump_cycles = max(dump_cycles, adaptive_dump_cycles)
        budget_floor_s = (
            estimated_dump_cycles * (dump_timeout_s + max(0.25, settle_after_batch_s))
            + swipe_budget * (duration_s + swipe_pause_s)
        )
        target_floor_s = effective_comment_target * 0.18
        effective_wall_s = min(600.0, max(20.0, budget_floor_s, target_floor_s))
        if effective_wall_s > configured_comment_scroll_wall_s:
            comment_scroll_wall_s = effective_wall_s
            context["comment_scroll_wall_s_configured"] = configured_comment_scroll_wall_s
            logger.info(
                "[%s] extra_data comment wall-clock cap lifted %.1fs -> %.1fs "
                "(target=%d post=%s swipes=%d dumps=%d)",
                serial,
                configured_comment_scroll_wall_s,
                comment_scroll_wall_s,
                effective_comment_target,
                post_comment_count,
                swipe_budget,
                estimated_dump_cycles,
            )
    context["comment_scroll_wall_s_effective"] = comment_scroll_wall_s
    use_screen_swipe = False
    use_u2_swipe_batch = _bool_context(
        context,
        "comment_u2_swipe_batch",
        large_target_fast_scroll,
    )
    context["comment_scroll_driver"] = "u2_http_batch" if use_u2_swipe_batch else "u2_batch"
    swipes_done = 0
    stall_detected = False

    async def _screen_swipe_coords() -> tuple[int, int, int, int]:
        _raise_if_cancelled(context)
        width, height = await _window_size(executor, serial)
        try:
            from relay.extra_data.parsers.facebook.scroll_swipe import (
                resolve_feed_scroll_swipe_from_xml,
            )

            if isinstance(scroll_xml, str) and scroll_xml.strip():
                feed_swipe = resolve_feed_scroll_swipe_from_xml(
                    scroll_xml,
                    screen_w=width,
                    screen_h=height,
                    start_x_ratio=0.76,
                    start_y_ratio=0.62,
                    end_y_ratio=max(0.18, 0.62 - max(0.26, min(0.75, float(distance)))),
                )
                if feed_swipe is not None:
                    return feed_swipe
        except Exception:
            pass
        x = int(width * 0.76)
        ratio = max(0.26, min(0.75, float(distance)))
        fy = int(height * 0.62)
        ty = int(height * max(0.18, 0.62 - ratio))
        return x, fy, x, ty

    async def _swipe_coords() -> tuple[int, int, int, int]:
        _raise_if_cancelled(context)
        if use_screen_swipe:
            return await _screen_swipe_coords()
        node_swipe = resolve_comment_scroll_swipe_from_xml(scroll_xml, distance_ratio=distance)
        if node_swipe:
            return node_swipe
        return await _screen_swipe_coords()

    async def _swipe_batch_and_dump(
        coords: tuple[int, int, int, int],
        count: int,
    ) -> tuple[str | None, int, bool]:
        _raise_if_cancelled(context)
        fx, fy, tx, ty = coords
        actions: list[dict[str, Any]] = []
        if use_u2_swipe_batch:
            actions.append({
                "op": "u2_swipe_batch",
                "count": count,
                "fx": fx,
                "fy": fy,
                "tx": tx,
                "ty": ty,
                "duration": duration_s,
                "pause_s": swipe_pause_s,
            })
        else:
            for idx in range(count):
                actions.append({
                    "op": "swipe",
                    "fx": fx,
                    "fy": fy,
                    "tx": tx,
                    "ty": ty,
                    "duration": duration_s,
                })
                if swipe_pause_s > 0 and idx + 1 < count:
                    actions.append({"op": "sleep", "seconds": swipe_pause_s})
        if settle_after_batch_s > 0:
            actions.append({"op": "sleep", "seconds": settle_after_batch_s})
        compressed = _bool_context(context, "hierarchy_compressed", False)
        dump_timeout = _float_context(context, "hierarchy_dump_timeout_s", 5.0, 2.0, 15.0)
        actions.append({
            "op": "dump_hierarchy",
            "compressed": compressed,
            "timeout": dump_timeout,
        })

        started = time.monotonic()
        result = await executor.run_batch(
            serial,
            actions,
            early_exit=True,
        )
        _raise_if_cancelled(context)
        results = result.get("results") or []
        completed_swipes = 0
        for entry in results:
            if entry.get("op") == "swipe" and entry.get("ok"):
                completed_swipes += 1
            elif entry.get("op") == "u2_swipe_batch" and entry.get("ok"):
                completed_swipes += max(0, int(entry.get("value") or 0))
        if not result.get("ok"):
            return None, completed_swipes, False
        dump_entry = next(
            (
                entry
                for entry in reversed(results)
                if entry.get("op") == "dump_hierarchy"
            ),
            None,
        )
        elapsed = time.monotonic() - started
        if not dump_entry or not dump_entry.get("ok"):
            return None, completed_swipes, True
        xml = dump_entry.get("value")
        if not isinstance(xml, str) or not _looks_like_hierarchy_xml(xml):
            return None, completed_swipes, True
        logger.info(
            "[%s] dump_hierarchy ok in-batch after %d swipes in %.2fs bytes=%d",
            serial,
            completed_swipes,
            elapsed,
            len(xml.encode("utf-8")),
        )
        return xml, completed_swipes, True

    wall_deadline = (
        time.monotonic() + comment_scroll_wall_s if comment_scroll_wall_s > 0 else None
    )
    cycle = 0
    while swipes_done < swipe_budget:
        _raise_if_cancelled(context)
        if len(snapshots) >= max_snapshots or swipes_done >= swipe_budget:
            break
        if wall_deadline is not None and time.monotonic() >= wall_deadline:
            logger.info(
                "[%s] extra_data comment wall-clock cap %.1fs reached after %d dump "
                "cycles (%d swipes, snapshots=%d)",
                serial,
                comment_scroll_wall_s,
                cycle,
                swipes_done,
                len(snapshots),
            )
            break

        effective_swipes_per_dump = (
            min(swipes_per_dump, _COMMENT_STALL_SWIPES_PER_DUMP)
            if stall_detected
            else swipes_per_dump
        )
        batch_swipes = min(effective_swipes_per_dump, swipe_budget - swipes_done)
        swipes_before_batch = swipes_done
        batch_coords = await _swipe_coords()
        next_xml, completed_swipes, batch_ok = await _swipe_batch_and_dump(
            batch_coords,
            batch_swipes,
        )
        swipes_done += completed_swipes
        if completed_swipes < batch_swipes or not batch_ok:
            logger.warning(
                "[%s] extra_data comment swipe batch failed at swipe %d "
                "(completed=%d/%d)",
                serial,
                swipes_done + 1,
                completed_swipes,
                batch_swipes,
            )
            return snapshots
        if not next_xml:
            break
        next_xml, abort_scroll = await _recover_comment_chrome(next_xml)
        if abort_scroll:
            logger.warning(
                "[%s] extra_data comment scroll stopped: left comment sheet",
                serial,
            )
            break

        next_bytes = len(next_xml.encode("utf-8"))
        if total_xml_bytes + next_bytes > max_xml_bytes:
            context["comment_scroll_stopped_reason"] = "xml_byte_cap_reached"
            context["comment_xml_bytes_total"] = total_xml_bytes
            context["comment_xml_bytes_next"] = next_bytes
            context["comment_xml_max_bytes_effective"] = max_xml_bytes
            logger.info("[%s] extra_data comment XML byte cap reached", serial)
            break

        digest = _sha256_hex(next_xml)
        duplicate_xml = digest in seen_xml
        if track_comment_keys and not duplicate_xml:
            current_comment_keys = _visible_comment_keys(next_xml)
            if current_comment_keys:
                no_new_probe_ready = True
                new_comment_keys = current_comment_keys - seen_comment_keys
                if new_comment_keys:
                    seen_comment_keys.update(new_comment_keys)
                    no_new_comment_dumps = 0
                    stall_detected = False
                elif stop_if_no_new_comments:
                    no_new_comment_dumps += 1
                    stall_detected = True
            elif no_new_probe_ready and stop_if_no_new_comments:
                no_new_comment_dumps += 1
                stall_detected = True
            if _comment_target_reached():
                logger.info(
                    "[%s] extra_data comment target reached after %d dump cycles "
                    "(%d swipes, collected=%d target=%d post=%s max_items=%d)",
                    serial,
                    cycle + 1,
                    swipes_done,
                    len(seen_comment_keys),
                    effective_comment_target,
                    post_comment_count,
                    max_items,
                )
                break
            if (
                stop_if_no_new_comments
                and no_new_probe_ready
                and no_new_comment_dumps >= no_new_comment_threshold
                and (cycle + 1) >= min_dumps
            ):
                logger.info(
                    "[%s] extra_data comment no-new break after %d dump cycles "
                    "(%d swipes, %d no-new comment dumps, snapshots=%d)",
                    serial,
                    cycle + 1,
                    swipes_done,
                    no_new_comment_dumps,
                    len(snapshots),
                )
                break

        if not duplicate_xml:
            seen_xml.add(digest)
            snapshots.append(next_xml)
            total_xml_bytes += next_bytes
            unchanged_dumps = 0
            use_screen_swipe = False
            scroll_xml = next_xml
            cycle += 1
            continue

        unchanged_dumps += 1
        stall_detected = True
        if retry_screen_swipe_on_stuck and not use_screen_swipe and unchanged_dumps <= 2:
            logger.info(
                "[%s] extra_data comment scroll unchanged XML — retry with screen swipe "
                "(dump cycle %d)",
                serial,
                cycle + 1,
            )
            use_screen_swipe = True
            swipes_done = swipes_before_batch
            continue
        if (
            no_growth_break > 0
            and (cycle + 1) >= min_dumps
            and unchanged_dumps >= no_growth_break
        ):
            logger.info(
                "[%s] extra_data comment no-growth break after %d dump cycles "
                "(%d swipes, %d unchanged XML dumps, snapshots=%d)",
                serial,
                cycle + 1,
                swipes_done,
                unchanged_dumps,
                len(snapshots),
            )
            break
        cycle += 1

    logger.info(
        "[%s] extra_data comment scroll done swipes=%d dumps=%d snapshots=%d",
        serial,
        swipes_done,
        len(snapshots),
        len(snapshots),
    )
    return snapshots


async def _press_back(executor: Any, serial: str) -> bool:
    """Best-effort BACK key press to bail out of an unintended sheet/dialog."""
    try:
        result = await executor.run_batch(
            serial,
            [{"op": "press_key", "key": "back"}],
            early_exit=True,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[%s] press_back failed: %s", serial, exc)
        return False
    if not result.get("ok"):
        return False
    results = result.get("results") or []
    return bool(results and results[0].get("ok"))


async def _press_back_unless_group_locked(
    executor: Any,
    serial: str,
    context: dict[str, Any],
    *,
    xml: str | None = None,
    reason: str = "",
) -> bool:
    """Press BACK only when caller already decided it is safe (overlay / IME)."""
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        fb_group_navigation_locked,
        note_fb_group_navigation,
    )

    note_fb_group_navigation(context, xml)
    if fb_group_navigation_locked(context):
        logger.info(
            "[%s] suppress system BACK (%s) fb_group_navigation=1",
            serial,
            reason or "unspecified",
        )
        return False
    return await _press_back(executor, serial)


def _diag_sheet_opened(xml: str | None) -> bool:
    """Return True iff the post-tap hierarchy looks like an FB comment sheet."""
    if not xml:
        return False
    try:
        from relay.extra_data.parsers.facebook import (
            _hierarchy_is_fb_comment_sheet,
            _parse_xml,
        )
    except Exception:  # pragma: no cover - import safety
        return False
    root = _parse_xml(xml)
    if root is None:
        return False
    try:
        return bool(_hierarchy_is_fb_comment_sheet(root))
    except Exception:  # pragma: no cover - parser safety
        return False


async def collect_fb_comment_target_with_tap(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[list[str], str | None, bool, dict[str, Any]]:
    """
    One u2 session: HTTP dump → resolve target → tap → settle → verify (no reconnect between steps).

    When the post-tap hierarchy does not look like a comment sheet we press
    BACK and retry the next-best alternate so the locked anchor stays in sync
    with the post that actually opened. Retry count is capped tightly to keep
    the worst-case extra latency small (`comment_target_verify_max_retries`,
    default 1, hard-capped at 3).
    """
    from relay.extra_data.ingest import _parse_items
    from relay.extra_data.parsers.facebook.comment_pipeline import (
        note_fb_group_navigation,
        should_press_back_after_failed_tap,
    )

    async with _collect_lock(serial):

        async def _flow() -> tuple[list[str], str | None, bool, dict[str, Any]]:
            collect_started = time.monotonic()
            logger.info(
                "[%s] extra_data collect+tap start strategy=fb_comment_target_tap",
                serial,
            )
            xml = await _dump_hierarchy(executor, serial, context)
            note_fb_group_navigation(context, xml)
            if not xml:
                return [], "u2_hierarchy_unavailable", False, {"reason_code": "u2_hierarchy_unavailable"}

            _, diagnostic = _parse_items("fb_comment_target", xml, context)

            if diagnostic.get("reason_code") == "already_on_comment_sheet":
                diagnostic["verified"] = True
                logger.info(
                    "[%s] extra_data fb_comment_target_tap: already on comment sheet — skip tap",
                    serial,
                )
                return [xml], None, False, diagnostic

            primary = diagnostic.get("target") if isinstance(diagnostic.get("target"), dict) else None
            alternates_raw = diagnostic.get("alternates") if isinstance(diagnostic.get("alternates"), list) else []
            alternates = [t for t in alternates_raw if isinstance(t, dict)]
            candidates = ([primary] if primary else []) + alternates
            tap_enabled = _bool_context(
                context,
                "comment_target_tap_enabled",
                _env_bool("AGENT_BOOT_COMMENT_TARGET_TAP_ENABLED", False),
            )
            if not tap_enabled:
                attempts = []
                if primary is not None:
                    attempts.append({
                        "index": 0,
                        "tapped": False,
                        "verified": "skipped",
                        "reason": "comment_target_tap_disabled",
                    })
                diagnostic["target"] = None
                diagnostic["resolved_target"] = primary
                diagnostic["verify_attempts"] = attempts
                diagnostic["verified"] = False
                diagnostic["chosen_index"] = None
                diagnostic["tap_disabled"] = True
                logger.info(
                    "[%s] extra_data fb_comment_target_tap: tap disabled; target resolved=%s",
                    serial,
                    primary is not None,
                )
                return [xml], None, False, diagnostic

            verify_enabled = _bool_context(context, "comment_target_verify", True)
            verify_max_retries = _int_context(
                context, "comment_target_verify_max_retries", 1, 0, 3
            )
            settle_s = _float_context(context, "post_tap_wait_s", 0.6, 0.0, 3.0)
            verify_back_settle_s = _float_context(
                context, "comment_target_verify_back_settle_s", 0.6, 0.0, 3.0
            )

            max_attempts = min(len(candidates), 1 + verify_max_retries) if verify_enabled else min(len(candidates), 1)
            attempts: list[dict[str, Any]] = []
            tapped = False
            chosen: dict[str, Any] | None = None
            chosen_index: int | None = None

            for attempt_idx in range(max_attempts):
                cand = candidates[attempt_idx]
                bounds = cand.get("bounds") if isinstance(cand, dict) else None
                if not (isinstance(bounds, list) and len(bounds) == 4):
                    attempts.append(
                        {"index": attempt_idx, "skipped": True, "reason": "invalid_bounds"}
                    )
                    continue
                click_ok, click_route = await _u2_click_comment_target(
                    executor, serial, cand, context
                )
                if not click_ok:
                    attempts.append(
                        {
                            "index": attempt_idx,
                            "tapped": False,
                            "reason": "tap_failed",
                            "click_route": click_route,
                        }
                    )
                    continue
                tapped = True
                logger.info(
                    "[%s] extra_data fb_comment_target_tap attempt=%d route=%s post_key=%s",
                    serial,
                    attempt_idx,
                    click_route,
                    cand.get("post_key"),
                )
                if settle_s > 0:
                    await asyncio.sleep(settle_s)

                if not verify_enabled:
                    attempts.append(
                        {
                            "index": attempt_idx,
                            "tapped": True,
                            "verified": "skipped",
                            "click_route": click_route,
                        }
                    )
                    chosen = cand
                    chosen_index = attempt_idx
                    break

                opened, verify_route = await _wait_comment_sheet_opened(
                    executor, serial, context
                )
                post_tap_xml: str | None = None
                if not opened:
                    post_tap_xml = await _dump_hierarchy(executor, serial, context)
                    opened = _diag_sheet_opened(post_tap_xml)
                    if opened:
                        verify_route = "xml_dump"
                attempts.append(
                    {
                        "index": attempt_idx,
                        "tapped": True,
                        "verified": opened,
                        "click_route": click_route,
                        "verify_route": verify_route,
                        "post_xml_available": post_tap_xml is not None,
                    }
                )
                if opened:
                    chosen = cand
                    chosen_index = attempt_idx
                    break

                # Sheet did not open: only BACK out of dismissible overlays (profile/photo).
                # Never BACK from group feed — that exits the group being crawled.
                is_last = attempt_idx >= max_attempts - 1
                if not is_last:
                    if post_tap_xml is None:
                        post_tap_xml = await _dump_hierarchy(executor, serial, context)
                    if post_tap_xml and should_press_back_after_failed_tap(
                        post_tap_xml, context
                    ):
                        backed = await _press_back_unless_group_locked(
                            executor,
                            serial,
                            context,
                            xml=post_tap_xml,
                            reason="comment_target_verify_overlay",
                        )
                        if verify_back_settle_s > 0:
                            await asyncio.sleep(verify_back_settle_s)
                        attempts[-1]["back_pressed"] = backed
                        logger.info(
                            "[%s] extra_data fb_comment_target_tap attempt=%d overlay verify_failed back=%s — trying next alternate",
                            serial,
                            attempt_idx,
                            backed,
                        )
                    else:
                        attempts[-1]["back_pressed"] = False
                        logger.info(
                            "[%s] extra_data fb_comment_target_tap attempt=%d verify_failed no_back — trying next alternate",
                            serial,
                            attempt_idx,
                        )

            if primary is None:
                miss_diag = diagnostic.get("resolution_diagnostic")
                logger.info(
                    "[%s] extra_data fb_comment_target_tap: skip tap reason=%s diag=%s",
                    serial,
                    diagnostic.get("reason_code"),
                    miss_diag,
                )

            diagnostic["target"] = chosen if chosen is not None else primary
            diagnostic["verify_attempts"] = attempts
            diagnostic["verified"] = bool(chosen is not None)
            diagnostic["chosen_index"] = chosen_index
            logger.info(
                "[%s] extra_data collect+tap done snapshots=1 total=%.2fs tapped=%s verified=%s attempts=%d chosen_index=%s",
                serial,
                time.monotonic() - collect_started,
                tapped,
                diagnostic["verified"],
                len(attempts),
                chosen_index,
            )
            return [xml], None, tapped, diagnostic

        if hasattr(executor, "with_session"):
            return await executor.with_session(serial, _flow)
        return await _flow()


async def collect_fb_comment_filter_apply(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """
    One u2 session: run the full comment-filter wizard (dump → tap → …) without
  farm round-trips between steps.
    """
    from relay.extra_data.ingest import _parse_items
    from relay.extra_data.parsers.facebook.comment_filter import normalize_comment_filter

    target_filter = normalize_comment_filter(
        context.get("comment_filter"),
        switch_to_all_comments=bool(context.get("switch_to_all_comments", True)),
    )
    report: dict[str, Any] = {
        "enabled": target_filter is not None,
        "target_filter": target_filter,
        "switched": False,
        "steps": [],
        "phase": "done",
    }
    if not target_filter:
        report["reason_code"] = "disabled"
        return report, None

    max_steps = min(5, _int_context(context, "comment_filter_max_steps", 5, 1, 8))
    step_pause = _float_context(context, "comment_filter_step_pause_s", 0.35, 0.0, 2.0)
    post_select_s = _float_context(context, "comment_filter_post_select_s", 0.85, 0.0, 3.0)

    async with _collect_lock(serial):

        async def _flow() -> tuple[dict[str, Any], str | None]:
            started = time.monotonic()
            logger.info(
                "[%s] extra_data filter_apply start target=%s max_steps=%d",
                serial,
                target_filter,
                max_steps,
            )
            for _ in range(max_steps):
                xml = await _dump_hierarchy(executor, serial, context)
                if not xml:
                    report["reason_code"] = "u2_hierarchy_unavailable"
                    report["phase"] = "error"
                    return report, "u2_hierarchy_unavailable"

                _, diagnostic = _parse_items("fb_comment_filter_next", xml, context)
                phase = str(diagnostic.get("phase") or "done")
                reason = str(diagnostic.get("reason_code") or "")
                step_info: dict[str, Any] = {"phase": phase, "reason_code": reason}
                report["steps"].append(step_info)

                if phase in {"done", "error"}:
                    if reason in {"already_on_filter", "already_all_comments"}:
                        report["switched"] = True
                    report["reason_code"] = reason or phase
                    report["phase"] = phase
                    break

                tap = diagnostic.get("tap") if isinstance(diagnostic.get("tap"), dict) else None
                bounds = tap.get("bounds") if tap else None
                if not isinstance(bounds, list) or len(bounds) != 4:
                    report["reason_code"] = reason or "tap_missing"
                    report["phase"] = "error"
                    break

                x1, y1, x2, y2 = [int(v) for v in bounds]
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                if not await _u2_click(executor, serial, cx, cy):
                    report["reason_code"] = "tap_failed"
                    report["phase"] = "error"
                    break
                step_info["tapped_at"] = [cx, cy]
                logger.info(
                    "[%s] extra_data filter_apply tap phase=%s at (%d,%d)",
                    serial,
                    phase,
                    cx,
                    cy,
                )

                if phase in {"select_option", "select_all"}:
                    if post_select_s > 0:
                        await asyncio.sleep(post_select_s)
                    continue

                if step_pause > 0:
                    await asyncio.sleep(step_pause)
            else:
                if "reason_code" not in report:
                    report["reason_code"] = "max_steps"
                    report["phase"] = "error"

            if report.get("phase") not in {"done", "error"} and report.get("steps"):
                last = report["steps"][-1]
                if last.get("phase") in {"select_option", "select_all"}:
                    report["reason_code"] = "filter_not_verified"
                    report["phase"] = "error"

            logger.info(
                "[%s] extra_data filter_apply done switched=%s reason=%s total=%.2fs steps=%d",
                serial,
                report.get("switched"),
                report.get("reason_code"),
                time.monotonic() - started,
                len(report.get("steps") or []),
            )
            return report, None

        if hasattr(executor, "with_session"):
            return await executor.with_session(serial, _flow)
        return await _flow()


async def collect_xml_snapshots(
    executor: Any,
    serial: str,
    strategy: str,
    context: dict[str, Any],
) -> tuple[list[str], str | None]:
    """
    Dump hierarchy XML snapshot(s) via u2.

    Returns (snapshots, error_code). error_code is None on success.
    """
    async with _collect_lock(serial):

        async def _collect() -> tuple[list[str], str | None]:
            collect_started = time.monotonic()
            logger.info(
                "[%s] extra_data collect start strategy=%s expand=%s open_post=%s",
                serial,
                strategy,
                _bool_context(
                    context,
                    "expand_see_more",
                    strategy in _POST_STRATEGIES or str(strategy).endswith("_posts"),
                ),
                _bool_context(context, "open_post_before_extract", False),
            )
            if strategy in _PROBE_ONLY_STRATEGIES:
                xml = await _dump_hierarchy(executor, serial, context)
                if not xml:
                    return [], "u2_hierarchy_unavailable"
                logger.info(
                    "[%s] extra_data collect done snapshots=1 total=%.2fs (probe-only)",
                    serial,
                    time.monotonic() - collect_started,
                )
                return [xml], None

            feed_xml: str | None = None
            detail_xml: str | None = None
            open_diag: dict[str, Any] = {}
            if strategy == "fb_posts" and _bool_context(context, "open_post_before_extract", False):
                feed_xml = await _dump_hierarchy(executor, serial, context)
                if not feed_xml:
                    return [], "u2_hierarchy_unavailable"
                context.setdefault("strategy", strategy)
                detail_xml, open_diag = await _maybe_open_fb_post_detail(
                    executor, serial, context, feed_xml
                )
                if open_diag:
                    context["open_post_detail_diagnostic"] = open_diag
                if (
                    _bool_context(context, "open_post_before_extract", False)
                    and _bool_context(context, "require_open_post_detail", True)
                    and not context.get("open_post_detail")
                ):
                    reason = "post_open_not_established"
                    if isinstance(open_diag, dict):
                        reason = str(open_diag.get("reason_code") or reason)
                    logger.info(
                        "[%s] open_post_before_extract required but not established reason=%s",
                        serial,
                        reason,
                    )
                    return [], f"post_open_required:{reason}"

            expand_default = strategy in _POST_STRATEGIES or str(strategy).endswith("_posts")
            cached_xml: str | None = detail_xml
            expand_requested = _bool_context(context, "expand_see_more", expand_default)
            if (
                strategy == "fb_posts"
                and isinstance(open_diag, dict)
                and open_diag.get("reason_code") == "comment_sheet"
            ):
                # The post-open tap already landed on the comment sheet. Running the
                # post "see more" expander here can tap/scroll the sheet before the
                # following fb_comments step gets a stable XML.
                expand_requested = False
                context["expand_see_more_skipped"] = "comment_sheet"
            if (
                expand_requested
                and strategy == "fb_posts"
                and cached_xml
                and _bool_context(context, "expand_skip_if_not_truncated", True)
            ):
                # Expanding "See more" is several taps + dumps. Skip it entirely when
                # the opened post text is not truncated — saves seconds per short post
                # without losing any content.
                try:
                    from relay.extra_data.parsers.facebook.feed_pipeline import (
                        parse_fb_posts_from_xml_with_diagnostic,
                    )

                    _probe_posts, _probe_diag = parse_fb_posts_from_xml_with_diagnostic(
                        cached_xml
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    _probe_posts, _probe_diag = [], {}
                    logger.debug("[%s] expand truncation probe failed: %s", serial, exc)
                if _probe_posts and int(_probe_diag.get("truncated_post_count", 0) or 0) == 0:
                    expand_requested = False
                    context["expand_see_more_skipped"] = "not_truncated"
                    logger.info(
                        "[%s] extra_data expand_see_more skipped: detail post not truncated",
                        serial,
                    )
            if strategy in _COMMENT_STRATEGIES:
                if expand_requested:
                    logger.info(
                        "[%s] extra_data expand_see_more skipped for %s (comment sheet has no see-more)",
                        serial,
                        strategy,
                    )
                expand_requested = False
            if expand_requested:
                expand_ctx = dict(context)
                if strategy in _POST_STRATEGIES or str(strategy).endswith("_posts"):
                    # Facebook: dump+coordinate tap first; avoids 30–60s u2 selector/reconnect loops.
                    expand_ctx.setdefault("expand_see_more_xml_probe_first", True)
                    expand_ctx.setdefault("expand_see_more_max_passes", 2)
                    # Skip selector storm before probe dump on fb_posts.
                    expand_ctx.setdefault("expand_see_more_fast", False)
                expand_taps, cached_xml = await expand_see_more_via_u2(executor, serial, expand_ctx)
                context["expand_see_more_taps"] = expand_taps

            if cached_xml and _looks_like_hierarchy_xml(cached_xml):
                logger.info("[%s] extra_data reuse expand hierarchy (skip redundant dump)", serial)
                xml = cached_xml
            else:
                xml = await _dump_hierarchy(executor, serial, context)
            if not xml:
                return [], "u2_hierarchy_unavailable"

            from relay.extra_data.parsers.facebook.comment_pipeline import (
                note_fb_group_navigation,
            )

            note_fb_group_navigation(context, feed_xml or xml)

            if strategy in _COMMENT_STRATEGIES:
                snapshots = await _collect_comment_snapshots(executor, serial, context, xml)
            else:
                snapshots = [xml]

            if not snapshots:
                return [], "u2_hierarchy_unavailable"

            if (
                context.get("open_post_detail")
                and _bool_context(context, "open_post_press_back_after_extract", False)
            ):
                await _press_back_unless_group_locked(
                    executor,
                    serial,
                    context,
                    xml=snapshots[-1] if snapshots else xml,
                    reason="open_post_after_extract",
                )
                context["open_post_detail_closed"] = True

            # Fresh framebuffer right after the last hierarchy dump (same UI state as parsed XML).
            if should_capture_screenshot(context):
                screenshot_b64 = await _capture_screenshot_b64(executor, serial)
                if screenshot_b64:
                    context["_ingest_screenshot_b64"] = screenshot_b64
                    logger.info(
                        "[%s] extra_data screenshot captured bytes~%d",
                        serial,
                        int(len(screenshot_b64) * 3 / 4),
                    )

            logger.info(
                "[%s] extra_data collect done snapshots=%d total=%.2fs",
                serial,
                len(snapshots),
                time.monotonic() - collect_started,
            )
            return snapshots, None

        if hasattr(executor, "with_session"):
            result = await executor.with_session(serial, _collect)
        else:
            result = await _collect()
        snapshots, err = result
        if err is None and strategy == "fb_comments":
            if _preparse_fb_comments_enabled(context):
                loop = asyncio.get_running_loop()
                try:
                    from relay.runtime import cpu_executor as _cpu_exec
                    parse_executor = _cpu_exec()
                except Exception:
                    parse_executor = None
                await loop.run_in_executor(
                    parse_executor,
                    _attach_preparsed_fb_comment_snapshots,
                    context,
                    snapshots,
                )
                _raise_if_cancelled(context)
            else:
                _clear_preparsed_fb_comments(context)
        return snapshots, err


def build_ingest_payload(
    *,
    serial: str,
    strategy: str,
    context: dict[str, Any],
    snapshots: list[str],
    request_id: str = "",
) -> dict[str, Any]:
    primary = snapshots[0]
    server_strategy = "fb_comment_target" if strategy == "fb_comment_target_tap" else strategy
    payload_context = dict(context)
    preparsed_items = payload_context.pop(_PREPARSED_FB_COMMENT_ITEMS_KEY, None)
    preparsed_diagnostic = payload_context.pop(_PREPARSED_FB_COMMENT_DIAGNOSTIC_KEY, None)
    preparsed_snapshot_count = payload_context.pop(
        _PREPARSED_FB_COMMENT_SNAPSHOT_COUNT_KEY,
        None,
    )
    preparsed_xml_bytes = payload_context.pop(_PREPARSED_FB_COMMENT_XML_BYTES_KEY, None)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "serial": serial,
        "strategy": server_strategy,
        "context": payload_context,
        "xml": primary,
        "xml_sha256": _sha256_hex(primary),
        "snapshot_count": len(snapshots),
        "captured_at_ms": int(time.time() * 1000),
    }
    include_preparsed = (
        server_strategy == "fb_comments"
        and payload_context.get("agent_boot_preparsed_comments") is True
        and isinstance(preparsed_items, list)
    )
    if include_preparsed:
        payload["preparsed"] = {
            "items": preparsed_items,
            "diagnostic": preparsed_diagnostic if isinstance(preparsed_diagnostic, dict) else {},
            "snapshot_count": preparsed_snapshot_count or len(snapshots),
            "xml_bytes": preparsed_xml_bytes
            or sum(len(snapshot.encode("utf-8")) for snapshot in snapshots),
        }
    if len(snapshots) > 1 and (not include_preparsed or _include_debug_xml_snapshots(payload_context)):
        payload["xml_snapshots"] = snapshots
    return payload
