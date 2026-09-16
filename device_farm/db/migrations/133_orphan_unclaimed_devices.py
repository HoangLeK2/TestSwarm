"""133 — drop unclaimed device rows whose managing agent no longer exists.

A phone row stays owned by the workspace whose agent first reported it, even
after that agent is archived. Nobody in that workspace can use the row (it is
unclaimed and its transport is gone), but the serial stays taken: registering
the same phone from another workspace's agent fails with
``serial already registered by another organization``
(``services/device_registration.py``) and the operator has no supported way to
free it.

Scope is deliberately narrow — only rows that are provably dead:
  * never claimed by a user (``user_id IS NULL``, status unpaired),
  * managed by a relay agent that is archived or gone from ``relay_agents``,
  * carrying no operational binding (account, campaign, execution, reservation).

An agent that is merely *offline* does NOT qualify. Offline is a heartbeat
gap — the agent can come back and its workspace still owns those phones.
Deciding a live-but-offline agent's phone belongs to someone else is an
operator call about a physical device, not something a migration can infer.

Forward-only: a deleted unclaimed row cannot be reconstructed, and does not
need to be — re-registering the serial creates a fresh one.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

log = logging.getLogger(__name__)

_BINDING_TABLES = (
    "device_accounts",
    "campaign_devices",
    "execution_devices",
    "device_reserve_sessions",
)


async def _table_exists(conn, table: str) -> bool:
    result = await conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_name = :table
            """
        ),
        {"table": table},
    )
    return result.first() is not None


async def _sqlite_table_exists(conn, table: str) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name = :table"),
        {"table": table},
    )
    return result.first() is not None


async def _has_table(conn, table: str) -> bool:
    try:
        return await _table_exists(conn, table)
    except Exception:  # SQLite has no information_schema
        return await _sqlite_table_exists(conn, table)


async def upgrade(conn) -> None:
    if not await _has_table(conn, "devices") or not await _has_table(conn, "relay_agents"):
        return

    clauses = [
        "user_id IS NULL",
        "(status IS NULL OR status = 'unpaired')",
        "managed_by_relay_id IS NOT NULL",
        """NOT EXISTS (
            SELECT 1 FROM relay_agents ra
            WHERE ra.relay_id = devices.managed_by_relay_id
              AND (ra.status IS NULL OR ra.status <> 'archived')
        )""",
    ]
    for table in _BINDING_TABLES:
        if await _has_table(conn, table):
            clauses.append(
                f"NOT EXISTS (SELECT 1 FROM {table} b WHERE b.device_id = devices.id)"
            )

    where_sql = " AND ".join(clauses)
    rows = (
        await conn.execute(
            text(
                f"SELECT id, serial, org_id, managed_by_relay_id FROM devices WHERE {where_sql}"
            )
        )
    ).fetchall()

    for row in rows:
        await conn.execute(
            text("DELETE FROM devices WHERE id = :device_id"),
            {"device_id": row.id},
        )
        log.info(
            "migration 133: freed serial %s (device %s, workspace %s, archived agent %s)",
            row.serial,
            row.id,
            row.org_id,
            row.managed_by_relay_id,
        )

    if rows:
        log.info("migration 133: removed %s orphan unclaimed device rows", len(rows))


async def downgrade(conn) -> None:
    # One-way: the rows had no user, no key in use and no bindings; the serial
    # is meant to be re-registered from whichever agent physically holds it.
    del conn
