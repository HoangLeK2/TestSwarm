"""081 — Multi-org user model, execution org FKs, tenant-scoped uniques, query indexes.

- users.org_id → default_org_id (workspace default, not request scope)
- organization_members: status, joined_at
- executions.organization_id → org_id + FK + trace columns
- execution_events/steps/results/dlq/artifacts: org_id FK
- analytics/alert/webhook tables: org_id FK where applicable
- tenant-scoped unique constraints (accounts, groups, campaigns, org_scenarios, …)
- composite indexes for common list queries
"""

from __future__ import annotations

from sqlalchemy import text


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


async def _rename_users_org_to_default(conn) -> None:
    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'users' AND column_name = 'org_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'users' AND column_name = 'default_org_id'
            ) THEN
                ALTER TABLE users RENAME COLUMN org_id TO default_org_id;
            END IF;
        END $$;
    """))
    await conn.execute(text("DROP INDEX IF EXISTS idx_users_org_id"))
    await conn.execute(
        text("CREATE INDEX IF NOT EXISTS idx_users_default_org_id ON users(default_org_id)")
    )
    await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_org_id"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_default_org_id'
            ) THEN
                ALTER TABLE users ADD CONSTRAINT fk_users_default_org_id
                    FOREIGN KEY (default_org_id) REFERENCES organizations(id) ON DELETE RESTRICT;
            END IF;
        END $$;
    """))


async def _normalize_system_user_roles(conn) -> None:
   
    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_user_role'
            ) THEN
                ALTER TABLE users DROP CONSTRAINT check_user_role;
            END IF;
        END $$;
    """))
    await conn.execute(text("""
        UPDATE users
           SET role = 'system'
         WHERE role IN ('admin', 'operator')
    """))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_user_role'
            ) THEN
                ALTER TABLE users
                    ADD CONSTRAINT check_user_role
                    CHECK (role IN ('superadmin', 'support', 'system'));
            END IF;
        END $$;
    """))


async def _organization_members_extras(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE organization_members
            ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'
    """))
    await conn.execute(text("""
        ALTER TABLE organization_members
            ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ
    """))
    await conn.execute(text("""
        UPDATE organization_members
           SET joined_at = COALESCE(joined_at, created_at)
         WHERE joined_at IS NULL
    """))
    await conn.execute(text("""
        ALTER TABLE organization_members
            ALTER COLUMN joined_at SET DEFAULT NOW()
    """))


async def _executions_org_and_trace(conn) -> None:
    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'executions' AND column_name = 'organization_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'executions' AND column_name = 'org_id'
            ) THEN
                ALTER TABLE executions RENAME COLUMN organization_id TO org_id;
            END IF;
        END $$;
    """))
    await conn.execute(text("ALTER TABLE executions ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("""
        UPDATE executions e
           SET org_id = COALESCE(
               e.org_id,
               c.org_id,
               (SELECT u.default_org_id FROM users u WHERE u.id = e.user_id LIMIT 1)
           )
          FROM campaigns c
         WHERE e.campaign_id = c.id
           AND (e.org_id IS NULL OR e.org_id = '')
    """))
    await conn.execute(text("""
        UPDATE executions e
           SET org_id = u.default_org_id
          FROM users u
         WHERE e.user_id = u.id
           AND (e.org_id IS NULL OR e.org_id = '')
           AND u.default_org_id IS NOT NULL
    """))
    for col, typ in (
        ("trigger_type", "VARCHAR(32)"),
        ("trigger_id", "VARCHAR(36)"),
        ("priority", "INTEGER NOT NULL DEFAULT 0"),
        ("retry_of_execution_id", "VARCHAR(36)"),
        ("correlation_id", "VARCHAR(64)"),
        ("idempotency_key", "VARCHAR(128)"),
    ):
        await conn.execute(text(f"ALTER TABLE executions ADD COLUMN IF NOT EXISTS {col} {typ}"))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_executions_org_status_created
            ON executions (org_id, status, created_at DESC)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_executions_campaign_created
            ON executions (campaign_id, created_at DESC)
    """))
    await _add_fk_org(conn, "executions")


