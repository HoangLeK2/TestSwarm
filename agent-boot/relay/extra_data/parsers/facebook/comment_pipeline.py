from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .constants import (
    _MAX_TS_ANCHOR_NODE_LEN,
    _RE_CMT_REACTIONS,
    _RE_CMT_REACTIONS_EN,
    _RE_CMT_REPLY_BTN,
    _RE_CMT_TS_SHARE,
    _RE_TS,
    _RE_COMMENT_NAME_DOT_SUFFIX,
    _RE_CMT_LIKE_BTN,
)
from .shared import COMMENT_BUTTON_TOKENS, XPATH_LIST, XPATH_RECYCLER

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _norm_fb_ui(s: str) -> str:
    s = unicodedata.normalize("NFC", (s or "").strip())
    return re.sub(r"\s+", " ", s)


def _node_has_comment_button_token(node) -> bool:
    """True only for the post action-bar Comment control, not Like/Share a11y strings."""
    t = _norm_fb_ui(node.get("text") or "")
    d = _norm_fb_ui(node.get("content-desc") or "")
    t_cf = t.casefold()
    d_cf = d.casefold()
    exact = {unicodedata.normalize("NFC", tok).casefold() for tok in COMMENT_BUTTON_TOKENS}

    if t_cf in exact:
        return True

    if not d_cf:
        return False

    if "nút thích" in d_cf or d_cf.startswith("like "):
        return False
    if "nút chia sẻ" in d_cf or "double tap to share" in d_cf:
        return False
    if "cảm xúc về bình luận" in d_cf or "react to the comment" in d_cf:
        return False

    if d_cf in exact:
        return True
    # FB action bar: "Nút Bình luận. Nhấn đúp để xem bình luận."
    if (d_cf.startswith("nút bình luận") or d_cf.startswith("comment button")) and (
        "Button" in (node.get("class") or "") or node.get("clickable") == "true"
    ):
        if "nút thích" not in d_cf and "react to the comment" not in d_cf:
            return True
    # Action-bar count badges only — not header stats like "23 bình luận" on comment sheet.
    if re.match(r"^\d+\s+bình luận\b", d_cf) or re.match(r"^bình luận[,.]?\s*\d", d_cf):
        cls = node.get("class") or ""
        if "Button" in cls or node.get("clickable") == "true":
            return True
    return False


