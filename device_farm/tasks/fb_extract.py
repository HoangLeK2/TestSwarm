"""
fb_extract.py — Facebook post parsing utilities.

Extracted from fb_group_crawl.py; contains only the XML parsing / extraction
helpers used by scenario_task.py (extract step, fb_posts strategy).
No crawl job / DB / network code here.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree as _lxml

log = logging.getLogger(__name__)

# ── Timestamp regex (Vietnamese + English) ────────────────────────────────────

_RE_TS = re.compile(
    r"(\d+\s*(giây|phút|giờ|ngày|tuần|tháng|năm)\s*(trước)?)"
    r"|(\d+\s*(second|minute|hour|day|week|month|year)s?\s*ago)"
    r"|(hôm qua|yesterday|just now|vừa xong|bây giờ|now)"
    r"|(T\d,\s*\d{1,2}/\d{1,2}/\d{4})"
    r"|(\d{1,2}/\d{1,2}/\d{4})"
    r"|(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

_RE_REEL_TYPE = re.compile(r"\breels?\b", re.IGNORECASE)
_RE_VIDEO_TYPE = re.compile(
    r"\b(video|clip|thước phim|watch video|xem video)\b", re.IGNORECASE
)
_RE_IMAGE_TYPE = re.compile(
    r"^(ảnh|photo|hình|image|picture)\b", re.IGNORECASE
)
_RE_LINK_TYPE = re.compile(
    r"(https?://\S{6,}|www\.[^\s]{4,}|\.\bcom\b|\.\bvn\b|\.\bnet\b|visit site|xem trang|đọc thêm)",
    re.IGNORECASE,
)

_RE_REACTIONS = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s*(lượt thích|reactions?|likes?)?$", re.IGNORECASE
)
_RE_COMMENTS = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s*(bình luận|comments?|phản hồi)$", re.IGNORECASE
)
_RE_SHARES = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s*(lượt chia sẻ|shares?)$", re.IGNORECASE
)

_NOISE_TEXTS = frozenset({
    "·", "•", "·",
    "like", "thích", "comment", "bình luận", "share", "chia sẻ",
    "follow", "theo dõi", "send", "gửi",
    "see more", "xem thêm", "see less", "thu gọn",
    "view post", "xem bài viết",
    "reply", "trả lời",
    "most relevant", "phù hợp nhất",
})

_NOISE_PREFIXES = (
    "lựa chọn khác cho bài viết",
    "ảnh đại diện của",
    "nút thích",
    "nút bình luận",
    "nút chia sẻ",
    "thước phim",
    "action chip profile picture",
)

_NOISE_CONTAINS = (
    "bảng ở cạnh",
    "mở tin của",
    "tin chưa xem",
    "có dùng ai",
    "xem thước phim",
    "thước phim",
    "trạng thái hoạt động",
    "đã chỉnh sửa",
)

_AD_RESOURCE_IDS = frozenset({
    "com.facebook.katana:id/sponsored_label",
    "com.facebook.katana:id/ad_unit_container",
    "com.facebook.lite:id/sponsored_label",
})

_LXML_PARSER = _lxml.XMLParser(recover=True, remove_comments=True, encoding="utf-8")

_XPATH_RECYCLER = '//node[contains(@class, "RecyclerView") and @scrollable="true"]'
_XPATH_LIST = '//node[contains(@class, "ListView") and @scrollable="true"]'


def _is_noise_text(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if t in _NOISE_TEXTS:
        return True
    if any(t.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return True
    if any(token in t for token in _NOISE_CONTAINS):
        return True
    return False


def _parse_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _cy(bounds: Tuple[int, int, int, int]) -> int:
    return (bounds[1] + bounds[3]) // 2


def _collect_text_nodes(element, toolbar_cutoff_y: int = 200) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for node in element.iter():
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
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
        nodes.append({
            "text":        content,
            "bounds":      bounds,
            "cy":          _cy(bounds),
            "resource_id": node.get("resource-id") or "",
        })
    nodes.sort(key=lambda n: n["cy"])
    return nodes


def _is_ad_container(element) -> bool:
    for node in element.iter():
        if (node.get("resource-id") or "") in _AD_RESOURCE_IDS:
            return True
    return False


def _extract_post(cluster: List[Dict[str, Any]], source_index: int) -> Optional[Dict[str, Any]]:
    ts_idx = next((i for i, n in enumerate(cluster) if _RE_TS.search(n["text"])), None)
    if ts_idx is None:
        return None

    timestamp = cluster[ts_idx]["text"]
    all_lower = " ".join(n["text"].lower() for n in cluster)

    if _RE_REEL_TYPE.search(all_lower):
        post_type: str = "reel"
    elif _RE_VIDEO_TYPE.search(all_lower):
        post_type = "video"
    elif _RE_LINK_TYPE.search(all_lower):
        post_type = "link"
    else:
        post_type = "text"

    author: Optional[str] = None
    body_parts: List[str] = []
    reactions = comments = shares = None
    image_desc: Optional[str] = None
    comment_preview: Optional[str] = None
    stats_seen: bool = False

    for i, node in enumerate(cluster):
        t = node["text"].strip()
        t_lower = t.lower()

        if i == ts_idx:
            continue
        if _is_noise_text(t) or len(t) <= 1:
            continue

        if (i < ts_idx and author is None and 2 <= len(t) <= 80
                and "•" not in t and "chia sẻ với" not in t_lower):
            author = t
            continue

        if 0 < i < ts_idx and t != author:
            body_parts.append(t)
            continue

        if i > ts_idx:
            if image_desc is None and _RE_IMAGE_TYPE.match(t_lower) and 8 < len(t) < 300:
                image_desc = t
                continue

            m_r = _RE_REACTIONS.match(t)
            m_c = _RE_COMMENTS.match(t)
            m_s = _RE_SHARES.match(t)

            if m_r and reactions is None:
                reactions = m_r.group(1)
                stats_seen = True
            elif m_c and comments is None:
                comments = m_c.group(1)
                stats_seen = True
            elif m_s and shares is None:
                shares = m_s.group(1)
                stats_seen = True
            elif not _is_noise_text(t):
                if stats_seen:
                    if comment_preview is None and len(t) > 5:
                        comment_preview = t
                else:
                    body_parts.append(t)

    body = " ".join(body_parts).strip()
    if body:
        b = body.lower()
        if any(b.startswith(prefix) for prefix in _NOISE_PREFIXES):
            body = ""
        if any(token in b for token in _NOISE_CONTAINS):
            body = ""
        if "chia sẻ với: nhóm công khai" in b and len(body) < 60:
            body = ""

    if not author and not body:
        return None

    if image_desc and post_type == "text":
        post_type = "photo"

    return {
        "author":          author or "",
        "text":            body,
        "timestamp":       timestamp,
        "reactions":       reactions,
        "comments":        comments,
        "shares":          shares,
        "source_index":    source_index,
        "post_type":       post_type,
        "image_desc":      image_desc,
        "comment_preview": comment_preview,
    }


def _extract_posts_from_recycler(root, source_index: int) -> Optional[List[Dict[str, Any]]]:
    containers = root.xpath(_XPATH_RECYCLER) or root.xpath(_XPATH_LIST)
    if not containers:
        return None
    feed = max(containers, key=lambda el: len(el.findall("node")))
    candidates = feed.findall("node")
    if len(candidates) < 2:
        return None
    posts: List[Dict[str, Any]] = []
    for candidate in candidates:
        if _is_ad_container(candidate):
            continue
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        post = _extract_post(nodes, source_index)
        if post:
            posts.append(post)
    return posts


def _cluster_into_posts(nodes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    if not nodes:
        return []
    GAP_THRESHOLD = 160
    clusters: List[List[Dict]] = []
    current: List[Dict] = [nodes[0]]
    prev_cy = nodes[0]["cy"]
    current_has_ts = bool(_RE_TS.search(nodes[0]["text"]))
    for node in nodes[1:]:
        gap = node["cy"] - prev_cy
        is_ts = bool(_RE_TS.search(node["text"]))
        if gap > GAP_THRESHOLD or (current_has_ts and is_ts and gap > 15):
            clusters.append(current)
            current = [node]
            current_has_ts = is_ts
        else:
            current.append(node)
            if is_ts:
                current_has_ts = True
        prev_cy = node["cy"]
    if current:
        clusters.append(current)
    return clusters


def _parse_xml(xml: str) -> Optional[Any]:
    try:
        raw = xml.encode("utf-8") if isinstance(xml, str) else xml
        return _lxml.fromstring(raw, parser=_LXML_PARSER)
    except Exception as exc:
        log.warning("fb_extract: XML parse error: %s", exc)
        return None


def parse_fb_posts_from_xml(xml: str, source_index: int = 0) -> List[Dict[str, Any]]:
    """Parse UIAutomator2 hierarchy XML → list of post dicts."""
    root = _parse_xml(xml)
    if root is None:
        return []
    posts = _extract_posts_from_recycler(root, source_index)
    if posts is not None:
        return posts
    nodes = _collect_text_nodes(root)
    clusters = _cluster_into_posts(nodes)
    result: List[Dict[str, Any]] = []
    for cluster in clusters:
        post = _extract_post(cluster, source_index)
        if post:
            result.append(post)
    return result


def _dedup(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate: same author + timestamp + text[:60] = same post."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for p in posts:
        key = (p["author"], p["timestamp"], p["text"][:60])
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _expand_see_more(device) -> int:
    """Tap all visible 'See more' / 'Xem thêm' buttons. Returns count expanded."""
    xml = device.hierarchy_xml(force_refresh=True)
    if not xml:
        return 0
    expanded = 0
    try:
        root = _parse_xml(xml)
        if root is None:
            return 0
        candidates = root.xpath(
            '//node[@clickable="true" and ('
            '@text="See more" or @text="Xem thêm" or '
            '@text="see more" or @text="xem thêm"'
            ')]'
        )
        for node in candidates:
            b = _parse_bounds(node)
            if b:
                device.tap((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
                expanded += 1
                time.sleep(0.4)
    except Exception:
        pass
    if expanded:
        time.sleep(0.8)
    return expanded
