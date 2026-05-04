from __future__ import annotations

import logging
import math
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree as _lxml

from .constants import (
    _LOGIN_SCREEN_MARKERS,
    _RATE_LIMIT_MARKERS,
    _author_prefix_match,
)
from .shared import XPATH_LIST, XPATH_RECYCLER

log = logging.getLogger(__name__)
_LXML_PARSER = _lxml.XMLParser(recover=True, remove_comments=True, encoding="utf-8")


def _parse_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _normalize_fb_ui_spacing(value: str) -> str:
    if not value:
        return ""
    s = unicodedata.normalize("NFC", value).replace("\u00a0", " ").replace("\u202f", " ")
    return s.strip()


def _cy(bounds: Tuple[int, int, int, int]) -> int:
    return (bounds[1] + bounds[3]) // 2


def _recycler_item_top_y_sort_key(el) -> Tuple[int, int]:
    b = _parse_bounds(el)
    if not b:
        return (2_147_483_647, 0)
    return (b[1], b[0])


def _infer_screen_size(root) -> Tuple[int, int]:
    best_area = 0
    best_wh = (1080, 2200)
    for node in root.iter():
        b = _parse_bounds(node)
        if not b:
            continue
        w, h = b[2] - b[0], b[3] - b[1]
        a = w * h
        if a > best_area and w >= 320 and h >= 480:
            best_area = a
            best_wh = (w, h)
    return best_wh


def _score_feed_container(el, screen_w: int, screen_h: int) -> float:
    b = _parse_bounds(el)
    if not b:
        return -1.0
    w, h = b[2] - b[0], b[3] - b[1]
    if h < max(120, int(screen_h * 0.11)):
        return -1.0
    cls = el.get("class") or ""
    node_count = len(el.findall(".//node"))
    if node_count < 3:
        return -1.0
    area = float(w * h)
    boost = 1.25 if "StaggeredGrid" in cls else 1.0
    score = area * math.log(1 + node_count) * boost
    width_ratio = w / float(screen_w or 1)
    if width_ratio < 0.72:
        score *= 0.45
    if h < 220 and w < int(screen_w * 0.92):
        score *= 0.35
    return score


def _pick_feed_container(containers: List[Any], root) -> Any:
    screen_w, screen_h = _infer_screen_size(root)
    ranked = [(_score_feed_container(el, screen_w, screen_h), el) for el in containers]
    ranked.sort(key=lambda t: t[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    return max(containers, key=lambda el: len(el.findall("node")))


def _collect_text_nodes(element, toolbar_cutoff_y: int = 200) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for node in element.iter():
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")

        is_author_hint = False
        desc_lower = desc.lower()
        matched_prefix = _author_prefix_match(desc_lower)
        if matched_prefix is not None:
            remainder = desc[len(matched_prefix):].strip().lstrip(",").strip()
            name_part = remainder.split(",")[0].strip()
            if 2 <= len(name_part) <= 80:
                content = name_part
                is_author_hint = True
            else:
                continue
        else:
            desc_lower_full = desc.lower()
            if not text and desc_lower_full.startswith("nút thích"):
                continue
            if not text and desc and re.search(r"\d", desc):
                content = desc
            else:
                content = text if text else desc
            if not content:
                continue

        bounds = _parse_bounds(node)
        if not bounds:
            continue
        if bounds[3] < toolbar_cutoff_y:
            continue
        if bounds[0] == bounds[2] or bounds[1] == bounds[3]:
            continue
        nodes.append(
            {
                "text": content,
                "bounds": bounds,
                "cy": _cy(bounds),
                "resource_id": node.get("resource-id") or "",
                "is_author_hint": is_author_hint,
            }
        )
    nodes.sort(key=lambda n: n["cy"])
    return nodes


def _parse_xml(xml: str) -> Optional[Any]:
    try:
        raw = xml.encode("utf-8") if isinstance(xml, str) else xml
        return _lxml.fromstring(raw, parser=_LXML_PARSER)
    except Exception as exc:
        log.warning("fb_extract: XML parse error: %s", exc)
        return None


def _scan_special_screen(root) -> Optional[str]:
    try:
        blob_parts: List[str] = []
        for node in root.iter():
            t = (node.get("text") or "").strip()
            d = (node.get("content-desc") or "").strip()
            if t:
                blob_parts.append(t)
            if d:
                blob_parts.append(d)
            if len(blob_parts) > 400:
                break
        blob = " ".join(blob_parts).casefold()
        for m in _LOGIN_SCREEN_MARKERS:
            if m in blob and "bình luận" not in blob and "comment" not in blob:
                return "login_screen"
        for m in _RATE_LIMIT_MARKERS:
            if m in blob:
                return "rate_limited"
    except Exception:
        return None
    return None


def _hierarchy_is_fb_comment_sheet(root) -> bool:
    has_close = False
    composer_top: Optional[int] = None
    filter_top: Optional[int] = None
    for node in root.iter():
        if (node.get("package") or "") != "com.facebook.katana":
            continue
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = (node.get("content-desc") or "").strip()
        cls = node.get("class") or ""
        lowered = f"{text} {desc}".lower()
        bounds = _parse_bounds(node)
        if "Button" in cls and (text in {"Đóng", "Close"} or desc in {"Đóng", "Close"}):
            has_close = True
        if (
            "autocomplete" in cls.lower()
            and ("viết bình luận" in lowered or "write a public comment" in lowered or "write a comment" in lowered)
        ):
            if bounds:
                composer_top = bounds[1] if composer_top is None else min(composer_top, bounds[1])
        if "phù hợp nhất" in lowered or "most relevant" in lowered or "all comments" in lowered or "tất cả bình luận" in lowered:
            if bounds:
                filter_top = bounds[1] if filter_top is None else min(filter_top, bounds[1])
    if not has_close:
        return False
    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return False
    feed = _pick_feed_container(containers, root)
    b = _parse_bounds(feed)
    if not b:
        return False
    _, _, _, y2 = b
    _, screen_h = _infer_screen_size(root)
    if screen_h < 400:
        return False
    if y2 <= int(screen_h * 0.78):
        return True
    if composer_top is not None and composer_top >= y2 - 40:
        return True
    if filter_top is not None and y2 <= int(screen_h * 0.86):
        return True
    return False


def _feed_comment_y_max(root, action_btn_y_mid: Optional[int]) -> Optional[int]:
    if action_btn_y_mid is None:
        return None
    if _hierarchy_is_fb_comment_sheet(root):
        return None
    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return None
    feed = _pick_feed_container(containers, root)
    for child in feed.findall("node"):
        b = _parse_bounds(child)
        if b and b[1] <= action_btn_y_mid <= b[3]:
            return b[3]
    return None

__all__ = [
    "_parse_xml",
    "_collect_text_nodes",
    "_infer_screen_size",
    "_hierarchy_is_fb_comment_sheet",
    "_scan_special_screen",
    "_parse_bounds",
    "_pick_feed_container",
    "_feed_comment_y_max",
    "_normalize_fb_ui_spacing",
    "_cy",
    "_recycler_item_top_y_sort_key",
]
