"""086 - Add campaign recovery policy for incident scenarios."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE campaigns
        ADD COLUMN IF NOT EXISTS recovery_policy JSONB NOT NULL DEFAULT '{}'::jsonb
    """))

