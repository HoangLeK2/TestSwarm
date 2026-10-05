"""045 — Add org_id scoping to core dashboard tables.

Adds org_id + (org_id, created_at) indexes and backfills from users.org_id for:
- accounts
- account_groups (+ members)
- device_groups (+ members)
- schedules (+ runs)
- content_items, content_collections
- notification_channels, notifications
- relay_agents (+ tokens/jobs/items)

This migration is idempotent.
"""

from __future__ import annotations

from sqlalchemy import text


async def _add_org_id(conn, table: str, *, sort_col: str = "created_at") -> None:
    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(
        text(f"CREATE INDEX IF NOT EXISTS idx_{table}_org_created ON {table}(org_id, {sort_col})")
    )


async def _backfill_from_user(conn, table: str) -> None:
    await conn.execute(text(f"""
        UPDATE {table} t
           SET org_id = u.org_id
          FROM users u
         WHERE t.user_id = u.id
           AND (t.org_id IS NULL OR t.org_id = '')
    """))


async def upgrade(conn) -> None:
    # accounts
    await _add_org_id(conn, "accounts")
    await _backfill_from_user(conn, "accounts")

    # account_groups + account_group_members (members table has group_id, no user_id)
    await _add_org_id(conn, "account_groups")
    await _backfill_from_user(conn, "account_groups")
    await _add_org_id(conn, "account_group_members", sort_col="added_at")
    await conn.execute(text("""
        UPDATE account_group_members m
           SET org_id = g.org_id
          FROM account_groups g
         WHERE m.group_id = g.id
           AND (m.org_id IS NULL OR m.org_id = '')
    """))

    # device_groups + memberships
    await _add_org_id(conn, "device_groups")
    await _backfill_from_user(conn, "device_groups")
    await _add_org_id(conn, "device_group_members", sort_col="added_at")
    await conn.execute(text("""
        UPDATE device_group_members m
           SET org_id = g.org_id
          FROM device_groups g
         WHERE m.group_id = g.id
           AND (m.org_id IS NULL OR m.org_id = '')
    """))

    # schedules + runs
    await _add_org_id(conn, "schedules")
    await _backfill_from_user(conn, "schedules")
    await _add_org_id(conn, "schedule_runs")
    await conn.execute(text("""
        UPDATE schedule_runs r
           SET org_id = s.org_id
          FROM schedules s
         WHERE r.schedule_id = s.id
           AND (r.org_id IS NULL OR r.org_id = '')
    """))

    # content
    await _add_org_id(conn, "content_items")
    await _backfill_from_user(conn, "content_items")
    await _add_org_id(conn, "content_collections")
    await _backfill_from_user(conn, "content_collections")

    # notifications
    await _add_org_id(conn, "notification_channels")
    await _backfill_from_user(conn, "notification_channels")
    await _add_org_id(conn, "notifications")
    await _backfill_from_user(conn, "notifications")

    # relay agents
    await _add_org_id(conn, "relay_agents")
    await _backfill_from_user(conn, "relay_agents")
    await _add_org_id(conn, "relay_agent_tokens")
    await _backfill_from_user(conn, "relay_agent_tokens")
    await _add_org_id(conn, "relay_agent_jobs")
    await _backfill_from_user(conn, "relay_agent_jobs")
    await _add_org_id(conn, "relay_agent_job_items")
    await conn.execute(text("""
        UPDATE relay_agent_job_items i
           SET org_id = j.org_id
          FROM relay_agent_jobs j
         WHERE i.job_id = j.id
           AND (i.org_id IS NULL OR i.org_id = '')
    """))


async def downgrade(conn) -> None:
    # Best-effort: we only drop columns, keep indexes cleanup minimal.
    for table in [
        "accounts",
        "account_groups",
        "account_group_members",
        "device_groups",
        "device_group_members",
        "schedules",
        "schedule_runs",
        "content_items",
        "content_collections",
        "notification_channels",
        "notifications",
        "relay_agents",
        "relay_agent_tokens",
        "relay_agent_jobs",
        "relay_agent_job_items",
    ]:
        await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS org_id"))

