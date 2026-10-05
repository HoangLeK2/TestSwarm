"""029 — scenarios.account_group_id FK.

Adds an optional link from a scenario to an ``account_groups`` row so the
dispatcher can draw a different account from the group for each device in a
fleet. When the group is deleted, the FK is set to NULL; the scenario falls
back to the primary-account path.

Idempotent; safe to re-run.
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    await conn.execute(
        """
        ALTER TABLE scenarios
            ADD COLUMN IF NOT EXISTS account_group_id VARCHAR(36)
                REFERENCES account_groups(id) ON DELETE SET NULL;
        """
    )
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scenarios_account_group
            ON scenarios(account_group_id);
        """
    )
