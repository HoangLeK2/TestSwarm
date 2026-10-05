"""Resolve how child content rows link to a parent content item."""
from __future__ import annotations

from typing import Any

from db.models.content import ContentItem
from services.content_store import compute_content_hash, scope_content_hash

_PARENT_ID_RAW_KEYS = (
    "post_key",
    "parent_post_id",
    "_pid",
    "stable_post_id",
)


def _raw_dict(item: ContentItem) -> dict[str, Any]:
    raw = item.raw_data
    if isinstance(raw, dict):
        return raw
    return {}


def _payload_for_hash(item: ContentItem) -> dict[str, Any]:
    raw = _raw_dict(item)
    if raw:
        return raw
    payload: dict[str, Any] = {}
    if item.body:
        payload["text"] = item.body
    if item.title:
        payload["title"] = item.title
    if item.author:
        payload["author"] = item.author
    return payload


def parent_link_candidates(item: ContentItem) -> list[str]:
    """All parent_id values that may appear on comments for this post."""
    out: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    add(item.content_hash)
    scope = item.execution_id
    payload = _payload_for_hash(item)

    for dedupe_field in ("post_key", "text", None):
        try:
            base = compute_content_hash(payload, dedupe_field)
        except Exception:
            continue
        add(base)
        if scope:
            add(scope_content_hash(base, scope))

    raw = _raw_dict(item)
    for key in _PARENT_ID_RAW_KEYS:
        add(raw.get(key))

    # Legacy bug: parent hash was scoped twice at save time.
    if scope and item.content_hash:
        add(scope_content_hash(item.content_hash, scope))

    return out


def parent_post_id_values(item: ContentItem) -> list[str]:
    """Parser post ids on the parent — match comment raw_data.parent_post_id."""
    raw = _raw_dict(item)
    out: list[str] = []
    seen: set[str] = set()
    for key in _PARENT_ID_RAW_KEYS:
        text = str(raw.get(key) or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
