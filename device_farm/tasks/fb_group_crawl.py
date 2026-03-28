"""
fb_group_crawl.py — Facebook Group Post Crawler

Crawls posts from a Facebook group using UIAutomator2 hierarchy XML.

Supports:
  - Facebook App native (com.facebook.katana)
  - Facebook Lite   (com.facebook.lite)
  - Chrome browser  (m.facebook.com — more stable structure)

Usage (via task queue):
    from tasks.fb_group_crawl import fb_group_crawl_task
    from runtime.core.task_queue import Task

    task = Task(fn=fb_group_crawl_task("123456789", max_posts=30))
    queue.put(task)

Usage (direct / HTTP API):
    POST /api/devices/{serial}/fb_crawl
    {
        "group_id": "123456789",
        "max_posts": 50,
        "max_scrolls": 30,
        "app": "chrome",
        "save_screenshots": false
    }

Each post dict returned:
    {
        "author":       str,        # Name or page that posted
        "text":         str,        # Post body (may be truncated if FB shows "See more")
        "timestamp":    str,        # Raw UI string: "2 giờ trước", "Yesterday", etc.
        "reactions":    str | null, # e.g. "1.2K"
        "comments":     str | null, # e.g. "45"
        "shares":       str | null,
        "source_index": int,        # Scroll step when first seen
    }

Notes:
  - Device must already be logged into Facebook in the target app/browser.
  - Facebook may show a login wall — handled automatically (tap "Not Now").
  - Parsing is heuristic; node structure varies across FB app versions.
  - "See more" posts will only return the truncated text visible on screen.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from lxml import etree as _lxml

log = logging.getLogger(__name__)

# ── App config ────────────────────────────────────────────────────────────────

APP_PACKAGES = {
    "facebook":      "com.facebook.katana",
    "facebook_lite": "com.facebook.lite",
    "chrome":        "com.android.chrome",
}

# Mobile web URL — always logged-in if Chrome has a session cookie
_GROUP_URL = "https://m.facebook.com/groups/{group_id}"

# ── Timestamp regex (Vietnamese + English) ────────────────────────────────────

_RE_TS = re.compile(
    r"(\d+\s*(giây|phút|giờ|ngày|tuần|tháng|năm)\s*(trước)?)"
    r"|(\d+\s*(second|minute|hour|day|week|month|year)s?\s*ago)"
    r"|(hôm qua|yesterday|just now|vừa xong|bây giờ|now)"
    r"|(T\d,\s*\d{1,2}/\d{1,2}/\d{4})"  # Vietnamese date format
    r"|(\d{1,2}/\d{1,2}/\d{4})"
    r"|(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)

# ── Post-type detection patterns ─────────────────────────────────────────────
# Applied to ALL text/content-desc in a post cluster to classify the post.

_RE_REEL_TYPE = re.compile(r"\breels?\b", re.IGNORECASE)
_RE_VIDEO_TYPE = re.compile(
    r"\b(video|clip|thước phim|watch video|xem video)\b", re.IGNORECASE
)
# Image: matches content-desc that FB puts on photo attachments
# ("Ảnh của X", "Photo by Y", etc.)  Must start with these keywords.
_RE_IMAGE_TYPE = re.compile(
    r"^(ảnh|photo|hình|image|picture)\b", re.IGNORECASE
)
_RE_LINK_TYPE = re.compile(
    r"(https?://\S{6,}|www\.[^\s]{4,}|\.\bcom\b|\.\bvn\b|\.\bnet\b|visit site|xem trang|đọc thêm)",
    re.IGNORECASE,
)

# ── Count patterns ─────────────────────────────────────────────────────────────

_RE_REACTIONS = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s*(lượt thích|reactions?|likes?)?$", re.IGNORECASE
)
_RE_COMMENTS = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s*(bình luận|comments?|phản hồi)$", re.IGNORECASE
)
_RE_SHARES = re.compile(
    r"^(\d[\d.,]*[KMkm]?)\s*(lượt chia sẻ|shares?)$", re.IGNORECASE
)

# Text values that are action labels / noise — skip these when building post body
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


# ── XML parsing helpers ───────────────────────────────────────────────────────
# We use lxml for:
#   • XPath queries to find RecyclerView / feed containers (not possible with stdlib ET)
#   • recover=True — handles the occasional malformed UIAutomator2 XML gracefully
#   • 5-20× faster parsing than stdlib xml.etree.ElementTree for large hierarchies


_LXML_PARSER = _lxml.XMLParser(recover=True, remove_comments=True, encoding="utf-8")

# XPath expressions for feed container detection.
# UIAutomator2 XML uses <node class="..."> for every element.
_XPATH_RECYCLER = (
    '//node[contains(@class, "RecyclerView") and @scrollable="true"]'
)
_XPATH_LIST = (
    '//node[contains(@class, "ListView") and @scrollable="true"]'
)
# WebView container (Chrome / m.facebook.com)
_XPATH_WEBVIEW = '//node[contains(@class, "WebView")]'

# Class names that are typically wrapper/container frames, not post cards themselves.
_AD_RESOURCE_IDS = frozenset({
    "com.facebook.katana:id/sponsored_label",
    "com.facebook.katana:id/ad_unit_container",
    "com.facebook.lite:id/sponsored_label",
})


def _parse_bounds(node) -> Optional[Tuple[int, int, int, int]]:
    """Parse '[x1,y1][x2,y2]' attribute → (x1, y1, x2, y2) or None."""
    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _cy(bounds: Tuple[int, int, int, int]) -> int:
    return (bounds[1] + bounds[3]) // 2


def _collect_text_nodes(
    element,
    toolbar_cutoff_y: int = 200,
) -> List[Dict[str, Any]]:
    """
    Walk an element subtree (lxml), collect all nodes that carry visible text.
    Returns a list of dicts sorted top-to-bottom by vertical centre.

    Accepts any lxml element — either the full root or a single post container.
    """
    nodes: List[Dict[str, Any]] = []
    for node in element.iter():
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        # Explicit text takes priority; content-desc is often accessibility/action labels.
        content = text if text else desc
        if not content:
            continue
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        # Skip system status bar / navigation bar area
        if bounds[3] < toolbar_cutoff_y:
            continue
        # Skip zero-size / invisible nodes
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
    """Return True if any child node has a known sponsored/ad resource-id."""
    for node in element.iter():
        if (node.get("resource-id") or "") in _AD_RESOURCE_IDS:
            return True
    return False


# ── Strategy A: RecyclerView-based post boundary detection ────────────────────
# Each direct <node> child of the RecyclerView is one post card (or story/ad).
# This is the correct, tree-structure-aware approach for FB app native.

def _extract_posts_from_recycler(
    root,
    source_index: int,
) -> Optional[List[Dict[str, Any]]]:
    """
    Find the best RecyclerView or ListView feed container and treat each of its
    direct <node> children as one post card.

    Returns a list of post dicts, or None if no suitable container was found
    (caller should fall back to gap-based clustering).
    """
    # Try RecyclerView first (FB app native), then ListView (older FB / Lite).
    containers = root.xpath(_XPATH_RECYCLER) or root.xpath(_XPATH_LIST)
    if not containers:
        return None

    # Pick the container with the most direct node children (most likely the feed).
    feed = max(containers, key=lambda el: len(el.findall("node")))
    candidates = feed.findall("node")
    if len(candidates) < 2:
        return None  # Too few children — probably not the feed, fall back.

    posts: List[Dict[str, Any]] = []
    for candidate in candidates:
        # Skip known ad containers
        if _is_ad_container(candidate):
            continue
        nodes = _collect_text_nodes(candidate, toolbar_cutoff_y=0)
        post = _extract_post(nodes, source_index)
        if post:
            posts.append(post)
    return posts


# ── Strategy B: Gap-based clustering (fallback for WebView / Chrome) ──────────
# Used when no RecyclerView is found (e.g. m.facebook.com in Chrome).

def _cluster_into_posts(nodes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Fallback: group text nodes into post blocks by vertical gap and timestamp anchors.

    A new cluster starts when:
      • Vertical gap from previous node > GAP_THRESHOLD  (blank space between posts)
      • OR a timestamp already exists in the current cluster and another timestamp
        appears (reliable post-boundary signal).
    """
    if not nodes:
        return []

    # 160 px covers FB image attachment nodes (typically 120-150 px below post text).
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


