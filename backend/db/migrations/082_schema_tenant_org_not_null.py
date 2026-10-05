"""082 — Enforce org_id NOT NULL on execution + analytics; FK schedule_runs.execution_id.

Follows 081: backfill remaining NULL org_id rows, then ALTER NOT NULL.
"""

from __future__ import annotations

from sqlalchemy import text


async def _backfill_execution_org_ids(conn) -> None:
    await conn.execute(text("""
        UPDATE executions e
           SET org_id = c.org_id
          FROM campaigns c
         WHERE e.campaign_id = c.id
           AND (e.org_id IS NULL OR e.org_id = '')
           AND c.org_id IS NOT NULL
    """))
    await conn.execute(text("""
        UPDATE executions e
           SET org_id = u.default_org_id
          FROM users u
         WHERE e.user_id = u.id
           AND (e.org_id IS NULL OR e.org_id = '')
           AND u.default_org_id IS NOT NULL
    """))
    await conn.execute(text("""
        UPDATE execution_results r
           SET org_id = e.org_id
          FROM executions e
         WHERE r.execution_id = e.id
           AND (r.org_id IS NULL OR r.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await conn.execute(text("""
        UPDATE execution_steps s
           SET org_id = e.org_id
          FROM executions e
         WHERE s.execution_id = e.id
           AND (s.org_id IS NULL OR s.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await conn.execute(text("""
        UPDATE execution_artifacts a
           SET org_id = e.org_id
          FROM executions e
         WHERE a.execution_id = e.id
           AND (a.org_id IS NULL OR a.org_id = '')
           AND e.org_id IS NOT NULL
    """))


async def _execution_artifacts_device_id(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE execution_artifacts
            ADD COLUMN IF NOT EXISTS device_id VARCHAR(36)
    """))
    await conn.execute(text("""
        UPDATE execution_artifacts a
           SET device_id = ed.device_id
          FROM execution_devices ed
         WHERE a.execution_id = ed.execution_id
           AND a.device_id IS NULL
           AND ed.device_id IS NOT NULL
    """))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_execution_artifacts_device_id'
            ) THEN
                ALTER TABLE execution_artifacts
                    ADD CONSTRAINT fk_execution_artifacts_device_id
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """))


async def _enforce_not_null_org(conn, table: str) -> None:
    missing = await conn.execute(
        text(f"SELECT count(1) FROM {table} WHERE org_id IS NULL OR org_id = ''")
    )
    if int(missing.scalar() or 0) > 0:
        raise RuntimeError(f"082: {table}.org_id backfill incomplete (NULL rows remain)")
    await conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN org_id SET NOT NULL"))


async def _analytics_org_backfill(conn) -> None:
    await conn.execute(text("""
        DELETE FROM notification_rules
         WHERE org_id IS NULL OR org_id = ''
    """))
    await conn.execute(text("""
        UPDATE webhook_delivery_log w
           SET org_id = c.org_id
          FROM notification_channels c
         WHERE w.channel_id = c.id
           AND (w.org_id IS NULL OR w.org_id = '')
           AND c.org_id IS NOT NULL
    """))
    await conn.execute(text("""
        UPDATE webhook_dlq w
           SET org_id = c.org_id
          FROM notification_channels c
         WHERE w.channel_id = c.id
           AND (w.org_id IS NULL OR w.org_id = '')
           AND c.org_id IS NOT NULL
    """))


async def _add_fk_org(conn, table: str, *, column: str = "org_id") -> None:
    constraint = f"fk_{table}_{column}_organizations"
    await conn.execute(text(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{constraint}'
            ) THEN
                ALTER TABLE {table}
                    ADD CONSTRAINT {constraint}
                    FOREIGN KEY ({column}) REFERENCES organizations(id) ON DELETE RESTRICT;
            END IF;
        END $$;
    """))


async def _schedule_runs_execution_fk(conn) -> None:
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_schedule_runs_execution_id'
            ) THEN
                ALTER TABLE schedule_runs
                    ADD CONSTRAINT fk_schedule_runs_execution_id
                    FOREIGN KEY (execution_id) REFERENCES executions(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """))


async def _reconnect_policies_fk(conn) -> None:
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_reconnect_policies_org_id'
            ) THEN
                ALTER TABLE reconnect_policies
                    ADD CONSTRAINT fk_reconnect_policies_org_id
                    FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE RESTRICT;
            END IF;
        END $$;
    """))


async def upgrade(conn) -> None:
    await _backfill_execution_org_ids(conn)
    await _execution_artifacts_device_id(conn)

    for table in ("executions", "execution_results", "execution_steps", "execution_artifacts"):
        exists = await conn.execute(text("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = :t AND column_name = 'org_id'
        """), {"t": table})
        if exists.scalar():
            await _enforce_not_null_org(conn, table)

    for table in (
        "metric_rollup_daily",
        "metric_rollup_weekly",
        "alert_rules",
        "alerts",
        "alert_decisions",
        "analytics_retention_policies",
    ):
        exists = await conn.execute(text("""
            SELECT 1 FROM information_schema.tables WHERE table_name = :t
        """), {"t": table})
        if exists.scalar():
            await _add_fk_org(conn, table)

    await _analytics_org_backfill(conn)

    nr_exists = await conn.execute(text("""
        SELECT 1 FROM information_schema.tables WHERE table_name = 'notification_rules'
    """))
    if nr_exists.scalar():
        await _add_fk_org(conn, "notification_rules")
        missing = await conn.execute(text(
            "SELECT count(1) FROM notification_rules WHERE org_id IS NULL OR org_id = ''"
        ))
        if int(missing.scalar() or 0) == 0:
            await conn.execute(text(
                "ALTER TABLE notification_rules ALTER COLUMN org_id SET NOT NULL"
            ))

    for table in ("webhook_delivery_log", "webhook_dlq"):
        exists = await conn.execute(text("""
            SELECT 1 FROM information_schema.tables WHERE table_name = :t
        """), {"t": table})
        if exists.scalar():
            await _add_fk_org(conn, table)

    np_exists = await conn.execute(text("""
        SELECT 1 FROM information_schema.tables WHERE table_name = 'notification_preferences'
    """))
    if np_exists.scalar():
        await _add_fk_org(conn, "notification_preferences")

    await _schedule_runs_execution_fk(conn)
    await _reconnect_policies_fk(conn)
