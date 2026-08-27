"""DF-010: Content Pipeline — CRUD operations for content items, collections, exports."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.content import ContentCollection, ContentItem
from db.models.execution import Execution


async def resolve_org_id(db: AsyncSession, *, user_id: str | None = None) -> str | None:
    if not user_id:
        return None
    from db.models.user import User

    result = await db.execute(select(User.default_org_id).where(User.id == user_id))
    return result.scalar_one_or_none()


async def compute_item_level(db: AsyncSession, parent_id: str | None) -> int:
    """Epic 06: root level=1, each child adds one."""
    if not parent_id:
        return 1
    result = await db.execute(
        select(ContentItem.item_level).where(
            (ContentItem.id == parent_id) | (ContentItem.content_hash == parent_id)
        )
    )
    parent_level = result.scalar_one_or_none()
    if parent_level is None:
        return 1
    return min(int(parent_level) + 1, 10)


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
    stmt = select(ContentItem).where(ContentItem.deleted_at.is_(None))

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
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                ContentItem.title.ilike(pattern, escape="\\"),
                ContentItem.body.ilike(pattern, escape="\\"),
                ContentItem.author.ilike(pattern, escape="\\"),
                ContentItem.author_id.ilike(pattern, escape="\\"),
                ContentItem.url.ilike(pattern, escape="\\"),
                ContentItem.content_hash.ilike(pattern, escape="\\"),
                ContentItem.tags.ilike(pattern, escape="\\"),
            )
        )

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Data
    data_stmt = stmt.order_by(ContentItem.extracted_at.desc()).offset(offset).limit(limit)
    result = await db.execute(data_stmt)
    items = list(result.scalars().all())

    return items, total


async def query_content_children(
    db: AsyncSession,
    parent_item: ContentItem,
    *,
    user_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ContentItem], int]:
    """Comments linked to a post via parent_id variants or parser post ids."""
    from services.content.parent_links import (
        parent_link_candidates,
        parent_post_id_values,
    )

    candidates = parent_link_candidates(parent_item)
    pid_values = parent_post_id_values(parent_item)
    link_filters = []
    if candidates:
        link_filters.append(ContentItem.parent_id.in_(candidates))
    for pid in pid_values:
        link_filters.append(ContentItem.raw_data["parent_post_id"].as_string() == pid)
        link_filters.append(ContentItem.raw_data["post_key"].as_string() == pid)
        link_filters.append(ContentItem.raw_data["_pid"].as_string() == pid)
        link_filters.append(ContentItem.raw_data["stable_post_id"].as_string() == pid)
        link_filters.append(ContentItem.raw_data["fb_post_id"].as_string() == pid)
    for candidate in candidates:
        link_filters.append(
            ContentItem.raw_data["parent_content_hash"].as_string() == candidate
        )

    if not link_filters:
        return [], 0

    stmt = select(ContentItem).where(
        ContentItem.deleted_at.is_(None),
        or_(
            ContentItem.content_type == "fb_comment",
            ContentItem.content_type.like("%comment"),
            ContentItem.item_level > 0,
        ),
        or_(*link_filters),
    )
    if parent_item.collection:
        stmt = stmt.where(ContentItem.collection == parent_item.collection)
    if parent_item.campaign_id:
        stmt = stmt.where(ContentItem.campaign_id == parent_item.campaign_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    if parent_item.org_id:
        stmt = stmt.where(ContentItem.org_id == parent_item.org_id)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    data_stmt = (
        stmt.order_by(ContentItem.extracted_at.asc().nullslast(), ContentItem.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(data_stmt)
    return list(result.scalars().all()), total


async def update_content_screenshot_path(
    db: AsyncSession,
    *,
    content_hash: str,
    collection: str,
    screenshot_path: str,
    execution_id: str | None = None,
    user_id: str | None = None,
    only_if_missing: bool = False,
) -> bool:
    stmt = (
        update(ContentItem)
        .where(
            ContentItem.content_hash == content_hash,
            ContentItem.collection == collection,
        )
        .values(screenshot_path=screenshot_path[:1000])
    )
    if execution_id:
        stmt = stmt.where(ContentItem.execution_id == execution_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    if only_if_missing:
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                ContentItem.screenshot_path.is_(None),
                ContentItem.screenshot_path == "",
            )
        )
    result = await db.execute(stmt)
    return bool(result.rowcount)


async def update_content_screenshot_paths(
    db: AsyncSession,
    *,
    content_hashes: list[str],
    collection: str,
    screenshot_path: str,
    execution_id: str | None = None,
    user_id: str | None = None,
    only_if_missing: bool = False,
) -> int:
    hashes = [str(h) for h in content_hashes if h]
    if not hashes:
        return 0
    stmt = (
        update(ContentItem)
        .where(
            ContentItem.content_hash.in_(hashes),
            ContentItem.collection == collection,
        )
        .values(screenshot_path=screenshot_path[:1000])
    )
    if execution_id:
        stmt = stmt.where(ContentItem.execution_id == execution_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    if only_if_missing:
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                ContentItem.screenshot_path.is_(None),
                ContentItem.screenshot_path == "",
            )
        )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


async def update_content_stats(
    db: AsyncSession,
    content_hash: str,
    likes_count: int | None = None,
    shares_count: int | None = None,
    comments_count: int | None = None,
) -> bool:
    """Update likes_count / shares_count / comments_count for a post identified by content_hash.

    Called after opening a post's comment section where Facebook shows the
    exact engagement counts (more accurate than feed-level counts).
    Only updates fields that are provided (not None).
    Returns True if a row was updated.
    """
    values: dict[str, Any] = {}
    if likes_count is not None:
        values["likes_count"] = likes_count
    if shares_count is not None:
        values["shares_count"] = shares_count
    if comments_count is not None:
        values["comments_count"] = comments_count
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


async def count_by_campaign(
    db: AsyncSession,
    campaign_id: str,
    *,
    user_id: str | None = None,
    dispatch_id: str | None = None,
) -> int:
    """Count saved content items attached to a campaign."""
    stmt = select(func.count(ContentItem.id)).where(ContentItem.campaign_id == campaign_id)
    if user_id:
        stmt = stmt.where(ContentItem.user_id == user_id)
    if dispatch_id:
        stmt = stmt.join(Execution, Execution.id == ContentItem.execution_id).where(
            Execution.meta["dispatch_id"].as_string() == dispatch_id
        )
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


async def list_collections(db: AsyncSession, *, user_id: str | None = None) -> list[ContentCollection]:
    stmt = select(ContentCollection).order_by(ContentCollection.updated_at.desc())
    if user_id:
        stmt = stmt.where(ContentCollection.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_collection(db: AsyncSession, name: str, *, user_id: str | None = None) -> int:
    """Delete collection + all its items. Returns items deleted."""
    item_stmt = delete(ContentItem).where(ContentItem.collection == name)
    coll_stmt = delete(ContentCollection).where(ContentCollection.name == name)
    if user_id:
        item_stmt = item_stmt.where(ContentItem.user_id == user_id)
        coll_stmt = coll_stmt.where(ContentCollection.user_id == user_id)
    result = await db.execute(item_stmt)
    count = result.rowcount
    await db.execute(coll_stmt)
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


# ── Stats ─────────────────────────────────────────────────────────────────────


async def content_stats(db: AsyncSession, *, user_id: str | None = None) -> dict[str, Any]:
    """Aggregate content stats."""

    def _where(stmt):
        if user_id:
            return stmt.where(ContentItem.user_id == user_id)
        return stmt

    total = (await db.execute(_where(select(func.count(ContentItem.id))))).scalar_one()

    platform_rows = await db.execute(
        _where(select(ContentItem.platform, func.count(ContentItem.id))).group_by(
            ContentItem.platform
        )
    )
    by_platform = {row[0] or "unknown": row[1] for row in platform_rows.all()}

    coll_rows = await db.execute(
        _where(select(ContentItem.collection, func.count(ContentItem.id))).group_by(
            ContentItem.collection
        )
    )
    by_collection = {row[0]: row[1] for row in coll_rows.all()}

    latest = (await db.execute(_where(select(func.max(ContentItem.extracted_at))))).scalar_one()

    return {
        "total_items": total,
        "by_platform": by_platform,
        "by_collection": by_collection,
        "latest_extraction": latest.isoformat() if latest else None,
    }
