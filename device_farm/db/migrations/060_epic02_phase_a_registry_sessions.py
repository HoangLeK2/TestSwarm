"""060 — Epic 02 Phase A: device registry fields, reserve sessions, idle thresholds."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_serial VARCHAR(128);
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS relay_serial VARCHAR(128);
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS status VARCHAR(20)
            NOT NULL DEFAULT 'paired';
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS paired_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS unpaired_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT '';
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE devices ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE devices
            SET device_serial = serial,
                status = CASE WHEN serial LIKE 'pending-%' THEN 'paired' ELSE 'paired' END,
                paired_at = COALESCE(paired_at, created_at),
                updated_at = COALESCE(updated_at, created_at)
            WHERE device_serial IS NULL OR device_serial = '';
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS device_reserve_sessions (
                id VARCHAR(36) PRIMARY KEY,
                device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                org_id VARCHAR(36) NOT NULL,
                owner_type VARCHAR(20) NOT NULL,
                owner_id VARCHAR(128) NOT NULL,
                claimed_at TIMESTAMPTZ NOT NULL,
                released_at TIMESTAMPTZ,
                last_heartbeat TIMESTAMPTZ NOT NULL,
                ttl_sec INTEGER NOT NULL,
                release_reason VARCHAR(20),
                ctx JSON,
                created_by_user_id VARCHAR(36)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_device_reserve_sessions_device_active
            ON device_reserve_sessions (device_id)
            WHERE released_at IS NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_device_reserve_sessions_owner
            ON device_reserve_sessions (owner_type, owner_id);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_device_reserve_sessions_heartbeat
            ON device_reserve_sessions (last_heartbeat)
            WHERE released_at IS NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS session_idle_thresholds JSON;
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE tenant_settings DROP COLUMN IF EXISTS session_idle_thresholds"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_device_reserve_sessions_heartbeat"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_device_reserve_sessions_owner"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_device_reserve_sessions_device_active"))
    await conn.execute(text("DROP TABLE IF EXISTS device_reserve_sessions"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS updated_at"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS notes"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS unpaired_at"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS paired_at"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS status"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS relay_serial"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS device_serial"))
