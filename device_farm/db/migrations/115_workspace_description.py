"""115 — Workspace description metadata."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT ''")
    )
