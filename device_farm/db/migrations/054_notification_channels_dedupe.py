"""054 — Remove duplicate default in-app notification channels per user/org.

Listing channels previously created a new Browser channel on every request when
tenant scoping hid rows with missing org_id, leaving many duplicates.
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        DELETE FROM notification_channels nc
         WHERE nc.type = 'in_app'
           AND nc.id NOT IN (
               SELECT DISTINCT ON (user_id, org_id) id
                 FROM notification_channels
                WHERE type = 'in_app'
                  AND user_id IS NOT NULL
                  AND org_id IS NOT NULL
                  AND org_id <> ''
                ORDER BY user_id, org_id, created_at DESC
           )
    """))


async def downgrade(conn) -> None:
    return
