"""100 - Device platform login attempts."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_platform_login_attempts (
            id                  VARCHAR(36) PRIMARY KEY,
            org_id              VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            device_id           VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            platform            VARCHAR(50) NOT NULL,
            account_id          VARCHAR(36) NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            state               VARCHAR(32) NOT NULL DEFAULT 'pending',
            reason              TEXT NULL,
            reserve_session_id  VARCHAR(36) NULL REFERENCES device_reserve_sessions(id) ON DELETE SET NULL,
            created_by_user_id  VARCHAR(36) NULL,
            started_at          TIMESTAMPTZ NULL,
            completed_at        TIMESTAMPTZ NULL,
            cancelled_at        TIMESTAMPTZ NULL,
            evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
            version             INTEGER NOT NULL DEFAULT 1,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_platform_login_attempts_org_device_state "
        "ON device_platform_login_attempts (org_id, device_id, state)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_platform_login_attempts_org_account_state "
        "ON device_platform_login_attempts (org_id, account_id, state)"
    ))


async def downgrade(conn) -> None:
    await conn.execute(text("DROP TABLE IF EXISTS device_platform_login_attempts"))
