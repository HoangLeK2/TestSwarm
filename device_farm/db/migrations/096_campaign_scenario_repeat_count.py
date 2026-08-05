"""096 - Per-campaign scenario repeat count."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE campaign_org_scenario_refs
        ADD COLUMN IF NOT EXISTS repeat_count INTEGER NOT NULL DEFAULT 1
    """))
    await conn.execute(text("""
        UPDATE campaign_org_scenario_refs
        SET repeat_count = 1
        WHERE repeat_count IS NULL OR repeat_count < 1
    """))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_campaign_org_scenario_refs_repeat_count'
            ) THEN
                ALTER TABLE campaign_org_scenario_refs
                ADD CONSTRAINT ck_campaign_org_scenario_refs_repeat_count
                CHECK (repeat_count >= 1 AND repeat_count <= 20);
            END IF;
        END $$;
    """))