def _extract_post(cluster: List[Dict[str, Any]], source_index: int) -> Optional[Dict[str, Any]]:
    """
    Build a post dict from a cluster of text nodes.

    Layout heuristic (Facebook post card, top → bottom):
      [Author name]
      [Timestamp]          ← anchor — required; no timestamp = not a post
      [Post body...]       (multiple TextViews; may also appear before timestamp)
      [Image/video desc]   content-desc of media attachment (optional)
      [Reaction count]     e.g. "1.2K"
      [Comment count]      e.g. "45 bình luận"
      [Share count]        e.g. "12 lượt chia sẻ"
      [Like|Comment|Share] ← noise buttons
      [First comment]      ← comment_preview — first visible reply (optional)

    Returns dict with keys:
      author, text, timestamp, reactions, comments, shares, source_index,
      post_type, image_desc, comment_preview  (DF-006 enrichment)
    """
    # Find timestamp index (required anchor)
    ts_idx = next((i for i, n in enumerate(cluster) if _RE_TS.search(n["text"])), None)
    if ts_idx is None:
        return None  # Not a post block

    timestamp = cluster[ts_idx]["text"]

    # ── Post type: scan all cluster texts for media signals ──────────────────
    # NOTE: _RE_IMAGE_TYPE uses ^ anchor (for content-desc matching); use
    # separate non-anchored search for cluster-wide scan.
    all_lower = " ".join(n["text"].lower() for n in cluster)
    if _RE_REEL_TYPE.search(all_lower):
        post_type: str = "reel"
    elif _RE_VIDEO_TYPE.search(all_lower):
        post_type = "video"
    elif _RE_LINK_TYPE.search(all_lower):
        post_type = "link"
    else:
        post_type = "text"  # may be upgraded to "photo" below if image_desc found

    author: Optional[str] = None
    body_parts: List[str] = []
    reactions = comments = shares = None
    image_desc: Optional[str] = None       # first image/video attachment description
    comment_preview: Optional[str] = None  # first visible comment text after post
    stats_seen: bool = False               # True once any engagement metric is found

    for i, node in enumerate(cluster):
        t = node["text"].strip()
        t_lower = t.lower()

        if i == ts_idx:
            continue  # already captured

        if _is_noise_text(t) or len(t) <= 1:
            continue

        # ── Author: first meaningful short text before timestamp ──────────────
        if (
            i < ts_idx
            and author is None
            and 2 <= len(t) <= 80
            and "•" not in t
            and "chia sẻ với" not in t_lower
        ):
            author = t
            continue

        # ── Pre-timestamp body (FB sometimes puts post text BEFORE timestamp) ─
        if 0 < i < ts_idx and t != author:
            body_parts.append(t)
            continue

        # ── Nodes AFTER timestamp ─────────────────────────────────────────────
        if i > ts_idx:
            # Image/video attachment: content-desc starts with image keyword.
            # Only capture the first one; skip button-length texts.
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
                    # Text appearing after engagement metrics = first visible comment.
                    # Capture only the first qualifying text; ignore subsequent replies.
                    if comment_preview is None and len(t) > 5:
                        comment_preview = t
                else:
                    # Post body text (before engagement section)
                    body_parts.append(t)

    body = " ".join(body_parts).strip()

    # Drop obvious non-post/action-only bodies.
    if body:
        b = body.lower()
        if any(b.startswith(prefix) for prefix in _NOISE_PREFIXES):
            body = ""
        if any(token in b for token in _NOISE_CONTAINS):
            body = ""
        if "chia sẻ với: nhóm công khai" in b and len(body) < 60:
            body = ""

    # Require at least author or body to consider this a real post
    if not author and not body:
        return None

    # Upgrade post_type to "photo" when an image content-desc was found
    # and no stronger media type (reel/video) was detected.
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
        # DF-006 enrichment — saved to CrawlPost when using crawl_jobs endpoint
        "post_type":       post_type,
        "image_desc":      image_desc,
        "comment_preview": comment_preview,
    }


