"""Automatic candidate readiness and bounded content discovery indexes."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def _column_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"] for column in inspect(sync_conn).get_columns(table)
        }
    )


async def upgrade(conn) -> None:
    columns = await _column_names(conn, "facebook_candidate_settings")
    additions = {
        "auto_ready_enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
        "auto_ready_threshold": "DOUBLE PRECISION NOT NULL DEFAULT 0.75",
        "auto_ready_min_evidence": "INTEGER NOT NULL DEFAULT 2",
    }
    for name, definition in additions.items():
        if name not in columns:
            await conn.execute(
                text(
                    f"ALTER TABLE facebook_candidate_settings "
                    f"ADD COLUMN {name} {definition}"
                )
            )

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_ci_discovery_account "
            "ON content_items (org_id, account_id, platform, extracted_at DESC) "
            "WHERE deleted_at IS NULL AND author IS NOT NULL"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_ci_discovery_org "
            "ON content_items (org_id, platform, extracted_at DESC) "
            "WHERE deleted_at IS NULL AND author IS NOT NULL"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_ci_discovery_org"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_ci_discovery_account"))
    columns = await _column_names(conn, "facebook_candidate_settings")
    for name in (
        "auto_ready_min_evidence",
        "auto_ready_threshold",
        "auto_ready_enabled",
    ):
        if name in columns:
            await conn.execute(
                text(
                    f"ALTER TABLE facebook_candidate_settings DROP COLUMN {name}"
                )
            )
