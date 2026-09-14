"""Let a ban investigation reach an account's runs.

executions.account_id has existed since the account model landed, but nothing
indexed it — the ten indexes on the table cover run_type, status, campaign,
scenario, user and org, and none of them lead with the account. So "which runs
did this account perform, and in what order" was a sequential scan over every
execution the deployment has ever recorded.

That is the first hop of the only question that matters after an account is
banned: account -> executions -> execution_steps -> the step that did it. The
other two hops are already indexed (idx_execution_steps_exec_index).

Leading with org_id keeps the tenancy predicate in the index; created_at carries
the ordering the execution list sorts on.
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    # Ascending is fine for a DESC listing — Postgres scans an index backwards.
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_executions_org_account_created "
            "ON executions (org_id, account_id, created_at)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_executions_org_account_created"))
