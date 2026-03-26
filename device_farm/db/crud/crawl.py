from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.crawl import CrawlJob, CrawlPost


async def create_crawl_job(
    db: AsyncSession,
    *,
    device_serial: str,
    campaign_id: Optional[str],
    group_id: str,
    app: str,
    config: dict,
    scenario_steps: list,
    name: str = "",
) -> CrawlJob:
    job = CrawlJob(
        name=name or f"FB Group {group_id} - {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        device_serial=device_serial,
        campaign_id=campaign_id,
        group_id=group_id,
        app=app,
        config=config,
        scenario_steps=scenario_steps,
        status="pending",
        errors=[],
    )
    db.add(job)
    await db.flush()
    return job


async def update_crawl_job(
    db: AsyncSession,
    job_id: str,
    *,
    status: Optional[str] = None,
    total_posts: Optional[int] = None,
    total_scrolls: Optional[int] = None,
    completed_at: Optional[datetime] = None,
    errors: Optional[list] = None,
) -> Optional[CrawlJob]:
    values: dict = {}
    if status is not None:
        values["status"] = status
    if total_posts is not None:
        values["total_posts"] = total_posts
    if total_scrolls is not None:
        values["total_scrolls"] = total_scrolls
    if completed_at is not None:
        values["completed_at"] = completed_at
    if errors is not None:
        values["errors"] = errors
    if values:
        await db.execute(update(CrawlJob).where(CrawlJob.id == job_id).values(**values))
    result = await db.execute(select(CrawlJob).where(CrawlJob.id == job_id))
    return result.scalar_one_or_none()


async def get_crawl_job(db: AsyncSession, job_id: str) -> Optional[CrawlJob]:
    result = await db.execute(
        select(CrawlJob)
        .options(selectinload(CrawlJob.posts))
        .where(CrawlJob.id == job_id)
    )
    return result.scalar_one_or_none()


async def list_crawl_jobs(
    db: AsyncSession,
    *,
    campaign_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[CrawlJob]:
    stmt = select(CrawlJob).order_by(CrawlJob.created_at.desc())
    if campaign_id:
        stmt = stmt.where(CrawlJob.campaign_id == campaign_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def save_crawl_posts(
    db: AsyncSession,
    job_id: str,
    posts: List[dict],
) -> int:
    """Bulk insert CrawlPost rows from post dicts.

    Accepts the dict shape returned by fb_group_crawl / scenario extract step.
    The crawl context uses key "timestamp"; DB column is "timestamp_raw".
    """
    if not posts:
        return 0
    rows = []
    for p in posts:
        # "timestamp" (from fb_group_crawl) → timestamp_raw
        ts_raw = p.get("timestamp_raw") or p.get("timestamp") or ""
        row = CrawlPost(
            job_id=job_id,
            author=str(p.get("author") or ""),
            text=str(p.get("text") or ""),
            timestamp_raw=str(ts_raw),
            reactions=p.get("reactions") or None,
            comments=p.get("comments") or None,
            shares=p.get("shares") or None,
            source_index=int(p.get("source_index") or 0),
        )
        rows.append(row)
    db.add_all(rows)
    await db.flush()
    return len(rows)


async def delete_crawl_job(db: AsyncSession, job_id: str) -> bool:
    result = await db.execute(delete(CrawlJob).where(CrawlJob.id == job_id))
    return result.rowcount > 0


async def get_crawl_posts(
    db: AsyncSession,
    job_id: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> List[CrawlPost]:
    result = await db.execute(
        select(CrawlPost)
        .where(CrawlPost.job_id == job_id)
        .order_by(CrawlPost.source_index, CrawlPost.scraped_at)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())
