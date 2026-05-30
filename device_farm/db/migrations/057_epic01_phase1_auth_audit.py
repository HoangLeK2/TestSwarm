"""057 — Epic 01 Phase 1: refresh tokens, password history, lockout columns."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_failed_login_at TIMESTAMPTZ;
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash VARCHAR(128) NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ,
                device_fingerprint VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_revoked
            ON refresh_tokens (user_id, revoked_at);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash
            ON refresh_tokens (token_hash);
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS password_history (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_password_history_user_created
            ON password_history (user_id, created_at DESC);
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_password_history_user_created"))
    await conn.execute(text("DROP TABLE IF EXISTS password_history"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_refresh_tokens_hash"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_refresh_tokens_user_revoked"))
    await conn.execute(text("DROP TABLE IF EXISTS refresh_tokens"))
    await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS last_failed_login_at"))
    await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS locked_until"))
    await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS failed_login_count"))
