"""073 — Extend activity_log for compliance audit fields (DF-T-04-015)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS before_state JSONB NOT NULL DEFAULT '{}'::jsonb"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS after_state JSONB NOT NULL DEFAULT '{}'::jsonb"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS reason TEXT"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS event_id VARCHAR(36)"))
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_activity_org_entity_created
            ON activity_log (org_id, entity_type, entity_id, created_at DESC)
            WHERE org_id IS NOT NULL AND entity_id IS NOT NULL;
            """
        )
    )
    await conn.execute(text("ALTER TABLE activity_log ALTER COLUMN action TYPE VARCHAR(64)"))
