"""Campaign FK helpers for content persistence."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def campaign_exists(db: AsyncSession, campaign_id: str) -> bool:
    """Check campaign row exists without requiring request tenant context."""
    from db.models.campaign import Campaign

    table = Campaign.__table__
    result = await db.execute(
        select(table.c.id).where(table.c.id == campaign_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def resolve_persist_campaign_id(
    db: AsyncSession,
    *,
    campaign_id: str | None,
    execution_id: str | None = None,
) -> str | None:
    """Return a campaign_id safe for content_items FK inserts.

    Prefers ``execution.campaign_id`` when an execution is known. Drops IDs that
    no longer exist in ``campaigns`` (e.g. stale Temporal workflow input after
    campaign deletion). Preview executions never attach a campaign FK.
    """
    from db.crud.execution import get_execution
    from db.models.enums import ExecutionKind

    effective = (campaign_id or "").strip() or None
    if execution_id:
        execution = await get_execution(db, execution_id)
        if execution is not None:
            if (execution.kind or "").strip() == ExecutionKind.PREVIEW.value:
                return None
            if execution.campaign_id:
                effective = (execution.campaign_id or "").strip() or None

    if not effective:
        return None

    if not await campaign_exists(db, effective):
        log.warning(
            "dropping stale campaign_id=%s for content persist (execution_id=%s)",
            effective,
            execution_id,
        )
        return None
    return effective
