from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import hashlib
import re
import unicodedata

# Responsibility: cluster -> dict extraction for posts and comments.

# NOTE: We are incrementally moving implementation out of `_core.py`.
# This module now owns the following exported helpers/logic blocks:
# - `_merge_post_type`
# - `_refine_comment_author_from_cluster`
# - `_maybe_fix_merged_feed_caption`
# - `_refresh_post_derived_hashes`
# Remaining extraction functions (`_extract_post`, `_extract_comment`, ...)
# are temporarily re-exported from `_core.py` until they are moved next.

from .dedup import (
    _POST_PID_BODY_PREFIX_LEN,
    _STABLE_POST_IMAGE_PREFIX_LEN,
    _STABLE_POST_PREFIX_LEN,
    _TRUNCATION_MARKERS,
)
from .constants import (
    _MAX_TS_ANCHOR_NODE_LEN,
    _NOISE_CONTAINS,
    _NOISE_PREFIXES,
    _NOISE_TEXTS,
    _RE_COMMENT_REACTIONS_LABEL,
    _RE_COMBINED_STATS,
    _RE_COMMENTS,
    _MIN_IMAGE_AREA_FOR_PHOTO_HINT,
    _RE_IMAGE_TYPE,
    _RE_LINK_TYPE,
    _RE_LIKE_BTN_DESC,
    _RE_POST_RESHARE_HEADER,
    _RE_REACTIONS,
    _RE_REEL_TYPE,
    _RE_SHARES,
    _RE_TS,
    _RE_VIEWS,
    _RE_VIDEO_TYPE,
    _RE_CMT_LIKE_BTN,
    _RE_CMT_REPLY_BTN,
    _RE_FB_CAROUSEL,
    _RE_FB_GROUP_PERM,
    _RE_FB_GROUP_POST,
    _RE_FB_POST_SLUG,
    _RE_FB_STORY_FBID,
    _RE_RES_REEL,
    _RE_RES_VIDEO,
    _VIDEO_CLASSES,
    _author_prefix_match,
)
from .parser import _parse_bounds

def _iter_node_text_and_desc(element) -> List[str]:
    out: List[str] = []
    for node in element.iter():
        for key in ("text", "content-desc"):
            v = (node.get(key) or "").strip()
            if v:
                out.append(v)
    return out


def _extract_fb_link_meta(element) -> Tuple[Optional[str], Optional[str], List[str]]:
    group_id: Optional[str] = None
    post_id: Optional[str] = None
    permalinks: List[str] = []
    for s in _iter_node_text_and_desc(element):
        m = _RE_FB_GROUP_POST.search(s)
        if m:
            group_id, post_id = m.group(1), m.group(2)
            permalinks.append(m.group(0))
            continue
        m = _RE_FB_GROUP_PERM.search(s)
        if m:
            group_id, post_id = m.group(1), m.group(2)
            permalinks.append(m.group(0))
            continue
        m = _RE_FB_POST_SLUG.search(s)
        if m and post_id is None:
            post_id = m.group(1)
            permalinks.append(m.group(0))
        m = _RE_FB_STORY_FBID.search(s)
        if m and post_id is None:
            post_id = m.group(1)
    return post_id, group_id, permalinks


def _resource_id_media_hint(element) -> Optional[str]:
    for node in element.iter():
        rid = (node.get("resource-id") or "").lower()
        if not rid:
            continue
        if _RE_RES_REEL.search(rid):
            return "reel"
        if _RE_RES_VIDEO.search(rid):
            return "video"
    return None


def _structural_post_type_hint(element) -> Optional[str]:
    rid_hint = _resource_id_media_hint(element)
    if rid_hint == "reel":
        return "reel"
    if rid_hint == "video":
        return "video"
    seen_video = False
    large_image = False
    for node in element.iter():
        cls = node.get("class") or ""
        if cls in _VIDEO_CLASSES:
            seen_video = True
            break
        if "ImageView" in cls:
            b = _parse_bounds(node)
            if b:
                area = (b[2] - b[0]) * (b[3] - b[1])
                if area >= _MIN_IMAGE_AREA_FOR_PHOTO_HINT:
                    large_image = True
    if seen_video:
        return "video"
    if large_image:
        return "photo"
    return None


