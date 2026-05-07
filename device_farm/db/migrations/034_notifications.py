from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_channels (
            id         VARCHAR(36)  PRIMARY KEY,
            name       VARCHAR(255) NOT NULL,
            type       VARCHAR(20)  NOT NULL,
            config     JSONB        NOT NULL DEFAULT '{}',
            events     JSONB        NOT NULL DEFAULT '[]',
            is_enabled BOOLEAN      NOT NULL DEFAULT TRUE,
            user_id    VARCHAR(36)  REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         VARCHAR(36)  PRIMARY KEY,
            channel_id VARCHAR(36)  REFERENCES notification_channels(id) ON DELETE SET NULL,
            event      VARCHAR(50)  NOT NULL,
            title      VARCHAR(255) NOT NULL,
            body       TEXT,
            data       JSONB        NOT NULL DEFAULT '{}',
            is_read    BOOLEAN      NOT NULL DEFAULT FALSE,
            sent_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            user_id    VARCHAR(36)  REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_notification_channels_user_type "
        "ON notification_channels (user_id, type)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_notification_channels_enabled "
        "ON notification_channels (is_enabled)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_notifications_user_read "
        "ON notifications (user_id, is_read)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_notifications_user_created "
        "ON notifications (user_id, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_notifications_event ON notifications (event)"
    ))
