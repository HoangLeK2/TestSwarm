"""070 — Epic 04: composite index for campaign execution aggregation (DF-T-04-007)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_executions_campaign_status
            ON executions (campaign_id, status);
            """
        )
    )
