"""Direct content_items writer for agent-side extra-data ingestion."""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import ftfy as _ftfy  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _ftfy = None

try:
    import dateparser as _dateparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _dateparser = None


_RE_RELATIVE_TIME = re.compile(
    r"^\s*(\d+)\s*(giây|phút|giờ|ngày|tuần|tháng|năm|second|minute|hour|day|week|month|year)s?\s*(trước|ago)?\s*$",
    re.IGNORECASE,
)
_RE_CALENDAR_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def clean_text(text: Any) -> Any:
    if not isinstance(text, str) or not text:
        return text
    if _ftfy is None:
        return text.strip()
    try:
        return _ftfy.fix_text(text).strip()
    except Exception:
        return text.strip()


def compute_content_hash(data: dict[str, Any], dedupe_field: str | None = None) -> str:
    if dedupe_field and dedupe_field in data:
        raw = str(data[dedupe_field])
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    normalized = unicodedata.normalize("NFC", raw.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def scope_content_hash(base_hash: str | None, scope: str | None = None) -> str | None:
    if not base_hash:
        return None
    if not scope:
        return base_hash
    return hashlib.sha256(f"{scope}:{base_hash}".encode("utf-8")).hexdigest()


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    s = str(val).strip().replace(",", "")
    if not s:
        return None
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


def _normalize_media_urls(value: Any) -> list[str]:
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


def _parse_captured_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # APK may send milliseconds.
        v = float(value)
        if v > 10_000_000_000:
            v = v / 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(value or "").strip()
    if s:
        try:
            return datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", s))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _parse_content_date(value: Any, *, captured_at: Any = None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    s = str(value).strip()
    if not s:
        return None
    s_clean = s.replace("\u00a0", " ").replace("\u202f", " ").strip()
    s_lower = s_clean.lower()

    try:
        if "t" in s_lower or "-" in s_lower:
            parsed = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", s_clean))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    m = _RE_CALENDAR_DATE.match(s_clean)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    base = _parse_captured_at(captured_at)
    if s_lower in {"hôm qua", "yesterday"}:
        return base - timedelta(days=1)
    if s_lower in {"just now", "vừa xong", "bây giờ", "now"}:
        return base

    m = _RE_RELATIVE_TIME.match(s_lower)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit in {"giây", "second"}:
            return base - timedelta(seconds=amount)
        if unit in {"phút", "minute"}:
            return base - timedelta(minutes=amount)
        if unit in {"giờ", "hour"}:
            return base - timedelta(hours=amount)
        if unit in {"ngày", "day"}:
            return base - timedelta(days=amount)
        if unit in {"tuần", "week"}:
            return base - timedelta(weeks=amount)
        if unit in {"tháng", "month"}:
            return base - timedelta(days=30 * amount)
        if unit in {"năm", "year"}:
            return base - timedelta(days=365 * amount)

    if _dateparser is not None:
        try:
            dt = _dateparser.parse(
                s_clean,
                languages=["vi", "en"],
                settings={
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "PREFER_DAY_OF_MONTH": "first",
                    "TO_TIMEZONE": "UTC",
                    "RELATIVE_BASE": base.replace(tzinfo=None),
                },
            )
            if dt is not None:
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def build_content_item_row(
    data: dict[str, Any],
    context: dict[str, Any],
    *,
    parent_id: str | None = None,
    item_level: int | None = None,
    captured_at: Any = None,
) -> dict[str, Any]:
    scope = context.get("hash_scope") or context.get("execution_id")
    base_hash = compute_content_hash(data, context.get("dedupe_field"))
    content_hash = scope_content_hash(base_hash, scope)
    scoped_parent_id = scope_content_hash(parent_id, scope) if parent_id else None
    body = clean_text(
        data.get("content")
        or data.get("body")
        or data.get("text")
        or data.get("message")
        or data.get("caption")
        or data.get("description")
    )
    author = clean_text(
        data.get("author")
        or data.get("name")
        or data.get("username")
        or data.get("full_name")
    )
    url = data.get("url") or data.get("permalink") or data.get("link")
    return {
        "id": str(uuid.uuid4()),
        "collection": context.get("collection") or "default",
        "platform": data.get("platform") or context.get("platform") or None,
        "content_type": data.get("content_type") or context.get("content_type") or "post",
        "title": str(data.get("title") or "")[:500] or None,
        "body": body,
        "author": str(author or "")[:255] or None,
        "author_id": str(data.get("author_id") or "")[:255] or None,
        "url": str(url or "")[:1000] or None,
        "likes_count": _safe_int(_first_present(data, "likes_count", "likes", "reactions", "like")),
        "comments_count": _safe_int(_first_present(data, "comments_count", "comments", "comment")),
        "shares_count": _safe_int(_first_present(data, "shares_count", "shares", "share")),
        "views_count": _safe_int(_first_present(data, "views_count", "views", "view")),
        "media_urls": _normalize_media_urls(_first_present(data, "media_urls", "media_artifacts", "permalink_candidates")),
        "screenshot_path": None,
        "raw_data": data,
        "tags": context.get("tags") or "",
        "content_hash": content_hash,
        "parent_id": scoped_parent_id,
        "item_level": int(item_level if item_level is not None else (context.get("item_level") or 0)),
        "device_serial": context.get("device_serial"),
        "campaign_id": context.get("campaign_id") or None,
        "execution_id": context.get("execution_id") or None,
        "scenario_name": context.get("scenario_name") or None,
        "user_id": context.get("user_id") or None,
        "extracted_at": _parse_captured_at(captured_at),
        "content_date": _parse_content_date(
            _first_present(data, "content_date", "posted_at", "published_at", "timestamp", "date", "date_posted"),
            captured_at=captured_at,
        ),
        "created_at": datetime.now(timezone.utc),
    }


class ContentItemWriter:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = (database_url or os.getenv("AGENT_BOOT_CONTENT_DATABASE_URL") or "").strip()
        self._pool = None
        self._pool_size = max(1, int(os.getenv("AGENT_BOOT_CONTENT_DB_POOL_SIZE", "2")))

    async def _ensure_pool(self):
        if not self._database_url:
            raise RuntimeError("AGENT_BOOT_CONTENT_DATABASE_URL is not configured")
        if self._pool is None:
            import asyncpg  # type: ignore
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=1,
                max_size=self._pool_size,
                command_timeout=float(os.getenv("AGENT_BOOT_CONTENT_DB_COMMAND_TIMEOUT", "10")),
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def insert_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"attempted": 0, "inserted": 0, "duplicates": 0}
        pool = await self._ensure_pool()
        payload = json.dumps(rows, ensure_ascii=False, default=str)
        sql = """
        WITH incoming AS (
            SELECT * FROM jsonb_to_recordset($1::jsonb) AS x(
                id text, collection text, platform text, content_type text, title text,
                body text, author text, author_id text, url text,
                likes_count integer, comments_count integer, shares_count integer, views_count integer,
                media_urls jsonb, screenshot_path text, raw_data jsonb, tags text,
                content_hash text, parent_id text, item_level integer, device_serial text,
                campaign_id text, execution_id text, scenario_name text, user_id text,
                extracted_at timestamptz, content_date timestamptz, created_at timestamptz
            )
        ),
        inserted AS (
            INSERT INTO content_items (
                id, collection, platform, content_type, title, body, author, author_id, url,
                likes_count, comments_count, shares_count, views_count, media_urls, screenshot_path,
                raw_data, tags, content_hash, parent_id, item_level, device_serial, campaign_id,
                execution_id, scenario_name, user_id, extracted_at, content_date, created_at
            )
            SELECT
                id, collection, platform, content_type, title, body, author, author_id, url,
                likes_count, comments_count, shares_count, views_count, media_urls::json, screenshot_path,
                raw_data::json, tags, content_hash, parent_id, item_level, device_serial, campaign_id,
                execution_id, scenario_name, user_id, extracted_at, content_date, created_at
            FROM incoming
            ON CONFLICT DO NOTHING
            RETURNING collection, user_id, platform, content_type
        )
        SELECT collection, user_id, platform, content_type, COUNT(*)::int AS inserted_count
        FROM inserted
        GROUP BY collection, user_id, platform, content_type
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                inserted_groups = await conn.fetch(sql, payload)
                inserted = sum(int(group["inserted_count"] or 0) for group in inserted_groups)
                for group in inserted_groups:
                    inserted_count = int(group["inserted_count"] or 0)
                    if inserted_count <= 0:
                        continue
                    await self._increment_collection_count(
                        conn,
                        collection=group["collection"],
                        user_id=group["user_id"],
                        platform=group["platform"],
                        content_type=group["content_type"],
                        inserted_count=inserted_count,
                    )
        return {"attempted": len(rows), "inserted": inserted, "duplicates": len(rows) - inserted}

    async def _increment_collection_count(
        self,
        conn: Any,
        *,
        collection: str,
        user_id: str | None,
        platform: str | None,
        content_type: str | None,
        inserted_count: int,
    ) -> None:
        inserted_count = max(0, int(inserted_count or 0))
        if inserted_count <= 0:
            return
        if user_id is None:
            await conn.execute(
                """
                INSERT INTO content_collections (
                    id, name, description, platform, content_type, item_count, user_id, created_at, updated_at
                ) VALUES ($1, $2, '', $3, $4, $5, NULL, NOW(), NOW())
                ON CONFLICT (name) WHERE user_id IS NULL DO UPDATE SET
                    item_count = content_collections.item_count + EXCLUDED.item_count,
                    platform = COALESCE(content_collections.platform, EXCLUDED.platform),
                    content_type = COALESCE(content_collections.content_type, EXCLUDED.content_type),
                    updated_at = NOW()
                """,
                str(uuid.uuid4()),
                collection,
                platform,
                content_type,
                inserted_count,
            )
            return
        await conn.execute(
            """
            INSERT INTO content_collections (
                id, name, description, platform, content_type, item_count, user_id, created_at, updated_at
            ) VALUES ($1, $2, '', $3, $4, $5, $6, NOW(), NOW())
            ON CONFLICT ON CONSTRAINT uq_content_collections_name_user DO UPDATE SET
                item_count = content_collections.item_count + EXCLUDED.item_count,
                platform = COALESCE(content_collections.platform, EXCLUDED.platform),
                content_type = COALESCE(content_collections.content_type, EXCLUDED.content_type),
                updated_at = NOW()
            """,
            str(uuid.uuid4()),
            collection,
            platform,
            content_type,
            inserted_count,
            user_id,
        )
