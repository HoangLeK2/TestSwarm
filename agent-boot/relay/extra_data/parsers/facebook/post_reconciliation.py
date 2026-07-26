from __future__ import annotations

import re
import unicodedata
from typing import Any

from .dedup import _dedup
from .post_extractor import (
    _refresh_post_derived_hashes,
    _split_author_prefix_from_timestamp,
)

_TRUNCATION_MARKERS = ("xem thêm", "see more", "view more")
_TRAILING_MEDIA_LABELS = ("ảnh", "photo", "video", "bật tiếng", "turn on sound")
_UNRELIABLE_AUTHORS = {
    "nội dung do ai tạo",
    "ai-generated content",
    "đáng chú ý",
    "featured",
}
_GROUP_CHROME_PREFIXES = (
    "tham gia nhóm ",
    "join group ",
)
_GROUP_COVER_MARKERS = (
    "ảnh bìa của nhóm",
    "group cover photo",
)
_IDENTITY_PAIRS = (
    ("_pid", "pid"),
    ("post_key", "post_key"),
    ("stable_post_id", "stable_post_id"),
    ("fb_post_id", "fb_post_id"),
)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    text = text.replace("…", " ").replace("...", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .·•-\n\t")


def _clean_preview(value: Any) -> str:
    text = _norm(value)
    for marker in _TRUNCATION_MARKERS:
        text = text.replace(marker, " ")
    text = re.sub(
        rf"(?:{'|'.join(re.escape(label) for label in _TRAILING_MEDIA_LABELS)})\s*$",
        "",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _identity_matches(post: dict[str, Any], opened: dict[str, Any]) -> bool:
    for post_key, opened_key in _IDENTITY_PAIRS:
        left = str(post.get(post_key) or "").strip()
        right = str(opened.get(opened_key) or "").strip()
        if left and right and left == right:
            return True
    return False


def _timestamp_parts(post: dict[str, Any]) -> tuple[str | None, str]:
    embedded, timestamp = _split_author_prefix_from_timestamp(
        str(post.get("timestamp") or "")
    )
    return embedded, _norm(timestamp)


def _body_anchor_regex(feed_text: Any) -> re.Pattern[str] | None:
    preview = _clean_preview(feed_text)
    words = re.findall(r"[\wÀ-ỹ]+", preview, flags=re.UNICODE)
    if len(words) < 4:
        return None
    # Drop the final word because Facebook often truncates in the middle of it
    # ("B…" in feed vs "BUILD" in detail).
    anchor_words = words[: min(8, max(4, len(words) - 1))]
    pattern = r"\s+".join(re.escape(word) for word in anchor_words)
    return re.compile(pattern, flags=re.IGNORECASE | re.UNICODE)


def _body_match_score(feed: dict[str, Any], detail: dict[str, Any]) -> int:
    feed_text = _clean_preview(feed.get("text"))
    detail_text = _norm(detail.get("text"))
    if len(feed_text) < 16 or len(detail_text) < 16:
        return 0
    if feed_text in detail_text or detail_text in feed_text:
        return 70
    anchor = _body_anchor_regex(feed.get("text"))
    return 55 if anchor is not None and anchor.search(str(detail.get("text") or "")) else 0


def _detail_match_score(
    feed: dict[str, Any],
    detail: dict[str, Any],
) -> int:
    score = 0
    if _identity_matches(detail, {
        "pid": feed.get("_pid"),
        "post_key": feed.get("post_key"),
        "stable_post_id": feed.get("stable_post_id"),
        "fb_post_id": feed.get("fb_post_id"),
    }):
        score += 100
    score += _body_match_score(feed, detail)
    _, feed_timestamp = _timestamp_parts(feed)
    _, detail_timestamp = _timestamp_parts(detail)
    if feed_timestamp and detail_timestamp and feed_timestamp == detail_timestamp:
        score += 35
    feed_author = _norm(feed.get("author"))
    detail_author, _ = _timestamp_parts(detail)
    reliable_detail_author = _norm(detail_author or detail.get("author"))
    if (
        feed_author
        and reliable_detail_author
        and feed_author == reliable_detail_author
        and feed_author not in _UNRELIABLE_AUTHORS
    ):
        score += 15
    return score


def _is_detail_chrome(post: dict[str, Any]) -> bool:
    author = _norm(post.get("author"))
    text = _norm(post.get("text"))
    image_desc = _norm(post.get("image_desc"))
    if author in {"đáng chú ý", "featured"}:
        return True
    if any(text.startswith(prefix) for prefix in _GROUP_CHROME_PREFIXES):
        return True
    return bool(image_desc and any(marker in image_desc for marker in _GROUP_COVER_MARKERS) and not text)


def _canonical_detail_body(feed: dict[str, Any], detail: dict[str, Any]) -> str:
    body = str(detail.get("text") or "").strip()
    anchor = _body_anchor_regex(feed.get("text"))
    match = anchor.search(body) if anchor is not None else None
    if match is not None:
        body = body[match.start():].strip()
    for marker in _TRUNCATION_MARKERS:
        body = re.sub(rf"\b{re.escape(marker)}\b", " ", body, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", body).strip()


def _source_variant(post: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key in ("_pid", "post_key", "stable_post_id", "fb_post_id", "source_index")
        if (value := post.get(key)) is not None and str(value).strip()
    }


def _merge_opened_post_variants(
    feed: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    canonical = dict(feed)
    detail_author, detail_timestamp = _split_author_prefix_from_timestamp(
        str(detail.get("timestamp") or "")
    )
    if detail_author and _norm(detail_author) not in _UNRELIABLE_AUTHORS:
        canonical["author"] = detail_author.strip()
    elif _norm(detail.get("author")) not in _UNRELIABLE_AUTHORS:
        canonical["author"] = detail.get("author")
    if detail_timestamp:
        canonical["timestamp"] = detail_timestamp

    detail_body = _canonical_detail_body(feed, detail)
    if len(detail_body) > len(_clean_preview(feed.get("text"))):
        canonical["text"] = detail_body

    for field in ("reactions", "comments", "shares", "views"):
        if canonical.get(field) is None and detail.get(field) is not None:
            canonical[field] = detail[field]

    detail_image = _norm(detail.get("image_desc"))
    if detail.get("image_desc") and not any(
        marker in detail_image for marker in _GROUP_COVER_MARKERS
    ):
        canonical["image_desc"] = detail["image_desc"]

    canonical["_source_variants"] = [
        _source_variant(feed),
        _source_variant(detail),
    ]
    canonical["_canonicalized_from_detail"] = True
    _refresh_post_derived_hashes(canonical)
    return canonical


def reconcile_fb_post_frames(
    frame_posts: list[list[dict[str, Any]]],
    *,
    opened_post: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reconcile feed identity with richer post-detail content.

    Feed rows remain the interaction authority. The selected detail row enriches
    the canonical content record, while unrelated content rows are preserved
    and obvious Facebook group chrome is discarded from every frame.
    """
    if not frame_posts:
        return [], {"reconciled_post_count": 0, "detail_chrome_dropped": 0}

    feed_posts = [dict(post) for post in frame_posts[0] if isinstance(post, dict)]
    detail_posts = [
        dict(post)
        for frame in frame_posts[1:]
        for post in frame
        if isinstance(post, dict)
    ]
    if not feed_posts or not detail_posts or not opened_post:
        return _dedup(feed_posts + detail_posts), {
            "reconciled_post_count": 0,
            "detail_chrome_dropped": 0,
        }

    feed_index = next(
        (
            index
            for index, post in enumerate(feed_posts)
            if _identity_matches(post, opened_post)
        ),
        None,
    )
    if feed_index is None:
        return _dedup(feed_posts + detail_posts), {
            "reconciled_post_count": 0,
            "detail_chrome_dropped": 0,
        }

    feed_target = feed_posts[feed_index]
    chrome_dropped = 0
    filtered_feed_posts: list[dict[str, Any]] = []
    for index, post in enumerate(feed_posts):
        if index != feed_index and _is_detail_chrome(post):
            chrome_dropped += 1
            continue
        filtered_feed_posts.append(post)
    content_detail_posts: list[tuple[int, dict[str, Any]]] = []
    for index, post in enumerate(detail_posts):
        if _is_detail_chrome(post):
            chrome_dropped += 1
            continue
        content_detail_posts.append((index, post))

    scored_details = [
        (_detail_match_score(feed_target, post), index, post)
        for index, post in content_detail_posts
    ]
    score, detail_index, detail_target = max(scored_details, default=(0, -1, {}))
    if score < 55:
        return _dedup(filtered_feed_posts + [post for _, post in content_detail_posts]), {
            "reconciled_post_count": 0,
            "detail_chrome_dropped": chrome_dropped,
        }

    feed_posts[feed_index] = _merge_opened_post_variants(feed_target, detail_target)
    feed_posts_without_chrome: list[dict[str, Any]] = []
    for index, post in enumerate(feed_posts):
        if index != feed_index and _is_detail_chrome(post):
            continue
        feed_posts_without_chrome.append(post)

    remaining_detail: list[dict[str, Any]] = []
    for index, post in enumerate(detail_posts):
        if index == detail_index:
            continue
        if _is_detail_chrome(post):
            continue
        remaining_detail.append(post)

    return _dedup(feed_posts_without_chrome + remaining_detail), {
        "reconciled_post_count": 1,
        "detail_chrome_dropped": chrome_dropped,
    }
