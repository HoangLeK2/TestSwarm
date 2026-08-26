"""Direct content_items writer for agent-side extra-data ingestion."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


class ContentDatabaseUnreachable(RuntimeError):
    """The content database could not be reached — extraction has nowhere to go."""


def _dsn_target(dsn: str) -> str:
    """host:port/database of a DSN, with credentials left out of the message."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return "the configured database"
    host = parts.hostname or "?"
    port = parts.port or 5432
    database = (parts.path or "").lstrip("/") or "?"
    return f"{host}:{port}/{database}"

# Optional FK columns on content_items that agent-boot may receive from device_farm
# workflow context. When stale/missing, drop the reference and still persist content.
_OPTIONAL_FK_FIELDS: tuple[str, ...] = ("campaign_id", "execution_id", "user_id", "org_id")
_FK_LOOKUP_TABLES: dict[str, str] = {
    "campaign_id": "campaigns",
    "execution_id": "executions",
    "user_id": "users",
    "org_id": "organizations",
}

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
    s = str(val).strip()
    if not s:
        return None
    multiplier = 1
    if s[-1].upper() == "K":
        multiplier = 1000
        s = s[:-1].strip()
    elif s[-1].upper() == "M":
        multiplier = 1_000_000
        s = s[:-1].strip()
    elif s[-1].upper() == "B":
        multiplier = 1_000_000_000
        s = s[:-1].strip()
    if multiplier > 1 and "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
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
    if parent_id and context.get("parent_id_already_scoped"):
        scoped_parent_id = str(parent_id)
    else:
        scoped_parent_id = scope_content_hash(parent_id, scope) if parent_id else None
    body = clean_text(
        data.get("content")
        or data.get("body")
        or data.get("text")
        or data.get("message")
        or data.get("caption")
        or data.get("description")
        or data.get("image_desc")
    )
    author = clean_text(
        data.get("author")
        or data.get("name")
        or data.get("username")
        or data.get("full_name")
    )
    url = data.get("url") or data.get("permalink") or data.get("link")
    screenshot_path = data.get("_screenshot_path") or data.get("screenshot_path") or None
    if screenshot_path is not None:
        screenshot_path = str(screenshot_path)[:1000] or None
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
        "screenshot_path": screenshot_path,
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
        "org_id": context.get("org_id") or None,
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

            # asyncpg.connect defaults to a 60s connect timeout and raises a
            # *message-less* asyncio.TimeoutError. The relay reports that as the
            # bare string "TimeoutError", so an unreachable content database
            # looked exactly like a phone problem: extraction collected the
            # hierarchy fine in 0.2s, then stalled a silent minute and failed
            # with a word that names no host, no stage and no cause. And because
            # self._pool is only assigned on success, every later extraction
            # paid the same full minute again.
            connect_timeout = float(
                os.getenv("AGENT_BOOT_CONTENT_DB_CONNECT_TIMEOUT", "10")
            )
            try:
                self._pool = await asyncpg.create_pool(
                    self._database_url,
                    min_size=1,
                    max_size=self._pool_size,
                    command_timeout=float(
                        os.getenv("AGENT_BOOT_CONTENT_DB_COMMAND_TIMEOUT", "10")
                    ),
                    timeout=connect_timeout,
                )
            except (asyncio.TimeoutError, OSError) as exc:
                raise ContentDatabaseUnreachable(
                    f"content database unreachable at {_dsn_target(self._database_url)} "
                    f"within {connect_timeout:g}s — extraction collected fine but "
                    f"cannot be stored (check AGENT_BOOT_CONTENT_DATABASE_URL)"
                ) from exc
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _existing_ids(self, conn, table: str, ids: list[str]) -> set[str]:
        if not ids:
            return set()
        try:
            valid_rows = await conn.fetch(
                f"SELECT id::text AS id FROM {table} WHERE id::text = ANY($1::text[])",
                ids,
            )
            return {str(row["id"]) for row in valid_rows}
        except Exception as exc:
            log.warning(
                "content_items FK guard: cannot verify %s (%s); dropping optional FK refs",
                table,
                exc,
            )
            return set()

    @staticmethod
    def _strip_optional_fk_fields(rows: list[dict[str, Any]]) -> list[str]:
        """Null-out optional FK columns; return names that were cleared."""
        stripped: list[str] = []
        for row in rows:
            for field in _OPTIONAL_FK_FIELDS:
                if row.get(field) is not None:
                    row[field] = None
                    if field not in stripped:
                        stripped.append(field)
        return stripped

    async def _sanitize_fk_field(
        self,
        conn,
        field: str,
        value: str | None,
    ) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        table = _FK_LOOKUP_TABLES.get(field)
        if not table:
            return text
        valid_ids = await self._existing_ids(conn, table, [text])
        if text not in valid_ids:
            log.info("content_items FK guard: dropping stale %s=%s", field, text)
            return None
        return text

    async def _resolve_org_id_from_user(self, conn, user_id: str | None) -> str | None:
        text = str(user_id or "").strip()
        if not text:
            return None
        try:
            row = await conn.fetchrow(
                "SELECT default_org_id::text AS org_id FROM users WHERE id::text = $1",
                text,
            )
        except Exception as exc:
            log.warning("content_items org_id lookup from user_id failed: %s", exc)
            return None
        if not row or not row.get("org_id"):
            return None
        return str(row["org_id"])

    async def prepare_context_for_persist(self, context: dict[str, Any]) -> dict[str, Any]:
        """Drop stale optional FK refs from ingest context before row build."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if not context.get("org_id") and context.get("user_id"):
                context["org_id"] = await self._resolve_org_id_from_user(conn, context.get("user_id"))
            for field in _OPTIONAL_FK_FIELDS:
                if field not in context:
                    continue
                context[field] = await self._sanitize_fk_field(conn, field, context.get(field))
        return context

    async def _sanitize_row_fk_refs(self, conn, rows: list[dict[str, Any]]) -> list[str]:
        """Validate optional FK refs on each row; return stripped field names."""
        stripped: list[str] = []
        for field in _OPTIONAL_FK_FIELDS:
            table = _FK_LOOKUP_TABLES[field]
            ids = sorted({str(row.get(field)) for row in rows if row.get(field)})
            if not ids:
                continue
            valid_ids = await self._existing_ids(conn, table, ids)
            for row in rows:
                value = row.get(field)
                if value and str(value) not in valid_ids:
                    row[field] = None
                    if field not in stripped:
                        stripped.append(field)
        if stripped:
            log.info(
                "content_items FK guard: stripped stale refs from rows: %s",
                ", ".join(stripped),
            )
        return stripped

    async def sanitize_campaign_id(self, campaign_id: str | None) -> str | None:
        """Return campaign_id only when the row still exists (content_items FK safe)."""
        text = str(campaign_id or "").strip()
        if not text:
            return None
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await self._sanitize_fk_field(conn, "campaign_id", text)

    @staticmethod
    def _is_content_items_fk_violation(exc: Exception) -> bool:
        msg = str(exc).lower()
        if "content_items" not in msg:
            return False
        return (
            "foreign key" in msg
            or "violates foreign key constraint" in msg
            or "_fkey" in msg
        )

    @staticmethod
    def _is_campaign_fk_violation(exc: Exception) -> bool:
        msg = str(exc).lower()
        return ContentItemWriter._is_content_items_fk_violation(exc) and "campaign_id" in msg

    async def lookup_parent_hash_for_post_pid(
        self,
        *,
        collection: str,
        execution_id: str | None,
        parent_post_id: str,
        items: list[dict[str, Any]],
    ) -> str | None:
        """Find parent post content_hash in DB by Facebook post id (_pid / fb_post_id)."""
        pid = str(parent_post_id or "").strip()
        if not pid:
            for item in items:
                if isinstance(item, dict) and item.get("_type") != "post_stats":
                    pid = str(item.get("parent_post_id") or "").strip()
                    if pid:
                        break
        if not pid or not collection:
            return None
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            base_where = """
                collection = $1
                  AND item_level <= 1
                  AND (
                    content_type IN ('fb_post', 'fb_group_posts', 'post')
                    OR content_type IS NULL
                  )
                  AND (
                    raw_data->>'_pid' = $2
                    OR raw_data->>'post_key' = $2
                    OR raw_data->>'fb_post_id' = $2
                    OR raw_data->>'stable_post_id' = $2
                  )
            """
            if execution_id:
                row = await conn.fetchrow(
                    f"""
                    SELECT content_hash
                    FROM content_items
                    WHERE {base_where}
                      AND execution_id = $3
                    ORDER BY extracted_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    collection,
                    pid,
                    str(execution_id),
                )
                if row and row.get("content_hash"):
                    return str(row["content_hash"])
            row = await conn.fetchrow(
                f"""
                SELECT content_hash
                FROM content_items
                WHERE {base_where}
                ORDER BY extracted_at DESC NULLS LAST
                LIMIT 1
                """,
                collection,
                pid,
            )
            if row and row.get("content_hash"):
                return str(row["content_hash"])
        return None

    async def lookup_latest_parent_hash_for_context(
        self,
        *,
        collection: str,
        execution_id: str | None,
        device_serial: str | None,
    ) -> str | None:
        """Find the latest post in the same crawl context for comment-sheet rows."""
        collection_text = str(collection or "").strip()
        execution_text = str(execution_id or "").strip()
        serial_text = str(device_serial or "").strip()
        if not collection_text or not execution_text:
            return None
        lookback_seconds = max(
            1,
            int(os.getenv("AGENT_BOOT_COMMENT_PARENT_LOOKBACK_SECONDS", "900")),
        )
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            args: list[Any] = [collection_text, execution_text, float(lookback_seconds)]
            serial_filter = ""
            if serial_text:
                args.append(serial_text)
                serial_filter = f"AND device_serial = ${len(args)}"
            row = await conn.fetchrow(
                f"""
                SELECT content_hash
                FROM content_items
                WHERE collection = $1
                  AND execution_id = $2
                  AND item_level = 0
                  AND (
                    content_type IN ('fb_post', 'fb_group_posts', 'post')
                    OR content_type IS NULL
                  )
                  AND created_at >= now() - ($3::double precision * interval '1 second')
                  {serial_filter}
                ORDER BY extracted_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                *args,
            )
            if row and row.get("content_hash"):
                return str(row["content_hash"])
        return None

    async def update_content_stats(
        self,
        *,
        content_hash: str | None,
        likes_count: Any = None,
        comments_count: Any = None,
        shares_count: Any = None,
    ) -> bool:
        """Update counters for an already-persisted root post."""
        target_hash = str(content_hash or "").strip()
        if not target_hash:
            return False
        likes = _safe_int(likes_count)
        comments = _safe_int(comments_count)
        shares = _safe_int(shares_count)
        if likes is None and comments is None and shares is None:
            return False
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE content_items
                SET
                  likes_count = COALESCE($2::integer, likes_count),
                  comments_count = COALESCE($3::integer, comments_count),
                  shares_count = COALESCE($4::integer, shares_count),
                  updated_at = now()
                WHERE content_hash = $1
                  AND item_level = 0
                RETURNING content_hash
                """,
                target_hash,
                likes,
                comments,
                shares,
            )
            return bool(row and row.get("content_hash"))

    async def _insert_rows_once(self, conn, rows: list[dict[str, Any]]) -> dict[str, Any]:
        payload = json.dumps(rows, ensure_ascii=False, default=str)
        sql = """
        WITH incoming AS (
            SELECT * FROM jsonb_to_recordset($1::jsonb) AS x(
                id text, collection text, platform text, content_type text, title text,
                body text, author text, author_id text, url text,
                likes_count integer, comments_count integer, shares_count integer, views_count integer,
                media_urls jsonb, screenshot_path text, raw_data jsonb, tags text,
                content_hash text, parent_id text, item_level integer, device_serial text,
                campaign_id text, execution_id text, scenario_name text, user_id text, org_id text,
                extracted_at timestamptz, content_date timestamptz, created_at timestamptz
            )
        ),
        inserted AS (
            INSERT INTO content_items (
                id, collection, platform, content_type, title, body, author, author_id, url,
                likes_count, comments_count, shares_count, views_count, media_urls, screenshot_path,
                raw_data, tags, content_hash, parent_id, item_level, device_serial, campaign_id,
                execution_id, scenario_name, user_id, org_id, extracted_at, content_date, created_at
            )
            SELECT
                id, collection, platform, content_type, title, body, author, author_id, url,
                likes_count, comments_count, shares_count, views_count, media_urls::json, screenshot_path,
                raw_data::json, tags, content_hash, parent_id, item_level, device_serial, campaign_id,
                execution_id, scenario_name, user_id, org_id, extracted_at, content_date, created_at
            FROM incoming
            ON CONFLICT DO NOTHING
            RETURNING content_hash
        )
        SELECT
            COALESCE(array_agg(content_hash), ARRAY[]::text[]) AS inserted_hashes,
            COUNT(*)::int AS inserted_count
        FROM inserted
        """
        async with conn.transaction():
            row = await conn.fetchrow(sql, payload)
            inserted_hashes = [str(h) for h in (row["inserted_hashes"] or []) if h]
            inserted = int(row["inserted_count"] or 0)
            if inserted <= 0:
                return {
                    "attempted": len(rows),
                    "inserted": 0,
                    "duplicates": len(rows),
                    "inserted_content_hashes": [],
                }
            # collection counts — group by first row metadata (same batch shares collection)
            groups: dict[tuple[str, str | None, str | None, str | None], int] = {}
            hash_set = set(inserted_hashes)
            for item in rows:
                ch = str(item.get("content_hash") or "")
                if ch not in hash_set:
                    continue
                key = (
                    str(item.get("collection") or ""),
                    item.get("user_id"),
                    item.get("org_id"),
                    item.get("platform"),
                    item.get("content_type"),
                )
                groups[key] = groups.get(key, 0) + 1
            for (
                collection,
                user_id,
                org_id,
                platform,
                content_type,
            ), inserted_count in groups.items():
                await self._increment_collection_count(
                    conn,
                    collection=collection,
                    user_id=user_id,
                    org_id=org_id,
                    platform=platform,
                    content_type=content_type,
                    inserted_count=inserted_count,
                )
        return {
            "attempted": len(rows),
            "inserted": inserted,
            "duplicates": len(rows) - inserted,
            "inserted_content_hashes": inserted_hashes,
        }

    async def insert_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"attempted": 0, "inserted": 0, "duplicates": 0}
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await self._sanitize_row_fk_refs(conn, rows)
            try:
                return await self._insert_rows_once(conn, rows)
            except Exception as exc:
                if not self._is_content_items_fk_violation(exc):
                    raise
                stripped = self._strip_optional_fk_fields(rows)
                log.warning(
                    "content_items optional FK insert failed (%s); retrying without %s",
                    exc,
                    ", ".join(stripped) or "optional FK refs",
                )
                return await self._insert_rows_once(conn, rows)

    async def _increment_collection_count(
        self,
        conn: Any,
        *,
        collection: str,
        user_id: str | None,
        org_id: str | None,
        platform: str | None,
        content_type: str | None,
        inserted_count: int,
    ) -> None:
        inserted_count = max(0, int(inserted_count or 0))
        if inserted_count <= 0:
            return
        effective_org = str(org_id or "").strip() or None
        if not effective_org and user_id:
            effective_org = await self._resolve_org_id_from_user(conn, user_id)
        if not effective_org:
            log.warning(
                "content_collections skip: missing org_id for collection=%s user_id=%s",
                collection,
                user_id,
            )
            return
        await conn.execute(
            """
            INSERT INTO content_collections (
                id, name, description, platform, content_type, item_count,
                user_id, org_id, created_at, updated_at
            ) VALUES ($1, $2, '', $3, $4, $5, $6, $7, NOW(), NOW())
            ON CONFLICT ON CONSTRAINT uq_content_collections_org_name_user DO UPDATE SET
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
            effective_org,
        )
