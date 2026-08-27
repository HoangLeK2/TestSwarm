"""Farm-owned persistence for content parsed by relay agents."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from common.variable_resolver import unresolved_var_names
from db.database import edge_ingest_session
from services.content.registry import require_valid_content_type
from services.content.secret_scrub import scrub_secrets
from web.metrics import (
    edge_ingest_batch_bytes,
    edge_ingest_duration_seconds,
    edge_ingest_rejected_total,
    edge_ingest_rows_total,
)
from services.content_store import (
    _first_present,
    _normalize_media_urls,
    _RE_CALENDAR_DATE,
    _RE_RELATIVE_TIME,
    _dateparser,
    _safe_int,
    clean_text,
    compute_content_hash,
    scope_content_hash,
)


class ContentUplinkError(RuntimeError):
    code = "content_uplink_invalid"


class ContentUplinkUnauthorized(ContentUplinkError):
    code = "content_uplink_unauthorized"


class ContentUplinkSaturated(ContentUplinkError):
    code = "content_uplink_saturated"


class ContentUplinkUnavailable(ContentUplinkError):
    code = "content_uplink_unavailable"


_semaphore: asyncio.Semaphore | None = None
_semaphore_loop: asyncio.AbstractEventLoop | None = None


def _ingest_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    loop = asyncio.get_running_loop()
    if _semaphore is None or _semaphore_loop is not loop:
        _semaphore = asyncio.Semaphore(max(1, int(os.getenv("EDGE_INGEST_CONCURRENCY", "4"))))
        _semaphore_loop = loop
    return _semaphore


_INSERT_CONTENT_SQL = text(
    """
    WITH incoming AS (
        SELECT * FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(
            id text, collection text, platform text, content_type text, title text,
            body text, author text, author_id text, url text,
            likes_count integer, comments_count integer, shares_count integer,
            views_count integer, media_urls jsonb, screenshot_path text,
            raw_data jsonb, tags text, content_hash text, parent_id text,
            item_level integer, device_serial text, campaign_id text,
            execution_id text, scenario_name text, scenario_id text,
            device_id text, account_id text, user_id text, org_id text,
            extracted_at timestamptz, content_date timestamptz,
            created_at timestamptz
        )
    )
    INSERT INTO content_items (
        id, collection, platform, content_type, title, body, author, author_id,
        url, likes_count, comments_count, shares_count, views_count, media_urls,
        screenshot_path, raw_data, tags, content_hash, parent_id, item_level,
        device_serial, campaign_id, execution_id, scenario_name, scenario_id,
        device_id, account_id, user_id, org_id, extracted_at, content_date,
        created_at
    )
    SELECT
        id, collection, platform, content_type, title, body, author, author_id,
        url, likes_count, comments_count, shares_count, views_count,
        media_urls::json, screenshot_path, raw_data::json, tags, content_hash,
        parent_id, item_level, device_serial, campaign_id, execution_id,
        scenario_name, scenario_id, device_id, account_id, user_id, org_id,
        extracted_at, content_date, created_at
    FROM incoming
    ON CONFLICT DO NOTHING
    RETURNING content_hash, collection, user_id, org_id, platform, content_type
    """
)

_UPSERT_COLLECTION_SQL = text(
    """
    INSERT INTO content_collections (
        id, name, description, platform, content_type, item_count,
        user_id, org_id, created_at, updated_at
    ) VALUES (
        :id, :name, '', :platform, :content_type, :item_count,
        :user_id, :org_id, NOW(), NOW()
    )
    ON CONFLICT ON CONSTRAINT uq_content_collections_org_name_user DO UPDATE SET
        item_count = content_collections.item_count + EXCLUDED.item_count,
        platform = COALESCE(content_collections.platform, EXCLUDED.platform),
        content_type = COALESCE(content_collections.content_type, EXCLUDED.content_type),
        updated_at = NOW()
    """
)

_LOOKUP_PARENT_BY_PID_SQL = text(
    """
    SELECT content_hash
    FROM content_items
    WHERE org_id = :org_id
      AND collection = :collection
      AND item_level <= 1
      AND (CAST(:execution_id AS varchar) IS NULL OR execution_id = CAST(:execution_id AS varchar))
      AND (
        raw_data->>'_pid' = :parent_post_id
        OR raw_data->>'post_key' = :parent_post_id
        OR raw_data->>'fb_post_id' = :parent_post_id
        OR raw_data->>'stable_post_id' = :parent_post_id
      )
    ORDER BY extracted_at DESC NULLS LAST
    LIMIT 1
    """
)

_LOOKUP_LATEST_PARENT_SQL = text(
    """
    SELECT content_hash
    FROM content_items
    WHERE org_id = :org_id
      AND collection = :collection
      AND execution_id = :execution_id
      AND item_level = 0
      AND (CAST(:device_serial AS varchar) IS NULL OR device_serial = CAST(:device_serial AS varchar))
      AND extracted_at >= NOW() - (:lookback_seconds * INTERVAL '1 second')
    ORDER BY extracted_at DESC NULLS LAST
    LIMIT 1
    """
)

_UPDATE_PARENT_STATS_SQL = text(
    """
    UPDATE content_items
    SET likes_count = COALESCE(:likes_count, likes_count),
        comments_count = COALESCE(:comments_count, comments_count),
        shares_count = COALESCE(:shares_count, shares_count),
        updated_at = NOW()
    WHERE org_id = :org_id
      AND content_hash = :content_hash
      AND item_level = 0
      AND (CAST(:execution_id AS varchar) IS NULL OR execution_id = CAST(:execution_id AS varchar))
    """
)

_UPSERT_ENTITIES_SQL = text(
    """
    INSERT INTO external_entities (
        id, org_id, platform, entity_type, identity_key, identity_confidence,
        external_id, canonical_url, display_name, status, current_attributes,
        current_metrics, first_seen_at, last_seen_at, created_at, updated_at
    )
    SELECT
        x.id, :org_id, x.platform, x.entity_type, x.identity_key,
        x.identity_confidence, x.external_id, x.canonical_url, x.display_name,
        x.status, x.attributes, x.metrics, x.observed_at, x.observed_at,
        NOW(), NOW()
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(
        id varchar, platform varchar, entity_type varchar, identity_key varchar,
        identity_confidence varchar, external_id varchar, canonical_url varchar,
        display_name varchar, status varchar, attributes jsonb, metrics jsonb,
        observed_at timestamptz
    )
    ON CONFLICT (org_id, platform, entity_type, identity_key) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        external_id = COALESCE(EXCLUDED.external_id, external_entities.external_id),
        canonical_url = COALESCE(EXCLUDED.canonical_url, external_entities.canonical_url),
        status = CASE
            WHEN external_entities.status IN ('resolved', 'active')
                 AND EXCLUDED.status = 'candidate'
            THEN external_entities.status ELSE EXCLUDED.status
        END,
        current_attributes = external_entities.current_attributes || EXCLUDED.current_attributes,
        current_metrics = external_entities.current_metrics || EXCLUDED.current_metrics,
        last_seen_at = GREATEST(external_entities.last_seen_at, EXCLUDED.last_seen_at),
        updated_at = NOW()
    RETURNING id::text, platform, entity_type, identity_key
    """
)

_UPSERT_ENTITY_OBSERVATIONS_SQL = text(
    """
    INSERT INTO external_entity_observations (
        id, org_id, external_entity_id, observed_at, display_name, attributes,
        metrics, raw_data, account_id, execution_id, created_at
    )
    SELECT
        x.id, :org_id, x.external_entity_id, x.observed_at, x.display_name,
        x.attributes, x.metrics, x.raw_data, x.account_id, x.execution_id, NOW()
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(
        id varchar, external_entity_id varchar, observed_at timestamptz,
        display_name varchar, attributes jsonb, metrics jsonb, raw_data jsonb,
        account_id varchar, execution_id varchar
    )
    ON CONFLICT (org_id, external_entity_id, execution_id)
        WHERE execution_id IS NOT NULL
    DO UPDATE SET
        observed_at = EXCLUDED.observed_at,
        display_name = EXCLUDED.display_name,
        attributes = EXCLUDED.attributes,
        metrics = EXCLUDED.metrics,
        raw_data = EXCLUDED.raw_data,
        account_id = EXCLUDED.account_id
    """
)

_UPSERT_ENTITY_DISCOVERIES_SQL = text(
    """
    INSERT INTO external_entity_discoveries (
        id, org_id, external_entity_id, query, rank, context, account_id,
        execution_id, observed_at, created_at
    )
    SELECT
        x.id, :org_id, x.external_entity_id, x.query, x.rank, x.context,
        x.account_id, x.execution_id, x.observed_at, NOW()
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x(
        id varchar, external_entity_id varchar, query varchar, rank integer,
        context jsonb, account_id varchar, execution_id varchar,
        observed_at timestamptz
    )
    ON CONFLICT (org_id, external_entity_id, execution_id, query)
        WHERE execution_id IS NOT NULL
    DO UPDATE SET
        rank = EXCLUDED.rank,
        context = EXCLUDED.context,
        account_id = EXCLUDED.account_id,
        observed_at = EXCLUDED.observed_at
    """
)


def _parse_captured_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    raw = str(value or "").strip()
    if raw:
        try:
            return datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", raw))
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _parse_content_date(value: Any, *, captured_at: Any = None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = str(value).strip().replace("\u00a0", " ").replace("\u202f", " ")
    if not raw:
        return None
    lower = raw.lower()
    try:
        if "t" in lower or "-" in lower:
            parsed = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", raw))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    calendar = _RE_CALENDAR_DATE.match(raw)
    if calendar:
        try:
            return datetime(
                int(calendar.group(3)),
                int(calendar.group(2)),
                int(calendar.group(1)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
    base = _parse_captured_at(captured_at)
    if lower in {"hôm qua", "yesterday"}:
        return base - timedelta(days=1)
    if lower in {"just now", "vừa xong", "bây giờ", "now"}:
        return base
    relative = _RE_RELATIVE_TIME.match(lower)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        delta = {
            "giây": timedelta(seconds=amount),
            "second": timedelta(seconds=amount),
            "phút": timedelta(minutes=amount),
            "minute": timedelta(minutes=amount),
            "giờ": timedelta(hours=amount),
            "hour": timedelta(hours=amount),
            "ngày": timedelta(days=amount),
            "day": timedelta(days=amount),
            "tuần": timedelta(weeks=amount),
            "week": timedelta(weeks=amount),
            "tháng": timedelta(days=30 * amount),
            "month": timedelta(days=30 * amount),
            "năm": timedelta(days=365 * amount),
            "year": timedelta(days=365 * amount),
        }[unit]
        return base - delta
    if _dateparser is not None:
        try:
            parsed = _dateparser.parse(
                raw,
                languages=["vi", "en"],
                settings={
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "PREFER_DAY_OF_MONTH": "first",
                    "TO_TIMEZONE": "UTC",
                    "RELATIVE_BASE": base.replace(tzinfo=None),
                },
            )
            if parsed is not None:
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return None


def _as_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    if isinstance(row, dict):
        return row
    return {}


async def _canonical_identity(db, *, relay_id: str, context: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(context.get("execution_id") or "").strip() or None
    result = await db.execute(
        text(
            """
            SELECT
                ra.org_id, COALESCE(e.user_id, ra.user_id) AS user_id,
                e.id AS execution_id,
                COALESCE(e.campaign_id, c.id) AS campaign_id,
                COALESCE(e.account_id, a.id) AS account_id,
                d.id AS device_id, os.id AS scenario_id
            FROM relay_agents ra
            LEFT JOIN executions e
              ON e.id = CAST(:execution_id AS varchar) AND e.org_id = ra.org_id
            -- A crawl can carry a campaign or account without an execution, and
            -- device_farm has already resolved and validated both before the
            -- request left. Deriving them from the execution alone dropped them
            -- on the floor for those runs. The org_id predicate keeps the tenant
            -- guarantee: anything belonging to another organization simply fails
            -- to join and lands as NULL, exactly as a stale FK used to.
            LEFT JOIN campaigns c
              ON c.id = CAST(:campaign_id AS varchar) AND c.org_id = ra.org_id
            LEFT JOIN accounts a
              ON a.id = CAST(:account_id AS varchar) AND a.org_id = ra.org_id
            LEFT JOIN devices d
              ON d.org_id = ra.org_id
             AND CAST(:device_serial AS varchar) IS NOT NULL
             AND (d.serial = CAST(:device_serial AS varchar)
                  OR d.device_serial = CAST(:device_serial AS varchar)
                  OR d.relay_serial = CAST(:device_serial AS varchar))
            LEFT JOIN org_scenarios os
              ON os.org_id = ra.org_id AND os.id = CAST(:scenario_id AS varchar)
            WHERE ra.relay_id = :relay_id
            LIMIT 1
            """
        ),
        {
            "relay_id": relay_id,
            "execution_id": execution_id,
            "campaign_id": str(context.get("campaign_id") or "").strip() or None,
            "account_id": str(context.get("account_id") or "").strip() or None,
            "device_serial": str(context.get("device_serial") or "").strip() or None,
            "scenario_id": str(context.get("scenario_id") or "").strip() or None,
        },
    )
    row = result.first()
    identity = _as_mapping(row)
    if not identity:
        raise ContentUplinkUnauthorized("relay is not enrolled")
    if execution_id and not identity.get("execution_id"):
        raise ContentUplinkUnauthorized("execution does not belong to relay organization")
    if not identity.get("org_id") or not identity.get("user_id"):
        raise ContentUplinkUnauthorized("relay has no canonical organization/user")
    return identity


async def _resolve_parent_id(
    db,
    *,
    hint: dict[str, Any],
    context: dict[str, Any],
    identity: dict[str, Any],
) -> str | None:
    parent_id = str(hint.get("parent_id") or "").strip() or None
    if parent_id and not bool(hint.get("parent_id_already_scoped")):
        parent_id = scope_content_hash(
            parent_id,
            context.get("hash_scope") or identity.get("execution_id"),
        )
    parent_post_id = str(hint.get("parent_post_id") or "").strip()
    if parent_post_id:
        result = await db.execute(
            _LOOKUP_PARENT_BY_PID_SQL,
            {
                "org_id": identity["org_id"],
                "collection": str(context.get("collection") or ""),
                "execution_id": identity.get("execution_id"),
                "parent_post_id": parent_post_id,
            },
        )
        row = _as_mapping(result.first())
        if row.get("content_hash"):
            parent_id = str(row["content_hash"])
    if (
        not parent_id
        and bool(hint.get("allow_latest_post_parent_fallback"))
        and identity.get("execution_id")
    ):
        result = await db.execute(
            _LOOKUP_LATEST_PARENT_SQL,
            {
                "org_id": identity["org_id"],
                "collection": str(context.get("collection") or ""),
                "execution_id": identity["execution_id"],
                "device_serial": str(context.get("device_serial") or "").strip() or None,
                "lookback_seconds": max(
                    1,
                    int(os.getenv("EDGE_INGEST_PARENT_LOOKBACK_SECONDS", "900")),
                ),
            },
        )
        row = _as_mapping(result.first())
        if row.get("content_hash"):
            parent_id = str(row["content_hash"])
    if bool(hint.get("require_verified_parent")) and not parent_id:
        raise ContentUplinkError("verified comment parent was not found")
    return parent_id


async def _update_parent_stats(
    db,
    *,
    parent_id: str,
    stats: dict[str, Any],
    identity: dict[str, Any],
) -> bool:
    result = await db.execute(
        _UPDATE_PARENT_STATS_SQL,
        {
            "org_id": identity["org_id"],
            "execution_id": identity.get("execution_id"),
            "content_hash": parent_id,
            "likes_count": _safe_int(stats.get("reactions")),
            "comments_count": _safe_int(stats.get("comments")),
            "shares_count": _safe_int(stats.get("shares")),
        },
    )
    return int(getattr(result, "rowcount", 0) or 0) > 0


def _build_row(
    raw_item: dict[str, Any],
    *,
    context: dict[str, Any],
    identity: dict[str, Any],
    expected_hash: str | None,
    parent_id: str | None,
) -> dict[str, Any]:
    raw = dict(raw_item)
    base_hash = compute_content_hash(raw, context.get("dedupe_field"))
    content_hash = scope_content_hash(
        base_hash,
        context.get("hash_scope") or identity.get("execution_id"),
    )
    if expected_hash and str(expected_hash) != content_hash:
        raise ContentUplinkError("content hash does not match raw item")

    stored = scrub_secrets(raw)
    body = clean_text(
        stored.get("content")
        or stored.get("body")
        or stored.get("text")
        or stored.get("message")
        or stored.get("caption")
        or stored.get("description")
        or stored.get("image_desc")
    )
    author = clean_text(
        stored.get("author")
        or stored.get("name")
        or stored.get("username")
        or stored.get("full_name")
    )
    url = stored.get("url") or stored.get("permalink") or stored.get("link")
    screenshot_path = stored.get("_screenshot_path") or stored.get("screenshot_path")
    captured_at = context.get("captured_at") or context.get("captured_at_ms")
    return {
        "id": str(uuid.uuid4()),
        "collection": str(context.get("collection") or "default"),
        "platform": stored.get("platform") or context.get("platform"),
        "content_type": str(context.get("content_type") or "post"),
        "title": str(stored.get("title") or "")[:500] or None,
        "body": body,
        "author": str(author or "")[:255] or None,
        "author_id": str(stored.get("author_id") or "")[:255] or None,
        "url": str(url or "")[:1000] or None,
        "likes_count": _safe_int(_first_present(stored, "likes_count", "likes", "reactions", "like")),
        "comments_count": _safe_int(_first_present(stored, "comments_count", "comments", "comment")),
        "shares_count": _safe_int(_first_present(stored, "shares_count", "shares", "share")),
        "views_count": _safe_int(_first_present(stored, "views_count", "views", "view")),
        "media_urls": _normalize_media_urls(
            _first_present(stored, "media_urls", "media_artifacts", "permalink_candidates")
        ),
        "screenshot_path": str(screenshot_path)[:1000] if screenshot_path else None,
        "raw_data": stored,
        "tags": str(context.get("tags") or ""),
        "content_hash": content_hash,
        "parent_id": parent_id,
        "item_level": int(context.get("item_level") or 0),
        "device_serial": context.get("device_serial"),
        "campaign_id": identity.get("campaign_id"),
        "execution_id": identity.get("execution_id"),
        "scenario_name": context.get("scenario_name"),
        "scenario_id": identity.get("scenario_id"),
        "device_id": identity.get("device_id"),
        "account_id": identity.get("account_id"),
        "user_id": identity.get("user_id"),
        "org_id": identity.get("org_id"),
        "extracted_at": _parse_captured_at(captured_at),
        "content_date": _parse_content_date(
            _first_present(
                stored,
                "content_date",
                "posted_at",
                "published_at",
                "timestamp",
                "date",
                "date_posted",
            ),
            captured_at=captured_at,
        ),
        "created_at": datetime.now(timezone.utc),
    }


async def _insert_content_rows(db, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "inserted_count": 0,
            "duplicate_count": 0,
            "inserted_content_hashes": [],
        }
    result = await db.execute(
        _INSERT_CONTENT_SQL,
        {"rows": json.dumps(rows, ensure_ascii=False, default=str)},
    )
    inserted_rows = [dict(row) for row in result.mappings().all()]
    groups: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in inserted_rows:
        key = (
            row["collection"],
            row["user_id"],
            row["org_id"],
            row["platform"],
            row["content_type"],
        )
        groups[key] += 1
    for (collection, user_id, org_id, platform, content_type), count in groups.items():
        await db.execute(
            _UPSERT_COLLECTION_SQL,
            {
                "id": str(uuid.uuid4()),
                "name": collection,
                "user_id": user_id,
                "org_id": org_id,
                "platform": platform,
                "content_type": content_type,
                "item_count": count,
            },
        )
    hashes = [str(row["content_hash"]) for row in inserted_rows]
    return {
        "inserted_count": len(hashes),
        "duplicate_count": len(rows) - len(hashes),
        "inserted_content_hashes": hashes,
    }


async def _upsert_entity_items(
    db,
    *,
    items: list[dict[str, Any]],
    captured_at: Any,
    context: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any]:
    observed_at = _parse_captured_at(captured_at).isoformat()
    unique: dict[tuple[str, str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for item in items:
        display_name = str(item.get("display_name") or "").strip()
        identity_key = str(item.get("identity_key") or "").strip()
        if not display_name or not identity_key:
            raise ContentUplinkError("entity display_name and identity_key are required")
        row = {
            "id": str(uuid.uuid4()),
            "platform": str(item.get("platform") or "unknown").strip().lower(),
            "entity_type": str(item.get("entity_type") or "source").strip().lower(),
            "identity_key": identity_key,
            "identity_confidence": str(item.get("identity_confidence") or "name_only"),
            "external_id": item.get("external_id"),
            "canonical_url": item.get("canonical_url"),
            "display_name": display_name,
            "status": str(item.get("status") or "candidate"),
            "attributes": scrub_secrets(dict(item.get("attributes") or {})),
            "metrics": scrub_secrets(dict(item.get("metrics") or {})),
            "observed_at": observed_at,
        }
        key = (row["platform"], row["entity_type"], row["identity_key"])
        unique[key] = (item, row)
    entity_rows = [row for _, row in unique.values()]
    result = await db.execute(
        _UPSERT_ENTITIES_SQL,
        {
            "rows": json.dumps(entity_rows, ensure_ascii=False, default=str),
            "org_id": identity["org_id"],
        },
    )
    returned = [dict(row) for row in result.mappings().all()]
    ids = {
        (str(row["platform"]), str(row["entity_type"]), str(row["identity_key"])): str(row["id"])
        for row in returned
    }
    observations = []
    discoveries = []
    query = str(context.get("search_query") or context.get("query") or "").strip()
    for key, (item, entity_row) in unique.items():
        entity_id = ids[key]
        observations.append(
            {
                "id": str(uuid.uuid4()),
                "external_entity_id": entity_id,
                "observed_at": observed_at,
                "display_name": entity_row["display_name"],
                "attributes": entity_row["attributes"],
                "metrics": entity_row["metrics"],
                "raw_data": scrub_secrets(dict(item.get("raw_data") or {})),
                "account_id": identity.get("account_id"),
                "execution_id": identity.get("execution_id"),
            }
        )
        if query:
            discoveries.append(
                {
                    "id": str(uuid.uuid4()),
                    "external_entity_id": entity_id,
                    "query": query,
                    "rank": item.get("rank"),
                    "context": {
                        "source_index": context.get("source_index"),
                        "device_serial": context.get("device_serial"),
                    },
                    "account_id": identity.get("account_id"),
                    "execution_id": identity.get("execution_id"),
                    "observed_at": observed_at,
                }
            )
    await db.execute(
        _UPSERT_ENTITY_OBSERVATIONS_SQL,
        {
            "rows": json.dumps(observations, ensure_ascii=False, default=str),
            "org_id": identity["org_id"],
        },
    )
    if discoveries:
        await db.execute(
            _UPSERT_ENTITY_DISCOVERIES_SQL,
            {
                "rows": json.dumps(discoveries, ensure_ascii=False, default=str),
                "org_id": identity["org_id"],
            },
        )
    return {
        "attempted_count": len(items),
        "inserted_count": len(returned),
        "duplicate_count": 0,
        "entity_ids": list(ids.values()),
        "observation_count": len(observations),
        "discovery_count": len(discoveries),
    }


async def _persist_edge_batch_once(
    *,
    relay_id: str,
    batch: dict[str, Any],
    trusted_context: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist one versioned relay batch in one transaction."""
    if int(batch.get("schema_version") or 0) != 1:
        raise ContentUplinkError("unsupported persist batch schema")
    kind = str(batch.get("kind") or "")
    if kind not in {"content", "entities"}:
        raise ContentUplinkError("unsupported persist batch kind")
    items = batch.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ContentUplinkError("persist batch items must be objects")
    hashes = batch.get("content_hashes") or []
    if hashes and (not isinstance(hashes, list) or len(hashes) != len(items)):
        raise ContentUplinkError("content_hashes must align with items")

    # Last gate before the row lands. The step guard catches the common path,
    # but every writer reaches the table through here, so an unresolved
    # placeholder is rejected once rather than trusted N times.
    unresolved = unresolved_var_names(trusted_context.get("collection"))
    if unresolved:
        edge_ingest_rejected_total.labels(reason="unresolved_variable").inc()
        raise ContentUplinkError(
            f"collection has unresolved variable ${{{unresolved[0]}}}"
        )

    started = time.perf_counter()
    async with edge_ingest_session() as db:
        identity = await _canonical_identity(db, relay_id=relay_id, context=trusted_context)
        if kind == "entities":
            result = await _upsert_entity_items(
                db,
                items=items,
                captured_at=batch.get("captured_at"),
                context=trusted_context,
                identity=identity,
            )
            result["db_ms"] = int((time.perf_counter() - started) * 1000)
            return result
        content_type = str(trusted_context.get("content_type") or "").strip()
        require_valid_content_type(content_type)
        parent_hint = batch.get("parent_hint")
        parent_id = None
        if isinstance(parent_hint, dict):
            parent_id = await _resolve_parent_id(
                db,
                hint=parent_hint,
                context=trusted_context,
                identity=identity,
            )
        rows = [
            _build_row(
                item,
                context=trusted_context,
                identity=identity,
                expected_hash=str(hashes[index]) if hashes else None,
                parent_id=parent_id,
            )
            for index, item in enumerate(items)
        ]
        result = await _insert_content_rows(db, rows)
        post_stats = batch.get("post_stats")
        result["parent_stats_updated"] = bool(
            parent_id
            and isinstance(post_stats, dict)
            and await _update_parent_stats(
                db,
                parent_id=parent_id,
                stats=post_stats,
                identity=identity,
            )
        )
    result["attempted_count"] = len(rows)
    result["db_ms"] = int((time.perf_counter() - started) * 1000)
    result["batch_content_hashes"] = [row["content_hash"] for row in rows]
    return result


