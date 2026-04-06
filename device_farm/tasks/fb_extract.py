"""
fb_extract.py — Facebook post parsing utilities.

Extracted from fb_group_crawl.py; contains only the XML parsing / extraction
helpers used by scenario_task.py (extract step, fb_posts strategy).
No crawl job / DB / network code here.
"""
from __future__ import annotations

import hashlib
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

# Số có thể đứng sau emoji/ký tự bất kỳ, format: 1.2K / 1,2K / 123 / 1.200
_RE_NUM = r"(\d[\d.,]*[KMkm]?)"

_RE_REACTIONS = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(lượt thích|reactions?|likes?)?\s*$", re.IGNORECASE
)
_RE_COMMENTS = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(bình luận|comments?|phản hồi)\s*$", re.IGNORECASE
)
_RE_SHARES = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(lượt chia sẻ|shares?)\s*$", re.IGNORECASE
)
_RE_VIEWS = re.compile(
    r"[^\d]*" + _RE_NUM + r"\s*(lượt xem|views?|lần xem)\s*$", re.IGNORECASE
)
# Combined stats node: "1,2K · 45 bình luận · 12 lượt chia sẻ"
_RE_COMBINED_STATS = re.compile(
    r"(\d[\d.,]*[KMkm]?)\s*"
    r"(lượt thích|reactions?|likes?|bình luận|comments?|phản hồi"
    r"|lượt chia sẻ|shares?|lượt xem|views?)?",
    re.IGNORECASE,
)
# content-desc nút like: "1.200 lượt thích. Nút Thích." → trích số
_RE_LIKE_BTN_DESC = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s+lượt thích[.\s]", re.IGNORECASE
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
    "nút bình luận",
    "nút chia sẻ",
    "thước phim",
    "action chip profile picture",
)
# "nút thích" không bỏ vào noise vì content-desc có thể chứa số like:
# "1.200 lượt thích. Nút Thích." → cần parse trước rồi skip

# Prefix dùng để trích xuất tên tác giả từ content-desc avatar
_AUTHOR_PREFIX = "ảnh đại diện của"

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


def _parse_stats(t: str) -> Dict[str, Optional[str]]:
    """Parse một text node thành dict stats. Hỗ trợ:
    - "1,2K lượt thích" / "❤️ 1,2K" / "1.200 lượt thích. Nút Thích."
    - "45 bình luận" / "12 lượt chia sẻ" / "5,4K lượt xem"
    - Combined: "1,2K · 45 bình luận · 12 lượt chia sẻ"
    Trả về dict với các key có giá trị tìm thấy, None nếu không có.
    """
    result: Dict[str, Optional[str]] = {
        "reactions": None, "comments": None, "shares": None, "views": None,
    }
    # Thử combined trước (có dấu ·)
    if "·" in t or "•" in t:
        parts = re.split(r"[·•]", t)
        for part in parts:
            part = part.strip()
            _apply_stat(part, result)
        return result
    _apply_stat(t, result)
    return result


