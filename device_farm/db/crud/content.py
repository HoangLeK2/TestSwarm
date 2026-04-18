"""DF-010: Content Pipeline — CRUD operations for content items, collections, exports."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.content import ContentCollection, ContentExport, ContentItem


async def get_content_by_hash(
    db: AsyncSession,
    content_hash: str,
    collection: str,
    *,
    user_id: str | None = None,
    execution_id: str | None = None,
) -> Optional[ContentItem]:
    stmt = select(ContentItem).where(
        ContentItem.content_hash == content_hash,
        ContentItem.collection == collection,
    )
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    if execution_id:
        stmt = stmt.where(ContentItem.execution_id == execution_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_content_item(db: AsyncSession, **kwargs) -> ContentItem:
    item = ContentItem(**kwargs)
    db.add(item)
    await db.flush()
    return item


async def get_content_item(
    db: AsyncSession, item_id: str, *, user_id: str | None = None
) -> Optional[ContentItem]:
    stmt = select(ContentItem).where(ContentItem.id == item_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def query_content(
    db: AsyncSession,
    *,
    collection: str | None = None,
    platform: str | None = None,
    content_type: str | None = None,
    search: str | None = None,
    device_serial: str | None = None,
    campaign_id: str | None = None,
    execution_id: str | None = None,
    content_hash: str | None = None,
    parent_id: str | None = None,
    user_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ContentItem], int]:
    """Query content items with filters. Returns (items, total_count)."""
    stmt = select(ContentItem)

    if collection:
        stmt = stmt.where(ContentItem.collection == collection)
    if platform:
        stmt = stmt.where(ContentItem.platform == platform)
    if content_type:
        stmt = stmt.where(ContentItem.content_type == content_type)
    if device_serial:
        stmt = stmt.where(ContentItem.device_serial == device_serial)
    if campaign_id:
        stmt = stmt.where(ContentItem.campaign_id == campaign_id)
    if execution_id:
        stmt = stmt.where(ContentItem.execution_id == execution_id)
    if content_hash:
        stmt = stmt.where(ContentItem.content_hash == content_hash)
    if parent_id:
        stmt = stmt.where(ContentItem.parent_id == parent_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    if date_from:
        stmt = stmt.where(ContentItem.extracted_at >= date_from)
    if date_to:
        stmt = stmt.where(ContentItem.extracted_at <= date_to)
    if search:
        # Escape LIKE special characters so user input is treated as a literal substring.
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(ContentItem.body.ilike(f"%{escaped}%", escape="\\"))

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Data
    data_stmt = stmt.order_by(ContentItem.extracted_at.desc()).offset(offset).limit(limit)
    result = await db.execute(data_stmt)
    items = list(result.scalars().all())

    return items, total


async def update_content_stats(
    db: AsyncSession,
    content_hash: str,
    likes_count: int | None = None,
    shares_count: int | None = None,
) -> bool:
    """Update likes_count / shares_count for a post identified by content_hash.

    Called after opening a post's comment section where Facebook shows the
    exact reaction/share counts (more accurate than feed-level counts).
    Only updates fields that are provided (not None).
    Returns True if a row was updated.
    """
    values: dict[str, Any] = {}
    if likes_count is not None:
        values["likes_count"] = likes_count
    if shares_count is not None:
        values["shares_count"] = shares_count
    if not values:
        return False
    result = await db.execute(
        update(ContentItem)
        .where(ContentItem.content_hash == content_hash, ContentItem.item_level == 0)
        .values(**values)
    )
    return result.rowcount > 0


async def count_by_execution(
    db: AsyncSession, execution_id: str, *, user_id: str | None = None
) -> int:
    """Phase 5 — count content items saved under an execution."""
    stmt = select(func.count(ContentItem.id)).where(ContentItem.execution_id == execution_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def delete_content_item(db: AsyncSession, item_id: str, *, user_id: str | None = None) -> bool:
    stmt = delete(ContentItem).where(ContentItem.id == item_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    result = await db.execute(stmt)
    return result.rowcount > 0


async def delete_content_by_collection(db: AsyncSession, collection: str) -> int:
    result = await db.execute(
        delete(ContentItem).where(ContentItem.collection == collection)
    )
    return result.rowcount


# ── Collections ───────────────────────────────────────────────────────────────


async def get_or_create_collection(
    db: AsyncSession, name: str, **kwargs,
) -> ContentCollection:
    user_id = kwargs.get("user_id")
    result = await db.execute(
        select(ContentCollection).where(
            ContentCollection.name == name,
            ContentCollection.user_id == user_id,
        )
    )
    coll = result.scalar_one_or_none()
    if coll:
        return coll
    coll = ContentCollection(name=name, **kwargs)
    db.add(coll)
    await db.flush()
    return coll


async def list_collections(db: AsyncSession, *, user_id: str) -> list[ContentCollection]:
    result = await db.execute(
        select(ContentCollection)
        .where(ContentCollection.user_id == user_id)
        .order_by(ContentCollection.updated_at.desc())
    )
    return list(result.scalars().all())


async def delete_collection(db: AsyncSession, name: str, *, user_id: str) -> int:
    """Delete collection + all its items. Returns items deleted."""
    result = await db.execute(
        delete(ContentItem).where(
            ContentItem.collection == name,
            ContentItem.user_id == user_id,
        )
    )
    count = result.rowcount
    await db.execute(
        delete(ContentCollection).where(
            ContentCollection.name == name,
            ContentCollection.user_id == user_id,
        )
    )
    return count


async def increment_collection_count(
    db: AsyncSession,
    name: str,
    *,
    user_id: str | None = None,
) -> None:
    stmt = update(ContentCollection).where(ContentCollection.name == name)
    if user_id:
        stmt = stmt.where(ContentCollection.user_id == user_id)
    await db.execute(
        stmt.values(item_count=ContentCollection.item_count + 1)
    )


# ── Exports ───────────────────────────────────────────────────────────────────


async def create_export(db: AsyncSession, **kwargs) -> ContentExport:
    export = ContentExport(**kwargs)
    db.add(export)
    await db.flush()
    return export


async def get_export(db: AsyncSession, export_id: str, *, user_id: str | None = None) -> Optional[ContentExport]:
    stmt = select(ContentExport).where(ContentExport.id == export_id)
    if user_id:
        stmt = stmt.where(ContentExport.user_id == user_id)
    result = await db.execute(
        stmt
    )
    return result.scalar_one_or_none()


async def update_export(db: AsyncSession, export_id: str, **kwargs) -> None:
    await db.execute(
        update(ContentExport).where(ContentExport.id == export_id).values(**kwargs)
    )


async def list_exports(db: AsyncSession, *, user_id: str, limit: int = 20) -> list[ContentExport]:
    result = await db.execute(
        select(ContentExport)
        .where(ContentExport.user_id == user_id)
        .order_by(ContentExport.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ── Stats ─────────────────────────────────────────────────────────────────────


async def content_stats(db: AsyncSession, *, user_id: str) -> dict[str, Any]:
    """Aggregate content stats."""
    total = (
        await db.execute(
            select(func.count(ContentItem.id)).where(ContentItem.user_id == user_id)
        )
    ).scalar_one()

    # By platform
    platform_rows = await db.execute(
        select(ContentItem.platform, func.count(ContentItem.id))
        .where(ContentItem.user_id == user_id)
        .group_by(ContentItem.platform)
    )
    by_platform = {row[0] or "unknown": row[1] for row in platform_rows.all()}

    # By collection
    coll_rows = await db.execute(
        select(ContentItem.collection, func.count(ContentItem.id))
        .where(ContentItem.user_id == user_id)
        .group_by(ContentItem.collection)
    )
    by_collection = {row[0]: row[1] for row in coll_rows.all()}

    # Latest
    latest = (await db.execute(
        select(func.max(ContentItem.extracted_at))
        .where(ContentItem.user_id == user_id)
    )).scalar_one()

    return {
        "total_items": total,
        "by_platform": by_platform,
        "by_collection": by_collection,
        "latest_extraction": latest.isoformat() if latest else None,
    }
