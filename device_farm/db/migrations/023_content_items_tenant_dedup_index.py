"""023 — Tenant-aware dedup index for content_items."""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        -- Drop legacy cross-tenant dedup index if present.
        DROP INDEX IF EXISTS idx_ci_hash_collection;
        """
    )

    await conn.execute(
        """
        -- Build tenant-aware unique index.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ci_hash_collection_user
            ON content_items(content_hash, collection, user_id);
        """
    )

    await conn.execute(
        """
        -- Keep null-tenant rows deduplicated too.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ci_hash_collection_null_user
            ON content_items(content_hash, collection)
            WHERE user_id IS NULL;
        """
    )
