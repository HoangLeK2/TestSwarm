"""Collect UI hierarchy XML via relay u2 for edge extra_data (PA B)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger("relay.extra_data.collector")

_collect_locks: dict[str, asyncio.Lock] = {}


def _collect_lock(serial: str) -> asyncio.Lock:
    lock = _collect_locks.get(serial)
    if lock is None:
        lock = asyncio.Lock()
        _collect_locks[serial] = lock
    return lock


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


async def _u2_swipe_vertical(
    executor: Any,
    serial: str,
    *,
    distance_ratio: float,
    duration_s: float,
) -> bool:
    width, height = await _window_size(executor, serial)
    cx = int(width * 0.5)
    y1 = int(height * 0.65)
    y2 = int(height * max(0.2, 0.65 - distance_ratio))
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


# Text selectors only — xpath on Facebook can scan the tree for 10s+ per attempt.
_SEE_MORE_U2_SELECTORS: tuple[dict[str, str], ...] = (
    {"textContains": "Xem thêm"},
    {"text": "Xem thêm"},
    {"textContains": "See more"},
    {"text": "See more"},
    {"descriptionContains": "Xem thêm"},
    {"descriptionContains": "See more"},
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
        if await _try_u2_see_more_selectors(executor, serial, context):
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
        total_taps, cached = await _expand_see_more_xml_probe_tap(executor, serial, context)
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


async def _dump_hierarchy(
    executor: Any,
    serial: str,
    context: dict[str, Any] | None = None,
) -> str | None:
    ctx = context or {}
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
    """Mirror APK collectCommentXmlSnapshots using u2 swipe + dump."""
    passes = _int_context(context, "comment_scroll_passes", 0, 0, 20)
    if passes <= 0:
        return [initial_xml]

    min_passes = _int_context(context, "min_comment_scan_passes", 1, 0, passes)
    no_growth_break = _int_context(context, "comment_no_growth_break", 3, 0, 20)
    max_snapshots = _int_context(context, "comment_max_snapshots", 16, 1, 31)
    max_xml_bytes = _int_context(context, "comment_xml_max_bytes", 6 * 1024 * 1024, 512 * 1024, 7 * 1024 * 1024)
    distance = _float_context(context, "comment_scroll_distance", 0.22, 0.08, 0.75)
    duration_ms = _int_context(context, "comment_scroll_duration_ms", 340, 120, 1600)
    pause_s = _float_context(context, "comment_scroll_pause_s", 0.30, 0.05, 4.0)

    snapshots: list[str] = [initial_xml]
    seen: set[str] = {_sha256_hex(initial_xml)}
    total_xml_bytes = len(initial_xml.encode("utf-8"))
    unchanged_passes = 0

    width, height = await _window_size(executor, serial)
    x = int(width * 0.55)
    y1 = int(height * 0.74)
    y2 = int(height * max(0.18, 0.74 - distance))
    duration_s = max(0.12, duration_ms / 1000.0)

    for i in range(passes):
        if len(snapshots) >= max_snapshots:
            logger.info("[%s] extra_data comment snapshot cap reached: %d", serial, len(snapshots))
            break

        swipe_result = await executor.run_batch(
            serial,
            [{
                "op": "swipe",
                "fx": x,
                "fy": y1,
                "tx": x,
                "ty": y2,
                "duration": duration_s,
            }],
            early_exit=True,
        )
        if not swipe_result.get("ok"):
            logger.warning("[%s] extra_data comment swipe failed at pass %d", serial, i + 1)
            break

        if pause_s > 0:
            await asyncio.sleep(pause_s)

        next_xml = await _dump_hierarchy(executor, serial, context)
        if not next_xml:
            break

        next_bytes = len(next_xml.encode("utf-8"))
        if total_xml_bytes + next_bytes > max_xml_bytes:
            logger.info("[%s] extra_data comment XML byte cap reached", serial)
            break

        digest = _sha256_hex(next_xml)
        if digest in seen:
            unchanged_passes += 1
            if no_growth_break > 0 and (i + 1) >= min_passes and unchanged_passes >= no_growth_break:
                logger.info("[%s] extra_data comment no-growth break after %d passes", serial, i + 1)
                break
            continue

        seen.add(digest)
        snapshots.append(next_xml)
        total_xml_bytes += next_bytes
        unchanged_passes = 0

    return snapshots


async def collect_fb_comment_target_with_tap(
    executor: Any,
    serial: str,
    context: dict[str, Any],
) -> tuple[list[str], str | None, bool, dict[str, Any]]:
    """
    One u2 session: HTTP dump → resolve target → tap → settle (no reconnect between steps).
    """
    from relay.extra_data.ingest import _parse_items

    async with _collect_lock(serial):

        async def _flow() -> tuple[list[str], str | None, bool, dict[str, Any]]:
            collect_started = time.monotonic()
            logger.info(
                "[%s] extra_data collect+tap start strategy=fb_comment_target_tap",
                serial,
            )
            xml = await _dump_hierarchy(executor, serial, context)
            if not xml:
                return [], "u2_hierarchy_unavailable", False, {"reason_code": "u2_hierarchy_unavailable"}

            _, diagnostic = _parse_items("fb_comment_target", xml, context)
            tapped = False
            target = diagnostic.get("target") if isinstance(diagnostic.get("target"), dict) else None
            bounds = target.get("bounds") if target else None
            if isinstance(bounds, list) and len(bounds) == 4:
                x1, y1, x2, y2 = [int(v) for v in bounds]
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                if await _u2_click(executor, serial, cx, cy):
                    tapped = True
                    logger.info(
                        "[%s] extra_data fb_comment_target_tap: tapped at (%d,%d)",
                        serial,
                        cx,
                        cy,
                    )
                    settle_s = _float_context(context, "post_tap_wait_s", 0.6, 0.0, 3.0)
                    if settle_s > 0:
                        await asyncio.sleep(settle_s)
            else:
                logger.info(
                    "[%s] extra_data fb_comment_target_tap: skip tap reason=%s",
                    serial,
                    diagnostic.get("reason_code"),
                )
            logger.info(
                "[%s] extra_data collect+tap done snapshots=1 total=%.2fs tapped=%s",
                serial,
                time.monotonic() - collect_started,
                tapped,
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

    max_steps = min(3, _int_context(context, "comment_filter_max_steps", 3, 1, 5))
    step_pause = _float_context(context, "comment_filter_step_pause_s", 0.35, 0.0, 2.0)

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
                    report["switched"] = True
                    report["reason_code"] = reason or "ok"
                    report["phase"] = "done"
                    break

                if step_pause > 0:
                    await asyncio.sleep(step_pause)
            else:
                if "reason_code" not in report:
                    report["reason_code"] = "max_steps"
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
                "[%s] extra_data collect start strategy=%s expand=%s",
                serial,
                strategy,
                _bool_context(
                    context,
                    "expand_see_more",
                    strategy in _POST_STRATEGIES or str(strategy).endswith("_posts"),
                ),
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

            expand_default = strategy in _POST_STRATEGIES or str(strategy).endswith("_posts")
            cached_xml: str | None = None
            if _bool_context(context, "expand_see_more", expand_default):
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

            if strategy in _COMMENT_STRATEGIES:
                snapshots = await _collect_comment_snapshots(executor, serial, context, xml)
            else:
                snapshots = [xml]

            if not snapshots:
                return [], "u2_hierarchy_unavailable"
            logger.info(
                "[%s] extra_data collect done snapshots=%d total=%.2fs",
                serial,
                len(snapshots),
                time.monotonic() - collect_started,
            )
            return snapshots, None

        if hasattr(executor, "with_session"):
            return await executor.with_session(serial, _collect)
        return await _collect()


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

    payload: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "serial": serial,
        "strategy": server_strategy,
        "context": context,
        "xml": primary,
        "xml_sha256": _sha256_hex(primary),
        "snapshot_count": len(snapshots),
        "captured_at_ms": int(time.time() * 1000),
    }
    if len(snapshots) > 1:
        payload["xml_snapshots"] = snapshots
    return payload
