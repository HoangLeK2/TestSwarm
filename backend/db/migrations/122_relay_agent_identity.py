"""122 — Agent identity: server-issued relay id, admin-owned display name.

Adds `relay_agents.name` (the admin-editable label; the agent never writes it),
collapses the duplicate rows one physical machine accumulated, and backfills the
name from the activation code that enrolled it.

Limitation: rows with `enrollment_token_id IS NULL` predate mandatory enrollment
tokens. Their hostname was the Docker container ID, which changed on every
`docker compose up`, so nothing in the row maps back to a physical machine and
they cannot be merged. Those rows are only archived once they have been offline
for more than 7 days, so they leave the admin list without taking live state
with them.
"""
from __future__ import annotations

from sqlalchemy import text


_DUPES = """
    WITH ranked AS (
        SELECT
            relay_id,
            FIRST_VALUE(relay_id) OVER (
                PARTITION BY enrollment_token_id
                ORDER BY COALESCE(last_heartbeat_at, connected_at) DESC
            ) AS keep_id
        FROM relay_agents
        WHERE enrollment_token_id IS NOT NULL
          AND status <> 'archived'
    )
"""


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE relay_agents "
            "ADD COLUMN IF NOT EXISTS name VARCHAR(255) NOT NULL DEFAULT ''"
        )
    )

    # Phones follow the surviving row before the losers are archived.
    await conn.execute(
        text(
            _DUPES
            + """
            UPDATE devices d
            SET managed_by_relay_id = r.keep_id
            FROM ranked r
            WHERE r.relay_id <> r.keep_id
              AND d.managed_by_relay_id = r.relay_id
            """
        )
    )
    await conn.execute(
        text(
            _DUPES
            + """
            UPDATE relay_agents a
            SET status = 'archived',
                disconnected_at = COALESCE(a.disconnected_at, NOW())
            FROM ranked r
            WHERE a.relay_id = r.relay_id
              AND r.relay_id <> r.keep_id
            """
        )
    )

    await conn.execute(
        text(
            """
            UPDATE relay_agents a
            SET name = t.name
            FROM relay_agent_tokens t
            WHERE a.enrollment_token_id = t.id
              AND a.name = ''
              AND COALESCE(t.name, '') <> ''
            """
        )
    )

    await conn.execute(
        text(
            """
            UPDATE relay_agents
            SET status = 'archived'
            WHERE enrollment_token_id IS NULL
              AND status <> 'online'
              AND COALESCE(last_heartbeat_at, connected_at) < NOW() - INTERVAL '7 days'
            """
        )
    )
