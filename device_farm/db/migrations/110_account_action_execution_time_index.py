"""Index account actions by execution for execution task logs."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_actions_execution_time "
            "ON account_actions (org_id, execution_id, created_at, id)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_account_actions_execution_time"))
