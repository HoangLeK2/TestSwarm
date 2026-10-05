"""079 — Epic 06: execution pin + artifact soft-delete timestamp (DF-T-06-011)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS pinned_by VARCHAR(36);
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE execution_artifacts
            ADD COLUMN IF NOT EXISTS object_deleted_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_artifacts_retention_cleanup
            ON execution_artifacts (object_deleted, captured_at, retention_class);
            """
        )
    )