def _parse_bounds_from_node(node) -> Optional[Tuple[int, int, int, int]]:
    m = _BOUNDS_RE.match(node.get("bounds") or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _is_tappable_fb_node(node) -> bool:
    if node.get("enabled") == "false":
        return False
    cls = node.get("class") or ""
    if "Button" in cls:
        return True
    return node.get("clickable") == "true"


def _resolve_comment_button_bounds(node) -> Optional[Tuple[Tuple[int, int, int, int], bool]]:
    """Map a label node to the tappable bounds (self or nearest clickable ancestor)."""
    if not _node_has_comment_button_token(node):
        return None
    cur = node
    for _ in range(12):
        if _is_tappable_fb_node(cur):
            bnds = _parse_bounds_from_node(cur)
            if bnds:
                is_btn = "Button" in (cur.get("class") or "")
                return bnds, is_btn
        parent = cur.getparent()
        if parent is None:
            break
        cur = parent
    return None


def build_comment_button_u2_click(node, bounds: Tuple[int, int, int, int]) -> dict[str, Any]:
    """Build U2 click targets from the clickable comment node (bounds-pinned xpath + selector)."""
    bounds_str = (node.get("bounds") or "").strip()
    if not bounds_str:
        bounds_str = f"[{bounds[0]},{bounds[1]}][{bounds[2]},{bounds[3]}]"
    text = _norm_fb_ui(node.get("text") or "")
    desc = _norm_fb_ui(node.get("content-desc") or "")
    rid = (node.get("resource-id") or "").strip()
    cls = (node.get("class") or "").strip()
    xpath = (
        f'//*[@bounds="{bounds_str}" and '
        f'(@clickable="true" or contains(@class, "Button"))]'
    )
    selector: dict[str, Any] = {"clickable": True}
    if text:
        selector["text"] = text
    elif desc:
        selector["description"] = desc
    if rid:
        selector["resourceId"] = rid
    if cls:
        selector["className"] = cls
    return {
        "xpath": xpath,
        "spec": {"xpath": xpath},
        "selector": selector,
        "bounds": list(bounds),
    }


def _resolve_comment_button_click_meta(node) -> Optional[dict[str, Any]]:
    """Resolve tappable comment control metadata for U2 click + bounds fallback."""
    if not _node_has_comment_button_token(node):
        return None
    cur = node
    for _ in range(12):
        if _is_tappable_fb_node(cur):
            bnds = _parse_bounds_from_node(cur)
            if bnds:
                is_btn = "Button" in (cur.get("class") or "")
                return {
                    "bounds": bnds,
                    "is_button": is_btn,
                    "u2_click": build_comment_button_u2_click(cur, bnds),
                }
        parent = cur.getparent()
        if parent is None:
            break
        cur = parent
    return None


def _comment_button_within_post_card(
    btn_bounds: Tuple[int, int, int, int],
    parent_bounds: Optional[Tuple[int, int, int, int]],
) -> bool:
    """Reject bottom-nav / chrome hits that sit below the feed card."""
    if not parent_bounds:
        return True
    x1, y1, x2, y2 = btn_bounds
    px1, py1, px2, py2 = parent_bounds
    if x2 <= px1 or x1 >= px2:
        return False
    if y2 > py2 + 32:
        return False
    if y1 < py1 - 16:
        return False
    return True


def _post_id_from_ctx(ctx: Dict[str, Any], post_id_var: Optional[str]) -> Optional[str]:
    if post_id_var:
        return ctx.get(post_id_var)
    return None


def _extract_comment(
    cluster: List[Dict[str, Any]],
    parent_post_id: Optional[str] = None,
    cluster_min_x: int = 150,
) -> Optional[Dict[str, Any]]:
    from .filters import _comment_line_is_badge, _is_cmt_noise, _is_comment_image_placeholder_text, _looks_like_comment_timestamp_row
    from .post_extractor import _is_hashtag_chip, _refine_comment_author_from_cluster

    author: Optional[str] = None
    badges: List[str] = []
    body_parts: List[str] = []
    timestamp: Optional[str] = None
    likes: Optional[str] = None
    pending_badges: List[str] = []

    def _flush_pending_badges() -> None:
        nonlocal pending_badges
        if pending_badges:
            badges.extend(pending_badges)
            pending_badges = []

    for node in cluster:
        t = node["text"].strip()
        if not t or len(t) <= 1:
            continue
        m = _RE_CMT_LIKE_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            _flush_pending_badges()
            continue
        m = _RE_CMT_REPLY_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            _flush_pending_badges()
            continue
        if _is_cmt_noise(t):
            continue
        m = _RE_CMT_REACTIONS.match(t) or _RE_CMT_REACTIONS_EN.match(t)
        if m:
            likes = m.group(1)
            continue
        if _is_comment_image_placeholder_text(t):
            if not any(p.strip() == "[image]" for p in body_parts):
                body_parts.append("[image]")
            continue
        if author is None and _comment_line_is_badge(t):
            pending_badges.append(t.strip())
            continue
        if author is None and node.get("is_author_hint"):
            if 2 <= len(t) <= 90 and not _comment_line_is_badge(t):
                author = t
                _flush_pending_badges()
                continue
        m_dot = _RE_COMMENT_NAME_DOT_SUFFIX.match(t.strip())
        if author is None and m_dot:
            left, right = m_dot.group(1).strip(), m_dot.group(2).strip()
            if 2 <= len(left) <= 60:
                if _comment_line_is_badge(right):
                    author = left
                    badges.append(right.strip())
                    _flush_pending_badges()
                    continue
                if len(right) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(right):
                    author = left
                    clean_r = _RE_CMT_TS_SHARE.sub("", right).strip()
                    if timestamp is None:
                        timestamp = clean_r if clean_r else right
                    _flush_pending_badges()
                    continue
        if len(t) <= _MAX_TS_ANCHOR_NODE_LEN and _RE_TS.search(t):
            clean = _RE_CMT_TS_SHARE.sub("", t).strip()
            if timestamp is None:
                timestamp = clean if clean else t
            continue
        node_x = int(node["bounds"][0]) if node.get("bounds") else cluster_min_x
        if (
            author is None
            and cluster_min_x >= 200
            and node_x >= 200
            and len(t) >= 4
            and not _comment_line_is_badge(t)
            and not _looks_like_comment_timestamp_row(t)
        ):
            body_parts.append(t)
            continue
        if author is None and 2 <= len(t) <= 80 and "·" not in t and "•" not in t and not _is_hashtag_chip(t):
            author = t
            _flush_pending_badges()
            continue
        if author is not None and _comment_line_is_badge(t):
            badges.append(t.strip())
            continue
        if author and unicodedata.normalize("NFC", t).lower() == unicodedata.normalize("NFC", author).lower():
            continue
        body_parts.append(t)

    if author and pending_badges:
        badges.extend(pending_badges)

    text = " ".join(body_parts).strip()
    author = _refine_comment_author_from_cluster(cluster, author)
    if not author and not text:
        return None

    norm_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    norm_text = unicodedata.normalize("NFC", text.strip().lower())
    norm_parent = unicodedata.normalize("NFC", (parent_post_id or "").strip().lower())
    comment_key = hashlib.sha1(f"{norm_parent}\x00{norm_author}\x00{norm_text}".encode("utf-8")).hexdigest()
    indent_level = 2 if cluster_min_x >= 280 else (1 if cluster_min_x >= 220 else 0)
    out: Dict[str, Any] = {
        "author": author or "",
        "text": text,
        "timestamp": timestamp,
        "likes": likes,
        "parent_post_id": parent_post_id,
        "indent_level": indent_level,
        "comment_key": comment_key,
    }
    if likes:
        out["reactions"] = likes
    if badges:
        seen_b: set[str] = set()
        deduped: List[str] = []
        for b in badges:
            k = unicodedata.normalize("NFC", (b or "").strip()).lower()
            if not k or k in seen_b:
                continue
            seen_b.add(k)
            deduped.append(b.strip())
        out["badges"] = deduped
    return out


def _find_binh_luan_button_in_element(element) -> Optional[Tuple[int, int, int]]:
    from .parser import _parse_bounds

    parent_bounds = _parse_bounds(element)
    best: Optional[Tuple[int, int, int]] = None
    best_y1 = 10**9
    fallback: Optional[Tuple[int, int, int]] = None
    fallback_y1 = 10**9
    for node in element.iter():
        resolved = _resolve_comment_button_bounds(node)
        if not resolved:
            continue
        bnds, is_btn = resolved
        if not _comment_button_within_post_card(bnds, parent_bounds):
            continue
        y1, y2 = bnds[1], bnds[3]
        y_mid = (y1 + y2) // 2
        if is_btn:
            if y1 < best_y1:
                best_y1 = y1
                best = (y1, y2, y_mid)
        elif y1 < fallback_y1:
            fallback_y1 = y1
            fallback = (y1, y2, y_mid)
    return best or fallback


def _legacy_last_binh_luan_anchors(root) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    from .parser import _feed_comment_y_max

    action_btn_y2: Optional[int] = None
    action_btn_y_mid: Optional[int] = None
    best_y1 = 10**9
    for node in root.iter():
        resolved = _resolve_comment_button_bounds(node)
        if not resolved:
            continue
        bnds, _is_btn = resolved
        y1, y2 = bnds[1], bnds[3]
        if y1 < best_y1:
            best_y1 = y1
            action_btn_y2 = y2
            action_btn_y_mid = (y1 + y2) // 2
    cy_max = _feed_comment_y_max(root, action_btn_y_mid)
    return action_btn_y2, action_btn_y_mid, cy_max


def _resolve_comment_sheet_anchors(root) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Vertical band for comment list on full-screen FB comment sheet.

    Uses filter row + composer chrome — not feed action-bar "Bình luận" buttons
    (which would latch onto stats like "23 bình luận" or per-comment controls).
    """
    from .parser import (
        _infer_screen_size,
        _normalize_fb_ui_spacing,
        _parse_bounds,
        _pick_feed_container,
    )

    _, screen_h = _infer_screen_size(root)
    filter_bottom: Optional[int] = None
    composer_top: Optional[int] = None
    post_header_bottom: Optional[int] = None

    for node in root.iter():
        pkg = node.get("package") or ""
        if pkg and pkg != "com.facebook.katana":
            continue
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")
        lowered = f"{text} {desc}".lower()
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        _x1, y1, _x2, y2 = bounds

        if any(
            tok in lowered
            for tok in (
                "viết bình luận",
                "write a public comment",
                "write a comment",
            )
        ):
            composer_top = y1 if composer_top is None else min(composer_top, y1)

        is_sort_row = any(
            tok in lowered
            for tok in (
                "phù hợp nhất",
                "most relevant",
                "tất cả bình luận",
                "all comments",
                "thay đổi bộ lọc",
                "change comment filter",
            )
        )
        if is_sort_row and (
            "bình luận" in lowered
            or "comments" in lowered
            or "bộ lọc" in lowered
            or "phù hợp nhất" in lowered
            or "most relevant" in lowered
        ):
            filter_bottom = y2 if filter_bottom is None else max(filter_bottom, y2)

        if "lựa chọn khác cho bài viết" in lowered or "other options for post" in lowered:
            post_header_bottom = y2 if post_header_bottom is None else max(post_header_bottom, y2)

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    recycler_top: Optional[int] = None
    if containers:
        feed = _pick_feed_container(containers, root)
        fb = _parse_bounds(feed)
        if fb:
            recycler_top = fb[1]

    action_btn_y2 = filter_bottom or post_header_bottom
    if action_btn_y2 is None and recycler_top is not None:
        action_btn_y2 = recycler_top + 48

    comment_y_max = composer_top if composer_top is not None else int(screen_h * 0.92)
    if action_btn_y2 is None:
        return None, None, comment_y_max

    action_btn_y_mid = (action_btn_y2 + comment_y_max) // 2
    return action_btn_y2, action_btn_y_mid, comment_y_max


def _comment_sheet_composer_top(root) -> Optional[int]:
    from .parser import _normalize_fb_ui_spacing, _parse_bounds

    composer_top: Optional[int] = None
    for node in root.iter():
        pkg = node.get("package") or ""
        if pkg and pkg != "com.facebook.katana":
            continue
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")
        lowered = f"{text} {desc}".lower()
        if not any(
            tok in lowered
            for tok in (
                "viết bình luận",
                "write a public comment",
                "write a comment",
            )
        ):
            continue
        bounds = _parse_bounds(node)
        if bounds:
            composer_top = bounds[1] if composer_top is None else min(composer_top, bounds[1])
    return composer_top


def detect_comment_sheet_interrupt_reason(root) -> Optional[str]:
    """Return why we left the comment sheet (keyboard, profile, etc.) for recovery."""
    from .comment_filter import _is_sort_bottom_sheet_open, _looks_like_fb_comment_filter_context
    from .parser import _hierarchy_is_fb_comment_sheet, _normalize_fb_ui_spacing

    if _is_sort_bottom_sheet_open(root):
        return None
    if not _hierarchy_is_fb_comment_sheet(root):
        if _looks_like_fb_comment_filter_context(root):
            return None
        return "left_comment_sheet"

    for node in root.iter():
        pkg = (node.get("package") or "").lower()
        if "inputmethod" in pkg:
            return "keyboard_open"
        if node.get("focused") != "true":
            continue
        cls = (node.get("class") or "").lower()
        blob = f"{_normalize_fb_ui_spacing(node.get('text') or '')} {_normalize_fb_ui_spacing(node.get('content-desc') or '')}".lower()
        if "edittext" in cls or "autocomplete" in cls:
            if any(
                tok in blob
                for tok in (
                    "viết bình luận",
                    "write a comment",
                    "write a public comment",
                )
            ):
                return "keyboard_open"
    return None


def detect_comment_sheet_interrupt_from_xml(xml: str) -> Optional[str]:
    from .parser import _parse_xml

    root = _parse_xml(xml)
    if root is None:
        return None
    return detect_comment_sheet_interrupt_reason(root)


def _hierarchy_looks_like_fb_post_feed(root) -> bool:
    """Scrollable feed with action bars — avatar nodes are normal, not profile overlay."""
    from .shared import XPATH_LIST, XPATH_RECYCLER

    if root is None:
        return False
    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return False
    has_scrollable = any(
        (c.get("scrollable") or "").lower() == "true" for c in containers
    )
    if not has_scrollable:
        return False
    for node in root.iter("node"):
        if _node_has_comment_button_token(node):
            return True
    return False


def is_group_feed_hierarchy(root) -> bool:
    """True when hierarchy looks like FB group/post feed (not comment sheet or profile)."""
    from .parser import _hierarchy_is_fb_comment_sheet, _normalize_fb_ui_spacing

    if _hierarchy_is_fb_comment_sheet(root):
        return False
    if _hierarchy_looks_like_fb_post_feed(root):
        for node in root.iter():
            pkg = node.get("package") or ""
            if pkg and pkg != "com.facebook.katana":
                continue
            text = _normalize_fb_ui_spacing(node.get("text") or "")
            desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")
            lowered = f"{text} {desc}".lower()
            if any(
                tok in lowered
                for tok in (
                    "bạn viết gì",
                    "what's on your mind",
                    "nhóm công khai",
                    "public group",
                    "chia sẻ với: nhóm",
                    "shared with: public group",
                )
            ):
                return True
    for node in root.iter():
        pkg = node.get("package") or ""
        if pkg and pkg != "com.facebook.katana":
            continue
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")
        lowered = f"{text} {desc}".lower()
        if "bạn viết gì" in lowered or "what's on your mind" in lowered:
            return True
        if "nhóm công khai" in lowered or "chia sẻ với: nhóm" in lowered:
            return True
    return False


def is_group_feed_from_xml(xml: str) -> bool:
    from .parser import _parse_xml

    root = _parse_xml(xml)
    if root is None:
        return False
    return is_group_feed_hierarchy(root)


_GROUP_NAV_CONTEXT_KEYS = (
    "collection",
    "scenario_name",
    "SAVE_COLLECTION",
    "content_strategy",
)


def context_implies_fb_group_navigation(context: dict[str, Any] | None) -> bool:
    """True when scenario/collection metadata indicates a FB group crawl."""
    if not context:
        return False
    if context.get("_fb_group_navigation"):
        return True
    if context.get("fb_group_id"):
        return True
    for key in _GROUP_NAV_CONTEXT_KEYS:
        blob = str(context.get(key) or "").lower()
        if not blob:
            continue
        if "fb_group" in blob or blob.startswith("fb_group"):
            return True
        if "group" in blob and ("fb" in blob or "facebook" in blob):
            return True
    return False


def note_fb_group_navigation(
    context: dict[str, Any],
    xml: str | None = None,
) -> bool:
    """Sticky lock: while crawling a FB group, never send system BACK (exits the group)."""
    if context.get("_fb_group_navigation"):
        return True
    if context_implies_fb_group_navigation(context):
        context["_fb_group_navigation"] = True
        return True
    if xml and is_group_feed_from_xml(xml):
        context["_fb_group_navigation"] = True
        return True
    return False


def fb_group_navigation_locked(context: dict[str, Any] | None) -> bool:
    return bool(context and context.get("_fb_group_navigation"))


def should_allow_system_back(
    xml: str | None,
    context: dict[str, Any] | None = None,
) -> bool:
    """Whether a system BACK is safe (dismiss overlay only, not group/comment sheet)."""
    if fb_group_navigation_locked(context):
        return False
    if xml and is_group_feed_from_xml(xml):
        return False
    if not xml:
        return False
    return detect_transient_overlay_from_xml(xml) is not None


def _avatar_desc_is_profile_overlay_context(root) -> bool:
    """Avatars on feed cards and comment threads are not full-screen profile viewer."""
    from .parser import _hierarchy_is_fb_comment_sheet
    from .post_open_pipeline import _hierarchy_has_post_detail_chrome

    if _hierarchy_looks_like_fb_post_feed(root):
        return False
    if is_group_feed_hierarchy(root):
        return False
    if _hierarchy_is_fb_comment_sheet(root):
        return False
    if _hierarchy_has_post_detail_chrome(root):
        return False
    return True


def detect_transient_overlay_reason(root) -> Optional[str]:
    """Profile viewer, photo viewer, share sheet — safe to dismiss with BACK."""
    from .parser import _normalize_fb_ui_spacing, _parse_bounds

    allow_avatar_overlay = _avatar_desc_is_profile_overlay_context(root)

    for node in root.iter():
        pkg = (node.get("package") or "").lower()
        if pkg and pkg != "com.facebook.katana":
            continue
        text = _normalize_fb_ui_spacing(node.get("text") or "")
        desc = _normalize_fb_ui_spacing(node.get("content-desc") or "")
        lowered = f"{text} {desc}".lower()
        if any(
            tok in lowered
            for tok in (
                "trang cá nhân",
                "xem trang cá nhân",
                "view profile",
            )
        ):
            return "profile_overlay"
        # Feed/comment avatars expose "Ảnh đại diện của …" — not a profile viewer overlay.
        if allow_avatar_overlay and any(
            tok in lowered
            for tok in (
                "profile picture",
                "ảnh đại diện của",
            )
        ):
            return "profile_overlay"
        if any(
            tok in lowered
            for tok in (
                "photo viewer",
                "xem ảnh",
                "view photo",
                "full screen",
            )
        ):
            bounds = _parse_bounds(node)
            if bounds and (bounds[2] - bounds[0]) >= 800:
                return "photo_viewer"
    return None


def detect_transient_overlay_from_xml(xml: str) -> Optional[str]:
    from .parser import _parse_xml

    root = _parse_xml(xml)
    if root is None:
        return None
    return detect_transient_overlay_reason(root)


def should_press_back_after_failed_tap(
    xml: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """Only BACK when we opened a dismissible overlay — never during group crawls."""
    if fb_group_navigation_locked(context):
        return False
    if not xml:
        return False
    if is_group_feed_from_xml(xml):
        return False
    return detect_transient_overlay_from_xml(xml) is not None


def comment_tap_point(
    bounds: Tuple[int, int, int, int],
    *,
    screen_w: int = 1080,
) -> Tuple[int, int]:
    """Tap the action-bar Comment control — bias right to miss avatar/name column."""
    x1, y1, x2, y2 = bounds
    width = max(1, x2 - x1)
    min_x = int(screen_w * 0.28)
    preferred = x1 + int(width * 0.72)
    cx = max(x1 + 4, min(x2 - 4, preferred))
    if cx < min_x and x2 > min_x:
        cx = min(x2 - 4, max(x1 + 4, min_x))
    cy = (y1 + y2) // 2
    return cx, cy


def interrupt_reason_allows_back(
    reason: Optional[str],
    context: dict[str, Any] | None = None,
) -> bool:
    """Dismiss IME with BACK only outside FB group navigation (BACK pops the whole group)."""
    if fb_group_navigation_locked(context):
        return False
    return reason == "keyboard_open"


FB_COMMENT_SHEET_WAIT_SELECTORS: tuple[dict[str, str], ...] = (
    {"descriptionContains": "Viết bình luận"},
    {"descriptionContains": "Write a comment"},
    {"descriptionContains": "Write a public comment"},
    {"textContains": "Viết bình luận"},
    {"textContains": "Phù hợp nhất"},
    {"textContains": "Most relevant"},
    {"textContains": "Tất cả bình luận"},
    {"textContains": "All comments"},
)


def _resolve_comment_region_anchors(root, row_match_pid: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    from .feed_pipeline import _is_ad_container
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_post,
        _resource_id_media_hint,
        _structural_post_type_hint,
    )
    from .parser import _collect_text_nodes, _hierarchy_is_fb_comment_sheet, _parse_bounds, _pick_feed_container

    if _hierarchy_is_fb_comment_sheet(root):
        sheet = _resolve_comment_sheet_anchors(root)
        if sheet[0] is not None:
            return sheet
        return _legacy_last_binh_luan_anchors(root)

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return _legacy_last_binh_luan_anchors(root)

    feed = _pick_feed_container(containers, root)
    children = feed.findall("node")
    if not children:
        return _legacy_last_binh_luan_anchors(root)

    rows: List[Tuple[int, Optional[Dict[str, Any]], Optional[Tuple[int, int, int]], Optional[int]]] = []
    for feed_item_index, candidate in enumerate(children):
        if _is_ad_container(candidate):
            continue
        cb = _parse_bounds(candidate)
        y_top = cb[1] if cb else 10**9
        card_bottom = cb[3] if cb else None
        btn = _find_binh_luan_button_in_element(candidate)
        post: Optional[Dict[str, Any]] = None
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        if nodes:
            fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
            post = _extract_post(
                nodes,
                0,
                structural_type_hint=_structural_post_type_hint(candidate),
                resource_id_media_hint=_resource_id_media_hint(candidate),
                fb_post_id=fb_pid,
                fb_group_id=fb_gid,
                permalink_candidates=perms,
                feed_item_index=feed_item_index,
            )
        rows.append((y_top, post, btn, card_bottom))

    if row_match_pid:
        pid_matches = [
            (yt, post, btn, cbot)
            for yt, post, btn, cbot in rows
            if post and post.get("_pid") == row_match_pid and btn
        ]
        if pid_matches:
            pid_matches.sort(key=lambda r: (r[0], r[2][0] if r[2] else 0))
            _yt, _post, btn, cbot = pid_matches[0]
            _y1, y2, y_mid = btn
            return y2, y_mid, cbot
        # Scoped post not on screen — do not latch onto another card's action bar.
        return None, None, None

    with_btn = [(yt, post, btn, cbot) for yt, post, btn, cbot in rows if btn]
    if with_btn:
        with_btn.sort(key=lambda r: (r[0], r[2][0] if r[2] else 0))
        _yt, _post, btn, cbot = with_btn[0]
        _y1, y2, y_mid = btn
        return y2, y_mid, cbot

    return _legacy_last_binh_luan_anchors(root)


def _find_comment_button_click_target_in_element(element) -> Optional[dict[str, Any]]:
    from .parser import _parse_bounds

    parent_bounds = _parse_bounds(element)
    best: Optional[tuple[int, dict[str, Any]]] = None
    fallback: Optional[tuple[int, dict[str, Any]]] = None
    for node in element.iter():
        meta = _resolve_comment_button_click_meta(node)
        if not meta:
            continue
        bnds = meta["bounds"]
        if not _comment_button_within_post_card(bnds, parent_bounds):
            continue
        y1 = bnds[1]
        if meta.get("is_button"):
            if best is None or y1 < best[0]:
                best = (y1, meta)
        elif fallback is None or y1 < fallback[0]:
            fallback = (y1, meta)
    chosen = best or fallback
    return chosen[1] if chosen else None


def _find_binh_luan_button_bounds_in_element(element) -> Optional[Tuple[int, int, int, int]]:
    hit = _find_comment_button_click_target_in_element(element)
    return hit["bounds"] if hit else None


def resolve_topmost_comment_target_from_xml(
    xml: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, int, int, int]]]:
    from .feed_pipeline import _is_ad_container
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_post,
        _resource_id_media_hint,
        _structural_post_type_hint,
    )
    from .parser import _collect_text_nodes, _parse_xml, _pick_feed_container

    root = _parse_xml(xml)
    if root is None:
        return None, None

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    feed_children = []
    if containers:
        feed = _pick_feed_container(containers, root)
        feed_children = feed.findall("node")

    scan_candidates: List[Tuple[int, Any]] = (
        [(i, c) for i, c in enumerate(feed_children) if not _is_ad_container(c)]
        if feed_children
        else [(0, root)]
    )

    best: Optional[Tuple[int, Dict[str, Any], Tuple[int, int, int, int]]] = None
    for feed_item_index, candidate in scan_candidates:
        btn = _find_binh_luan_button_bounds_in_element(candidate)
        if not btn:
            continue
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        if not nodes:
            continue
        fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
        post = _extract_post(
            nodes,
            0,
            structural_type_hint=_structural_post_type_hint(candidate),
            resource_id_media_hint=_resource_id_media_hint(candidate),
            fb_post_id=fb_pid,
            fb_group_id=fb_gid,
            permalink_candidates=perms,
            feed_item_index=feed_item_index,
        )
        if not post or not post.get("_pid"):
            continue
        y_top = btn[1]
        if best is None or y_top < best[0]:
            best = (y_top, post, btn)

    if best is None:
        return None, None
    _yt, post, btn = best
    return post, btn


def _build_comment_candidate(
    candidate,
    *,
    feed_item_index: int,
) -> Optional[Dict[str, Any]]:
    """Materialise a comment-target candidate from a feed card element.

    Returns ``None`` when the card has no usable Comment button or no post
    fingerprint. The returned dict carries enough metadata for downstream
    scoring, tie-breaking and anchor locking (see ``_score_comment_candidate``
    and ``resolve_comment_targets_from_xml``).
    """
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_post,
        _resource_id_media_hint,
        _structural_post_type_hint,
    )
    from .parser import _collect_text_nodes, _parse_bounds

    btn = _find_comment_button_click_target_in_element(candidate)
    if not btn:
        return None
    comment_bounds = btn["bounds"]
    parent_bounds = _parse_bounds(candidate)
    if not _comment_button_within_post_card(comment_bounds, parent_bounds):
        return None
    nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
    if not nodes:
        return None
    fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
    post = _extract_post(
        nodes,
        0,
        structural_type_hint=_structural_post_type_hint(candidate),
        resource_id_media_hint=_resource_id_media_hint(candidate),
        fb_post_id=fb_pid,
        fb_group_id=fb_gid,
        permalink_candidates=perms,
        feed_item_index=feed_item_index,
    )
    if not post or not post.get("_pid"):
        return None
    return {
        "comment_bounds": comment_bounds,
        "comment_u2_click": btn.get("u2_click"),
        "parent_post_bounds": parent_bounds,
        "post": post,
        "feed_item_index": feed_item_index,
    }


def _comment_candidate_passes_filter(
    cand: Dict[str, Any],
    *,
    screen_h: int,
    band_low: float = 0.12,
    band_high: float = 0.97,
) -> bool:
    """Reject buttons in status-bar / bottom-nav chrome; allow low action bars."""
    x1, y1, x2, y2 = cand["comment_bounds"]
    if x2 <= x1 or y2 <= y1:
        return False
    if screen_h <= 0:
        return True
    top_limit = int(screen_h * band_low)
    bottom_limit = int(screen_h * band_high)
    nav_strip = max(56, int(screen_h * 0.022))
    if y1 < top_limit:
        return False
    if y1 > bottom_limit:
        return False
    if y1 >= screen_h - nav_strip:
        return False
    return True


def diagnose_comment_target_resolution(
    xml: str,
    *,
    band_low: float = 0.12,
    band_high: float = 0.97,
) -> Dict[str, Any]:
    """Explain why ``resolve_comment_targets_from_xml`` found no candidates."""
    from .feed_pipeline import _is_ad_container
    from .parser import _infer_screen_size, _parse_xml, _pick_feed_container

    root = _parse_xml(xml)
    if root is None:
        return {"reason_code": "xml_parse_error"}

    screen_w, screen_h = _infer_screen_size(root)
    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    feed_children: List[Any] = []
    if containers:
        feed = _pick_feed_container(containers, root)
        feed_children = feed.findall("node")

    token_nodes = 0
    for node in root.iter():
        if _node_has_comment_button_token(node):
            token_nodes += 1

    buttons_in_cards = 0
    missing_post_pid = 0
    filtered_by_band = 0
    for feed_item_index, element in enumerate(feed_children):
        if _is_ad_container(element):
            continue
        btn = _find_comment_button_click_target_in_element(element)
        if not btn:
            continue
        buttons_in_cards += 1
        cand = _build_comment_candidate(element, feed_item_index=feed_item_index)
        if cand is None:
            missing_post_pid += 1
            continue
        if not _comment_candidate_passes_filter(
            cand, screen_h=screen_h, band_low=band_low, band_high=band_high
        ):
            filtered_by_band += 1

    return {
        "reason_code": "diagnostic",
        "screen_size": [screen_w, screen_h],
        "feed_children": len(feed_children),
        "comment_token_nodes": token_nodes,
        "buttons_in_cards": buttons_in_cards,
        "missing_post_pid": missing_post_pid,
        "filtered_by_band": filtered_by_band,
        "band": [band_low, band_high],
    }


def _score_comment_candidate(
    cand: Dict[str, Any],
    *,
    screen_h: int,
    screen_w: int = 1080,
    center_y_ratio: float,
) -> Dict[str, Any]:
    """Score a candidate using the center-of-card heuristic + penalties.

    Lower score wins. The breakdown is preserved for diagnostics so we can audit
    why a particular candidate was preferred in production traces.
    """
    x1, y1, x2, y2 = cand["comment_bounds"]
    comment_y_mid = (y1 + y2) // 2
    parent_bounds = cand.get("parent_post_bounds")
    if parent_bounds:
        focus_y = (parent_bounds[1] + parent_bounds[3]) // 2
    else:
        focus_y = comment_y_mid
    safe_h = max(1, screen_h)
    target_y = int(safe_h * center_y_ratio)

    distance = abs(focus_y - target_y) / safe_h

    cut_penalty = 0.0
    visible_ratio = 1.0
    if parent_bounds:
        py1, py2 = parent_bounds[1], parent_bounds[3]
        total_h = max(1, py2 - py1)
        cut_top = max(0, -py1)
        cut_bottom = max(0, py2 - safe_h)
        visible_ratio = max(0.0, (total_h - cut_top - cut_bottom) / total_h)
        cut_penalty = (1.0 - visible_ratio) * 0.6

    post = cand.get("post") or {}
    has_strong_key = bool(
        post.get("post_key") or post.get("stable_post_id") or post.get("fb_post_id")
    )
    has_timestamp = bool(post.get("timestamp"))
    metadata_missing_penalty = 0.0
    if not has_strong_key:
        metadata_missing_penalty += 0.30
    if not has_timestamp:
        metadata_missing_penalty += 0.10

    bottom_risk_penalty = 0.0
    if y2 >= int(safe_h * 0.88):
        bottom_risk_penalty = 0.25
    elif y2 >= int(safe_h * 0.82):
        bottom_risk_penalty = 0.10

    x_mid = (x1 + x2) // 2
    left_column_penalty = 0.35 if x_mid < int(max(1, screen_w) * 0.22) else 0.0

    score = (
        distance
        + cut_penalty
        + metadata_missing_penalty
        + bottom_risk_penalty
        + left_column_penalty
    )
    return {
        "score": round(score, 4),
        "breakdown": {
            "distance": round(distance, 4),
            "cut_penalty": round(cut_penalty, 4),
            "metadata_missing_penalty": round(metadata_missing_penalty, 4),
            "bottom_risk_penalty": round(bottom_risk_penalty, 4),
            "left_column_penalty": round(left_column_penalty, 4),
            "visible_ratio": round(visible_ratio, 4),
            "focus_y": focus_y,
            "comment_y_mid": comment_y_mid,
            "comment_x_mid": x_mid,
            "has_strong_key": has_strong_key,
            "has_timestamp": has_timestamp,
        },
    }


def resolve_comment_targets_from_xml(
    xml: str,
    *,
    center_y_ratio: float = 0.5,
    max_candidates: int = 5,
    band_low: float = 0.12,
    band_high: float = 0.97,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Rank visible FB Comment buttons per the post-comment linking spec.

    The picker enforces three guarantees demanded by the upstream design:

    1. Filtering — drop buttons outside the ``[band_low, band_high]`` vertical
       band so we never click into the chrome (status bar, composer, nav).
    2. Scoring — prefer the card whose body (or button if the body is unknown)
       sits closest to mid-screen, with penalties for offscreen cuts, weak
       fingerprints and bottom-of-screen taps.
    3. Tie-breaks — always prefer candidates with a strong stable identifier so
       the locked anchor downstream survives feed reordering.

    Returns ``(top, ranked)`` where ``top`` is the winning candidate dict (or
    ``None`` when no card qualifies) and ``ranked`` is the top
    ``max_candidates`` candidates sorted best-first. Each candidate carries the
    raw ``post`` dict, ``comment_bounds``, ``parent_post_bounds``, ``score`` and
    ``breakdown`` — callers should treat these as opaque metadata for the agent
    boot side to convert into a target payload.
    """
    from .feed_pipeline import _is_ad_container
    from .parser import _infer_screen_size, _parse_xml, _pick_feed_container

    root = _parse_xml(xml)
    if root is None:
        return None, []

    screen_w, screen_h = _infer_screen_size(root)
    if screen_h <= 0:
        screen_h = 2200
    if screen_w <= 0:
        screen_w = 1080
    center_y_ratio = max(band_low, min(band_high, float(center_y_ratio)))

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    feed_children: List[Any] = []
    if containers:
        feed = _pick_feed_container(containers, root)
        feed_children = feed.findall("node")

    scan_candidates: List[Tuple[int, Any]] = (
        [(i, c) for i, c in enumerate(feed_children) if not _is_ad_container(c)]
        if feed_children
        else [(0, root)]
    )

    scored: List[Dict[str, Any]] = []
    for feed_item_index, element in scan_candidates:
        cand = _build_comment_candidate(element, feed_item_index=feed_item_index)
        if cand is None:
            continue
        if not _comment_candidate_passes_filter(
            cand, screen_h=screen_h, band_low=band_low, band_high=band_high
        ):
            continue
        cand.update(
            _score_comment_candidate(
                cand,
                screen_h=screen_h,
                screen_w=screen_w,
                center_y_ratio=center_y_ratio,
            )
        )
        scored.append(cand)

    if not scored and band_high < 0.99:
        for feed_item_index, element in scan_candidates:
            cand = _build_comment_candidate(element, feed_item_index=feed_item_index)
            if cand is None:
                continue
            if not _comment_candidate_passes_filter(
                cand, screen_h=screen_h, band_low=0.08, band_high=0.99
            ):
                continue
            cand.update(
                _score_comment_candidate(
                    cand,
                    screen_h=screen_h,
                    screen_w=screen_w,
                    center_y_ratio=center_y_ratio,
                )
            )
            scored.append(cand)

    if not scored:
        return None, []

    def _tie_key(c: Dict[str, Any]) -> Tuple[float, int, int, float, float, int]:
        post = c.get("post") or {}
        has_strong = bool(
            post.get("post_key") or post.get("stable_post_id") or post.get("fb_post_id")
        )
        has_parent_box = c.get("parent_post_bounds") is not None
        breakdown = c.get("breakdown") or {}
        visible = float(breakdown.get("visible_ratio", 0.0))
        distance = float(breakdown.get("distance", 1.0))
        y1 = int(c["comment_bounds"][1])
        return (
            float(c.get("score", 0.0)),
            0 if has_strong else 1,
            0 if has_parent_box else 1,
            -visible,
            distance,
            y1,
        )

    scored.sort(key=_tie_key)
    ranked = scored[: max(1, int(max_candidates))]
    return ranked[0], ranked


def resolve_center_comment_target_from_xml(
    xml: str,
    *,
    center_y_ratio: float = 0.5,
) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[int, int, int, int]]]:
    """Back-compat wrapper returning ``(post, bounds)`` of the top candidate.

    Existing callers that only need the legacy two-tuple shape (e.g. older
    tests) can keep using this helper; new code should call
    :func:`resolve_comment_targets_from_xml` directly so it can also reason
    about alternates for the after-tap verify retry loop.
    """
    top, _ = resolve_comment_targets_from_xml(xml, center_y_ratio=center_y_ratio)
    if not top:
        return None, None
    return top["post"], top["comment_bounds"]


