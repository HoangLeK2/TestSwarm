"""088 - Allow device vars for recovery-only org scenarios on a campaign."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE campaign_org_scenario_device_variables
        DROP CONSTRAINT IF EXISTS fk_cosdv_campaign_org_scenario_ref
    """))
    await conn.execute(text("""
        ALTER TABLE campaign_org_scenario_device_variables
        ADD CONSTRAINT fk_cosdv_campaign
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    """))
    await conn.execute(text("""
        ALTER TABLE campaign_org_scenario_device_variables
        ADD CONSTRAINT fk_cosdv_org_scenario
            FOREIGN KEY (org_scenario_id) REFERENCES org_scenarios(id) ON DELETE CASCADE
    """))
