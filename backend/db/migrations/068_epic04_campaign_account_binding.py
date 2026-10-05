"""068 — Epic 04: campaign account binding (DF-T-04-009)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS account_group_id VARCHAR(36)
                REFERENCES account_groups(id) ON DELETE SET NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS scenario_account_id VARCHAR(36)
                REFERENCES accounts(id) ON DELETE SET NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS per_device_accounts JSONB NOT NULL DEFAULT '{}';
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaigns_account_group
            ON campaigns (account_group_id);
            """
        )
    )
