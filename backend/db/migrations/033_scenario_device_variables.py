"""033_scenario_device_variables — per-(scenario,device) vars and drop legacy device_variables."""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_device_variables (
            scenario_id VARCHAR(36) NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
            device_id   VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            vars        JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (scenario_id, device_id)
        );
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdv_scenario ON scenario_device_variables (scenario_id);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sdv_device ON scenario_device_variables (device_id);"
    )
    # Legacy global store is no longer used.
    await conn.execute("DROP TABLE IF EXISTS device_variables;")

