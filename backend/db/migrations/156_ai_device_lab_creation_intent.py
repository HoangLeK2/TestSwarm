"""Add tenant-scoped idempotency for service campaign draft creation."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE service_campaigns ADD COLUMN IF NOT EXISTS creation_intent_key VARCHAR(128) NULL"))
    await conn.execute(text("""CREATE UNIQUE INDEX IF NOT EXISTS uq_service_campaigns_creation_intent
        ON service_campaigns(org_id,creation_intent_key) WHERE creation_intent_key IS NOT NULL"""))
