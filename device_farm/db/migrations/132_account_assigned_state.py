"""132 — account FSM: add `assigned` between `unassigned` and `active`.

Linking a device used to promote an account straight to `active`, so `active`
meant "has a phone", not "is logged in". It now stops at `assigned`; only a
verified platform session (device_platform_sessions.state = 'active') promotes
to `active`. Backfill demotes every `active` account that has no live session
behind it — it never had one, the old rule just said otherwise.
"""
from __future__ import annotations

from sqlalchemy import text

_NEW_STATES = "('unassigned', 'assigned', 'active', 'suspended', 'banned', 'retired')"
_OLD_STATES = "('unassigned', 'active', 'suspended', 'banned', 'retired')"


async def _swap_state_constraint(conn, allowed: str) -> None:
    await conn.execute(
        text("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS check_account_state")
    )
    await conn.execute(
        text(f"ALTER TABLE accounts ADD CONSTRAINT check_account_state CHECK (state IN {allowed})")
    )


async def upgrade(conn) -> None:
    # Constraint first: the backfill below writes a value the old CHECK rejects.
    await _swap_state_constraint(conn, _NEW_STATES)

    await conn.execute(
        text(
            """
            UPDATE accounts
            SET state = 'assigned',
                status = 'assigned',
                state_reason = 'no verified session',
                state_changed_at = NOW()
            WHERE state = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM device_platform_sessions dps
                  WHERE dps.account_id = accounts.id
                    AND dps.state = 'active'
              )
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(
        text(
            """
            UPDATE accounts
            SET state = 'active', status = 'active'
            WHERE state = 'assigned'
            """
        )
    )
    await _swap_state_constraint(conn, _OLD_STATES)
