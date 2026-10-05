from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE scenario_templates
        ADD COLUMN IF NOT EXISTS display_name VARCHAR(255) DEFAULT ''
    """))
