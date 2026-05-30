"""048 — Persist last scenario validation summary on scenarios."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE scenarios
        ADD COLUMN IF NOT EXISTS last_validation_summary JSONB,
        ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ
    """))
