"""Record how large an account's social graph actually is, over time.

Nothing in the system knew how many friends an account had. That number is not
a nice-to-have statistic: it decides which playbook an account should run (a
friendless account and a settled one need opposite strategies), and it is the
only way to tell whether any of the friend-growing work is working. Sends were
already observable; growth was not.

History rather than a single column on `accounts`: the useful question is "is
this account growing, and how fast", which a point-in-time value cannot answer.
Keeping observations append-only also means a bad read never destroys a good
one.
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    postgres = conn.dialect.name == "postgresql"
    timestamp_type = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    now = "NOW()" if postgres else "CURRENT_TIMESTAMP"

    await conn.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS account_graph_metrics (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL
                    REFERENCES organizations(id) ON DELETE RESTRICT,
                account_id VARCHAR(36) NOT NULL
                    REFERENCES accounts(id) ON DELETE CASCADE,
                platform VARCHAR(50) NOT NULL,
                metric VARCHAR(32) NOT NULL,
                value INTEGER NOT NULL,
                source VARCHAR(32) NOT NULL DEFAULT 'count_label',
                evidence VARCHAR(255),
                device_serial VARCHAR(128),
                execution_id VARCHAR(36),
                observed_at {timestamp_type} NOT NULL DEFAULT {now},
                created_at {timestamp_type} NOT NULL DEFAULT {now}
            )
            """
        )
    )
    # The hot read is "latest value for this account+metric", and the growth
    # query walks the same key backwards in time.
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_account_graph_metrics_latest "
            "ON account_graph_metrics (org_id, account_id, metric, observed_at)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_account_graph_metrics_latest"))
    await conn.execute(text("DROP TABLE IF EXISTS account_graph_metrics"))
