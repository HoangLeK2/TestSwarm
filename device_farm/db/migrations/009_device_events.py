"""
009_device_events — Create device_events table for event log & notifications.
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_events (
            id          VARCHAR(36) PRIMARY KEY,
            serial      VARCHAR(128) NOT NULL,
            event       VARCHAR(64)  NOT NULL,
            reason      VARCHAR(256),
            old_state   VARCHAR(32),
            new_state   VARCHAR(32),
            device_model VARCHAR(128),
            device_brand VARCHAR(64),
            extra_data  JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_device_events_serial ON device_events (serial)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_device_events_event ON device_events (event)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_device_events_created_at ON device_events (created_at)"
    ))
