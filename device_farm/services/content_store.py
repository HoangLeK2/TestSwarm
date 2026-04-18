"""DF-010: Content Store — save extracted content with deduplication."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

try:
    import ftfy as _ftfy  # type: ignore
except Exception:
    _ftfy = None

try:
    import dateparser as _dateparser  # type: ignore
except Exception:
    _dateparser = None


def clean_text(text: Any) -> Any:
   
    if not isinstance(text, str) or not text:
        return text
    if _ftfy is None:
        return text.strip()
    try:
        return _ftfy.fix_text(text).strip()
    except Exception:
        return text.strip()


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


def scope_content_hash(base_hash: str, execution_id: str | None = None) -> str:
    """Scope hash by execution so each run can persist historical data.

    - When execution_id is None: keep backward-compatible hash.
    - When execution_id exists: same content in different runs becomes distinct.
    """
    if not execution_id:
        return base_hash
    raw = f"{execution_id}:{base_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    """Return first key that exists and is not None."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _normalize_media_urls(value: Any) -> list[str]:
    """Normalize media URL/container payload to a JSON-safe list[str]."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v is not None and str(v).strip()]
            except Exception:
                pass
        return [s]
    return []


_RE_RELATIVE_TIME = re.compile(
    r"^\s*(\d+)\s*(giây|phút|giờ|ngày|tuần|tháng|năm|second|minute|hour|day|week|month|year)s?\s*(trước|ago)?\s*$",
    re.IGNORECASE,
)
_RE_CALENDAR_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def _parse_content_date(value: Any) -> datetime | None:
    """Best-effort parser for extracted publish timestamps."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    s = str(value).strip()
    if not s:
        return None

    # Normalize common separators/whitespace from mobile a11y content.
    s_clean = s.replace("\u00a0", " ").replace("\u202f", " ").strip()
    s_lower = s_clean.lower()

    # ISO / RFC-ish timestamps first.
    try:
        if "t" in s_lower or "-" in s_lower:
            iso_raw = re.sub(r"[Zz]$", "+00:00", s_clean)
            parsed = datetime.fromisoformat(iso_raw)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    # dd/mm/yyyy
    m = _RE_CALENDAR_DATE.match(s_clean)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    now = datetime.now(timezone.utc)
    if s_lower in {"hôm qua", "yesterday"}:
        return now - timedelta(days=1)
    if s_lower in {"just now", "vừa xong", "bây giờ", "now"}:
        return now

    m = _RE_RELATIVE_TIME.match(s_lower)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit in {"giây", "second"}:
            return now - timedelta(seconds=amount)
        if unit in {"phút", "minute"}:
            return now - timedelta(minutes=amount)
        if unit in {"giờ", "hour"}:
            return now - timedelta(hours=amount)
        if unit in {"ngày", "day"}:
            return now - timedelta(days=amount)
        if unit in {"tuần", "week"}:
            return now - timedelta(weeks=amount)
        if unit in {"tháng", "month"}:
            return now - timedelta(days=30 * amount)
        if unit in {"năm", "year"}:
            return now - timedelta(days=365 * amount)

    # "March 15", "3/15/2026", "yesterday at 5pm", "il y a 2 heures", etc.
    if _dateparser is not None:
        try:
            dt = _dateparser.parse(
                s_clean,
                languages=["vi", "en"],
                settings={
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "PREFER_DAY_OF_MONTH": "first",
                    "TO_TIMEZONE": "UTC",
                    "RELATIVE_BASE": now.replace(tzinfo=None),
                },
            )
            if dt is not None:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    return None