async def persist_edge_batch(
    *,
    relay_id: str,
    batch: dict[str, Any],
    trusted_context: dict[str, Any],
) -> dict[str, Any]:
    """Persist one batch without allowing relay load to exhaust API capacity."""
    kind = str(batch.get("kind") or "unknown")
    items = batch.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    batch_size = len(json.dumps(batch, ensure_ascii=False, default=str).encode("utf-8"))
    edge_ingest_batch_bytes.observe(batch_size)
    if batch_size > max(1, int(os.getenv("EDGE_INGEST_MAX_BATCH_BYTES", "16777216"))):
        edge_ingest_rejected_total.labels(reason="too_large").inc()
        raise ContentUplinkError("persist batch exceeds byte limit")
    if item_count > max(1, int(os.getenv("EDGE_INGEST_MAX_ITEMS", "5000"))):
        edge_ingest_rejected_total.labels(reason="too_many_items").inc()
        raise ContentUplinkError("persist batch exceeds item limit")

    semaphore = _ingest_semaphore()
    try:
        await asyncio.wait_for(
            semaphore.acquire(),
            timeout=max(0.01, float(os.getenv("EDGE_INGEST_QUEUE_TIMEOUT", "2"))),
        )
    except asyncio.TimeoutError as exc:
        edge_ingest_rejected_total.labels(reason="saturated").inc()
        raise ContentUplinkSaturated("edge ingest concurrency limit reached") from exc

    started = time.perf_counter()
    try:
        result = await _persist_edge_batch_once(
            relay_id=relay_id,
            batch=batch,
            trusted_context=trusted_context,
        )
    except Exception:
        edge_ingest_rows_total.labels(kind=kind, status="failed").inc(item_count)
        raise
    else:
        edge_ingest_rows_total.labels(kind=kind, status="persisted").inc(
            int(result.get("inserted_count") or 0)
        )
        return result
    finally:
        edge_ingest_duration_seconds.labels(kind=kind).observe(time.perf_counter() - started)
        semaphore.release()
