"""Add fenced leases and acknowledgement time to the AI Lab farm outbox."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE farm_job_outbox "
            "ADD COLUMN IF NOT EXISTS lease_token VARCHAR(64) NULL"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE farm_job_outbox "
            "ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ NULL"
        )
    )
    await conn.execute(text("DROP INDEX IF EXISTS idx_farm_job_outbox_delivery"))
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_farm_job_outbox_delivery "
            "ON farm_job_outbox(status, available_at, lease_until)"
        )
    )
