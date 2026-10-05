"""098 - Persist latest active-account verification evidence per device assignment."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE device_accounts
        ADD COLUMN IF NOT EXISTS verification_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
        ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ NULL,
        ADD COLUMN IF NOT EXISTS verification_attempted_at TIMESTAMPTZ NULL,
        ADD COLUMN IF NOT EXISTS verification_evidence JSONB NOT NULL DEFAULT '{}'::jsonb
    """))


async def downgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE device_accounts
        DROP COLUMN IF EXISTS verification_evidence,
        DROP COLUMN IF EXISTS verification_attempted_at,
        DROP COLUMN IF EXISTS verified_at,
        DROP COLUMN IF EXISTS verification_status
    """))