def _feed_inline_band_top(root) -> Optional[int]:
    """Top Y for inline comments on post detail (may sit above the action bar)."""
    from .constants import _RE_CMT_LIKE_BTN
    from .parser import _normalize_fb_ui_spacing, _parse_bounds

    tops: List[int] = []
    for node in root.iter():
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        for attr in ("text", "content-desc"):
            raw = _normalize_fb_ui_spacing(node.get(attr) or "")
            if _RE_CMT_LIKE_BTN.match(raw):
                tops.append(bounds[1])
    if not tops:
        return None
    return max(0, min(tops) - 250)


def _feed_post_pid_for_comment_scope(
    root,
    requested_pid: Optional[str],
) -> Optional[str]:
    """PID of the feed card whose comment band we parse (visible on screen)."""
    from .feed_pipeline import _is_ad_container
    from .post_extractor import (
        _extract_fb_link_meta,
        _extract_post,
        _resource_id_media_hint,
        _structural_post_type_hint,
    )
    from .parser import _collect_text_nodes, _parse_bounds, _pick_feed_container

    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return None

    feed = _pick_feed_container(containers, root)
    children = feed.findall("node")
    if not children:
        return None

    rows: List[Tuple[int, Optional[Dict[str, Any]], Optional[Tuple[int, int, int]]]] = []
    for feed_item_index, candidate in enumerate(children):
        if _is_ad_container(candidate):
            continue
        cb = _parse_bounds(candidate)
        y_top = cb[1] if cb else 10**9
        btn = _find_binh_luan_button_in_element(candidate)
        post: Optional[Dict[str, Any]] = None
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        if nodes:
            fb_pid, fb_gid, perms = _extract_fb_link_meta(candidate)
            post = _extract_post(
                nodes,
                0,
                structural_type_hint=_structural_post_type_hint(candidate),
                resource_id_media_hint=_resource_id_media_hint(candidate),
                fb_post_id=fb_pid,
                fb_group_id=fb_gid,
                permalink_candidates=perms,
                feed_item_index=feed_item_index,
            )
        rows.append((y_top, post, btn))

    if requested_pid:
        pid_matches = [
            (yt, post, btn)
            for yt, post, btn in rows
            if post and post.get("_pid") == requested_pid and btn
        ]
        if pid_matches:
            return requested_pid

    with_btn = [(yt, post, btn) for yt, post, btn in rows if btn and post and post.get("_pid")]
    if not with_btn:
        return None
    with_btn.sort(key=lambda r: (r[0], r[2][0] if r[2] else 0))
    return str(with_btn[0][1]["_pid"])