def _apply_stat(t: str, result: Dict[str, Optional[str]]) -> None:
    """Apply 1 đoạn text vào result dict nếu match stats pattern."""
    # Like button desc: "1.200 lượt thích. Nút Thích."
    m = _RE_LIKE_BTN_DESC.match(t)
    if m and result["reactions"] is None:
        result["reactions"] = m.group(1)
        return
    m = _RE_VIEWS.search(t)
    if m and result["views"] is None:
        result["views"] = m.group(1)
        return
    m = _RE_SHARES.search(t)
    if m and result["shares"] is None:
        result["shares"] = m.group(1)
        return
    m = _RE_COMMENTS.search(t)
    if m and result["comments"] is None:
        result["comments"] = m.group(1)
        return
    # Reactions: số đứng một mình hoặc với nhãn "lượt thích"
    m = _RE_REACTIONS.search(t)
    if m and result["reactions"] is None:
        label = (m.group(2) or "").lower()
        # Nếu không có label → chỉ chấp nhận nếu text ngắn (tránh nhầm body)
        if label or len(t.strip()) <= 10:
            result["reactions"] = m.group(1)


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

        # Trích xuất tên tác giả từ content-desc avatar: "Ảnh đại diện của {NAME}..."
        is_author_hint = False
        desc_lower = desc.lower()
        if desc_lower.startswith(_AUTHOR_PREFIX):
            remainder = desc[len(_AUTHOR_PREFIX):].strip().lstrip(",").strip()
            # Lấy phần trước dấu phẩy đầu tiên (bỏ ", Nút." hoặc phần phụ)
            name_part = remainder.split(",")[0].strip()
            if 2 <= len(name_part) <= 80:
                content = name_part
                is_author_hint = True
            else:
                continue
        else:
            # "nút thích" content-desc có thể chứa số like → dùng desc thay vì bỏ
            desc_lower_full = desc.lower()
            if not text and desc_lower_full.startswith("nút thích"):
                # Bỏ qua, không có số
                continue
            # Ưu tiên content-desc nếu chứa số stats và text rỗng/ngắn
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
        nodes.append({
            "text":        content,
            "bounds":      bounds,
            "cy":          _cy(bounds),
            "resource_id": node.get("resource-id") or "",
            "is_author_hint": is_author_hint,
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

    # Ưu tiên node có is_author_hint (từ content-desc avatar) làm author
    author: Optional[str] = next(
        (n["text"] for n in cluster if n.get("is_author_hint") and n["text"]),
        None,
    )
    body_parts: List[str] = []
    reactions = comments = shares = views = None
    image_desc: Optional[str] = None
    comment_preview: Optional[str] = None
    stats_seen: bool = False

    for i, node in enumerate(cluster):
        t = node["text"].strip()
        t_lower = t.lower()

        if i == ts_idx:
            continue
        if node.get("is_author_hint"):
            continue  # đã xử lý ở trên
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

            stats = _parse_stats(t)
            matched_stat = False
            if stats["reactions"] is not None and reactions is None:
                reactions = stats["reactions"]
                matched_stat = True
            if stats["comments"] is not None and comments is None:
                comments = stats["comments"]
                matched_stat = True
            if stats["shares"] is not None and shares is None:
                shares = stats["shares"]
                matched_stat = True
            if stats["views"] is not None and views is None:
                views = stats["views"]
                matched_stat = True

            if matched_stat:
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

    # _pid: 16-char MD5 of author+body[:120], mirrors _compute_post_id_from_nodes.
    # Used to cross-reference this feed post with its comment-view header in the executor.
    _pid_raw = f"{author or ''}\x00{body[:120]}"
    _pid = hashlib.md5(_pid_raw.encode()).hexdigest()[:16]

    return {
        "author":          author or "",
        "text":            body,
        "timestamp":       timestamp,
        "reactions":       reactions,
        "comments":        comments,
        "shares":          shares,
        "views":           views,
        "source_index":    source_index,
        "post_type":       post_type,
        "image_desc":      image_desc,
        "comment_preview": comment_preview,
        "_pid":            _pid,
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


# ── Comment-like button patterns (from real UIAutomator XML) ─────────────────
# "Nút Thích bình luận của Đỗ. Nhấn đúp..."  → author short name = "Đỗ"
# "Trả lời bình luận của Tuấn, nút. ..."     → author short name = "Tuấn"
_RE_CMT_LIKE_BTN = re.compile(
    r"^Nút Thích bình luận của (.+?)\.", re.IGNORECASE
)
_RE_CMT_REPLY_BTN = re.compile(
    r"^Trả lời bình luận của (.+?),", re.IGNORECASE
)
# "N cảm xúc" → comment reaction count (different from post reactions)
_RE_CMT_REACTIONS = re.compile(r"^(\d[\d.,]*[KMkm]?)\s+cảm xúc$", re.IGNORECASE)

# Timestamp or post-share suffix that can appear in comment timestamp field
_RE_CMT_TS_SHARE = re.compile(r"•\s*Chia sẻ với.*$", re.IGNORECASE)

# Noise specific to comment area
_CMT_NOISE_TEXTS = frozenset({
    "thích", "trả lời", "like", "reply",
    "xem thêm câu trả lời", "ẩn câu trả lời",
    "theo dõi", "· theo dõi",
})


def _is_cmt_noise(text: str) -> bool:
    t = text.strip().lower()
    if not t or t in _CMT_NOISE_TEXTS:
        return True
    if t.startswith("nút thích bình luận"):
        return True
    if t.startswith("trả lời bình luận"):
        return True
    return False


def _cluster_into_comments(nodes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Cluster comment text-nodes into per-comment groups.

    Strategy:
    - Each comment starts with an author node (short text, x≥180).
    - A "Nút Thích bình luận của X." desc-node marks the boundary AFTER a comment.
    - Gap > 80px also starts a new cluster.
    """
    if not nodes:
        return []
    GAP = 80
    clusters: List[List[Dict]] = []
    current: List[Dict] = [nodes[0]]
    prev_cy = nodes[0]["cy"]

    for node in nodes[1:]:
        gap = node["cy"] - prev_cy
        t = node["text"].strip()
        # A "Nút Thích bình luận" button marks the end of a comment block
        is_end_marker = bool(_RE_CMT_LIKE_BTN.match(t))
        if gap > GAP or is_end_marker:
            if is_end_marker:
                current.append(node)  # include the marker in current cluster
            clusters.append(current)
            current = [] if is_end_marker else [node]
        else:
            current.append(node)
        prev_cy = node["cy"]

    if current:
        clusters.append(current)
    return clusters


def _extract_comment(
    cluster: List[Dict[str, Any]],
    parent_post_id: Optional[str] = None,
    cluster_min_x: int = 150,
) -> Optional[Dict[str, Any]]:
    """Extract one comment from a text-node cluster.

    Based on observed Facebook feed XML:
    - Author:    first short text (x≥180, len 2-80, no "·")
    - Body:      subsequent longer text node(s)
    - Timestamp: optional, matches _RE_TS; strip "•Chia sẻ với..." suffix
    - Likes:     "N cảm xúc" text node OR author from "Nút Thích bình luận của X."
    """
    author: Optional[str] = None
    body_parts: List[str] = []
    timestamp: Optional[str] = None
    likes: Optional[str] = None

    for node in cluster:
        t = node["text"].strip()
        if not t or len(t) <= 1:
            continue

        # Extract author name from like-button desc
        m = _RE_CMT_LIKE_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            continue

        # Extract author from reply-button desc (secondary fallback)
        m = _RE_CMT_REPLY_BTN.match(t)
        if m:
            if author is None:
                author = m.group(1).strip()
            continue

        # Skip other noise
        if _is_cmt_noise(t):
            continue

        # "N cảm xúc" → likes
        m = _RE_CMT_REACTIONS.match(t)
        if m:
            likes = m.group(1)
            continue

        # Timestamp
        if _RE_TS.search(t):
            # Strip "•Chia sẻ với: Nhóm công khai" suffix (appears on post timestamps leaking in)
            clean = _RE_CMT_TS_SHARE.sub("", t).strip()
            if timestamp is None:
                timestamp = clean if clean else t
            continue

        # Author: first short text that hasn't been assigned yet
        if author is None and 2 <= len(t) <= 80 and "·" not in t and "•" not in t:
            author = t
            continue

        # Everything else = body
        body_parts.append(t)

    text = " ".join(body_parts).strip()
    if not author and not text:
        return None

    # indent_level: 0 = top-level comment, 1 = reply (indented x≥220), 2 = deeply nested (x≥280)
    indent_level = 0
    if cluster_min_x >= 280:
        indent_level = 2
    elif cluster_min_x >= 220:
        indent_level = 1

    return {
        "author":         author or "",
        "text":           text,
        "timestamp":      timestamp,
        "likes":          likes,
        "parent_post_id": parent_post_id,
        "indent_level":   indent_level,
    }


def _compute_post_id_from_nodes(nodes: List[Dict[str, Any]]) -> Optional[str]:
    """Compute parent_post_id from the post header nodes at top of comment view.

    Post author node has is_author_hint=True and x≈34 (left-aligned, not indented).
    Post body is the first long text at x≈34 below the author.
    """
    import hashlib
    # Author hint at x < 60 (post author avatar, e.g. "Ảnh đại diện của Khanh Châu")
    post_author = next(
        (n["text"] for n in nodes if n.get("is_author_hint") and n["bounds"][0] < 60),
        None,
    )
    if not post_author:
        return None
    # First substantial body text at x < 60
    post_body = next(
        (n["text"] for n in nodes
         if not n.get("is_author_hint") and n["bounds"][0] < 60 and len(n["text"]) > 20),
        "",
    )
    raw = f"{post_author}\x00{post_body[:120]}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def parse_fb_comments_from_xml(
    xml: str,
    parent_post_id: Optional[str] = None,
    max_items: int = 50,
) -> List[Dict[str, Any]]:
    """Parse comments from current screen XML.

    Works for both:
    - Feed view: extracts comment-preview nodes below post action buttons
    - Post detail view: extracts all visible comments

    Each returned dict: {author, text, timestamp, likes, parent_post_id}.

    parent_post_id is:
    1. Passed in externally (from executor ctx), OR
    2. Auto-derived from the post header nodes in the XML (for post detail view)
    """
    root = _parse_xml(xml)
    if root is None:
        return []

    all_nodes = _collect_text_nodes(root, toolbar_cutoff_y=200)
    if not all_nodes:
        return []

    # Auto-derive parent_post_id from post header if not provided
    if parent_post_id is None:
        parent_post_id = _compute_post_id_from_nodes(all_nodes)

    # Find the y-coordinate of the action buttons row (Thích / Bình luận / Chia sẻ)
    # Comments only appear BELOW this row.
    action_btn_y2 = None
    for node in root.iter():
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls = node.get("class", "")
        if (text == "Bình luận" or desc == "Bình luận") and "Button" in cls:
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
            if m:
                action_btn_y2 = int(m.group(4))
                # Take the LAST such button if multiple posts on screen
                # (we want comments for the last post's button we see)

    # Filter: only comment-region nodes (indented x≥150, below action buttons)
    comment_nodes = [
        n for n in all_nodes
        if n["bounds"][0] >= 150
        and (action_btn_y2 is None or n["cy"] > action_btn_y2)
        and not n.get("is_author_hint")
    ]

    if not comment_nodes:
        return []

    clusters = _cluster_into_comments(comment_nodes)
    result: List[Dict[str, Any]] = []
    for cluster in clusters:
        if len(result) >= max_items:
            break
        cluster_min_x = min((n["bounds"][0] for n in cluster if n["bounds"]), default=150)
        comment = _extract_comment(cluster, parent_post_id, cluster_min_x=cluster_min_x)
        if comment:
            result.append(comment)

    # Prepend post-level stats from the comment view header (reactions, shares)
    # so the executor can update the parent post's stats in the DB.
    header_stats = _extract_header_stats(root)
    if header_stats:
        result.insert(0, header_stats)

    return result


def _dedup_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate comments: same author + text[:60] = same comment."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for c in comments:
        key = (c["author"], c["text"][:60])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _post_id_from_ctx(ctx: Dict[str, Any], post_id_var: Optional[str]) -> Optional[str]:
    """Read parent_post_id from ctx. Returns None → parser will auto-derive from XML."""
    if post_id_var:
        return ctx.get(post_id_var)
    return None


def _expand_see_more(
    device,
    max_passes: int = 2,
    scroll_between: bool = False,
    scroll_distance: float = 0.3,
) -> int:
    """Tap all visible 'See more' / 'Xem thêm' buttons.

    Args:
        max_passes: how many expand+redump cycles to attempt.
        scroll_between: if True, do a small scroll down between passes so that
            content pushed below the viewport is revealed and can also be expanded.
            Useful for very long posts where the full article spans multiple screens.
        scroll_distance: fraction of screen height to scroll between passes (0–1).
    Returns total count expanded."""
    total = 0
    for pass_num in range(max_passes):
        if pass_num > 0 and scroll_between:
            device.scroll(direction="down", distance=scroll_distance)
            time.sleep(0.5)
        xml = device.hierarchy_xml(force_refresh=True)
        if not xml:
            break
        expanded = 0
        try:
            root = _parse_xml(xml)
            if root is None:
                break
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
            break
        if expanded:
            time.sleep(1.0)  # Allow content to fully expand before next pass
            total += expanded
        else:
            break  # Nothing left to expand
    return total


def _extract_header_stats(root) -> Optional[Dict[str, Any]]:
    """Extract post-level stats from the comment view header area (y < 250).

    When a post's comment section is open, Facebook shows a header row with:
    - Reactions count: a Button with text="83" (numeric only)
    - Shares count: a Button with text="42 lượt chia sẻ"

    These nodes sit above toolbar_cutoff_y=200, so they're invisible to the
    normal comment extractor. This function scans for them explicitly.
    """
    reactions: Optional[str] = None
    shares: Optional[str] = None
    for node in root.iter():
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        # Only consider nodes completely above y=260 (header area)
        if bounds[1] > 260:
            continue
        cls = node.get("class", "")
        if "Button" not in cls:
            continue
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        t = text or desc
        if not t:
            continue
        # Numeric-only → reactions count (e.g. "83")
        if re.match(r"^\d[\d.,]*[KMkm]?$", t) and reactions is None:
            reactions = t
            continue
        # "N lượt chia sẻ" → shares count
        m = _RE_SHARES.search(t)
        if m and shares is None:
            shares = m.group(1)

    if reactions is None and shares is None:
        return None
    return {"_type": "post_stats", "reactions": reactions, "shares": shares}
