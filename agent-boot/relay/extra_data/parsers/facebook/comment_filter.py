from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .parser import _hierarchy_is_fb_comment_sheet, _infer_screen_size, _parse_bounds, _parse_xml
from .ui_expansion import _bounds_center, _resolve_expand_clickable_bounds

Bounds = Tuple[int, int, int, int]

COMMENT_FILTER_MODES = frozenset({"most_relevant", "newest", "all_comments"})

_FILTER_LABELS: Dict[str, Tuple[str, ...]] = {
    "most_relevant": ("phù hợp nhất", "most relevant"),
    "newest": ("mới nhất", "newest"),
    "all_comments": ("tất cả bình luận", "all comments"),
}

_SORT_SHEET_TITLE_VN = ("phù hợp nhất", "mới nhất", "tất cả bình luận")
_SORT_SHEET_TITLE_EN = ("most relevant", "newest", "all comments")


def _norm(value: str) -> str:
    return " ".join((value or "").replace("\n", " ").split())


def _norm_lower(value: str) -> str:
    return _norm(value).lower()


def _node_blob(node) -> str:
    return _norm_lower(f"{node.get('text') or ''} {node.get('content-desc') or ''}")


def normalize_comment_filter(
    value: Any,
    *,
    switch_to_all_comments: bool = True,
) -> Optional[str]:
    """Resolve target filter mode from step field or legacy switch."""
    if value is not None and str(value).strip():
        mode = _norm_lower(str(value))
        if mode in ("none", "skip", "off", "no", "default", "keep"):
            return None
        aliases = {
            "most_relevant": "most_relevant",
            "relevant": "most_relevant",
            "phù hợp nhất": "most_relevant",
            "newest": "newest",
            "mới nhất": "newest",
            "all": "all_comments",
            "all_comments": "all_comments",
            "tất cả bình luận": "all_comments",
        }
        resolved = aliases.get(mode)
        if resolved in COMMENT_FILTER_MODES:
            return resolved
    if switch_to_all_comments is False:
        return None
    return "all_comments"


def _is_sort_bottom_sheet_open(root) -> bool:
    """True when the 3-option comment sort bottom sheet is visible."""
    _, screen_h = _infer_screen_size(root)
    y_min = int(screen_h * 0.42) if screen_h >= 400 else 0
    hits_vn = set()
    hits_en = set()
    for node in root.iter("node"):
        text = _norm_lower(node.get("text") or "")
        if not text or len(text) > 48:
            continue
        bounds = _parse_bounds(node)
        if bounds and bounds[1] < y_min:
            continue
        if text == "phù hợp nhất":
            hits_vn.add("phù hợp nhất")
        elif text == "mới nhất":
            hits_vn.add("mới nhất")
        elif text == "tất cả bình luận":
            hits_vn.add("tất cả bình luận")
        elif text == "most relevant":
            hits_en.add("most relevant")
        elif text == "newest":
            hits_en.add("newest")
        elif text == "all comments":
            hits_en.add("all comments")
    return len(hits_vn) >= 2 or len(hits_en) >= 2


def _is_description_line(text: str) -> bool:
    tl = _norm_lower(text)
    if not tl:
        return True
    if tl in _SORT_SHEET_TITLE_VN or tl in _SORT_SHEET_TITLE_EN:
        return False
    prefixes = (
        "hiển thị ",
        "show all ",
        "displays all ",
        "display all ",
    )
    return any(tl.startswith(p) for p in prefixes) or "có thể là spam" in tl or "may be spam" in tl


def _indicator_shows_filter(blob: str, target: str) -> bool:
    labels = _FILTER_LABELS.get(target, ())
    if not any(label in blob for label in labels):
        return False
    if "thay đổi bộ lọc" not in blob and "change comment filter" not in blob:
        return False
    if target == "all_comments":
        return True
    if target == "most_relevant":
        return "tất cả bình luận" not in blob and "all comments" not in blob
    if target == "newest":
        return "tất cả bình luận" not in blob and "all comments" not in blob
    return True


def _is_already_on_filter(root, target: str) -> bool:
    if _is_sort_bottom_sheet_open(root):
        return False
    for node in root.iter("node"):
        blob = _node_blob(node)
        if _indicator_shows_filter(blob, target):
            return True
        text = _norm_lower(node.get("text") or "")
        desc = _norm_lower(node.get("content-desc") or "")
        if target == "all_comments" and text == "tất cả bình luận" and ("spam" in desc or "hiển thị tất cả" in desc):
            return True
        if target == "all_comments" and "đang hiển thị" in desc and ("tất cả bình luận" in desc or "all comments" in desc):
            return True
        if target == "newest" and "đang hiển thị" in desc and ("mới nhất" in desc or "newest" in desc):
            return True
        if target == "most_relevant" and "đang hiển thị" in desc and (
            "phù hợp nhất" in desc or "most relevant" in desc
        ):
            return True
    return False


