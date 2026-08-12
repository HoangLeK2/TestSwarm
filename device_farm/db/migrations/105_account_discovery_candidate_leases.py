"""Account discovery lifecycle and atomic candidate leases."""

from __future__ import annotations

from sqlalchemy import inspect, text


async def _column_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"] for column in inspect(sync_conn).get_columns(table)
        }
    )


async def upgrade(conn) -> None:
    postgres = conn.dialect.name == "postgresql"
    timestamp_type = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    now = "NOW()" if postgres else "CURRENT_TIMESTAMP"

    await conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS account_discovery_states (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                account_id VARCHAR(36) NOT NULL
                    REFERENCES accounts(id) ON DELETE CASCADE,
                platform VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'uninitialized',
                initialized_at {timestamp_type},
                discovery_requested_at {timestamp_type},
                discovery_started_at {timestamp_type},
                last_discovery_at {timestamp_type},
                next_discovery_at {timestamp_type},
                last_error VARCHAR(1000),
                created_at {timestamp_type} NOT NULL DEFAULT {now},
                updated_at {timestamp_type} NOT NULL DEFAULT {now},
                CONSTRAINT uq_account_discovery_states_identity
                    UNIQUE (org_id, account_id, platform),
                CONSTRAINT ck_account_discovery_states_status CHECK (status IN (
                    'uninitialized', 'discovery_requested', 'discovering',
                    'ready', 'active', 'error'
                ))
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_discovery_states_org_id "
            "ON account_discovery_states (org_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_discovery_states_due "
            "ON account_discovery_states "
            "(org_id, platform, status, next_discovery_at)"
        )
    )

    columns = await _column_names(conn, "facebook_candidates")
    additions = {
        "lease_token": "VARCHAR(64)",
        "leased_by_execution_id": "VARCHAR(64)",
        "leased_at": timestamp_type,
        "lease_expires_at": timestamp_type,
    }
    for name, sql_type in additions.items():
        if name not in columns:
            await conn.execute(
                text(f"ALTER TABLE facebook_candidates ADD COLUMN {name} {sql_type}")
            )

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_entity_status "
            "ON facebook_candidates "
            "(org_id, external_entity_id, status, account_id)"
        )
    )
    if postgres:
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_ready_lease "
                "ON facebook_candidates "
                "(org_id, account_id, final_score DESC, updated_at DESC, id) "
                "WHERE status = 'ready_to_connect'"
            )
        )
    else:
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_ready_lease "
                "ON facebook_candidates "
                "(org_id, account_id, final_score DESC, updated_at DESC, id)"
            )
        )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_facebook_candidates_ready_lease"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_facebook_candidates_entity_status"))
    await conn.execute(text("DROP TABLE IF EXISTS account_discovery_states"))
    columns = await _column_names(conn, "facebook_candidates")
    for name in (
        "lease_expires_at",
        "leased_at",
        "leased_by_execution_id",
        "lease_token",
    ):
        if name in columns:
            await conn.execute(
                text(f"ALTER TABLE facebook_candidates DROP COLUMN {name}")
            )
