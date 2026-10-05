"""
031_drop_content_exports — Remove deprecated async export job table.

The API now uses direct streaming export only (`/api/content/export/stream`),
so the persisted export job table is no longer used.
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        DROP TABLE IF EXISTS content_exports;
    """))
