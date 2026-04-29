from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Tuple

# Post *body* still folded / lazy — same markers used by extract retry + quality scoring.
_TRUNCATION_MARKERS: Tuple[str, ...] = (
    "xem thêm",
    "see more",
    "view more",
    "xem thêm bình luận",
    "view more comments",
    "xem thêm câu trả lời",
    "view more replies",
)


def _dedup(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate feed posts while preferring the richer/fuller version.

    Key keeps compatibility with historical behavior:
    same author + timestamp + text-prefix[:60] is considered the same post.
    """
    by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []

    def _quality(post: Dict[str, Any]) -> Tuple[int, int, int]:
        text = str(post.get("text") or "")
        stats_count = sum(
            1
            for k in ("reactions", "comments", "shares", "views", "image_desc", "comment_preview")
            if post.get(k)
        )
        unresolved = int(any(mk in text.lower() for mk in _TRUNCATION_MARKERS))
        # Prefer resolved/non-truncated text first, then length, then richer metadata.
        return (-unresolved, len(text), stats_count)

    def _norm_text(value: str) -> str:
        t = unicodedata.normalize("NFC", (value or "").lower())
        t = re.sub(r"\s+", " ", t).strip()
        for mk in _TRUNCATION_MARKERS:
            t = t.replace(mk, "")
        return re.sub(r"\s+", " ", t).strip()

    def _likely_same_logical_post(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        ta = _norm_text(str(a.get("text") or ""))
        tb = _norm_text(str(b.get("text") or ""))
        if not ta or not tb:
            return True
        # Truncated/expanded variants usually keep one body as prefix of the other.
        return ta.startswith(tb) or tb.startswith(ta)

    for p in posts:
        stable_post_id = str(p.get("stable_post_id") or "")
        timestamp = str(p.get("timestamp") or "")
        if stable_post_id:
            key = ("sid", stable_post_id)
        else:
            # Backward compatibility fallback for old records without stable_post_id.
            author = str(p.get("author") or "")
            text = str(p.get("text") or "")
            key = ("legacy", f"{author}\x00{timestamp}\x00{text[:60]}")

        existing = by_key.get(key)
        if existing is None:
            by_key[key] = p
            order.append(key)
            continue

        # Guard against stable-id collisions (same sid but clearly different bodies).
        if key[0] == "sid" and not _likely_same_logical_post(existing, p):
            collision_key = ("sid-collision", f"{stable_post_id}\x00{p.get('post_key') or p.get('_pid') or len(order)}")
            if collision_key not in by_key:
                by_key[collision_key] = p
                order.append(collision_key)
            continue

        if _quality(p) > _quality(existing):
            by_key[key] = p

    return [by_key[k] for k in order]


def _dedup_comments(comments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate comments: same author + text[:60] = same comment."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for c in comments:
        key = c.get("comment_key") or (c["author"], c["text"][:60])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


__all__ = ["_dedup", "_dedup_comments"]

