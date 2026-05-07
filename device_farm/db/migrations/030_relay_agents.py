"""
030_relay_agents — Create relay_agents table to persist relay-agent identity.

One row per relay_id (upserted on connect, updated on heartbeat, status=offline on disconnect).
Stale online rows are cleared at server startup via a reconciliation query in web/server.py.
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS relay_agents (
            id                VARCHAR(36)   PRIMARY KEY,
            relay_id          VARCHAR(128)  NOT NULL UNIQUE,
            hostname          VARCHAR(255)  NOT NULL DEFAULT '',
            ip                VARCHAR(64)   NOT NULL DEFAULT '',
            version           VARCHAR(32)   NOT NULL DEFAULT '',
            serials           JSONB         NOT NULL DEFAULT '[]',
            status            VARCHAR(16)   NOT NULL DEFAULT 'online',
            connected_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            last_heartbeat_at TIMESTAMPTZ,
            disconnected_at   TIMESTAMPTZ,
            created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agents_status ON relay_agents (status)"
    ))
