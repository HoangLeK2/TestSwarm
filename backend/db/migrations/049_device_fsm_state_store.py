"""049 — Device FSM: device_states + device_state_transitions + backfill UNKNOWN."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_states (
            device_id          VARCHAR(36) PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
            state              VARCHAR(32) NOT NULL DEFAULT 'unknown',
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_event_id      VARCHAR(128),
            session_id         VARCHAR(128),
            reconnecting_since TIMESTAMPTZ
        )
    """))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_state_transitions (
            id          BIGSERIAL PRIMARY KEY,
            device_id   VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            from_state  VARCHAR(32) NOT NULL,
            to_state    VARCHAR(32) NOT NULL,
            event       VARCHAR(64) NOT NULL,
            source      VARCHAR(32) NOT NULL,
            event_id    VARCHAR(128),
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            payload     JSONB
        )
    """))

    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_device_state_transitions_device_ts
        ON device_state_transitions (device_id, timestamp DESC)
    """))

    await conn.execute(text("""
        INSERT INTO device_states (device_id, state, updated_at)
        SELECT id, 'unknown', COALESCE(last_seen, created_at, NOW())
        FROM devices
        ON CONFLICT (device_id) DO NOTHING
    """))

    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_device_fsm_state'
            ) THEN
                ALTER TABLE device_states ADD CONSTRAINT check_device_fsm_state
                CHECK (state IN (
                    'unknown', 'connecting', 'online', 'busy', 'reconnecting', 'dead'
                ));
            END IF;
        END $$;
    """))