def _parse_xml(xml: str) -> Optional[Any]:
    """Parse UIAutomator2 XML with lxml (recover=True handles malformed output)."""
    try:
        raw = xml.encode("utf-8") if isinstance(xml, str) else xml
        return _lxml.fromstring(raw, parser=_LXML_PARSER)
    except Exception as exc:
        log.warning("fb_crawl: XML parse error: %s", exc)
        return None


def parse_fb_posts_from_xml(xml: str, source_index: int = 0) -> List[Dict[str, Any]]:
    """
    Parse UIAutomator2 hierarchy XML → list of post dicts.

    Strategy A (preferred): XPath to find the RecyclerView/ListView feed container;
    each direct <node> child is treated as one post card. Gives precise boundaries.

    Strategy B (fallback): when no scrollable feed container is found (e.g. Chrome
    WebView where FB renders as m.facebook.com), fall back to vertical-gap clustering
    over all visible text nodes.

    Can be used standalone for testing / offline replay.
    """
    root = _parse_xml(xml)
    if root is None:
        return []

    # Strategy A — RecyclerView tree-structure aware
    posts = _extract_posts_from_recycler(root, source_index)
    if posts is not None:
        log.debug("fb_crawl: RecyclerView strategy → %d post candidates", len(posts))
        return posts

    # Strategy B — gap-based fallback (Chrome / WebView / older layouts)
    log.debug("fb_crawl: no RecyclerView found, using gap-based clustering")
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


