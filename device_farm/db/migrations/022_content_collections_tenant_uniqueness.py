"""022 — Make content_collections unique per (name, user_id)."""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        DO $$
        BEGIN
            -- Drop legacy global unique constraint/index on name, if present.
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'content_collections_name_key'
            ) THEN
                ALTER TABLE content_collections DROP CONSTRAINT content_collections_name_key;
            END IF;

            -- New tenant-scoped uniqueness.
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_content_collections_name_user'
            ) THEN
                ALTER TABLE content_collections
                    ADD CONSTRAINT uq_content_collections_name_user UNIQUE (name, user_id);
            END IF;

            -- Keep null-tenant rows unique too (Postgres UNIQUE treats NULLs as distinct).
            CREATE UNIQUE INDEX IF NOT EXISTS idx_content_collections_name_null_user
                ON content_collections(name)
                WHERE user_id IS NULL;
        END $$;
        """
    )
