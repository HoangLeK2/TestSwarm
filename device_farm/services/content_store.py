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

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _content_images_enabled() -> bool:
    return _env_bool("DEVICE_FARM_CONTENT_IMAGES_ENABLED", False)


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
    scenario_id: str | None = None,
    device_id: str | None = None,
    account_id: str | None = None,
    dedupe_field: str | None = None,
    dedup_action: str = "skip",
    screenshot_bytes: bytes | None = None,
    tags: str = "",
    parent_id: str | None = None,
    parent_id_already_scoped: bool = False,
    item_level: int | None = None,
    user_id: str | None = None,
    org_id: str | None = None,
    hash_scope: str | None = None,
    db: AsyncSession | None = None,
    *,
    skip_normalization: bool = False,
    skip_type_validation: bool = False,
) -> dict[str, Any]:
    """
    Save extracted content to database with deduplication.

    hash_scope: used only for per-run dedup scoping; NOT stored as FK.
                Falls back to execution_id when absent.

    Returns {"saved": True, "id": ...} or {"saved": False, "reason": "duplicate", "id": ...}
    """
    from services.content.errors import ContentTypeError
    from services.content.registry import get_registry, require_valid_content_type

    if not skip_type_validation:
        from services.content.legacy_type_map import qualify_content_type

        qualified = qualify_content_type(content_type, platform=platform) or content_type
        type_entry = require_valid_content_type(qualified, caller_id=user_id)
        content_type = qualified
        if not platform:
            platform = type_entry.platform

    payload = dict(data or {})
    if not skip_normalization and not skip_type_validation:
        from services.content.normalizer import normalize

        normalized = normalize(payload, content_type)
        payload = normalized.to_content_store_dict()
        platform = platform or normalized.platform

    from services.content.secret_scrub import scrub_secrets

    payload = scrub_secrets(payload)
    from tenancy.context import get_current_org_id
    from db.crud.content import (
        create_content_item, get_content_by_hash,
        get_or_create_collection, increment_collection_count,
    )

    scope = hash_scope or execution_id
    base_hash = compute_content_hash(payload, dedupe_field)
    content_hash = scope_content_hash(base_hash, scope)
    if parent_id and parent_id_already_scoped:
        scoped_parent_id = str(parent_id)
    else:
        scoped_parent_id = scope_content_hash(parent_id, scope) if parent_id else None
    external_id = payload.get("external_id")
    if external_id is not None:
        external_id = str(external_id)[:255]

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
                    user_id=user_id, execution_id=scope,
                )
                if existing:
                    return {"saved": False, "reason": "duplicate", "id": existing.id, "via": "bloom"}
    except Exception as exc:
        log.debug("bloom fast path skipped (%s)", exc)

    owns_session = db is None

    async def _save_with_session(db_session: AsyncSession, *, owns_session: bool) -> dict[str, Any]:
        from db.crud.content import compute_item_level, resolve_org_id
        from services.content.campaign_ref import resolve_persist_campaign_id
        from services.content.dedup import apply_external_id_dedup

        nonlocal campaign_id
        campaign_id = await resolve_persist_campaign_id(
            db_session,
            campaign_id=campaign_id,
            execution_id=execution_id or scope,
        )

        effective_org = org_id or get_current_org_id() or await resolve_org_id(db_session, user_id=user_id)
        if effective_org and external_id:
            dedup_result = await apply_external_id_dedup(
                db_session,
                org_id=effective_org,
                collection=collection,
                platform=platform,
                external_id=external_id,
                normalized_data=payload,
                dedup_action=dedup_action,  # type: ignore[arg-type]
            )
            if dedup_result is not None:
                if owns_session:
                    await db_session.commit()
                return dedup_result

        resolved_level = item_level
        if resolved_level is None:
            resolved_level = await compute_item_level(db_session, scoped_parent_id)

        # Dedup check
        existing = await get_content_by_hash(
            db_session,
            content_hash,
            collection,
            user_id=user_id,
            execution_id=scope,
        )
        if existing:
            return {"saved": False, "reason": "duplicate", "id": existing.id}

        # Ensure collection exists
        await get_or_create_collection(
            db_session,
            collection,
            platform=platform,
            content_type=content_type,
            user_id=user_id,
        )

        # Screenshot: bytes → object storage; else URL from payload or linked execution.
        screenshot_path = await _resolve_content_screenshot_path(
            db_session,
            payload=payload,
            execution_id=execution_id,
            screenshot_bytes=screenshot_bytes,
            content_hash=content_hash,
        )

        # Map known fields from data dict
        _body = clean_text(
            payload.get("content")
            or payload.get("body")
            or payload.get("text")
            or payload.get("message")
            or payload.get("caption")
            or payload.get("description")
        )
        _author = clean_text(
            payload.get("author")
            or payload.get("name")
            or payload.get("username")
            or payload.get("full_name")
        )
        _url = (
            payload.get("url")
            or payload.get("permalink")
            or payload.get("link")
        )
        _media_urls = _normalize_media_urls(
            _first_present(payload, "media_urls", "media_artifacts", "permalink_candidates")
        )
        _content_date = _parse_content_date(
            _first_present(
                payload,
                "content_date",
                "posted_at",
                "published_at",
                "timestamp",
                "date",
                "date_posted",
            )
        )

        create_kwargs = dict(
            collection=collection,
            platform=platform,
            content_type=content_type,
            title=str(payload.get("title") or "")[:500] or None,
            body=_body,
            author=str(_author or "")[:255] or None,
            author_id=str(payload.get("author_id") or "")[:255] or None,
            url=str(_url or "")[:1000] or None,
            likes_count=_safe_int(_first_present(payload, "likes_count", "likes", "reactions", "like")),
            comments_count=_safe_int(_first_present(payload, "comments_count", "comments", "comment")),
            shares_count=_safe_int(_first_present(payload, "shares_count", "shares", "share")),
            views_count=_safe_int(_first_present(payload, "views_count", "views", "view")),
            media_urls=_media_urls,
            raw_data=payload,
            tags=tags,
            content_hash=content_hash,
            device_serial=device_serial,
            campaign_id=campaign_id,
            execution_id=execution_id,
            scenario_name=scenario_name,
            scenario_id=scenario_id,
            device_id=device_id,
            account_id=account_id,
            external_id=external_id,
            screenshot_path=screenshot_path,
            content_date=_content_date,
            parent_id=scoped_parent_id,
            item_level=resolved_level,
            user_id=user_id,
        )
        if effective_org:
            create_kwargs["org_id"] = effective_org

        item = await create_content_item(db_session, **create_kwargs)

        await increment_collection_count(db_session, collection, user_id=user_id)
        if owns_session:
            await db_session.commit()

        # Phase 5 — record in Bloom filter so future checks fast-path.
        try:
            from services import bloom_dedup
            await bloom_dedup.mark_seen(bloom_bucket, content_hash)
        except Exception as exc:
            log.debug("bloom mark_seen skipped (%s)", exc)

        log.info(f"Content saved: id={item.id} collection={collection} hash={content_hash[:12]}")
        return {"saved": True, "id": item.id}

    if owns_session:
        async with activity_session() as db_session:
            return await _save_with_session(db_session, owns_session=True)
    return await _save_with_session(db, owns_session=False)