def _has_feed_inline_comment_markers(root, y_min: int) -> bool:
    """True when feed post detail shows inline comments below the action bar."""
    from .constants import _RE_CMT_LIKE_BTN, _RE_CMT_REPLY_BTN
    from .parser import _normalize_fb_ui_spacing, _parse_bounds

    for node in root.iter():
        bounds = _parse_bounds(node)
        if bounds and bounds[1] < y_min:
            continue
        for attr in ("text", "content-desc"):
            raw = _normalize_fb_ui_spacing(node.get(attr) or "")
            if _RE_CMT_LIKE_BTN.match(raw) or _RE_CMT_REPLY_BTN.match(raw):
                return True
        desc = node.get("content-desc") or ""
        if "Ảnh đại diện của" in desc and bounds and bounds[0] <= 220:
            return True
    return False


def parse_fb_comments_from_xml_with_diagnostic(
    xml: str,
    parent_post_id: Optional[str] = None,
    max_items: int = 50,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    from .clustering import _cluster_into_comments, _coalesce_comment_clusters
    from .filters import (
        _is_comment_row_parse_noise,
        _is_duplicate_short_author_footer_row,
        _is_comment_reaction_count_row,
        _is_compact_comment_action_label,
        _is_comment_left_avatar_name_strip,
        _is_junk_parsed_comment_row,
    )
    from .parser import (
        _collect_text_nodes,
        _hierarchy_is_fb_comment_sheet,
        _infer_screen_size,
        _parse_xml,
        _scan_special_screen,
    )
    from .post_extractor import _compute_post_id_from_nodes
    from .feed_pipeline import _extract_header_stats

    t0 = time.monotonic()

    def _diag(reason: str, **extra) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "reason_code": reason,
            "posts_returned": 0,
            "comments_returned": 0,
            "anchor_button_found": False,
            "nodes_in_band": 0,
            "candidate_clusters": 0,
            "locale_tokens_hit": [],
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
        }
        base.update(extra)
        return base

    root = _parse_xml(xml)
    if root is None:
        return [], _diag("xml_parse_error")

    special = _scan_special_screen(root)
    if special:
        return [], _diag(special)

    is_comment_sheet = _hierarchy_is_fb_comment_sheet(root)
    feed_inline = False
    if not is_comment_sheet:
        probe_scope = _feed_post_pid_for_comment_scope(root, parent_post_id) or parent_post_id
        probe_y2, _, _ = _resolve_comment_region_anchors(root, probe_scope)
        if probe_y2 is not None and _has_feed_inline_comment_markers(root, probe_y2):
            feed_inline = True
        else:
            return [], _diag(
                "not_comment_sheet",
                anchor_button_found=probe_y2 is not None,
                nodes_in_band=0,
            )

    all_nodes = _collect_text_nodes(root, toolbar_cutoff_y=200)
    if not all_nodes:
        return [], _diag("no_text_nodes")

    requested_pid = parent_post_id
    if is_comment_sheet:
        parent_post_id = _compute_post_id_from_nodes(all_nodes) or parent_post_id
    else:
        visible_pid = _feed_post_pid_for_comment_scope(root, requested_pid)
        if visible_pid:
            parent_post_id = visible_pid
        elif requested_pid:
            return [], _diag(
                "parent_post_not_visible",
                anchor_button_found=False,
                nodes_in_band=0,
                requested_parent_post_id=requested_pid,
            )
        elif parent_post_id is None:
            parent_post_id = _compute_post_id_from_nodes(all_nodes)

    row_match_pid = parent_post_id
    action_btn_y2, _action_btn_y_mid, comment_y_max = _resolve_comment_region_anchors(root, row_match_pid)
    # Only widen the vertical band when no tapped/scoped post — otherwise we pull
    # highlighted parent-thread comments from above the target card (wrong post).
    if feed_inline and requested_pid is None:
        band_top = _feed_inline_band_top(root)
        if band_top is not None and (action_btn_y2 is None or band_top < action_btn_y2):
            action_btn_y2 = band_top
    anchor_found = action_btn_y2 is not None
    screen_w, screen_h = _infer_screen_size(root)
    comment_x_max = max(380, int(screen_w * 0.76))

    def _include_comment_text_node(n: Dict[str, Any]) -> bool:
        x0 = int(n["bounds"][0])
        text = (n.get("text") or "").strip()
        if x0 >= 96:
            return True
        if _is_comment_left_avatar_name_strip(n):
            return True
        # FB group sheet: body often sits at x≈56–95, not only avatar strip.
        return len(text) >= 4 and x0 >= 48

    def _in_comment_vertical_band(n: Dict[str, Any]) -> bool:
        x0 = n["bounds"][0]
        if x0 >= comment_x_max:
            if x0 < screen_w - 24 and _is_comment_reaction_count_row(n["text"]):
                pass
            else:
                return False
        if action_btn_y2 is not None and n["cy"] <= action_btn_y2:
            return False
        if comment_y_max is not None and n["bounds"][1] >= comment_y_max:
            return False
        return True

    comment_nodes: List[Dict[str, Any]] = []
    for n in all_nodes:
        if not _in_comment_vertical_band(n):
            continue
        if _is_compact_comment_action_label(n["text"], list(n["bounds"])):
            continue
        # Feed preview: skip duplicate author hints in the avatar column. On the full
        # comment sheet (Vivo etc.) names sit at x≈196 as content-desc ViewGroups.
        if n.get("is_author_hint") and not _is_comment_left_avatar_name_strip(n):
            if int(n["bounds"][0]) < 96:
                continue
        if _include_comment_text_node(n):
            comment_nodes.append(n)

    if not comment_nodes:
        reason = "anchor_not_found" if not anchor_found else "no_nodes_in_band"
        return [], _diag(
            reason,
            anchor_button_found=anchor_found,
            nodes_in_band=0,
            screen_size=[screen_w, screen_h],
        )

    # Top-edge sort keeps author → meta → body order (cy sort mis-orders rows on Vivo sheet).
    comment_nodes.sort(key=lambda n: (n["bounds"][1], n["bounds"][0]))

    clusters = _coalesce_comment_clusters(_cluster_into_comments(comment_nodes))
    result: List[Dict[str, Any]] = []
    last_kept_body: Optional[Dict[str, Any]] = None
    for cluster in clusters:
        if len(result) >= max_items:
            break
        cluster_min_x = min((n["bounds"][0] for n in cluster if n["bounds"]), default=150)
        comment = _extract_comment(cluster, parent_post_id, cluster_min_x=cluster_min_x)
        if not comment or _is_comment_row_parse_noise(comment) or _is_junk_parsed_comment_row(comment):
            continue
        if _is_duplicate_short_author_footer_row(comment, last_kept_body):
            continue
        result.append(comment)
        last_kept_body = comment

    header_stats = _extract_header_stats(root, y_max=action_btn_y2)
    if header_stats:
        result.insert(0, header_stats)

    _pr = header_stats.get("reactions") if header_stats else None
    _ps = header_stats.get("shares") if header_stats else None
    _pc = header_stats.get("comments") if header_stats else None
    if _pr is not None or _ps is not None or _pc is not None:
        for c in result:
            if c.get("_type") == "post_stats":
                continue
            if _pr is not None:
                c["post_reactions"] = _pr
            if _ps is not None:
                c["post_shares"] = _ps
            if _pc is not None:
                c["post_comments"] = _pc

    if not result:
        return [], _diag(
            "empty_cluster",
            anchor_button_found=anchor_found,
            nodes_in_band=len(comment_nodes),
            candidate_clusters=len(clusters),
            screen_size=[screen_w, screen_h],
        )

    return result, {
        "reason_code": "ok",
        "comments_returned": len([c for c in result if c.get("_type") != "post_stats"]),
        "anchor_button_found": anchor_found,
        "nodes_in_band": len(comment_nodes),
        "candidate_clusters": len(clusters),
        "screen_size": [screen_w, screen_h],
        "locale_tokens_hit": [],
        "has_header_stats": bool(header_stats),
        "parse_mode": "feed_inline" if feed_inline else "comment_sheet",
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
    }


