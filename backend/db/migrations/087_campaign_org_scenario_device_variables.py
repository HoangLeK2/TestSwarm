"""087 - Per-device variables scoped to campaign org-scenario refs."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS campaign_org_scenario_device_variables (
            campaign_id VARCHAR(36) NOT NULL,
            org_scenario_id VARCHAR(36) NOT NULL,
            device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            vars JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (campaign_id, org_scenario_id, device_id),
            CONSTRAINT fk_cosdv_campaign_org_scenario_ref
                FOREIGN KEY (campaign_id, org_scenario_id)
                REFERENCES campaign_org_scenario_refs(campaign_id, org_scenario_id)
                ON DELETE CASCADE
        )
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cosdv_campaign_scenario
        ON campaign_org_scenario_device_variables (campaign_id, org_scenario_id)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_cosdv_device
        ON campaign_org_scenario_device_variables (device_id)
    """))
