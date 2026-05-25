"""021 — Adjust content export status CHECK to include 'ready'."""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'content_exports'
            ) THEN
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_content_export_status'
            ) THEN
                ALTER TABLE content_exports DROP CONSTRAINT check_content_export_status;
            END IF;

            ALTER TABLE content_exports
                ADD CONSTRAINT check_content_export_status
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'ready'));
        END $$;
        """
    )
