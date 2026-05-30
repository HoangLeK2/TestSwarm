"""058 — Epic 01 Phase 2: session metadata on refresh_tokens."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS last_ip VARCHAR(64);
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE refresh_tokens ADD COLUMN IF NOT EXISTS user_agent VARCHAR(512);
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE refresh_tokens
            SET last_used_at = COALESCE(last_used_at, created_at)
            WHERE last_used_at IS NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_last_used
            ON refresh_tokens (last_used_at);
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_refresh_tokens_last_used"))
    await conn.execute(text("ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS user_agent"))
    await conn.execute(text("ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS last_ip"))
    await conn.execute(text("ALTER TABLE refresh_tokens DROP COLUMN IF EXISTS last_used_at"))
