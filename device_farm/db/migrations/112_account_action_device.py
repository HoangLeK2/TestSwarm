"""Record which device performed each account action.

Without this the ledger can say "this account liked something" but not which
phone did it, so the activity feed's device filter had to discard account
actions outright (api/routes/analytics.py returned false() for that branch).

Both columns are kept: device_id for the relation, device_serial so the row
still reads correctly after a device is deleted and the FK goes NULL.
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("ALTER TABLE account_actions ADD COLUMN IF NOT EXISTS device_id VARCHAR(36)")
    )
    await conn.execute(
        text("ALTER TABLE account_actions ADD COLUMN IF NOT EXISTS device_serial VARCHAR(128)")
    )
    # Nullable + SET NULL: deleting a phone must not delete its audit history.
    await conn.execute(
        text(
            "DO $$ BEGIN "
            "ALTER TABLE account_actions ADD CONSTRAINT fk_account_actions_device "
            "FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE SET NULL; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
        )
    )
    # device_serial leads, not org_id: the activity feed scopes tenancy through
    # a join on `accounts`, so account_actions.org_id is never in the WHERE
    # clause and an org-leading index would sit unused. updated_at is the column
    # the feed union actually sorts on.
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_actions_device_time "
            "ON account_actions (device_serial, updated_at, id)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_account_actions_device_time"))
    await conn.execute(
        text("ALTER TABLE account_actions DROP CONSTRAINT IF EXISTS fk_account_actions_device")
    )
    await conn.execute(text("ALTER TABLE account_actions DROP COLUMN IF EXISTS device_serial"))
    await conn.execute(text("ALTER TABLE account_actions DROP COLUMN IF EXISTS device_id"))
