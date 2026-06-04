"""Collection-scoped external_id dedup (DF-T-06-010)."""
from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.content import ContentItem

log = logging.getLogger(__name__)

DedupAction = Literal["skip", "update", "error"]


async def find_by_external_id(
    db: AsyncSession,
    *,
    org_id: str,
    collection: str,
    platform: str | None,
    external_id: str,
) -> ContentItem | None:
    stmt = select(ContentItem).where(
        ContentItem.org_id == org_id,
        ContentItem.collection == collection,
        ContentItem.external_id == external_id,
        ContentItem.deleted_at.is_(None),
    )
    if platform:
        stmt = stmt.where(ContentItem.platform == platform)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def apply_external_id_dedup(
    db: AsyncSession,
    *,
    org_id: str,
    collection: str,
    platform: str | None,
    external_id: str | None,
    normalized_data: dict[str, Any],
    dedup_action: DedupAction = "skip",
) -> dict[str, Any] | None:
    """Return dedup result dict when hit; None when caller should insert."""
    if not external_id:
        log.warning(
            "content_without_external_id collection=%s platform=%s",
            collection,
            platform,
        )
        return None

    existing = await find_by_external_id(
        db,
        org_id=org_id,
        collection=collection,
        platform=platform,
        external_id=external_id,
    )
    if existing is None:
        return None

    try:
        from web.metrics import content_dedup_hit_total

        content_dedup_hit_total.labels(collection=collection, platform=platform or "unknown", action=dedup_action).inc()
    except Exception:
        pass

    if dedup_action == "error":
        from services.content.errors import ContentError

        raise ContentError(
            "duplicate external_id in collection",
            code="CONTENT_DEDUP_CONFLICT",
            details={"existing_id": existing.id, "external_id": external_id},
        )

    if dedup_action == "update":
        await db.execute(
            update(ContentItem)
            .where(ContentItem.id == existing.id)
            .values(
                likes_count=normalized_data.get("likes_count"),
                comments_count=normalized_data.get("comments_count"),
                shares_count=normalized_data.get("shares_count"),
                views_count=normalized_data.get("views_count"),
                body=normalized_data.get("body"),
                raw_data=normalized_data,
            )
        )
        await db.flush()
        return {"saved": False, "reason": "dedup_update", "id": existing.id, "dedup_hit": True}

    return {"saved": False, "reason": "dedup_skip", "id": existing.id, "dedup_hit": True}
