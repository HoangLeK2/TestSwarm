"""041 — Append-only account profile / session audit timeline."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS account_events (
            id            VARCHAR(36)  PRIMARY KEY,
            account_id    VARCHAR(36)  NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            user_id       VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
            event_type    VARCHAR(50)  NOT NULL,
            device_serial VARCHAR(100),
            platform      VARCHAR(50),
            entity_type   VARCHAR(50),
            entity_id     VARCHAR(36),
            details       JSONB        NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_account_events_account_created "
        "ON account_events (account_id, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_account_events_type_created "
        "ON account_events (event_type, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_account_events_user_created "
        "ON account_events (user_id, created_at DESC) "
        "WHERE user_id IS NOT NULL"
    ))