async def _execution_events_org(conn) -> None:
    await conn.execute(text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'execution_events' AND column_name = 'organization_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'execution_events' AND column_name = 'org_id'
            ) THEN
                ALTER TABLE execution_events RENAME COLUMN organization_id TO org_id;
            END IF;
        END $$;
    """))
    await conn.execute(text("""
        UPDATE execution_events ev
           SET org_id = e.org_id
          FROM executions e
         WHERE ev.execution_id = e.id
           AND (ev.org_id IS NULL OR ev.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_execution_events_execution_time
            ON execution_events (execution_id, occurred_at DESC)
    """))
    await _add_fk_org(conn, "execution_events")


async def _execution_steps_org_device(conn) -> None:
    await conn.execute(text("ALTER TABLE execution_steps ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("ALTER TABLE execution_steps ADD COLUMN IF NOT EXISTS device_id VARCHAR(36)"))
    await conn.execute(text("""
        UPDATE execution_steps s
           SET org_id = e.org_id
          FROM executions e
         WHERE s.execution_id = e.id
           AND (s.org_id IS NULL OR s.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_execution_steps_device_id'
            ) THEN
                ALTER TABLE execution_steps
                    ADD CONSTRAINT fk_execution_steps_device_id
                    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """))
    await _add_fk_org(conn, "execution_steps")


async def _execution_results_org(conn) -> None:
    await conn.execute(text("ALTER TABLE execution_results ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("""
        UPDATE execution_results r
           SET org_id = e.org_id
          FROM executions e
         WHERE r.execution_id = e.id
           AND (r.org_id IS NULL OR r.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await _add_fk_org(conn, "execution_results")


async def _execution_dlq_org(conn) -> None:
    await conn.execute(text("ALTER TABLE execution_dlq ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("""
        UPDATE execution_dlq d
           SET org_id = e.org_id
          FROM executions e
         WHERE d.execution_id = e.id
           AND (d.org_id IS NULL OR d.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await _add_fk_org(conn, "execution_dlq")


async def _execution_artifacts_org(conn) -> None:
    await conn.execute(text("ALTER TABLE execution_artifacts ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("""
        UPDATE execution_artifacts a
           SET org_id = e.org_id
          FROM executions e
         WHERE a.execution_id = e.id
           AND (a.org_id IS NULL OR a.org_id = '')
           AND e.org_id IS NOT NULL
    """))
    await _add_fk_org(conn, "execution_artifacts")


async def _analytics_alert_fks(conn) -> None:
    for table in (
        "metric_rollup_daily",
        "metric_rollup_weekly",
        "notification_rules",
        "notification_preferences",
        "webhook_delivery_log",
        "webhook_dlq",
        "alert_rules",
        "alerts",
        "alert_decisions",
        "analytics_retention_policies",
    ):
        exists = await conn.execute(text("""
            SELECT 1 FROM information_schema.tables
             WHERE table_name = :t
        """), {"t": table})
        if not exists.scalar():
            continue
        col_exists = await conn.execute(text("""
            SELECT 1 FROM information_schema.columns
             WHERE table_name = :t AND column_name = 'org_id'
        """), {"t": table})
        if col_exists.scalar():
            await _add_fk_org(conn, table)


async def _tenant_unique_accounts(conn) -> None:
    await conn.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY org_id, platform, username
                       ORDER BY created_at ASC NULLS LAST, id ASC
                   ) AS rn
              FROM accounts
             WHERE org_id IS NOT NULL AND org_id <> ''
        )
        UPDATE accounts a
           SET username = left(a.username, 240) || '_' || substring(a.id, 1, 6)
          FROM ranked r
         WHERE a.id = r.id AND r.rn > 1
    """))
    await conn.execute(text("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS uq_accounts_platform_username"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_accounts_org_platform_username'
            ) THEN
                ALTER TABLE accounts ADD CONSTRAINT uq_accounts_org_platform_username
                    UNIQUE (org_id, platform, username);
            END IF;
        END $$;
    """))


async def _tenant_unique_device_groups(conn) -> None:
    await conn.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY org_id, name
                       ORDER BY created_at ASC NULLS LAST, id ASC
                   ) AS rn
              FROM device_groups
             WHERE org_id IS NOT NULL AND org_id <> ''
        )
        UPDATE device_groups g
           SET name = left(g.name, 240) || '_' || substring(g.id, 1, 6)
          FROM ranked r
         WHERE g.id = r.id AND r.rn > 1
    """))
    await conn.execute(text("ALTER TABLE device_groups DROP CONSTRAINT IF EXISTS uq_device_groups_name_user"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_device_groups_org_name'
            ) THEN
                ALTER TABLE device_groups ADD CONSTRAINT uq_device_groups_org_name
                    UNIQUE (org_id, name);
            END IF;
        END $$;
    """))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_device_group_members_org_group_device'
            ) THEN
                ALTER TABLE device_group_members ADD CONSTRAINT uq_device_group_members_org_group_device
                    UNIQUE (org_id, group_id, device_id);
            END IF;
        END $$;
    """))


async def _tenant_unique_account_groups(conn) -> None:
    await conn.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY org_id, platform, name
                       ORDER BY created_at ASC NULLS LAST, id ASC
                   ) AS rn
              FROM account_groups
             WHERE org_id IS NOT NULL AND org_id <> ''
        )
        UPDATE account_groups g
           SET name = left(g.name, 240) || '_' || substring(g.id, 1, 6)
          FROM ranked r
         WHERE g.id = r.id AND r.rn > 1
    """))
    await conn.execute(text("ALTER TABLE account_groups DROP CONSTRAINT IF EXISTS uq_account_groups_user_name"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_account_groups_org_platform_name'
            ) THEN
                ALTER TABLE account_groups ADD CONSTRAINT uq_account_groups_org_platform_name
                    UNIQUE (org_id, platform, name);
            END IF;
        END $$;
    """))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_account_group_members_org_group_account'
            ) THEN
                ALTER TABLE account_group_members ADD CONSTRAINT uq_account_group_members_org_group_account
                    UNIQUE (org_id, group_id, account_id);
            END IF;
        END $$;
    """))


async def _tenant_unique_campaigns_org_scenarios(conn) -> None:
    await conn.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS name_lower VARCHAR(255)"))
    await conn.execute(text("""
        UPDATE campaigns SET name_lower = lower(name) WHERE name_lower IS NULL OR name_lower = ''
    """))
    await conn.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY org_id, name_lower
                       ORDER BY created_at ASC NULLS LAST, id ASC
                   ) AS rn
              FROM campaigns
             WHERE deleted_at IS NULL
               AND org_id IS NOT NULL
        )
        UPDATE campaigns c
           SET name = left(c.name, 240) || '_' || substring(c.id, 1, 6),
               name_lower = lower(left(c.name, 240) || '_' || substring(c.id, 1, 6))
          FROM ranked r
         WHERE c.id = r.id AND r.rn > 1
    """))
    await conn.execute(text("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS uq_campaign_org_name"))
    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_campaigns_org_name_lower_active
            ON campaigns (org_id, name_lower)
            WHERE deleted_at IS NULL
    """))
    exists = await conn.execute(text("""
        SELECT 1 FROM information_schema.tables WHERE table_name = 'org_scenarios'
    """))
    if exists.scalar():
        await conn.execute(text("ALTER TABLE org_scenarios ADD COLUMN IF NOT EXISTS name_lower VARCHAR(255)"))
        await conn.execute(text("""
            UPDATE org_scenarios SET name_lower = lower(name)
             WHERE name_lower IS NULL OR name_lower = ''
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_org_scenarios_org_name_lower_active
                ON org_scenarios (org_id, name_lower)
                WHERE deleted_at IS NULL
        """))


async def _tenant_unique_content_collections(conn) -> None:
    await conn.execute(text("ALTER TABLE content_collections DROP CONSTRAINT IF EXISTS uq_content_collections_name_user"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_content_collections_org_name_user'
            ) THEN
                ALTER TABLE content_collections ADD CONSTRAINT uq_content_collections_org_name_user
                    UNIQUE (org_id, name, user_id);
            END IF;
        END $$;
    """))