def _extract_media_artifacts(element) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for node in element.iter():
        desc = (node.get("content-desc") or "").strip()
        text = (node.get("text") or "").strip()
        label = desc or text
        if not label:
            continue
        if _author_prefix_match(desc.lower()) is not None:
            continue
        m = _RE_FB_CAROUSEL.search(label)
        if not m:
            continue
        slot, total = int(m.group(1)), int(m.group(2))
        b = _parse_bounds(node)
        found.append(
            {
                "kind": "carousel_photo",
                "label": label,
                "slot": slot,
                "total": total,
                "bounds": [b[0], b[1], b[2], b[3]] if b else None,
                "android_class": node.get("class") or "",
            }
        )
    found.sort(key=lambda x: (x["slot"], (x["bounds"] or [0, 0, 0, 0])[1]))
    return found


def _compute_post_id_from_nodes(nodes: List[Dict[str, Any]]) -> Optional[str]:
    post_author = next(
        (n["text"] for n in nodes if n.get("is_author_hint") and n["bounds"][0] < 60),
        None,
    )
    if not post_author:
        return None
    post_body = next(
        (
            n["text"]
            for n in nodes
            if not n.get("is_author_hint") and n["bounds"][0] < 60 and len(n["text"]) > 20
        ),
        "",
    )
    raw = f"{post_author}\x00{post_body[:_POST_PID_BODY_PREFIX_LEN]}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _apply_stat(t: str, result: Dict[str, Optional[str]]) -> None:
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
    m = _RE_REACTIONS.search(t)
    if m and result["reactions"] is None:
        label = (m.group(2) or "").lower()
        stripped = t.strip()
        if label:
            result["reactions"] = m.group(1)
        elif len(stripped) <= 8 and re.fullmatch(r"[^\d]*\d[\d.,]*[KMkm]?\s*", stripped, flags=re.IGNORECASE):
            result["reactions"] = m.group(1)


def _parse_stats(t: str) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {"reactions": None, "comments": None, "shares": None, "views": None}
    if "·" in t or "•" in t:
        parts = re.split(r"[·•]", t)
        for part in parts:
            _apply_stat(part.strip(), result)
        return result
    _apply_stat(t, result)
    return result


_RE_ACTION_BAR_COUNT = re.compile(r"^\d[\d.,]*[KMkm]?$")


def _action_bar_count_from_node(node) -> Optional[str]:
    """Read like/comment/share count from a Button's child badge (text or content-desc)."""
    for child in node.iter():
        for key in ("text", "content-desc"):
            raw = (child.get(key) or "").strip()
            if _RE_ACTION_BAR_COUNT.match(raw):
                return raw
    return None


def _extract_post_action_bar_stats(element) -> Dict[str, Optional[str]]:
    """Parse post-level Thích / Bình luận / Chia sẻ counts from the action bar row.

    FB often exposes counts only on child nodes (e.g. text=\"23\" under Button
    content-desc=\"Bình luận\"), not in the button description itself.
    """
    stats: Dict[str, Optional[str]] = {
        "reactions": None,
        "comments": None,
        "shares": None,
    }
    for node in element.iter("node"):
        cls = node.get("class") or ""
        clickable = (node.get("clickable") or "").lower() == "true"
        if "Button" not in cls and not clickable:
            continue
        count = _action_bar_count_from_node(node)
        if not count:
            continue
        desc = (node.get("content-desc") or "").strip().lower()
        text = (node.get("text") or "").strip().lower()
        label = desc or text
        if not label:
            continue
        if label in ("bình luận", "comment", "comments"):
            stats["comments"] = count
            continue
        if "chia sẻ bài viết" in label or ("nút chia sẻ" in label and "bài viết" in label):
            stats["shares"] = count
            continue
        if "bình luận của" in label:
            continue
        if label.startswith("nút thích") or label.startswith("like"):
            stats["reactions"] = count
    return stats


