"""015 — Data integrity: missing FK indexes, serial length normalization, range CHECK constraints."""
from __future__ import annotations


async def upgrade(conn) -> None:
    # ── 1. Missing FK indexes ────────────────────────────────────────────────
    await conn.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_schedules_device_group
            ON schedules(device_group_id);
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_scenario_templates_user
            ON scenario_templates(user_id);
        """
    )
    await conn.exec_driver_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_content_collections_user
            ON content_collections(user_id);
        """
    )
    # content_exports was optional (create_all / legacy); dropped in 031_drop_content_exports
    await conn.exec_driver_sql(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'content_exports'
            ) THEN
                CREATE INDEX IF NOT EXISTS idx_content_exports_user
                    ON content_exports(user_id);
            END IF;
        END $$;
        """
    )

    # ── 2. Normalize device_serial length: VARCHAR(64) → VARCHAR(128) ────────
    await conn.exec_driver_sql(
        """
        ALTER TABLE execution_dlq
            ALTER COLUMN device_serial TYPE VARCHAR(128);
        """
    )

    # ── 3. Range CHECK constraints ───────────────────────────────────────────
    # adb_port must be valid TCP port (1–65535)
    await conn.exec_driver_sql(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_adb_port'
            ) THEN
                ALTER TABLE devices ADD CONSTRAINT check_adb_port
                    CHECK (adb_port >= 1 AND adb_port <= 65535);
            END IF;
        END $$;
        """
    )

    # item_level must be 0 (post), 1 (comment), or 2 (reply)
    await conn.exec_driver_sql(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'check_item_level'
            ) THEN
                ALTER TABLE content_items ADD CONSTRAINT check_item_level
                    CHECK (item_level >= 0 AND item_level <= 2);
            END IF;
        END $$;
        """
    )
