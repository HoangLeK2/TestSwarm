"""
039_relay_agent_jobs — Durable batch onboarding jobs for relay agents.
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS relay_agent_jobs (
            id          VARCHAR(36)  PRIMARY KEY,
            user_id     VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            relay_id    VARCHAR(128) NOT NULL,
            kind        VARCHAR(32)  NOT NULL,
            status      VARCHAR(32)  NOT NULL DEFAULT 'pending',
            total       INTEGER      NOT NULL DEFAULT 0,
            ok          INTEGER      NOT NULL DEFAULT 0,
            failed      INTEGER      NOT NULL DEFAULT 0,
            pending     INTEGER      NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            started_at  TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS relay_agent_job_items (
            id          VARCHAR(36)  PRIMARY KEY,
            job_id      VARCHAR(36)  NOT NULL REFERENCES relay_agent_jobs(id) ON DELETE CASCADE,
            serial      VARCHAR(255) NOT NULL,
            device_id   VARCHAR(36)  REFERENCES devices(id) ON DELETE SET NULL,
            status      VARCHAR(32)  NOT NULL DEFAULT 'pending',
            step        VARCHAR(64)  NOT NULL DEFAULT '',
            attempts    INTEGER      NOT NULL DEFAULT 0,
            error       TEXT         NOT NULL DEFAULT '',
            result      JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            started_at  TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            UNIQUE(job_id, serial)
        )
    """))

    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_jobs_user_created ON relay_agent_jobs (user_id, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_jobs_relay_created ON relay_agent_jobs (relay_id, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_jobs_status ON relay_agent_jobs (status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_job_items_job_status ON relay_agent_job_items (job_id, status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_job_items_job_serial ON relay_agent_job_items (job_id, serial)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_job_items_device_id ON relay_agent_job_items (device_id)"
    ))