# ── Login-wall handler ────────────────────────────────────────────────────────

_LOGIN_DISMISS = [
    "Not Now", "Không phải bây giờ",
    "Maybe Later", "Lúc khác",
    "Close", "Đóng",
    "Cancel", "Hủy",
    "Continue as Guest", "Tiếp tục không đăng nhập",
    "Skip", "Bỏ qua",
]


def _dismiss_login_wall(device, errors: List[str]) -> None:
    """Tap 'Not Now' / 'Close' if Facebook shows a login prompt."""
    time.sleep(0.8)
    xml = device.hierarchy_xml(force_refresh=True)
    if not xml:
        return
    try:
        root = _parse_xml(xml)
        if root is None:
            return
        for node in root.iter():
            text = (node.get("text") or node.get("content-desc") or "").strip()
            if text in _LOGIN_DISMISS:
                b = _parse_bounds(node)
                if b:
                    cx = (b[0] + b[2]) // 2
                    cy = (b[1] + b[3]) // 2
                    device.tap(cx, cy)
                    log.info("fb_crawl: dismissed login wall ('%s')", text)
                    time.sleep(1.2)
                    return
    except Exception as exc:
        errors.append(f"login wall check error: {exc}")


# ── "See more" expander ───────────────────────────────────────────────────────

def _expand_see_more(device) -> int:
    """
    Tap all visible 'See more' / 'Xem thêm' buttons to expand truncated posts.
    Returns count of expansions.
    """
    xml = device.hierarchy_xml(force_refresh=True)
    if not xml:
        return 0
    expanded = 0
    try:
        root = _parse_xml(xml)
        if root is None:
            return 0
        # XPath: clickable nodes whose text is a "see more" label
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
        time.sleep(0.8)  # wait for expansion animation
    return expanded


# ── Main task factory ─────────────────────────────────────────────────────────

