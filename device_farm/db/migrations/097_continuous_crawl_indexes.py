"""Indexes supporting bounded continuous-crawl frontier and idempotent execution lookup."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_external_entities_crawl_frontier "
            "ON external_entities (org_id, platform, entity_type, status, id)"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_executions_org_idempotency "
            "ON executions (org_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS uq_executions_org_idempotency"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_external_entities_crawl_frontier"))
