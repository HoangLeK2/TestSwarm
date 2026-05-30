"""050 — Fleet stats indexes, tenant dead threshold, device FSM scan indexes."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS tenant_settings (
            org_id              VARCHAR(36) PRIMARY KEY
                                REFERENCES organizations(id) ON DELETE CASCADE,
            dead_threshold_sec  INTEGER NOT NULL DEFAULT 600
        )
    """))

    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_device_states_state
        ON device_states (state)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_device_states_state_reconnecting_since
        ON device_states (state, reconnecting_since)
        WHERE state = 'reconnecting'
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_device_states_state_updated_at
        ON device_states (state, updated_at)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_mcp_sessions_status_device_serial
        ON mcp_sessions (status, device_serial)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_device_group_members_group_device
        ON device_group_members (group_id, device_id)
    """))
