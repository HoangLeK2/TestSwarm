"""Remove campaigns.scenario — single source of truth is scenarios table."""

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE campaigns DROP COLUMN IF EXISTS scenario"))
