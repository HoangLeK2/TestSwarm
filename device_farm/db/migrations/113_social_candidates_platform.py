"""Make the connection-candidate pipeline platform-neutral.

The candidate tables were built for Facebook and carry its name, but every
concept in them — discover a profile, score it, lease it, send a connection
request — is identical on TikTok/Instagram/Threads. Rather than duplicate the
schema per platform, the platform becomes a column.

`platform` is denormalised from `accounts.platform` so the ready-candidate lease
query can filter without joining, and so a single account row can never be
ambiguous about which network a candidate belongs to.

`requested_at` records when the connection request actually left the device.
`updated_at` cannot serve this purpose because every later write overwrites it,
which makes "how long has this request been pending?" unanswerable — the exact
question the acceptance-rate feedback loop needs.

The table keeps its `facebook_candidates` name for now; renaming it is a
separate, larger migration.
"""

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

    columns = await _column_names(conn, "facebook_candidates")

    if "platform" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE facebook_candidates "
                "ADD COLUMN platform VARCHAR(50) NOT NULL DEFAULT 'facebook'"
            )
        )
        # Existing rows predate multi-platform support and are all Facebook.
        await conn.execute(
            text(
                "UPDATE facebook_candidates SET platform = 'facebook' "
                "WHERE platform IS NULL OR platform = ''"
            )
        )

    if "requested_at" not in columns:
        await conn.execute(
            text(
                "ALTER TABLE facebook_candidates "
                f"ADD COLUMN requested_at {timestamp_type}"
            )
        )
        # Backfill what is knowable: rows already awaiting a reply have been
        # pending since their last write. Rows in other states stay NULL.
        await conn.execute(
            text(
                "UPDATE facebook_candidates SET requested_at = updated_at "
                "WHERE requested_at IS NULL AND status = 'request_pending'"
            )
        )

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_facebook_candidates_platform_account "
            "ON facebook_candidates (org_id, platform, account_id, status)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(
        text("DROP INDEX IF EXISTS idx_facebook_candidates_platform_account")
    )
    await conn.execute(
        text("ALTER TABLE facebook_candidates DROP COLUMN IF EXISTS requested_at")
    )
    await conn.execute(
        text("ALTER TABLE facebook_candidates DROP COLUMN IF EXISTS platform")
    )
