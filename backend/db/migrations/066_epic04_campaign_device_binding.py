"""066 — Epic 04: campaign device binding & fan-out (DF-T-04-008)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE campaigns
            ADD COLUMN IF NOT EXISTS per_device_overrides JSONB NOT NULL DEFAULT '{}';
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS campaign_targets (
                id VARCHAR(36) PRIMARY KEY,
                campaign_id VARCHAR(36) NOT NULL
                    REFERENCES campaigns(id) ON DELETE CASCADE,
                dispatch_id VARCHAR(36) NOT NULL,
                device_id VARCHAR(36) NOT NULL
                    REFERENCES devices(id) ON DELETE CASCADE,
                source_kind VARCHAR(20) NOT NULL,
                source_ref_id VARCHAR(36) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaign_targets_campaign
            ON campaign_targets (campaign_id);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaign_targets_dispatch
            ON campaign_targets (dispatch_id);
            """
        )
    )
