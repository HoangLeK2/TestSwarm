"""064 — Epic 04: __system org for read-only scenario templates (DF-T-04-005)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO organizations (id, business_name, business_email, slug, status, plan, created_at, updated_at)
            VALUES (
                '__system',
                'Device Farm Templates',
                'templates@device-farm.local',
                '__system',
                'active',
                'standard',
                NOW(),
                NOW()
            )
            ON CONFLICT (id) DO NOTHING;
            """
        )
    )
