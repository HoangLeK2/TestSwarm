"""Set-based persistence for reusable external entities discovered on devices."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class ExternalEntityWriter:
    """Persist a parsed page in three set-based statements on a shared pool."""

    def __init__(self, pool_provider: Callable[[], Awaitable[Any]]) -> None:
        self._pool_provider = pool_provider

    async def persist_items(
        self,
        items: list[dict[str, Any]],
        *,
        context: dict[str, Any],
        captured_at: Any = None,
    ) -> dict[str, Any]:
        if not items:
            return {"attempted": 0, "upserted": 0, "observed": 0, "discovered": 0}

        observed_at = _iso_timestamp(captured_at)
        entity_rows = [_entity_row(item, observed_at) for item in items]
        unique_by_key: dict[
            tuple[str, str, str],
            tuple[dict[str, Any], dict[str, Any]],
        ] = {}
        for item, row in zip(items, entity_rows, strict=True):
            key = (
                str(row["platform"]),
                str(row["entity_type"]),
                str(row["identity_key"]),
            )
            unique_by_key[key] = (item, row)
        unique_entity_rows = [row for _, row in unique_by_key.values()]
        pool = await self._pool_provider()
        async with pool.acquire() as conn:
            org_id = await _canonical_org_id(conn, context)
            async with conn.transaction():
                returned = await conn.fetch(
                    """
                    INSERT INTO external_entities (
                        id, org_id, platform, entity_type, identity_key,
                        identity_confidence, external_id, canonical_url,
                        display_name, status, current_attributes, current_metrics,
                        first_seen_at, last_seen_at, created_at, updated_at
                    )
                    SELECT
                        x.id, $2, x.platform, x.entity_type, x.identity_key,
                        x.identity_confidence, x.external_id, x.canonical_url,
                        x.display_name, x.status, x.attributes, x.metrics,
                        x.observed_at, x.observed_at, NOW(), NOW()
                    FROM jsonb_to_recordset($1::jsonb) AS x(
                        id varchar, platform varchar, entity_type varchar,
                        identity_key varchar, identity_confidence varchar,
                        external_id varchar, canonical_url varchar,
                        display_name varchar, status varchar,
                        attributes jsonb, metrics jsonb, observed_at timestamptz
                    )
                    ON CONFLICT (org_id, platform, entity_type, identity_key)
                    DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        external_id = COALESCE(EXCLUDED.external_id, external_entities.external_id),
                        canonical_url = COALESCE(
                            EXCLUDED.canonical_url,
                            external_entities.canonical_url
                        ),
                        status = CASE
                            WHEN external_entities.status IN ('resolved', 'active')
                                 AND EXCLUDED.status = 'candidate'
                            THEN external_entities.status
                            ELSE EXCLUDED.status
                        END,
                        current_attributes = (
                            external_entities.current_attributes
                            || EXCLUDED.current_attributes
                        ),
                        current_metrics = (
                            external_entities.current_metrics
                            || EXCLUDED.current_metrics
                        ),
                        last_seen_at = GREATEST(
                            external_entities.last_seen_at,
                            EXCLUDED.last_seen_at
                        ),
                        updated_at = NOW()
                    RETURNING id::text, platform, entity_type, identity_key
                    """,
                    json.dumps(unique_entity_rows, ensure_ascii=False),
                    org_id,
                )
                ids = {
                    (
                        str(row["platform"]),
                        str(row["entity_type"]),
                        str(row["identity_key"]),
                    ): str(row["id"])
                    for row in returned
                }
                observation_rows = []
                discovery_rows = []
                query = str(context.get("search_query") or context.get("query") or "").strip()
                for key, (item, entity_row) in unique_by_key.items():
                    entity_id = ids[key]
                    observation_rows.append(
                        {
                            "id": str(uuid.uuid4()),
                            "external_entity_id": entity_id,
                            "observed_at": observed_at,
                            "display_name": entity_row["display_name"],
                            "attributes": entity_row["attributes"],
                            "metrics": entity_row["metrics"],
                            "raw_data": dict(item.get("raw_data") or {}),
                            "account_id": context.get("account_id"),
                            "execution_id": context.get("execution_id"),
                        }
                    )
                    if query:
                        discovery_rows.append(
                            {
                                "id": str(uuid.uuid4()),
                                "external_entity_id": entity_id,
                                "query": query,
                                "rank": item.get("rank"),
                                "context": {
                                    "source_index": context.get("source_index"),
                                    "device_serial": context.get("device_serial"),
                                },
                                "account_id": context.get("account_id"),
                                "execution_id": context.get("execution_id"),
                                "observed_at": observed_at,
                            }
                        )
                await conn.execute(
                    """
                    INSERT INTO external_entity_observations (
                        id, org_id, external_entity_id, observed_at, display_name,
                        attributes, metrics, raw_data, account_id, execution_id,
                        created_at
                    )
                    SELECT
                        x.id, $2, x.external_entity_id, x.observed_at,
                        x.display_name, x.attributes, x.metrics, x.raw_data,
                        x.account_id, x.execution_id, NOW()
                    FROM jsonb_to_recordset($1::jsonb) AS x(
                        id varchar, external_entity_id varchar,
                        observed_at timestamptz, display_name varchar,
                        attributes jsonb, metrics jsonb, raw_data jsonb,
                        account_id varchar, execution_id varchar
                    )
                    ON CONFLICT (
                        org_id, external_entity_id, execution_id
                    ) WHERE execution_id IS NOT NULL
                    DO UPDATE SET
                        observed_at = EXCLUDED.observed_at,
                        display_name = EXCLUDED.display_name,
                        attributes = EXCLUDED.attributes,
                        metrics = EXCLUDED.metrics,
                        raw_data = EXCLUDED.raw_data,
                        account_id = EXCLUDED.account_id
                    """,
                    json.dumps(observation_rows, ensure_ascii=False),
                    org_id,
                )
                if discovery_rows:
                    await conn.execute(
                        """
                        INSERT INTO external_entity_discoveries (
                            id, org_id, external_entity_id, query, rank, context,
                            account_id, execution_id, observed_at, created_at
                        )
                        SELECT
                            x.id, $2, x.external_entity_id, x.query, x.rank,
                            x.context, x.account_id, x.execution_id,
                            x.observed_at, NOW()
                        FROM jsonb_to_recordset($1::jsonb) AS x(
                            id varchar, external_entity_id varchar, query varchar,
                            rank integer, context jsonb, account_id varchar,
                            execution_id varchar, observed_at timestamptz
                        )
                        ON CONFLICT (
                            org_id, external_entity_id, execution_id, query
                        ) WHERE execution_id IS NOT NULL
                        DO UPDATE SET
                            rank = EXCLUDED.rank,
                            context = EXCLUDED.context,
                            account_id = EXCLUDED.account_id,
                            observed_at = EXCLUDED.observed_at
                        """,
                        json.dumps(discovery_rows, ensure_ascii=False),
                        org_id,
                    )
        return {
            "attempted": len(items),
            "upserted": len(returned),
            "observed": len(observation_rows),
            "discovered": len(discovery_rows),
            "entity_ids": list(ids.values()),
        }


def _iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    raw = str(value or "").strip()
    if raw:
        return raw
    return datetime.now(timezone.utc).isoformat()


def _entity_row(item: dict[str, Any], observed_at: str) -> dict[str, Any]:
    platform = str(item.get("platform") or "unknown").strip().lower()
    entity_type = str(item.get("entity_type") or "source").strip().lower()
    display_name = str(item.get("display_name") or "").strip()
    identity_key = str(item.get("identity_key") or "").strip()
    if not display_name or not identity_key:
        raise ValueError("display_name and identity_key are required")
    return {
        "id": str(uuid.uuid4()),
        "platform": platform,
        "entity_type": entity_type,
        "identity_key": identity_key,
        "identity_confidence": str(
            item.get("identity_confidence") or "name_only"
        ),
        "external_id": item.get("external_id"),
        "canonical_url": item.get("canonical_url"),
        "display_name": display_name,
        "status": str(item.get("status") or "candidate"),
        "attributes": dict(item.get("attributes") or {}),
        "metrics": dict(item.get("metrics") or {}),
        "observed_at": observed_at,
    }


async def _canonical_org_id(conn: Any, context: dict[str, Any]) -> str:
    supplied = str(context.get("org_id") or "").strip()
    execution_id = str(context.get("execution_id") or "").strip()
    if execution_id:
        execution_org = await conn.fetchval(
            "SELECT org_id::text FROM executions WHERE id::text = $1",
            execution_id,
        )
        if not execution_org:
            raise ValueError("execution_id is not valid for entity persistence")
        canonical = str(execution_org)
        if supplied and supplied != canonical:
            raise ValueError("org_id does not match execution ownership")
        supplied = canonical
    if not supplied:
        raise ValueError("org_id is required for external entity persistence")

    account_id = str(context.get("account_id") or "").strip()
    if account_id:
        account_org = await conn.fetchval(
            "SELECT org_id::text FROM accounts WHERE id::text = $1",
            account_id,
        )
        if not account_org or str(account_org) != supplied:
            raise ValueError("account_id does not belong to entity organization")
    return supplied
