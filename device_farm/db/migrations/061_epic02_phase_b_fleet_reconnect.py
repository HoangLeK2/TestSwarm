"""061 — Epic 02 Phase B: reconnect policies + fleet query indexes."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS reconnect_policies (
                org_id VARCHAR(36) PRIMARY KEY,
                interval_base_ms INTEGER NOT NULL DEFAULT 1000,
                max_interval_ms INTEGER NOT NULL DEFAULT 60000,
                max_attempts INTEGER NOT NULL DEFAULT 20,
                jitter_factor DOUBLE PRECISION NOT NULL DEFAULT 0.2,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_by VARCHAR(36)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_org_paired_at
            ON devices (org_id, paired_at DESC);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_org_last_seen
            ON devices (org_id, last_seen DESC);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_org_name
            ON devices (org_id, name);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_device_fsm_org_state
            ON device_states (state, device_id);
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_device_fsm_org_state"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_devices_org_name"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_devices_org_last_seen"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_devices_org_paired_at"))
    await conn.execute(text("DROP TABLE IF EXISTS reconnect_policies"))