def fb_group_crawl_task(
    group_id: str,
    max_posts: int = 50,
    max_scrolls: int = 30,
    app: str = "chrome",
    scroll_pause: float = 2.5,
    wait_load: float = 4.0,
    expand_posts: bool = True,
    save_screenshots: bool = False,
) -> Callable:
    """
    Return a task function for the device farm dispatcher.

    Args:
        group_id:         FB group numeric ID or slug ("123456789" or "mygroupslug")
        max_posts:        Stop collecting when this many unique posts reached
        max_scrolls:      Hard scroll limit (safety cap)
        app:              "chrome" | "facebook" | "facebook_lite"
        scroll_pause:     Seconds to wait after each scroll for feed to load
        wait_load:        Seconds to wait after opening the group URL
        expand_posts:     Tap "See more" buttons to get full text
        save_screenshots: Include base64 JPEG at each scroll in result

    Result dict:
        {
          "success":      bool,
          "posts":        List[post_dict],
          "total":        int,
          "scrolls":      int,
          "errors":       List[str],
          "screenshots":  List[str],   # base64 JPEG, only when save_screenshots=True
        }
    """

    def _task(device) -> Dict[str, Any]:
        url = _GROUP_URL.format(group_id=group_id)
        pkg = APP_PACKAGES.get(app, APP_PACKAGES["chrome"])
        errors: List[str] = []
        all_posts: List[Dict[str, Any]] = []
        screenshots: List[str] = []
        scroll_count = 0

        log.info("fb_crawl[%s]: opening %s (app=%s)", group_id, url, app)

        # ── Step 1: Open group URL ────────────────────────────────────────────
        try:
            device.open_url(url, package=pkg)
        except Exception as exc:
            errors.append(f"open_url failed: {exc}")
            # Fallback: try without specifying package
            try:
                device.open_url(url)
            except Exception as exc2:
                errors.append(f"open_url fallback failed: {exc2}")
                return _result(False, all_posts, scroll_count, errors, screenshots)

        # ── Step 2: Wait for initial load ────────────────────────────────────
        time.sleep(wait_load)

        # Handle login prompt
        _dismiss_login_wall(device, errors)

        # ── Step 3: Scroll + parse loop ───────────────────────────────────────
        no_new_streak = 0

        while scroll_count <= max_scrolls and len(all_posts) < max_posts:
            # Optionally expand "See more" buttons
            if expand_posts:
                _expand_see_more(device)

            # Screenshot
            if save_screenshots:
                frame = device.take_screenshot()
                if frame:
                    import base64 as _b64
                    screenshots.append(_b64.b64encode(frame).decode())

            # Dump + parse
            xml = device.hierarchy_xml(force_refresh=True)
            if xml:
                new_batch = parse_fb_posts_from_xml(xml, source_index=scroll_count)
                prev_total = len(all_posts)
                all_posts = _dedup(all_posts + new_batch)
                added = len(all_posts) - prev_total
                log.info(
                    "fb_crawl[%s]: scroll=%d  +%d new  total=%d/%d",
                    group_id, scroll_count, added, len(all_posts), max_posts,
                )
                if added == 0:
                    no_new_streak += 1
                else:
                    no_new_streak = 0
            else:
                errors.append(f"scroll {scroll_count}: hierarchy_xml returned None")
                no_new_streak += 1
                log.warning("fb_crawl[%s]: scroll=%d  hierarchy=None", group_id, scroll_count)

            # Stop if no new posts for 3 consecutive scrolls (reached end / blocked)
            if no_new_streak >= 3:
                log.info("fb_crawl[%s]: 3 scrolls with no new posts — stopping", group_id)
                break

            if len(all_posts) >= max_posts:
                break

            # Scroll down
            device.scroll("down", distance=0.6)
            scroll_count += 1
            time.sleep(scroll_pause)

        # Trim to requested max
        all_posts = all_posts[:max_posts]
        log.info("fb_crawl[%s]: done — %d posts, %d scrolls", group_id, len(all_posts), scroll_count)
        return _result(True, all_posts, scroll_count, errors, screenshots)

    _task.__name__ = f"fb_group_crawl_{group_id}"
    return _task


def _result(
    success: bool,
    posts: List[Dict],
    scrolls: int,
    errors: List[str],
    screenshots: List[str],
) -> Dict[str, Any]:
    return {
        "success":     success,
        "posts":       posts,
        "total":       len(posts),
        "scrolls":     scrolls,
        "errors":      errors,
        "screenshots": screenshots,
    }