async def save_content_item(
    data: dict[str, Any],
    collection: str = "default",
    platform: str | None = None,
    content_type: str = "post",
    device_serial: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
    scenario_name: str | None = None,
    dedupe_field: str | None = None,
    screenshot_bytes: bytes | None = None,
    tags: str = "",
    parent_id: str | None = None,
    item_level: int = 0,
    user_id: str | None = None,
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

    base_hash = compute_content_hash(data, dedupe_field)
    content_hash = scope_content_hash(base_hash, execution_id)
    scoped_parent_id = scope_content_hash(parent_id, execution_id) if parent_id else None

    # Phase 5 — Bloom filter fast path. Skips DB when probably duplicate.
    # Graceful no-op when Redis/RedisBloom unavailable. False positives
    # (~0.1%) are still verified in DB before returning "duplicate".
    bloom_bucket = f"content:{collection}"
    try:
        from services import bloom_dedup
        if await bloom_dedup.is_duplicate(bloom_bucket, content_hash):
            async with activity_session() as db:
                existing = await get_content_by_hash(
                    db, content_hash, collection,
                    user_id=user_id, execution_id=execution_id,
                )
                if existing:
                    return {"saved": False, "reason": "duplicate", "id": existing.id, "via": "bloom"}
    except Exception as exc:
        log.debug("bloom fast path skipped (%s)", exc)

    async with activity_session() as db:
        # Dedup check
        existing = await get_content_by_hash(
            db,
            content_hash,
            collection,
            user_id=user_id,
            execution_id=execution_id,
        )
        if existing:
            return {"saved": False, "reason": "duplicate", "id": existing.id}

        # Ensure collection exists
        await get_or_create_collection(
            db,
            collection,
            platform=platform,
            content_type=content_type,
            user_id=user_id,
        )

        # Save screenshot if provided
        screenshot_path = None
        if screenshot_bytes:
            screenshot_path = _save_screenshot(screenshot_bytes, content_hash)

        # Map known fields from data dict
        _body = clean_text(
            data.get("content")
            or data.get("body")
            or data.get("text")
            or data.get("message")
            or data.get("caption")
            or data.get("description")
        )
        _author = clean_text(
            data.get("author")
            or data.get("name")
            or data.get("username")
            or data.get("full_name")
        )
        _url = (
            data.get("url")
            or data.get("permalink")
            or data.get("link")
        )
        _media_urls = _normalize_media_urls(
            _first_present(data, "media_urls", "media_artifacts", "permalink_candidates")
        )
        _content_date = _parse_content_date(
            _first_present(
                data,
                "content_date",
                "posted_at",
                "published_at",
                "timestamp",
                "date",
                "date_posted",
            )
        )

        item = await create_content_item(
            db,
            collection=collection,
            platform=platform,
            content_type=content_type,
            title=str(data.get("title") or "")[:500] or None,
            body=_body,
            author=str(_author or "")[:255] or None,
            author_id=str(data.get("author_id") or "")[:255] or None,
            url=str(_url or "")[:1000] or None,
            likes_count=_safe_int(_first_present(data, "likes_count", "likes", "reactions", "like")),
            comments_count=_safe_int(_first_present(data, "comments_count", "comments", "comment")),
            shares_count=_safe_int(_first_present(data, "shares_count", "shares", "share")),
            views_count=_safe_int(_first_present(data, "views_count", "views", "view")),
            media_urls=_media_urls,
            raw_data=data,
            tags=tags,
            content_hash=content_hash,
            device_serial=device_serial,
            campaign_id=campaign_id,
            execution_id=execution_id,
            scenario_name=scenario_name,
            screenshot_path=screenshot_path,
            content_date=_content_date,
            parent_id=scoped_parent_id,
            item_level=item_level,
            user_id=user_id,
        )

        await increment_collection_count(db, collection, user_id=user_id)
        await db.commit()

        # Phase 5 — record in Bloom filter so future checks fast-path.
        try:
            from services import bloom_dedup
            await bloom_dedup.mark_seen(bloom_bucket, content_hash)
        except Exception as exc:
            log.debug("bloom mark_seen skipped (%s)", exc)

        log.info(f"Content saved: id={item.id} collection={collection} hash={content_hash[:12]}")
        return {"saved": True, "id": item.id}


def _save_screenshot(data: bytes, content_hash: str) -> str:
    """
    Save screenshot bytes. Returns URL/path string stored in DB.

    Tries MinIO first; falls back to local filesystem.
    Skips blank/black frames (quality gate in object storage / minio_store).
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