def _is_already_all_comments_filter(root) -> bool:
    return _is_already_on_filter(root, "all_comments")


def _find_filter_indicator_bounds(root) -> Optional[Bounds]:
    best: Optional[Tuple[int, Bounds]] = None
    for node in root.iter("node"):
        blob = _node_blob(node)
        if "thay đổi bộ lọc" not in blob and "change comment filter" not in blob:
            continue
        if "tất cả bình luận" in blob and ("spam" in blob or "hiển thị tất cả" in blob):
            continue
        bounds = _resolve_expand_clickable_bounds(node)
        if not bounds:
            continue
        y_top = bounds[1]
        if best is None or y_top < best[0]:
            best = (y_top, bounds)
    return best[1] if best else None


def _find_filter_option_bounds(root, target: str) -> Optional[Bounds]:
    if not _is_sort_bottom_sheet_open(root):
        return None
    labels = set(_FILTER_LABELS.get(target, ()))
    candidates: List[Tuple[int, int, Bounds]] = []
    for node in root.iter("node"):
        text = _norm(node.get("text") or "")
        tl = text.lower()
        if tl not in labels:
            continue
        if _is_description_line(text):
            continue
        bounds = _resolve_expand_clickable_bounds(node)
        if not bounds:
            continue
        x1, y1, x2, y2 = bounds
        row_h = max(1, y2 - y1)
        tap_bounds = (x1, y1, x2, y1 + max(28, row_h // 3))
        candidates.append((tap_bounds[1], tap_bounds[2] - tap_bounds[0], tap_bounds))
    if not candidates:
        for node in root.iter("node"):
            desc = _norm(node.get("content-desc") or "")
            dl = desc.lower()
            if not any(dl.startswith(label) for label in labels):
                continue
            if _is_description_line(desc):
                continue
            bounds = _resolve_expand_clickable_bounds(node)
            if not bounds:
                continue
            x1, y1, x2, y2 = bounds
            row_h = max(1, y2 - y1)
            tap_bounds = (x1, y1, x2, y1 + max(28, row_h // 3))
            candidates.append((tap_bounds[1], tap_bounds[2] - tap_bounds[0], tap_bounds))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[-1][2]


def _find_all_comments_option_bounds(root) -> Optional[Bounds]:
    return _find_filter_option_bounds(root, "all_comments")


def _looks_like_fb_comment_filter_context(root) -> bool:
    if _hierarchy_is_fb_comment_sheet(root):
        return True
    return _find_filter_indicator_bounds(root) is not None or _is_sort_bottom_sheet_open(root)


def resolve_comment_filter_next_tap(
    xml: str,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return the next tap needed to reach the requested FB comment sort filter."""
    ctx = context or {}
    target = normalize_comment_filter(
        ctx.get("comment_filter"),
        switch_to_all_comments=bool(ctx.get("switch_to_all_comments", True)),
    )
    if not target:
        return {
            "phase": "done",
            "reason_code": "filter_disabled",
            "target_filter": None,
            "tap": None,
        }

    root = _parse_xml(xml)
    if root is None:
        return {
            "phase": "error",
            "reason_code": "invalid_xml",
            "target_filter": target,
            "tap": None,
        }

    if _is_already_on_filter(root, target):
        return {
            "phase": "done",
            "reason_code": "already_on_filter",
            "target_filter": target,
            "tap": None,
        }

    if not _looks_like_fb_comment_filter_context(root):
        return {
            "phase": "done",
            "reason_code": "not_comment_sheet",
            "target_filter": target,
            "tap": None,
        }

    if _is_sort_bottom_sheet_open(root):
        bounds = _find_filter_option_bounds(root, target)
        if bounds:
            return {
                "phase": "select_option",
                "reason_code": "ok",
                "target_filter": target,
                "tap": {"bounds": list(bounds), "center": list(_bounds_center(bounds))},
            }
        return {
            "phase": "done",
            "reason_code": "option_not_found",
            "target_filter": target,
            "tap": None,
        }

    bounds = _find_filter_indicator_bounds(root)
    if bounds:
        return {
            "phase": "open_sheet",
            "reason_code": "ok",
            "target_filter": target,
            "tap": {"bounds": list(bounds), "center": list(_bounds_center(bounds))},
        }
    return {
        "phase": "done",
        "reason_code": "indicator_not_found",
        "target_filter": target,
        "tap": None,
    }


__all__ = [
    "COMMENT_FILTER_MODES",
    "normalize_comment_filter",
    "resolve_comment_filter_next_tap",
    "_is_sort_bottom_sheet_open",
    "_is_already_all_comments_filter",
    "_is_already_on_filter",
]
