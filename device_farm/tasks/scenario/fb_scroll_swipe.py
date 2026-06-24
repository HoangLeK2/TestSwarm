"""FB scroll helpers for scenario steps (farm-side, no agent-boot import)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

_SUGGESTED_GROUPS_MARKERS = (
    "gợi ý cho bạn",
    "suggested for you",
    "made for you",
    "tham gia nhóm",
    "join group",
    "nhóm gợi ý",
    "suggested groups",
    "dành cho bạn",
)

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _parse_bounds(raw: str | None) -> Optional[Tuple[int, int, int, int]]:
    if not raw:
        return None
    match = _BOUNDS_RE.search(raw)
    if not match:
        return None
    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip().lower()


def _contains_marker(blob: str) -> bool:
    return any(marker in blob for marker in _SUGGESTED_GROUPS_MARKERS)


def _suggested_groups_block_top(root: ET.Element, screen_h: int) -> Optional[int]:
    block_top: int | None = None
    for node in root.iter("node"):
        blob = _norm(f"{node.get('text') or ''} {node.get('content-desc') or ''}")
        cls = node.get("class") or ""
        is_marker = _contains_marker(blob)
        is_lower_carousel = (
            "HorizontalScrollView" in cls
            and (node.get("scrollable") or "").lower() == "true"
        )
        if not is_marker and not is_lower_carousel:
            continue
        bounds = _parse_bounds(node.get("bounds"))
        if not bounds:
            continue
        _x1, y1, _x2, y2 = bounds
        if is_lower_carousel and y1 < int(screen_h * 0.40):
            continue
        if is_marker or y1 >= int(screen_h * 0.45):
            if block_top is None or y1 < block_top:
                block_top = y1
    return block_top


def resolve_feed_scroll_swipe_from_xml(
    xml: str,
    *,
    screen_w: int,
    screen_h: int,
    start_x_ratio: float = 0.5,
    start_y_ratio: float = 0.65,
    end_y_ratio: float = 0.47,
) -> Optional[Tuple[int, int, int, int]]:
    if screen_w <= 0 or screen_h <= 0 or not xml:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None

    block_top = _suggested_groups_block_top(root, screen_h)
    if block_top is None:
        has_marker = any(
            _contains_marker(_norm(f"{n.get('text') or ''} {n.get('content-desc') or ''}"))
            for n in root.iter("node")
        )
        if not has_marker:
            return None
        block_top = int(screen_h * 0.58)

    pad = max(56, int(screen_h * 0.035))
    safe_bottom = min(int(screen_h * 0.55), block_top - pad)
    safe_top = max(int(screen_h * 0.12), int(screen_h * 0.18))
    if safe_bottom - safe_top < int(screen_h * 0.10):
        safe_bottom = max(safe_top + int(screen_h * 0.10), int(screen_h * 0.38))
        safe_top = int(screen_h * 0.12)

    travel = int(screen_h * max(0.16, min(0.30, start_y_ratio - end_y_ratio)))
    fy = min(safe_bottom, int(screen_h * start_y_ratio))
    if fy >= block_top - pad:
        fy = block_top - pad
    ty = max(safe_top, fy - travel)
    if ty >= fy:
        ty = max(safe_top, fy - max(48, int(screen_h * 0.12)))
    if ty >= fy:
        return None

    sx = int(screen_w * min(0.95, max(0.05, start_x_ratio)))
    return sx, fy, sx, ty
