"""DF-007: Account & Profile Manager — accounts + device_accounts tables."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id VARCHAR(36) PRIMARY KEY,
                platform VARCHAR(50) NOT NULL,
                username VARCHAR(255) NOT NULL,
                password_encrypted VARCHAR(500),
                display_name VARCHAR(255) DEFAULT '',
                status VARCHAR(20) DEFAULT 'active',
                cooldown_until TIMESTAMPTZ,
                proxy_id VARCHAR(36),
                metadata JSON DEFAULT '{}',
                notes TEXT DEFAULT '',
                tags VARCHAR(500) DEFAULT '',
                user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_used_at TIMESTAMPTZ,
                total_usage_minutes FLOAT DEFAULT 0,
                usage_today_minutes FLOAT DEFAULT 0,
                usage_reset_date DATE,
                CONSTRAINT uq_accounts_platform_username UNIQUE (platform, username)
            )
            """
        )
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id)")
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS device_accounts (
                id VARCHAR(36) PRIMARY KEY,
                device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                account_id VARCHAR(36) NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                is_primary BOOLEAN DEFAULT FALSE,
                assigned_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_da_device_account UNIQUE (device_id, account_id)
            )
            """
        )
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_da_device ON device_accounts(device_id)")
    )
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_da_account ON device_accounts(account_id)")
    )
