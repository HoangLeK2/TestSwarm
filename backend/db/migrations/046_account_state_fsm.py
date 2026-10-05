"""046 — Account FSM: state, state_reason, state_changed_at + index for cooldown cron."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE accounts
        ADD COLUMN IF NOT EXISTS state VARCHAR(20),
        ADD COLUMN IF NOT EXISTS state_reason TEXT,
        ADD COLUMN IF NOT EXISTS state_changed_at TIMESTAMPTZ
    """))

    await conn.execute(text("""
        UPDATE accounts
        SET state = CASE
            WHEN status = 'disabled' THEN 'suspended'
            ELSE COALESCE(status, 'active')
        END
        WHERE state IS NULL
    """))

    await conn.execute(text("""
        UPDATE accounts
        SET status = state
        WHERE status = 'disabled' OR status IS DISTINCT FROM state
    """))

    await conn.execute(text("""
        UPDATE accounts
        SET state_changed_at = COALESCE(updated_at, created_at, NOW())
        WHERE state_changed_at IS NULL
    """))

    await conn.execute(text("""
        ALTER TABLE accounts
        ALTER COLUMN state SET DEFAULT 'active'
    """))

    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_accounts_state_cooldown_until
        ON accounts (state, cooldown_until)
        WHERE state = 'cooldown' AND cooldown_until IS NOT NULL
    """))

    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_account_status'
            ) THEN
                ALTER TABLE accounts DROP CONSTRAINT check_account_status;
            END IF;
        END $$;
    """))

    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_account_status'
            ) THEN
                ALTER TABLE accounts ADD CONSTRAINT check_account_status
                CHECK (status IN ('active', 'cooldown', 'suspended', 'banned', 'retired'));
            END IF;
        END $$;
    """))

    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_account_state'
            ) THEN
                ALTER TABLE accounts ADD CONSTRAINT check_account_state
                CHECK (state IN ('active', 'cooldown', 'suspended', 'banned', 'retired'));
            END IF;
        END $$;
    """))

    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_accounts_platform_active_lru
        ON accounts (platform, last_used_at NULLS FIRST)
        WHERE state = 'active'
    """))
