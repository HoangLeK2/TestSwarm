"""025 — Repair missing executions.scenario_version_id in drifted databases.

Some environments may have partial/failed startup migrations where the app keeps
running (DB init warning) and later crashes at runtime with:
UndefinedColumnError: executions.scenario_version_id does not exist.

This migration is intentionally idempotent and defensive:
1) Ensure `scenario_versions` table exists (minimal shape if missing)
2) Ensure `executions.scenario_version_id` exists
3) Ensure FK + index exist
"""
from __future__ import annotations


async def upgrade(conn) -> None:
    # 1) Ensure scenario_versions exists (minimal, safe shape for FK target)
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_versions (
            id VARCHAR(36) PRIMARY KEY,
            scenario_id VARCHAR(36) NULL,
            version INTEGER NOT NULL DEFAULT 1,
            steps JSONB NOT NULL DEFAULT '[]'::jsonb,
            nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            edges JSONB NOT NULL DEFAULT '[]'::jsonb,
            variables JSONB NOT NULL DEFAULT '{}'::jsonb,
            instructions TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )

    # 2) Ensure column exists on executions
    await conn.execute(
        """
        ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS scenario_version_id VARCHAR(36);
        """
    )

    # 3a) Ensure index exists
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_executions_sv
        ON executions(scenario_version_id);
        """
    )

    # 3b) Ensure FK exists (name may vary in drifted DBs)
    await conn.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'executions'::regclass
                  AND contype = 'f'
                  AND conname = 'executions_scenario_version_id_fkey'
            ) THEN
                ALTER TABLE executions
                    ADD CONSTRAINT executions_scenario_version_id_fkey
                    FOREIGN KEY (scenario_version_id)
                    REFERENCES scenario_versions(id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
