"""117 - Track device pool ownership separately from assigned workspace."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE devices
            ADD COLUMN IF NOT EXISTS managed_by_org_id VARCHAR(36)
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices
            ADD COLUMN IF NOT EXISTS managed_by_relay_id VARCHAR(128)
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE devices
               SET managed_by_org_id = org_id
             WHERE managed_by_org_id IS NULL
               AND org_id IS NOT NULL
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_managed_by_org_id
                ON devices (managed_by_org_id)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_managed_by_relay_id
                ON devices (managed_by_relay_id)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_org_created_at
                ON devices (org_id, created_at DESC)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_devices_managed_by_org_created_at
                ON devices (managed_by_org_id, created_at DESC)
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_relay_agents_org_connected_at
                ON relay_agents (org_id, connected_at DESC)
            """
        )
    )