def parse_fb_comments_from_xml(
    xml: str,
    parent_post_id: Optional[str] = None,
    max_items: int = 50,
) -> List[Dict[str, Any]]:
    rows, _ = parse_fb_comments_from_xml_with_diagnostic(xml, parent_post_id, max_items)
    return rows


def resolve_comment_scroll_swipe_from_xml(
    xml: str,
    *,
    distance_ratio: float = 0.22,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Swipe inside the main scrollable comment list (RecyclerView), not screen-fixed
    coords that can land on clickable rows.
    Returns (fx, fy, tx, ty) finger-up swipe to reveal more comments below.
    """
    from .parser import (
        _hierarchy_is_fb_comment_sheet,
        _parse_bounds,
        _parse_xml,
        _pick_feed_container,
    )
    from .shared import XPATH_LIST, XPATH_RECYCLER

    root = _parse_xml(xml)
    if root is None:
        return None
    containers = root.xpath(XPATH_RECYCLER) or root.xpath(XPATH_LIST)
    if not containers:
        return None
    if _hierarchy_is_fb_comment_sheet(root):
        feed = None
        best_area = 0
        for el in containers:
            b = _parse_bounds(el)
            if not b:
                continue
            area = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
            if (el.get("scrollable") or "").lower() == "true":
                area = int(area * 1.15)
            if area > best_area:
                best_area = area
                feed = el
        if feed is None:
            feed = _pick_feed_container(containers, root)
    else:
        feed = _pick_feed_container(containers, root)
    bounds = _parse_bounds(feed)
    if not bounds:
        return None
    x1, y1, x2, y2 = bounds
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    if height < 80:
        return None

    on_sheet = _hierarchy_is_fb_comment_sheet(root)
    # Swipe in the right-side body gutter; left/avatar and center text columns can
    # open profiles or focus the composer when Android classifies a weak gesture as a tap.
    safe_x = x1 + int(width * (0.76 if on_sheet else 0.62))
    pad_y = max(8, int(height * 0.06))
    inner_top = y1 + pad_y
    inner_bottom = y2 - pad_y
    if on_sheet:
        inner_top = max(inner_top, y1 + int(height * 0.14))
        composer_top = _comment_sheet_composer_top(root)
        if composer_top is not None:
            inner_bottom = min(inner_bottom, composer_top - 64)
    inner_h = max(1, inner_bottom - inner_top)
    if inner_h < 48:
        return None
    ratio = max(0.26 if on_sheet else 0.18, min(0.75, float(distance_ratio)))
    fy = inner_top + int(inner_h * 0.70)
    ty = inner_top + int(inner_h * max(0.15, 0.70 - ratio))
    min_travel = min(int(inner_h * 0.55), max(160, int(inner_h * 0.24)))
    if fy - ty < min_travel:
        ty = max(inner_top, fy - min_travel)
    if ty >= fy:
        ty = max(inner_top, fy - max(48, int(inner_h * ratio)))
    return safe_x, fy, safe_x, ty


__all__ = [
    "_find_binh_luan_button_in_element",
    "_legacy_last_binh_luan_anchors",
    "_resolve_comment_sheet_anchors",
    "_resolve_comment_region_anchors",
    "_find_binh_luan_button_bounds_in_element",
    "resolve_topmost_comment_target_from_xml",
    "resolve_center_comment_target_from_xml",
    "resolve_comment_targets_from_xml",
    "_build_comment_candidate",
    "_comment_candidate_passes_filter",
    "_score_comment_candidate",
    "parse_fb_comments_from_xml_with_diagnostic",
    "parse_fb_comments_from_xml",
    "resolve_comment_scroll_swipe_from_xml",
    "detect_comment_sheet_interrupt_from_xml",
    "detect_comment_sheet_interrupt_reason",
    "is_group_feed_hierarchy",
    "is_group_feed_from_xml",
    "context_implies_fb_group_navigation",
    "note_fb_group_navigation",
    "fb_group_navigation_locked",
    "should_allow_system_back",
    "detect_transient_overlay_reason",
    "detect_transient_overlay_from_xml",
    "should_press_back_after_failed_tap",
    "comment_tap_point",
    "build_comment_button_u2_click",
    "_find_comment_button_click_target_in_element",
    "diagnose_comment_target_resolution",
    "FB_COMMENT_SHEET_WAIT_SELECTORS",
    "interrupt_reason_allows_back",
    "_post_id_from_ctx",
]
