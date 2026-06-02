"""063 — Epic 04: org scenario validation summary (DF-T-04-004)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE org_scenarios
            ADD COLUMN IF NOT EXISTS last_validation_summary JSONB,
            ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ
            """
        )
    )
