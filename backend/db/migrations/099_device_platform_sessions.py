"""099 - Device platform session provenance."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_platform_sessions (
            id                    VARCHAR(36) PRIMARY KEY,
            org_id                VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            device_id             VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            platform              VARCHAR(50) NOT NULL,
            account_id            VARCHAR(36) NULL REFERENCES accounts(id) ON DELETE SET NULL,
            state                 VARCHAR(32) NOT NULL DEFAULT 'unknown',
            state_reason          TEXT NULL,
            established_at        TIMESTAMPTZ NULL,
            last_ready_at         TIMESTAMPTZ NULL,
            last_checked_at       TIMESTAMPTZ NULL,
            invalidated_at        TIMESTAMPTZ NULL,
            login_attempt_id      VARCHAR(36) NULL,
            establishment_method  VARCHAR(40) NULL,
            app_package           VARCHAR(128) NOT NULL DEFAULT 'com.facebook.katana',
            app_version           VARCHAR(64) NULL,
            display_name_observed VARCHAR(255) NULL,
            evidence              JSONB NOT NULL DEFAULT '{}'::jsonb,
            version               INTEGER NOT NULL DEFAULT 1,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_device_platform_sessions_device_platform UNIQUE (org_id, device_id, platform)
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_platform_sessions_org_platform_state "
        "ON device_platform_sessions (org_id, platform, state)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_platform_sessions_org_account_state "
        "ON device_platform_sessions (org_id, account_id, state)"
    ))


async def downgrade(conn) -> None:
    await conn.execute(text("DROP TABLE IF EXISTS device_platform_sessions"))
