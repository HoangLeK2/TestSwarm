from __future__ import annotations

from typing import Any, List, Optional, Tuple

_SEE_MORE_EXPAND_PHRASES: Tuple[str, ...] = (
    "see more",
    "xem thêm",
    "xemthem",
    "view more",
    "view more comments",
    "view more replies",
    "xem thêm bình luận",
    "xem thêm câu trả lời",
    "xem bài viết đầy đủ",
    "xem toàn bộ",
    "đọc thêm",
)

_SEE_MORE_TAP_CENTER_DEDUP_PX: int = 52

_PROFILE_TAB_CHIP_MARKERS: Tuple[str, ...] = (
    "tất cả",
    "ảnh",
    "reels",
    "all",
    "photos",
    "videos",
)


def _parse_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    b = node.get("bounds")
    if not b:
        return None
    try:
        p1, p2 = b.strip("[]").split("][")
        x1, y1 = map(int, p1.split(","))
        x2, y2 = map(int, p2.split(","))
        return x1, y1, x2, y2
    except Exception:
        return None


def _normalize_fb_ui_spacing(value: str) -> str:
    return " ".join((value or "").replace("\n", " ").split())


def _bounds_center(b: Tuple[int, int, int, int]) -> Tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def _tap_centers_within(
    b1: Tuple[int, int, int, int],
    b2: Tuple[int, int, int, int],
    max_d: int,
) -> bool:
    x1, y1 = _bounds_center(b1)
    x2, y2 = _bounds_center(b2)
    return abs(x1 - x2) <= max_d and abs(y1 - y2) <= max_d


def _resolve_expand_clickable_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    if (node.get("clickable") or "").lower() == "true":
        b = _parse_bounds(node)
        if b:
            return b
    cur = node
    for _ in range(6):
        cur = cur.getparent()
        if cur is None:
            break
        if (cur.get("clickable") or "").lower() == "true":
            b = _parse_bounds(cur)
            if b:
                return b
    return None


def _expand_clickable_area(b: Tuple[int, int, int, int]) -> int:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _bounds_contains_outer_inner(
    outer: Tuple[int, int, int, int],
    inner: Tuple[int, int, int, int],
) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _is_profile_tab_chip_label(merged: str) -> bool:
    txt = _normalize_fb_ui_spacing(merged).lower()
    if not txt:
        return False
    has_index = "trong số" in txt or " of " in txt
    if not has_index:
        return False
    return any(marker in txt for marker in _PROFILE_TAB_CHIP_MARKERS)


def detect_profile_tab_strip_bottom(root) -> Optional[int]:
    """Bottom Y of FB profile/page sticky tab chips (e.g. Tất cả / Ảnh / Reels)."""
    if root is None:
        return None
    chip_bottoms: list[int] = []
    for node in root.iter("node"):
        merged = _normalize_fb_ui_spacing(
            f"{node.get('text') or ''} {node.get('content-desc') or ''}"
        )
        if not _is_profile_tab_chip_label(merged):
            continue
        bounds = _parse_bounds(node)
        if bounds:
            chip_bottoms.append(bounds[3])
    if len(chip_bottoms) < 2:
        return None
    return max(chip_bottoms)


def profile_tab_strip_min_tap_y(root, *, margin: int = 12) -> Optional[int]:
    bottom = detect_profile_tab_strip_bottom(root)
    if bottom is None:
        return None
    return bottom + margin


def hierarchy_has_profile_tab_strip(root) -> bool:
    return detect_profile_tab_strip_bottom(root) is not None


def _collect_see_more_tap_plan(root) -> List[Tuple[int, int, int, int]]:
    """Ordered tap targets: prefer Button, then smallest area; skip wrapper rows."""
    if root is None:
        return []

    def _in_tabstrip_context(node) -> bool:
        cur = node
        for _ in range(5):
            cur = cur.getparent()
            if cur is None:
                break
            t = _normalize_fb_ui_spacing(cur.get("text") or "")
            d = _normalize_fb_ui_spacing(cur.get("content-desc") or "")
            merged = f"{t} {d}".strip().lower()
            if not merged or "xem thêm" not in merged:
                continue
            if "…" in merged or "..." in merged:
                return False
            if any(
                tab_kw in merged
                for tab_kw in ("tất cả", "ảnh", "reels", "all", "photos", "trong số", " of ")
            ):
                return True
        return False

    nodes = root.xpath('//node[@text or @content-desc]')
    candidates: List[Tuple[int, int, Tuple[int, int, int, int]]] = []
    for node in nodes:
        txt = ((node.get("text") or "") + " " + (node.get("content-desc") or "")).strip().lower()
        if not txt or not any(k in txt for k in _SEE_MORE_EXPAND_PHRASES):
            continue
        txt_norm = _normalize_fb_ui_spacing(txt)
        if txt_norm in {"xem thêm, 4 trong số 4", "see more, 4 of 4"}:
            continue
        if (
            ("xem thêm" in txt_norm and "trong số" in txt_norm)
            or ("see more" in txt_norm and " of " in txt_norm)
        ):
            continue
        if (
            "xem thêm" in txt_norm
            and "…" not in txt_norm
            and "..." not in txt_norm
            and any(tab_kw in txt_norm for tab_kw in ("tất cả", "ảnh", "reels", "all", "photos"))
        ):
            continue
        if "xem thêm" in txt_norm and _in_tabstrip_context(node):
            continue
        b = _resolve_expand_clickable_bounds(node)
        if not b:
            continue
        cls = node.get("class") or ""
        btn_prio = 0 if "Button" in cls else 1
        candidates.append((btn_prio, _expand_clickable_area(b), b))

    candidates.sort(key=lambda x: (x[0], x[1]))
    out: List[Tuple[int, int, int, int]] = []
    for _btn_prio, area, b in candidates:
        if any(a2 < area and _bounds_contains_outer_inner(b, b2) for _p2, a2, b2 in candidates):
            continue
        if any(_tap_centers_within(b, ob, _SEE_MORE_TAP_CENTER_DEDUP_PX) for ob in out):
            continue
        out.append(b)
    return out


__all__ = [
    "_SEE_MORE_EXPAND_PHRASES",
    "_SEE_MORE_TAP_CENTER_DEDUP_PX",
    "_bounds_center",
    "_collect_see_more_tap_plan",
    "detect_profile_tab_strip_bottom",
    "hierarchy_has_profile_tab_strip",
    "profile_tab_strip_min_tap_y",
]

