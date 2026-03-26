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
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

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

def _parse_bounds(node: ET.Element) -> Optional[Tuple[int, int, int, int]]:
    """Parse '[x1,y1][x2,y2]' → (x1, y1, x2, y2) or None."""
    m = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def _cy(bounds: Tuple[int, int, int, int]) -> int:
    return (bounds[1] + bounds[3]) // 2


def _collect_text_nodes(root: ET.Element, toolbar_cutoff_y: int = 200) -> List[Dict[str, Any]]:
    """
    Walk hierarchy, collect all nodes that have visible text.
    Returns list of dicts sorted top-to-bottom by vertical center.
    """
    nodes = []
    for node in root.iter():
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        # Prefer explicit text. content-desc is often accessibility/action labels.
        content = text if text else desc
        if not content:
            continue
        bounds = _parse_bounds(node)
        if not bounds:
            continue
        # Skip system status bar / navigation bar
        if bounds[3] < toolbar_cutoff_y:
            continue
        # Skip zero-size invisible nodes
        if bounds[0] == bounds[2] or bounds[1] == bounds[3]:
            continue
        nodes.append({
            "text":   content,
            "bounds": bounds,
            "cy":     _cy(bounds),
        })
    nodes.sort(key=lambda n: n["cy"])
    return nodes


def _cluster_into_posts(nodes: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """
    Group nearby text nodes into post "blocks".

    A new cluster starts when:
      - Vertical gap from previous node > GAP_THRESHOLD (blank space between posts)
      - OR a timestamp node is seen after the first one in the current cluster
        (timestamp = reliable post-boundary marker)
    """
    if not nodes:
        return []

    GAP_THRESHOLD = 100  # pixels — FB post cards have clear vertical separation

    clusters: List[List[Dict]] = []
    current: List[Dict] = [nodes[0]]
    prev_cy = nodes[0]["cy"]
    current_has_ts = bool(_RE_TS.search(nodes[0]["text"]))

    for node in nodes[1:]:
        gap = node["cy"] - prev_cy
        is_ts = bool(_RE_TS.search(node["text"]))

        # Start a new cluster if:
        # 1. Large visual gap between nodes
        # 2. We already have a timestamp and see another timestamp (next post)
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
      [Timestamp]    ← anchor — required; no timestamp = not a post
      [Post body...] (multiple TextViews)
      [Reaction count] [Comment count] [Share count]
      [Like | Comment | Share buttons] ← noise
    """
    # Find timestamp index (required anchor)
    ts_idx = next((i for i, n in enumerate(cluster) if _RE_TS.search(n["text"])), None)
    if ts_idx is None:
        return None  # Not a post block

    timestamp = cluster[ts_idx]["text"]
    author: Optional[str] = None
    body_parts: List[str] = []
    reactions = comments = shares = None

    for i, node in enumerate(cluster):
        t = node["text"].strip()
        t_lower = t.lower()

        if i == ts_idx:
            continue  # already captured

        if _is_noise_text(t) or len(t) <= 1:
            continue

        # Author: first meaningful short-ish text before timestamp.
        if (
            i < ts_idx
            and author is None
            and 2 <= len(t) <= 80
            and "•" not in t
            and "chia sẻ với" not in t_lower
            and not _is_noise_text(t)
        ):
            author = t
            continue

        # Nodes between author and timestamp → pre-timestamp body
        # (Facebook sometimes puts post text BEFORE the timestamp)
        if 0 < i < ts_idx and t != author and not _is_noise_text(t):
            body_parts.append(t)
            continue

        # Nodes AFTER timestamp
        if i > ts_idx:
            m_r = _RE_REACTIONS.match(t)
            m_c = _RE_COMMENTS.match(t)
            m_s = _RE_SHARES.match(t)
            if m_r and reactions is None:
                reactions = m_r.group(1)
            elif m_c and comments is None:
                comments = m_c.group(1)
            elif m_s and shares is None:
                shares = m_s.group(1)
            else:
                # Post body text after timestamp (most common FB layout)
                if not _is_noise_text(t):
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

    return {
        "author":       author or "",
        "text":         body,
        "timestamp":    timestamp,
        "reactions":    reactions,
        "comments":     comments,
        "shares":       shares,
        "source_index": source_index,
    }


def parse_fb_posts_from_xml(xml: str, source_index: int = 0) -> List[Dict[str, Any]]:
    """
    Public helper: Parse UIAutomator2 hierarchy XML → list of post dicts.
    Can be used standalone for testing / offline replay.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        log.warning("fb_crawl: XML parse error: %s", exc)
        return []

    nodes = _collect_text_nodes(root)
    clusters = _cluster_into_posts(nodes)
    posts: List[Dict[str, Any]] = []
    for cluster in clusters:
        post = _extract_post(cluster, source_index)
        if post:
            posts.append(post)
    return posts


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
        root = ET.fromstring(xml)
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
        root = ET.fromstring(xml)
        for node in root.iter():
            text = (node.get("text") or node.get("content-desc") or "").strip().lower()
            if text in ("see more", "xem thêm"):
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
