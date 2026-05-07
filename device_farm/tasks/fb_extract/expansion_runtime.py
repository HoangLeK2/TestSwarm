from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from .parser import _parse_xml
from .ui_expansion import _bounds_center, _collect_see_more_tap_plan


def _xml_has_actionable_see_more_expand(xml: str) -> bool:
    if not (xml or "").strip():
        return False
    root = _parse_xml(xml)
    return bool(_collect_see_more_tap_plan(root))


def _expand_see_more(
    device,
    max_passes: int = 5,
    scroll_between: bool = False,
    scroll_distance: float = 0.3,
    max_total_taps: int = 40,
    no_change_threshold: int = 3,
) -> int:
    total = 0
    no_change_streak = 0
    for pass_num in range(max_passes):
        if total >= max_total_taps:
            break
        if pass_num > 0 and scroll_between:
            device.scroll(direction="down", distance=scroll_distance, duration_ms=780)
            time.sleep(1.0)
        expanded_this_pass = 0
        try:
            while total < max_total_taps:
                xml = device.hierarchy_xml(force_refresh=True)
                if not xml:
                    break
                root = _parse_xml(xml)
                if root is None:
                    break
                plan = _collect_see_more_tap_plan(root)
                if not plan:
                    break
                b = min(plan, key=lambda bb: (_bounds_center(bb)[1], _bounds_center(bb)[0]))
                cx, cy = _bounds_center(b)
                device.tap(cx, cy)
                expanded_this_pass += 1
                total += 1
                time.sleep(0.4)
        except Exception:
            break
        if expanded_this_pass:
            time.sleep(1.5 + expanded_this_pass * 0.2)
            no_change_streak = 0
        else:
            no_change_streak += 1
            if no_change_streak >= no_change_threshold:
                break
            if scroll_between:
                device.scroll(direction="down", distance=max(0.15, scroll_distance / 2), duration_ms=720)
                time.sleep(0.85)
    return total


def expand_see_more_with_lazy_hydration(
    device,
    *,
    max_rounds: int = 6,
    scroll_distance: float = 0.25,
    scroll_settle_s: float = 0.8,
    settle_base: float = 1.5,
    settle_per_tap: float = 0.2,
    max_total_taps: int = 40,
) -> int:
    total_taps = 0
    for _ in range(max(1, max_rounds)):
        if total_taps >= max_total_taps:
            break
        xml_before = device.hierarchy_xml(force_refresh=True) or ""
        remaining = max_total_taps - total_taps
        taps = _expand_see_more(
            device,
            max_passes=1,
            scroll_between=False,
            scroll_distance=scroll_distance,
            max_total_taps=remaining,
            no_change_threshold=1,
        )
        total_taps += taps
        if taps == 0 and not _xml_has_actionable_see_more_expand(xml_before):
            break
        if taps:
            time.sleep(settle_base + taps * settle_per_tap)
        time.sleep(scroll_settle_s)
        xml_after = device.hierarchy_xml(force_refresh=True) or ""
        if xml_before == xml_after:
            break
    return total_taps


def prefetch_viewport_scrolls(
    device,
    *,
    passes: int = 3,
    distance: float = 0.3,
    pause_s: float = 0.7,
) -> None:
    for _ in range(max(0, passes)):
        try:
            device.scroll(direction="down", distance=distance)
        except Exception:
            break
        time.sleep(pause_s)


__all__ = [
    "_xml_has_actionable_see_more_expand",
    "_expand_see_more",
    "expand_see_more_with_lazy_hydration",
    "prefetch_viewport_scrolls",
]

