from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id            VARCHAR(36)  PRIMARY KEY,
            action        VARCHAR(50)  NOT NULL,
            entity_type   VARCHAR(50),
            entity_id     VARCHAR(36),
            device_serial VARCHAR(100),
            user_id       VARCHAR(36)  REFERENCES users(id) ON DELETE CASCADE,
            details       JSONB        NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log (created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log (action)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_device ON activity_log (device_serial)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_user_created "
        "ON activity_log (user_id, created_at DESC)"
    ))