def _merge_action_bar_stats(post: Dict[str, Any], element) -> None:
    bar = _extract_post_action_bar_stats(element)
    for key in ("reactions", "comments", "shares"):
        value = bar.get(key)
        if value:
            post[key] = value


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


def _is_post_action_delimiter(text: str) -> bool:
    t = (text or "").strip()
    tl = t.lower()
    if tl in ("bình luận", "comment"):
        return True
    if tl.startswith("nút thích."):
        return True
    if tl.startswith("nút chia sẻ") and "bài viết" in tl:
        return True
    return False


def _is_fb_comment_thread_chrome_row(text: str) -> bool:
    tl = (text or "").strip().lower()
    if tl.startswith("nút thích bình luận"):
        return True
    if tl.startswith("trả lời bình luận"):
        return True
    if _RE_COMMENT_REACTIONS_LABEL.match((text or "").strip()):
        return True
    return False


def _is_hashtag_chip(text: str) -> bool:
    s = (text or "").strip()
    if not s.startswith("#") or " " in s or "\n" in s:
        return False
    return len(s) < 48


def _find_post_time_anchor(cluster: List[Dict[str, Any]]) -> Tuple[int, str]:
    for i, n in enumerate(cluster):
        raw = n["text"].strip()
        if len(raw) > _MAX_TS_ANCHOR_NODE_LEN:
            continue
        raw_l = raw.lower()
        if "duy nhất" in raw_l and "trước" not in raw_l and "ago" not in raw_l:
            continue
        if _RE_TS.search(raw):
            return i, raw
    for i, n in enumerate(cluster):
        if _is_post_action_delimiter(n["text"]):
            return i, ""
    return len(cluster), ""


def _merge_post_type(
    text_type: str,
    structural: Optional[str],
    rid_hint: Optional[str],
    *,
    has_fb_link: bool,
    body_len: int,
) -> str:
    out = text_type
    if rid_hint == "reel" or structural == "reel":
        out = "reel"
    elif rid_hint == "video" or structural == "video":
        if out != "reel":
            out = "video"
    elif structural == "photo" and out == "text":
        out = "photo"
    if has_fb_link and out == "text" and body_len < 56:
        out = "link"
    return out


