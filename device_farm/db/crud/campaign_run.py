"""CRUD for CampaignRun — one record per campaign execution."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import CampaignRun


async def create_campaign_run(
    db: AsyncSession,
    campaign_id: str,
    device_serials: list[str],
    workflow_ids: list[str],
    scenarios_count: int,
) -> CampaignRun:
    run = CampaignRun(
        campaign_id=campaign_id,
        status="running",
        device_serials=device_serials,
        workflow_ids=workflow_ids,
        scenarios_count=scenarios_count,
    )
    db.add(run)
    await db.flush()
    return run


async def get_campaign_run(db: AsyncSession, run_id: str) -> Optional[CampaignRun]:
    result = await db.execute(select(CampaignRun).where(CampaignRun.id == run_id))
    return result.scalar_one_or_none()


async def list_campaign_runs(
    db: AsyncSession,
    campaign_id: str,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[CampaignRun], int]:
    stmt = select(CampaignRun).where(CampaignRun.campaign_id == campaign_id)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    data_stmt = stmt.order_by(CampaignRun.started_at.desc()).offset(offset).limit(limit)
    result = await db.execute(data_stmt)
    return list(result.scalars().all()), total


async def finish_campaign_run(
    db: AsyncSession,
    run_id: str,
    status: str = "completed",
) -> None:
    await db.execute(
        update(CampaignRun)
        .where(CampaignRun.id == run_id)
        .values(status=status, finished_at=datetime.now(timezone.utc))
    )


async def run_content_stats(
    db: AsyncSession, run_id: str
) -> dict:
    """Count saved/duplicate items for a specific run."""
    from db.models.content import ContentItem
    from sqlalchemy import func as f

    total = (
        await db.execute(
            select(f.count(ContentItem.id)).where(ContentItem.run_id == run_id)
        )
    ).scalar_one()

    latest = (
        await db.execute(
            select(f.max(ContentItem.extracted_at)).where(ContentItem.run_id == run_id)
        )
    ).scalar_one()

    return {
        "run_id": run_id,
        "total_items": total,
        "latest_extraction": latest.isoformat() if latest else None,
    }
