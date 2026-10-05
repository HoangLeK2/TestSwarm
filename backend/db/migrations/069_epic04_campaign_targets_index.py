"""069 — Epic 04: campaign_targets composite index (DF-T-04-008 perf)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaign_targets_campaign_dispatch
            ON campaign_targets (campaign_id, dispatch_id);
            """
        )
    )