def _extract_post(
    cluster: List[Dict[str, Any]],
    source_index: int,
    *,
    structural_type_hint: Optional[str] = None,
    resource_id_media_hint: Optional[str] = None,
    fb_post_id: Optional[str] = None,
    fb_group_id: Optional[str] = None,
    permalink_candidates: Optional[List[str]] = None,
    feed_item_index: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if not cluster:
        return None
    anchor_idx, timestamp = _find_post_time_anchor(cluster)
    all_lower = " ".join(n["text"].lower() for n in cluster)
    if _RE_REEL_TYPE.search(all_lower):
        post_type: str = "reel"
    elif _RE_VIDEO_TYPE.search(all_lower):
        post_type = "video"
    elif _RE_LINK_TYPE.search(all_lower):
        post_type = "link"
    elif _RE_POST_RESHARE_HEADER.search(all_lower) and (fb_post_id or permalink_candidates):
        post_type = "link"
    else:
        post_type = "text"

    author: Optional[str] = next((n["text"] for n in cluster if n.get("is_author_hint") and n["text"]), None)
    body_parts: List[str] = []
    reactions = comments = shares = views = None
    image_desc: Optional[str] = None
    comment_preview_parts: List[str] = []
    stats_seen: bool = False
    first_author_idx = next((i for i, n in enumerate(cluster) if n.get("is_author_hint")), None)

    for i, node in enumerate(cluster):
        t = node["text"].strip()
        t_lower = t.lower()
        if i == anchor_idx:
            continue
        if node.get("is_author_hint"):
            continue
        if len(t) <= 1 and not _RE_ACTION_BAR_COUNT.match(t):
            continue
        if _is_noise_text(t) and not (i > anchor_idx and t_lower in ("bình luận", "comment")):
            continue
        if any(t_lower.startswith(p) for p in _NOISE_PREFIXES):
            continue
        if any(token in t_lower for token in _NOISE_CONTAINS):
            continue
        if _RE_FB_CAROUSEL.search(t):
            if image_desc is None:
                image_desc = t
            continue
        if (
            i < anchor_idx
            and author is None
            and 2 <= len(t) <= 50
            and "•" not in t
            and "chia sẻ với" not in t_lower
            and "http" not in t_lower
            and "www." not in t_lower
            and not _is_hashtag_chip(t)
        ):
            author = t
            continue
        if i < anchor_idx and t != author:
            if first_author_idx is not None and i < first_author_idx:
                continue
            if image_desc is None and _RE_IMAGE_TYPE.match(t_lower) and 8 < len(t) < 300:
                image_desc = t
                continue
            body_parts.append(t)
            continue

        if i > anchor_idx:
            if image_desc is None and _RE_IMAGE_TYPE.match(t_lower) and 8 < len(t) < 300:
                image_desc = t
                continue
            if _is_post_action_delimiter(t):
                if first_author_idx is not None and i < first_author_idx:
                    continue
                stats_seen = True
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
                if first_author_idx is not None and i < first_author_idx:
                    continue
                stats_seen = True
            elif not _is_noise_text(t):
                if stats_seen:
                    if _is_fb_comment_thread_chrome_row(t):
                        continue
                    comment_preview_parts.append(t)
                else:
                    body_parts.append(t)

    comment_preview = " ".join(comment_preview_parts).strip() or None
    body = " ".join(body_parts).strip()
    if not body and image_desc:
        body = image_desc.strip()
    if body and "chia sẻ với: nhóm công khai" in body.lower() and len(body) < 60:
        body = ""
    permalinks = list(permalink_candidates or [])
    has_fb_link = bool(fb_post_id or permalinks)
    has_stats = any(v is not None for v in (reactions, comments, shares, views))
    has_signal = any((author, body, timestamp, image_desc, has_stats, has_fb_link))
    if not has_signal:
        return None
    incomplete = not (author and body)
    if image_desc and post_type == "text":
        post_type = "photo"
    post_type = _merge_post_type(
        post_type,
        structural_type_hint,
        resource_id_media_hint,
        has_fb_link=has_fb_link,
        body_len=len(body),
    )

    _pid_raw = f"{author or ''}\x00{body[:_POST_PID_BODY_PREFIX_LEN]}"
    _pid = hashlib.md5(_pid_raw.encode()).hexdigest()[:16]
    _stable_prefix = unicodedata.normalize("NFC", re.sub(r"\s+", " ", body.lower()).strip())
    _stable_prefix = _stable_prefix.replace("…", "").replace("...", "")
    for _mk in _TRUNCATION_MARKERS:
        _stable_prefix = _stable_prefix.replace(_mk, "")
    _stable_prefix = _stable_prefix.strip()[:_STABLE_POST_PREFIX_LEN]
    _sid_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    _sid_img = unicodedata.normalize("NFC", (image_desc or "").strip().lower())[:_STABLE_POST_IMAGE_PREFIX_LEN]
    _sid_raw = f"{_sid_author}\x00{_stable_prefix}\x00{_sid_img}"
    stable_post_id = hashlib.sha1(_sid_raw.encode("utf-8")).hexdigest()
    _pk_raw = f"{author or ''}\x00{body}\x00{image_desc or ''}\x00{comment_preview or ''}"
    post_key = hashlib.sha1(_pk_raw.encode("utf-8")).hexdigest()
    out: Dict[str, Any] = {
        "author": author or "",
        "text": body,
        "timestamp": timestamp,
        "reactions": reactions,
        "comments": comments,
        "shares": shares,
        "views": views,
        "source_index": source_index,
        "post_type": post_type,
        "image_desc": image_desc,
        "comment_preview": comment_preview,
        "_pid": _pid,
        "stable_post_id": stable_post_id,
        "post_key": post_key,
        "fb_post_id": fb_post_id,
        "fb_group_id": fb_group_id,
        "permalink_candidates": permalinks,
    }
    if feed_item_index is not None:
        out["feed_item_index"] = feed_item_index
    if incomplete:
        out["_incomplete"] = True
    return out


def _maybe_fix_merged_feed_caption(post: Dict[str, Any]) -> None:
    """Two feed previews glued with `**` + second post's time row — keep first caption."""
    body = post.get("text") or ""
    if "**" not in body:
        return
    main = re.split(r"\s*\*\*\s*", body, maxsplit=1)[0].strip()
    if re.search(r"Xem thêm\s+\d+\s*(?:ngày|giờ|phút)\s*•", main, re.I):
        main = re.sub(
            r"(Xem thêm)\s+\d+\s*(?:ngày|giờ|phút)\s*•.*$",
            r"\1",
            main,
            flags=re.I,
        )
    post["text"] = main


def _refresh_post_derived_hashes(post: Dict[str, Any]) -> None:
    """Recompute `_pid` / `stable_post_id` / `post_key` after mutating author or body."""
    author = post.get("author") or ""
    body = post.get("text") or ""
    image_desc = post.get("image_desc")
    comment_preview = post.get("comment_preview")

    _pid_raw = f"{author or ''}\x00{body[:_POST_PID_BODY_PREFIX_LEN]}"
    post["_pid"] = hashlib.md5(_pid_raw.encode()).hexdigest()[:16]

    _stable_prefix = unicodedata.normalize("NFC", re.sub(r"\s+", " ", body.lower()).strip())
    _stable_prefix = _stable_prefix.replace("…", "").replace("...", "")
    for _mk in _TRUNCATION_MARKERS:
        _stable_prefix = _stable_prefix.replace(_mk, "")
    _stable_prefix = _stable_prefix.strip()[:_STABLE_POST_PREFIX_LEN]

    _sid_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    _sid_img = unicodedata.normalize("NFC", (str(image_desc or "")).strip().lower())[
        :_STABLE_POST_IMAGE_PREFIX_LEN
    ]
    _sid_raw = f"{_sid_author}\x00{_stable_prefix}\x00{_sid_img}"
    post["stable_post_id"] = hashlib.sha1(_sid_raw.encode("utf-8")).hexdigest()

    _pk_raw = f"{author or ''}\x00{body}\x00{image_desc or ''}\x00{comment_preview or ''}"
    post["post_key"] = hashlib.sha1(_pk_raw.encode("utf-8")).hexdigest()


def _refine_comment_author_from_cluster(
    cluster: List[Dict[str, Any]],
    author: Optional[str],
) -> Optional[str]:
    """Like/reply button desc sometimes contains full name (e.g. Van -> Van Nguyen)."""
    if not author:
        return author
    au = unicodedata.normalize("NFC", author.strip())
    au_l = au.lower()
    best = ""
    for node in cluster:
        t = node["text"].strip()
        # These regexes live in `_core.py` for now; keep the logic using the
        # already-defined patterns by importing them lazily to avoid duplication.
        m = _RE_CMT_LIKE_BTN.match(t)
        if m:
            cand = m.group(1).strip()
            if len(cand) > len(best):
                best = cand
        m = _RE_CMT_REPLY_BTN.match(t)
        if m:
            cand = m.group(1).strip()
            if len(cand) > len(best):
                best = cand
    if not best:
        return author
    best = unicodedata.normalize("NFC", best)
    bl = best.lower()
    if len(best) > len(au) and bl.startswith(au_l):
        return best
    return author


from .comment_pipeline import _extract_comment  # noqa: E402
from .feed_pipeline import _extract_header_stats  # noqa: E402


__all__ = [
    "_merge_post_type",
    "_maybe_fix_merged_feed_caption",
    "_refresh_post_derived_hashes",
    "_refine_comment_author_from_cluster",
    "_extract_post",
    "_extract_comment",
    "_extract_media_artifacts",
    "_extract_fb_link_meta",
    "_resource_id_media_hint",
    "_structural_post_type_hint",
    "_compute_post_id_from_nodes",
    "_extract_header_stats",
]