async def _query_indexes(conn) -> None:
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_devices_org_status
            ON devices (org_id, status)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_devices_org_last_seen
            ON devices (org_id, last_seen)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_accounts_org_platform_status
            ON accounts (org_id, platform, status)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_campaigns_org_status_created
            ON campaigns (org_id, status, created_at DESC)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_notifications_org_user_read_created
            ON notifications (org_id, user_id, is_read, created_at DESC)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_relay_agents_org_status_heartbeat
            ON relay_agents (org_id, status, last_heartbeat_at DESC)
    """))
    exists = await conn.execute(text("""
        SELECT 1 FROM information_schema.tables WHERE table_name = 'schedule_runs'
    """))
    if exists.scalar():
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_schedule_runs_org_schedule_started
                ON schedule_runs (org_id, schedule_id, started_at DESC)
        """))


async def upgrade(conn) -> None:
    await _rename_users_org_to_default(conn)
    await _normalize_system_user_roles(conn)
    await _organization_members_extras(conn)
    await _executions_org_and_trace(conn)
    await _execution_events_org(conn)
    await _execution_steps_org_device(conn)
    await _execution_results_org(conn)
    await _execution_dlq_org(conn)
    await _execution_artifacts_org(conn)
    await _analytics_alert_fks(conn)
    await _tenant_unique_accounts(conn)
    await _tenant_unique_device_groups(conn)
    await _tenant_unique_account_groups(conn)
    await _tenant_unique_campaigns_org_scenarios(conn)
    await _tenant_unique_content_collections(conn)
    await _query_indexes(conn)
