"""071 — Epic 04 DLQ lifecycle columns + status constraints (DF-T-04-012)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE execution_dlq
            ADD COLUMN IF NOT EXISTS failed_step_id TEXT,
            ADD COLUMN IF NOT EXISTS failure_reason TEXT,
            ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS closed_by TEXT,
            ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS close_reason TEXT,
            ADD COLUMN IF NOT EXISTS replayed_to_execution_id TEXT,
            ADD COLUMN IF NOT EXISTS artifact_refs JSONB DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS campaign_id TEXT;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_dlq_campaign_status_created
            ON execution_dlq (campaign_id, status, created_at DESC);
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'check_dlq_status'
                ) THEN
                    ALTER TABLE execution_dlq DROP CONSTRAINT check_dlq_status;
                END IF;
                ALTER TABLE execution_dlq ADD CONSTRAINT check_dlq_status
                CHECK (status IN (
                    'pending', 'retrying', 'resolved', 'dismissed',
                    'closed', 'replayed'
                ));
            END $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'check_execution_status'
                ) THEN
                    ALTER TABLE executions DROP CONSTRAINT check_execution_status;
                END IF;
                ALTER TABLE executions ADD CONSTRAINT check_execution_status
                CHECK (status IN (
                    'pending', 'running', 'paused',
                    'completed', 'failed', 'cancelled',
                    'dlq_open', 'dlq_closed'
                ));
            END $$;
            """
        )
    )
