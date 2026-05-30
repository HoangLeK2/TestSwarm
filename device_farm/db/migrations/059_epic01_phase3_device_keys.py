"""059 — Epic 01 Phase 3: versioned device keys scaffold."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS device_keys (
                id VARCHAR(36) PRIMARY KEY,
                device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                key_hash VARCHAR(128) NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                revoked_at TIMESTAMPTZ
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_device_keys_device_status_version
            ON device_keys (device_id, status, version);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_device_keys_device_version
            ON device_keys (device_id, version);
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_device_keys_device_version"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_device_keys_device_status_version"))
    await conn.execute(text("DROP TABLE IF EXISTS device_keys"))
