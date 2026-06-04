"""CRUD for campaign dispatch target snapshots (DF-T-04-008)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.campaign import CampaignTarget
from db.models.utils import _uuid
from services.campaign.constants import CAMPAIGN_TARGET_INSERT_CHUNK


async def insert_campaign_targets(
    db: AsyncSession,
    *,
    campaign_id: str,
    dispatch_id: str,
    rows: list[tuple[str, str, str]],
) -> list[CampaignTarget]:
    """Insert snapshot rows: (device_id, source_kind, source_ref_id)."""
    created: list[CampaignTarget] = []
    for i in range(0, len(rows), CAMPAIGN_TARGET_INSERT_CHUNK):
        chunk = rows[i : i + CAMPAIGN_TARGET_INSERT_CHUNK]
        batch = [
            CampaignTarget(
                id=_uuid(),
                campaign_id=campaign_id,
                dispatch_id=dispatch_id,
                device_id=device_id,
                source_kind=source_kind,
                source_ref_id=source_ref_id,
            )
            for device_id, source_kind, source_ref_id in chunk
        ]
        db.add_all(batch)
        created.extend(batch)
    await db.flush()
    return created


async def list_targets_for_dispatch(
    db: AsyncSession,
    dispatch_id: str,
) -> list[CampaignTarget]:
    result = await db.execute(
        select(CampaignTarget)
        .where(CampaignTarget.dispatch_id == dispatch_id)
        .order_by(CampaignTarget.created_at)
    )
    return list(result.scalars().all())
