"""065 — Epic 04: campaign data model extensions (DF-T-04-006)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS name_lower VARCHAR(255);
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS created_by VARCHAR(36)
                REFERENCES users(id) ON DELETE SET NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE campaigns
            SET name_lower = LOWER(name)
            WHERE name_lower IS NULL OR name_lower = '';
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE campaigns
            SET created_by = user_id
            WHERE created_by IS NULL AND user_id IS NOT NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ALTER COLUMN name_lower SET NOT NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE campaign_org_scenario_refs
            ADD COLUMN IF NOT EXISTS order_index INTEGER NOT NULL DEFAULT 0;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS campaign_tags (
                id VARCHAR(36) PRIMARY KEY,
                campaign_id VARCHAR(36) NOT NULL
                    REFERENCES campaigns(id) ON DELETE CASCADE,
                tag VARCHAR(100) NOT NULL,
                CONSTRAINT uq_campaign_tags UNIQUE (campaign_id, tag)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaign_tags_campaign
            ON campaign_tags (campaign_id);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_campaigns_org_name_active
            ON campaigns (org_id, name_lower)
            WHERE deleted_at IS NULL AND status != 'archived';
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'campaigns_org_id_name_key'
                ) THEN
                    ALTER TABLE campaigns DROP CONSTRAINT campaigns_org_id_name_key;
                END IF;
            END $$;
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
                    'draft', 'idle', 'running', 'paused', 'completed', 'failed', 'archived'
                ));
            END $$;
            """
        )
    )
