"""DF-010: Content Store — save extracted content with deduplication."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import unicodedata
from typing import Any

log = logging.getLogger(__name__)


def compute_content_hash(
    data: dict[str, Any],
    dedupe_field: str | None = None,
) -> str:
    """
    Compute SHA256 hash for content deduplication.

    If dedupe_field is set and exists in data, hash only that field.
    Otherwise hash the full data dict with deterministic JSON serialization.

    Unicode is NFC-normalized before hashing to handle composed/decomposed forms.
    """
    if dedupe_field and dedupe_field in data:
        raw = str(data[dedupe_field])
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, default=str)

    normalized = unicodedata.normalize("NFC", raw.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_int(val: Any) -> int | None:
    """Parse value to int, handling strings like '1.2K', '45K', etc."""
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return None
    # Handle suffixes: 1.2K → 1200, 45K → 45000, 1.5M → 1500000
    multiplier = 1
    if s[-1].upper() == "K":
        multiplier = 1000
        s = s[:-1]
    elif s[-1].upper() == "M":
        multiplier = 1_000_000
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except (ValueError, TypeError):
        return None


async def save_content_item(
    data: dict[str, Any],
    collection: str = "default",
    platform: str | None = None,
    content_type: str = "post",
    device_serial: str | None = None,
    campaign_id: str | None = None,
    run_id: str | None = None,
    execution_id: str | None = None,
    scenario_name: str | None = None,
    dedupe_field: str | None = None,
    screenshot_bytes: bytes | None = None,
    tags: str = "",
    parent_id: str | None = None,
    item_level: int = 0,
) -> dict[str, Any]:
    """
    Save extracted content to database with deduplication.

    Returns {"saved": True, "id": ...} or {"saved": False, "reason": "duplicate", "id": ...}
    """
    from db.database import activity_session
    from db.crud.content import (
        create_content_item, get_content_by_hash,
        get_or_create_collection, increment_collection_count,
    )

    content_hash = compute_content_hash(data, dedupe_field)

    async with activity_session() as db:
        # Dedup check
        existing = await get_content_by_hash(db, content_hash, collection)
        if existing:
            return {"saved": False, "reason": "duplicate", "id": existing.id}

        # Ensure collection exists
        await get_or_create_collection(db, collection, platform=platform, content_type=content_type)

        # Save screenshot if provided
        screenshot_path = None
        if screenshot_bytes:
            screenshot_path = _save_screenshot(screenshot_bytes, content_hash)

        # Map known fields from data dict
        item = await create_content_item(
            db,
            collection=collection,
            platform=platform,
            content_type=content_type,
            title=str(data.get("title") or "")[:500] or None,
            body=data.get("content") or data.get("body") or data.get("text"),
            author=str(data.get("author") or "")[:255] or None,
            author_id=str(data.get("author_id") or "")[:255] or None,
            url=str(data.get("url") or "")[:1000] or None,
            likes_count=_safe_int(data.get("likes_count") or data.get("likes")),
            comments_count=_safe_int(data.get("comments_count") or data.get("comments")),
            shares_count=_safe_int(data.get("shares_count") or data.get("shares")),
            views_count=_safe_int(data.get("views_count") or data.get("views")),
            media_urls=data.get("media_urls", []),
            raw_data=data,
            tags=tags,
            content_hash=content_hash,
            device_serial=device_serial,
            campaign_id=campaign_id,
            run_id=run_id,
            execution_id=execution_id,
            scenario_name=scenario_name,
            screenshot_path=screenshot_path,
            parent_id=parent_id,
            item_level=item_level,
        )

        await increment_collection_count(db, collection)
        await db.commit()

        log.info(f"Content saved: id={item.id} collection={collection} hash={content_hash[:12]}")
        return {"saved": True, "id": item.id}


def _save_screenshot(data: bytes, content_hash: str) -> str:
    """
    Save screenshot bytes. Returns URL/path string stored in DB.

    Tries MinIO first; falls back to local filesystem.
    Skips blank/black frames (quality gate in minio_store).
    """
    from services import minio_store

    if not minio_store.is_quality_ok(data):
        log.debug("content_store: skipped blank/black screenshot %s", content_hash[:12])
        return ""

    object_name = f"content-screenshots/{content_hash[:16]}.jpg"
    if minio_store.enabled():
        url = minio_store.upload(data, object_name)
        if url:
            return url

    # Local fallback
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screenshots")
    os.makedirs(base, exist_ok=True)
    filename = f"{content_hash[:16]}.jpg"
    path = os.path.join(base, filename)
    with open(path, "wb") as f:
        f.write(data)
    return f"screenshots/{filename}"
