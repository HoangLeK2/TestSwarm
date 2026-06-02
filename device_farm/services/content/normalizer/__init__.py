"""Unified content normalizer (DF-T-06-007)."""
from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from services.content.errors import NormalizationError
from services.content.normalizer.models import NormalizedContent, NormalizedCounters
from services.content_store import _parse_content_date, _safe_int, clean_text

log = logging.getLogger(__name__)

_MAX_RAW_BYTES = 1_048_576
_STANDARD_KEYS = frozenset(
    {
        "content_type",
        "platform",
        "text_content",
        "text",
        "body",
        "content",
        "message",
        "caption",
        "description",
        "title",
        "author",
        "author_name",
        "author_id",
        "username",
        "name",
        "full_name",
        "url",
        "permalink",
        "link",
        "external_id",
        "id",
        "media_urls",
        "media_artifacts",
        "permalink_candidates",
        "posted_at",
        "published_at",
        "timestamp",
        "date",
        "date_posted",
        "content_date",
        "likes",
        "likes_count",
        "reactions",
        "like",
        "comments",
        "comments_count",
        "comment",
        "shares",
        "shares_count",
        "share",
        "views",
        "views_count",
        "view",
        "followers",
        "followers_count",
        "follower_count",
        "following",
        "following_count",
        "bio",
        "is_verified",
        "counters",
    }
)


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _media_urls(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v).strip()]
    if isinstance(value, str) and value.strip():
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v is not None and str(v).strip()]
            except Exception:
                pass
        return [value.strip()]
    return []


def _extract_counters(data: dict[str, Any]) -> NormalizedCounters:
    nested = data.get("counters")
    if isinstance(nested, dict):
        return NormalizedCounters(
            likes=_safe_int(_first(nested, "likes", "like", "reactions")),
            comments=_safe_int(_first(nested, "comments", "comment")),
            shares=_safe_int(_first(nested, "shares", "share")),
            views=_safe_int(_first(nested, "views", "view")),
            followers=_safe_int(_first(nested, "followers", "follower_count")),
            following=_safe_int(_first(nested, "following", "following_count")),
        )
    return NormalizedCounters(
        likes=_safe_int(_first(data, "likes_count", "likes", "reactions", "like")),
        comments=_safe_int(_first(data, "comments_count", "comments", "comment")),
        shares=_safe_int(_first(data, "shares_count", "shares", "share")),
        views=_safe_int(_first(data, "views_count", "views", "view")),
        followers=_safe_int(_first(data, "followers_count", "followers", "follower_count")),
        following=_safe_int(_first(data, "following_count", "following")),
    )


def _split_raw(data: dict[str, Any]) -> dict[str, Any]:
    raw = {k: v for k, v in data.items() if k not in _STANDARD_KEYS}
    encoded = json.dumps(raw, sort_keys=True, default=str).encode("utf-8")
    if len(encoded) > _MAX_RAW_BYTES:
        raise NormalizationError(
            "raw_data exceeds 1 MB limit",
            code="RAW_DATA_SIZE_EXCEEDED",
            details={"size_bytes": len(encoded)},
        )
    return raw


def _require_content(data: dict[str, Any], *, content_type: str) -> None:
    text = clean_text(
        _first(data, "text_content", "text", "body", "content", "message", "caption", "description")
    )
    media = _media_urls(_first(data, "media_urls", "media_artifacts", "permalink_candidates"))
    permalink = _first(data, "permalink", "url", "link")
    if content_type == "ig_profile":
        username = _first(data, "username", "author_id", "author")
        if not username:
            raise NormalizationError(
                "ig_profile requires username",
                code="NORMALIZATION_MISSING_FIELDS",
                details={"missing": ["username"]},
            )
        return
    if not text and not media and not permalink:
        raise NormalizationError(
            "content item has no text, media, or permalink",
            code="NORMALIZATION_MISSING_FIELDS",
            details={"missing": ["text_or_media_required", "permalink"]},
        )


def normalize(engine_output: dict[str, Any], content_type: str, *, hint_config: dict | None = None) -> NormalizedContent:
    """Normalize engine output to standard content schema."""
    from services.content.registry import get_registry

    entry = get_registry().get(content_type)
    if entry is None:
        raise NormalizationError(
            f"unknown content_type: {content_type}",
            code="CONTENT_TYPE_NOT_REGISTERED",
        )

    data = deepcopy(engine_output or {})
    if isinstance(data.get("data"), dict):
        data = {**data["data"], **{k: v for k, v in data.items() if k != "data"}}

    _require_content(data, content_type=content_type)

    text = clean_text(
        _first(data, "text_content", "text", "body", "content", "message", "caption", "description")
    )
    counters = _extract_counters(data)
    posted_at = _parse_content_date(
        _first(data, "posted_at", "published_at", "timestamp", "date", "date_posted", "content_date")
    )
    external_id = _first(data, "external_id", "id")
    if external_id is not None:
        external_id = str(external_id)[:255]

    normalized = NormalizedContent(
        content_type=content_type,
        platform=entry.platform,
        text_content=text,
        title=str(data.get("title") or "")[:500] or None,
        author_id=str(_first(data, "author_id", "username") or "")[:255] or None,
        author_name=str(clean_text(_first(data, "author_name", "author", "name", "full_name")) or "")[:255] or None,
        permalink=str(_first(data, "permalink", "url", "link") or "")[:1000] or None,
        external_id=external_id,
        media_urls=_media_urls(_first(data, "media_urls", "media_artifacts", "permalink_candidates")),
        counters=counters,
        posted_at=posted_at,
        raw_data=_split_raw(data),
    )
    return normalized
