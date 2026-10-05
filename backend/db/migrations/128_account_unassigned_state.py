"""128 — account FSM: add `unassigned`, retire the `cooldown` state.

`unassigned` means "no DeviceAccount row" and is the state new accounts start
in. `cooldown` stops being a lifecycle state and becomes what the pickers
already treated it as: an eligibility gate on `accounts.cooldown_until`. The
column stays; existing cooldown rows flip to `active` and keep their timer, so
no account loses its rest window.
"""
from __future__ import annotations

from sqlalchemy import text

_NEW_STATES = "('unassigned', 'active', 'suspended', 'banned', 'retired')"
_OLD_STATES = "('active', 'cooldown', 'suspended', 'banned', 'retired')"


async def _swap_state_constraint(conn, allowed: str) -> None:
    await conn.execute(
        text("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS check_account_state")
    )
    await conn.execute(
        text(f"ALTER TABLE accounts ADD CONSTRAINT check_account_state CHECK (state IN {allowed})")
    )


async def upgrade(conn) -> None:
    # Constraint first: the backfill below writes values the old CHECK rejects.
    await _swap_state_constraint(conn, _NEW_STATES)
    await conn.execute(
        text("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS check_account_status")
    )

    # Resting accounts stay resting — only the state label changes.
    await conn.execute(
        text(
            """
            UPDATE accounts
            SET state = 'active',
                status = 'active'
            WHERE state = 'cooldown' OR status = 'cooldown'
            """
        )
    )

    # Accounts with no device link are 'unassigned'. Terminal and operator-set
    # states (banned/retired/suspended) are left alone — an unlinked banned
    # account is still banned.
    await conn.execute(
        text(
            """
            UPDATE accounts
            SET state = 'unassigned',
                status = 'unassigned',
                state_reason = 'no device linked',
                state_changed_at = NOW()
            WHERE state = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM device_accounts da WHERE da.account_id = accounts.id
              )
            """
        )
    )

    await conn.execute(text("ALTER TABLE accounts ALTER COLUMN state SET DEFAULT 'unassigned'"))
    await conn.execute(text("ALTER TABLE accounts ALTER COLUMN status SET DEFAULT 'unassigned'"))
    # Partial index was predicated on state = 'cooldown', which no longer exists.
    await conn.execute(text("DROP INDEX IF EXISTS idx_accounts_state_cooldown_until"))


async def downgrade(conn) -> None:
    await conn.execute(
        text(
            """
            UPDATE accounts
            SET state = 'active', status = 'active'
            WHERE state = 'unassigned'
            """
        )
    )
    await _swap_state_constraint(conn, _OLD_STATES)
    await conn.execute(text("ALTER TABLE accounts ALTER COLUMN state SET DEFAULT 'active'"))
    await conn.execute(text("ALTER TABLE accounts ALTER COLUMN status SET DEFAULT 'active'"))
