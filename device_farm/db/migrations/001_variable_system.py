"""DF-001: Variable System — add variables column to campaigns + scenarios."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS variables JSON DEFAULT '{}'")
    )
    await conn.execute(
        text("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS variables JSON DEFAULT '{}'")
    )