async def _resolve_content_screenshot_path(
    db,
    *,
    payload: dict[str, Any],
    execution_id: str | None,
    screenshot_bytes: bytes | None,
    content_hash: str,
) -> str | None:
    """Resolve screenshot_path for content_items (URL only — binary lives in object storage)."""
    if not _content_images_enabled():
        return None

    if screenshot_bytes:
        path = _save_screenshot(screenshot_bytes, content_hash)
        return path or None

    for key in ("screenshot_path", "_screenshot_path", "screenshot_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1000]

    if not execution_id:
        return None

    from db.crud.execution_steps import list_execution_steps
    from services.content_artifacts import normalize_artifact_url

    steps = await list_execution_steps(db, execution_id)
    for step in reversed(steps):
        arts = step.artifacts_json if isinstance(step.artifacts_json, list) else []
        for art in reversed(arts):
            if not isinstance(art, dict):
                continue
            artifact_id = str(art.get("screenshot_artifact_id") or "").strip()
            if artifact_id:
                return f"/artifacts/{artifact_id}/content"
            inner = art.get("payload") if isinstance(art.get("payload"), dict) else {}
            url = art.get("screenshot_url") or inner.get("full")
            if url:
                return normalize_artifact_url(str(url))
    return None


def crop_jpeg_screenshot(jpeg: bytes, bounds: list[int] | tuple[int, ...]) -> bytes | None:
    """Crop a full-screen JPEG to a post card region (feed evidence per item)."""
    if len(bounds) != 4:
        return None
    try:
        import io

        from PIL import Image
    except Exception:
        return None
    try:
        x1, y1, x2, y2 = (int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3]))
        if x2 <= x1 or y2 <= y1:
            return None
        img = Image.open(io.BytesIO(jpeg))
        pad = 6
        crop = img.crop(
            (
                max(0, x1 - pad),
                max(0, y1 - pad),
                min(img.width, x2 + pad),
                min(img.height, y2 + pad),
            )
        )
        buf = io.BytesIO()
        crop.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        log.debug("crop_jpeg_screenshot failed: %s", exc)
        return None


async def attach_screenshot_to_content_hashes(
    *,
    content_hashes: list[str],
    collection: str,
    screenshot_bytes: bytes,
    execution_id: str | None = None,
    user_id: str | None = None,
    only_if_missing: bool = False,
    per_hash_bytes: dict[str, bytes] | None = None,
) -> int:
    """Upload screenshot(s) and set screenshot_path on matching content rows."""
    from db.crud.content import update_content_screenshot_path
    from db.database import activity_session

    if not _content_images_enabled() or not content_hashes:
        return 0
    updated = 0
    async with activity_session() as db:
        for content_hash in content_hashes:
            payload = (per_hash_bytes or {}).get(str(content_hash)) or screenshot_bytes
            if not payload:
                continue
            path = _save_screenshot(payload, str(content_hash))
            if not path:
                continue
            if await update_content_screenshot_path(
                db,
                content_hash=str(content_hash),
                collection=collection,
                screenshot_path=path,
                execution_id=execution_id,
                user_id=user_id,
                only_if_missing=only_if_missing,
            ):
                updated += 1
        if updated:
            await db.commit()
    return updated


def _save_screenshot(data: bytes, content_hash: str) -> str:
    """
    Save screenshot bytes. Returns URL/path string stored in DB.

    Tries MinIO first; falls back to local filesystem.
    Skips blank/black frames (quality gate in object storage / minio_store).
    """
    if not _content_images_enabled():
        return ""

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
