"""Tenant-safe catalog operations for reusable external entities."""
from __future__ import annotations

import re
import hashlib
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.external_entity import (
    ExternalEntity,
    ExternalEntityDiscovery,
    ExternalEntityObservation,
)
from db.models.account import Account
from db.models.execution import Execution
from tenancy.context import use_tenant_scope


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_external_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parts.path).rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


def build_identity_key(
    *,
    external_id: str | None,
    canonical_url: str | None,
    display_name: str,
) -> tuple[str, str]:
    stable_id = str(external_id or "").strip()
    if stable_id:
        return f"id:{hashlib.sha256(stable_id.encode('utf-8')).hexdigest()}", "external_id"
    normalized_url = normalize_external_url(canonical_url)
    if normalized_url:
        digest = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
        return f"url:{digest}", "canonical_url"
    normalized_name = unicodedata.normalize("NFKC", display_name).casefold().strip()
    normalized_name = re.sub(r"\s+", " ", normalized_name)
    if not normalized_name:
        raise ValueError("display_name is required when external identity is unavailable")
    digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()
    return f"name:{digest}", "name_only"


async def upsert_external_entity(
    db: AsyncSession,
    *,
    org_id: str,
    platform: str,
    entity_type: str,
    display_name: str,
    external_id: str | None = None,
    canonical_url: str | None = None,
    status: str = "candidate",
    attributes: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
    query: str | None = None,
    rank: int | None = None,
    discovery_context: dict[str, Any] | None = None,
    raw_data: dict[str, Any] | None = None,
    account_id: str | None = None,
    execution_id: str | None = None,
    created_by: str | None = None,
) -> tuple[ExternalEntity, bool]:
    platform_key = platform.strip().lower()
    type_key = entity_type.strip().lower()
    name = display_name.strip()
    if not platform_key or not type_key or not name:
        raise ValueError("platform, entity_type and display_name are required")
    canonical = normalize_external_url(canonical_url)
    identity_key, confidence = build_identity_key(
        external_id=external_id,
        canonical_url=canonical,
        display_name=name,
    )
    seen_at = observed_at or _now()
    attrs = dict(attributes or {})
    current_metrics = dict(metrics or {})

    with use_tenant_scope(org_id):
        if execution_id:
            execution_owner = await db.scalar(
                select(Execution.org_id).where(
                    Execution.id == execution_id,
                    Execution.org_id == org_id,
                )
            )
            if execution_owner is None:
                raise ValueError("execution_id does not belong to organization")
        if account_id:
            account_owner = await db.scalar(
                select(Account.org_id).where(
                    Account.id == account_id,
                    Account.org_id == org_id,
                )
            )
            if account_owner is None:
                raise ValueError("account_id does not belong to organization")
        result = await db.execute(
            select(ExternalEntity).where(
                ExternalEntity.org_id == org_id,
                ExternalEntity.platform == platform_key,
                ExternalEntity.entity_type == type_key,
                ExternalEntity.identity_key == identity_key,
            )
        )
        entity = result.scalar_one_or_none()
        if entity is None and confidence != "name_only":
            fallback_identity_key, _ = build_identity_key(
                external_id=None,
                canonical_url=None,
                display_name=name,
            )
            entity = await db.scalar(
                select(ExternalEntity).where(
                    ExternalEntity.org_id == org_id,
                    ExternalEntity.platform == platform_key,
                    ExternalEntity.entity_type == type_key,
                    ExternalEntity.identity_key == fallback_identity_key,
                )
            )
            if entity is not None:
                entity.identity_confidence = confidence

        created = False
        if entity is None:
            candidate = ExternalEntity(
                org_id=org_id,
                platform=platform_key,
                entity_type=type_key,
                identity_key=identity_key,
                identity_confidence=confidence,
                external_id=str(external_id).strip() if external_id else None,
                canonical_url=canonical,
                display_name=name,
                status=status,
                current_attributes=attrs,
                current_metrics=current_metrics,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                created_by=created_by,
            )
            try:
                async with db.begin_nested():
                    db.add(candidate)
                    await db.flush()
                entity = candidate
                created = True
            except IntegrityError:
                entity = await db.scalar(
                    select(ExternalEntity).where(
                        ExternalEntity.org_id == org_id,
                        ExternalEntity.platform == platform_key,
                        ExternalEntity.entity_type == type_key,
                        ExternalEntity.identity_key == identity_key,
                    )
                )
                if entity is None:
                    raise

        if not created:
            entity.display_name = name
            entity.external_id = str(external_id).strip() if external_id else entity.external_id
            entity.canonical_url = canonical or entity.canonical_url
            if entity.status == "candidate" or status != "candidate":
                entity.status = status
            entity.current_attributes = {
                **dict(entity.current_attributes or {}),
                **attrs,
            }
            entity.current_metrics = {
                **dict(entity.current_metrics or {}),
                **current_metrics,
            }
            entity.last_seen_at = max(_as_utc(entity.last_seen_at), _as_utc(seen_at))

        observation = None
        if execution_id:
            observation = await db.scalar(
                select(ExternalEntityObservation).where(
                    ExternalEntityObservation.org_id == entity.org_id,
                    ExternalEntityObservation.external_entity_id == entity.id,
                    ExternalEntityObservation.execution_id == execution_id,
                )
            )
        if observation is None:
            observation = ExternalEntityObservation(
                org_id=entity.org_id,
                external_entity_id=entity.id,
                execution_id=execution_id,
            )
            db.add(observation)
        observation.observed_at = seen_at
        observation.display_name = name
        observation.attributes = attrs
        observation.metrics = current_metrics
        observation.raw_data = dict(raw_data or {})
        observation.account_id = account_id

        cleaned_query = str(query or "").strip()
        if cleaned_query:
            discovery = None
            if execution_id:
                discovery = await db.scalar(
                    select(ExternalEntityDiscovery).where(
                        ExternalEntityDiscovery.org_id == entity.org_id,
                        ExternalEntityDiscovery.external_entity_id == entity.id,
                        ExternalEntityDiscovery.execution_id == execution_id,
                        ExternalEntityDiscovery.query == cleaned_query,
                    )
                )
            if discovery is None:
                discovery = ExternalEntityDiscovery(
                    org_id=entity.org_id,
                    external_entity_id=entity.id,
                    execution_id=execution_id,
                    query=cleaned_query,
                )
                db.add(discovery)
            discovery.rank = rank
            discovery.context = dict(discovery_context or {})
            discovery.account_id = account_id
            discovery.observed_at = seen_at
        await db.flush()
        return entity, created


