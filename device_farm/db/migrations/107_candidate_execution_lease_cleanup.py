"""Index candidate leases for constant-time terminal execution cleanup."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_execution_lease "
            "ON facebook_candidates (org_id, leased_by_execution_id) "
            "WHERE lease_token IS NOT NULL"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(
        text("DROP INDEX IF EXISTS idx_facebook_candidates_execution_lease")
    )
