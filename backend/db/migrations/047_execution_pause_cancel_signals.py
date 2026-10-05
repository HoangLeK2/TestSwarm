"""047 — Execution pause/cancel signal timestamps and cancel metadata."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE executions
        ADD COLUMN IF NOT EXISTS pause_signal_received_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS cancel_signal_received_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS cancel_reason TEXT
    """))

    # Allow paused status (idempotent for re-runs).
    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_execution_status'
            ) THEN
                ALTER TABLE executions DROP CONSTRAINT check_execution_status;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_execution_status'
            ) THEN
                ALTER TABLE executions ADD CONSTRAINT check_execution_status
                CHECK (status IN (
                    'pending', 'running', 'paused',
                    'completed', 'failed', 'cancelled'
                ));
            END IF;
        END $$;
    """))