async def get_external_entities_by_ids(
    db: AsyncSession,
    *,
    org_id: str,
    entity_ids: list[str],
) -> list[ExternalEntity]:
    if not entity_ids:
        return []
    ordered_unique = list(dict.fromkeys(entity_ids))
    with use_tenant_scope(org_id):
        result = await db.execute(
            select(ExternalEntity).where(
                ExternalEntity.org_id == org_id,
                ExternalEntity.id.in_(ordered_unique),
            )
        )
        by_id = {row.id: row for row in result.scalars()}
    return [by_id[entity_id] for entity_id in ordered_unique if entity_id in by_id]


async def get_external_entity(
    db: AsyncSession,
    *,
    org_id: str,
    entity_id: str,
) -> ExternalEntity | None:
    rows = await get_external_entities_by_ids(
        db,
        org_id=org_id,
        entity_ids=[entity_id],
    )
    return rows[0] if rows else None


async def list_external_entities(
    db: AsyncSession,
    *,
    org_id: str,
    platform: str | None = None,
    entity_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ExternalEntity], int]:
    filters = [ExternalEntity.org_id == org_id]
    if platform:
        filters.append(ExternalEntity.platform == platform.strip().lower())
    if entity_type:
        filters.append(ExternalEntity.entity_type == entity_type.strip().lower())
    if status:
        filters.append(ExternalEntity.status == status.strip().lower())
    if search:
        filters.append(ExternalEntity.display_name.ilike(f"%{search.strip()}%"))
    with use_tenant_scope(org_id):
        total = int(
            await db.scalar(
                select(func.count(ExternalEntity.id)).where(*filters)
            )
            or 0
        )
        result = await db.execute(
            select(ExternalEntity)
            .where(*filters)
            .order_by(ExternalEntity.last_seen_at.desc(), ExternalEntity.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars()), total
