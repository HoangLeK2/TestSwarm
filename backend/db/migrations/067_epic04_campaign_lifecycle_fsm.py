"""067 — Epic 04: campaign lifecycle FSM timestamps + lock (DF-T-04-007)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS lock_version INTEGER NOT NULL DEFAULT 0;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaigns_status
            ON campaigns (status);
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'check_campaign_status'
                ) THEN
                    ALTER TABLE campaigns DROP CONSTRAINT check_campaign_status;
                END IF;
                ALTER TABLE campaigns ADD CONSTRAINT check_campaign_status
                CHECK (status IN (
                    'draft', 'scheduled', 'idle', 'running', 'paused',
                    'completed', 'cancelled', 'failed', 'archived'
                ));
            END $$;
            """
        )
    )
