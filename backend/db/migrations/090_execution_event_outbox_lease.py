"""090 — lease execution-event outbox rows before publishing."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE execution_events
                ADD COLUMN IF NOT EXISTS publish_claim_token VARCHAR(64),
                ADD COLUMN IF NOT EXISTS publish_claimed_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_events_outbox_lease
            ON execution_events (publish_claimed_at, id)
            WHERE published_at IS NULL;
            """
        )
    )
