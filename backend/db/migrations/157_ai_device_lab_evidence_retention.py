"""Index AI Device Lab evidence retention scans without rewriting migration 149."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_evidence_items_retention
            ON evidence_items(status, pinned_by_report, retention_until, org_id)
            """
        )
    )
