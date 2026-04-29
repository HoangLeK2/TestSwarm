from __future__ import annotations

from typing import Any, Dict, List, Optional

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

from .dedup import _TRUNCATION_MARKERS


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

    _pid_raw = f"{author or ''}\x00{body[:120]}"
    post["_pid"] = hashlib.md5(_pid_raw.encode()).hexdigest()[:16]

    _stable_prefix = unicodedata.normalize("NFC", re.sub(r"\s+", " ", body.lower()).strip())
    _stable_prefix = _stable_prefix.replace("…", "").replace("...", "")
    for _mk in _TRUNCATION_MARKERS:
        _stable_prefix = _stable_prefix.replace(_mk, "")
    _stable_prefix = _stable_prefix.strip()[:100]

    _sid_author = unicodedata.normalize("NFC", (author or "").strip().lower())
    _sid_img = unicodedata.normalize("NFC", (str(image_desc or "")).strip().lower())[:40]
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
        m = _core._RE_CMT_LIKE_BTN.match(t)
        if m:
            cand = m.group(1).strip()
            if len(cand) > len(best):
                best = cand
        m = _core._RE_CMT_REPLY_BTN.match(t)
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


# Temporary re-exports (to be moved in later phases).
from . import _impl as _core  # noqa: E402

_extract_post = _core._extract_post
_extract_comment = _core._extract_comment
_extract_media_artifacts = _core._extract_media_artifacts
_extract_fb_link_meta = _core._extract_fb_link_meta
_extract_header_stats = _core._extract_header_stats


__all__ = [
    "_merge_post_type",
    "_maybe_fix_merged_feed_caption",
    "_refresh_post_derived_hashes",
    "_refine_comment_author_from_cluster",
    "_extract_post",
    "_extract_comment",
    "_extract_media_artifacts",
    "_extract_fb_link_meta",
    "_extract_header_stats",
]

