"""028 — account_groups + account_group_members.

Introduces logical account pools so a scenario can draw a different account
per device at dispatch time instead of relying on the 1-primary-per-device
rule in `device_accounts`.

Tables:
  account_groups         — pool metadata (platform, strategy, rotation cursor)
  account_group_members  — (group_id, account_id) pairs, ordered by position,
                           with last_used_at for LRU strategy

Idempotent; safe to re-run.
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_groups (
            id                VARCHAR(36) PRIMARY KEY,
            user_id           VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            name              VARCHAR(255) NOT NULL,
            description       TEXT NOT NULL DEFAULT '',
            platform          VARCHAR(50) NOT NULL,
            rotation_strategy VARCHAR(32) NOT NULL DEFAULT 'round_robin',
            rotation_cursor   INTEGER NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_account_groups_user_name UNIQUE (user_id, name)
        );
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_groups_user "
        "ON account_groups(user_id);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_groups_platform "
        "ON account_groups(platform);"
    )

    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_group_members (
            id           VARCHAR(36) PRIMARY KEY,
            group_id     VARCHAR(36) NOT NULL
                         REFERENCES account_groups(id) ON DELETE CASCADE,
            account_id   VARCHAR(36) NOT NULL
                         REFERENCES accounts(id)       ON DELETE CASCADE,
            position     INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ,
            added_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_agm_group_account UNIQUE (group_id, account_id)
        );
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agm_group_position "
        "ON account_group_members(group_id, position);"
    )
    # Partial index ordered by LRU; NULLS FIRST ensures unseeded members pick first.
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agm_group_lru "
        "ON account_group_members(group_id, last_used_at NULLS FIRST);"
    )
