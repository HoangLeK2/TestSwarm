"""075 — Preview execution kind + organization_id (DF-T-04-018)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS kind VARCHAR(32) NOT NULL DEFAULT 'campaign';
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS organization_id VARCHAR(36);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_executions_kind_org_user_created
            ON executions (kind, organization_id, user_id, created_at DESC);
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE executions AS e
            SET organization_id = c.org_id
            FROM campaigns AS c
            WHERE e.campaign_id = c.id
              AND e.organization_id IS NULL;
            """
        )
    )
