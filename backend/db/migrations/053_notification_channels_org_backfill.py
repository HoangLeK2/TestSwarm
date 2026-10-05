"""053 — Backfill org_id on notification channels created without tenancy scoping.

After migration 045, new channels were still inserted without org_id in API/service
code paths. Tenant ORM filters then hid them from list endpoints.
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        UPDATE notification_channels t
           SET org_id = u.org_id
          FROM users u
         WHERE t.user_id = u.id
           AND (t.org_id IS NULL OR t.org_id = '')
           AND u.org_id IS NOT NULL
           AND u.org_id <> ''
    """))
    await conn.execute(text("""
        UPDATE notifications t
           SET org_id = u.org_id
          FROM users u
         WHERE t.user_id = u.id
           AND (t.org_id IS NULL OR t.org_id = '')
           AND u.org_id IS NOT NULL
           AND u.org_id <> ''
    """))


async def downgrade(conn) -> None:
    # Data backfill only; no schema change to revert.
    return
