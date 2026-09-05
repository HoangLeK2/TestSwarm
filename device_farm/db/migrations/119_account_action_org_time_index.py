"""Let the activity feed reach account actions through an index.

The feed unions activity_logs, account_events and account_actions and sorts on
updated_at. Its account_actions branch used to scope tenancy by joining
`accounts`, so org_id never appeared in the WHERE clause and no index could
serve the default (no device filter) view — it fell back to a sequential scan
that grew with the whole ledger.

api/routes/analytics.py now filters on account_actions.org_id directly. This is
the index that makes that predicate worth having; it also serves the
per-account and per-execution reads, which already lead with org_id.

idx_account_actions_device_time stays: it still serves "what did this phone do".
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    # Ascending is fine for the DESC feed — Postgres scans an index backwards.
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_actions_org_time "
            "ON account_actions (org_id, updated_at, id)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_account_actions_org_time"))
