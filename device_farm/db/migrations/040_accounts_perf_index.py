"""040 — Index for platform LRU account rotation (get_available_account)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_accounts_platform_active_lru
        ON accounts (platform, last_used_at NULLS FIRST)
        WHERE status = 'active'
    """))
