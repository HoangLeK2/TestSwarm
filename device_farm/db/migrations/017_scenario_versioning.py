"""017 — Scenario versioning: snapshot scenario at execution time."""
from __future__ import annotations


async def upgrade(conn) -> None:
    # ── Create scenario_versions table ───────────────────────────────────────
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_versions (
            id VARCHAR(36) PRIMARY KEY,
            scenario_id VARCHAR(36) NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
            version INTEGER NOT NULL DEFAULT 1,
            steps JSONB NOT NULL DEFAULT '[]'::jsonb,
            nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            edges JSONB NOT NULL DEFAULT '[]'::jsonb,
            variables JSONB NOT NULL DEFAULT '{}'::jsonb,
            instructions TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_sv_scenario_version UNIQUE (scenario_id, version)
        );
        """
    )

    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sv_scenario ON scenario_versions(scenario_id);"
    )

    # ── Add scenario_version_id FK to executions ─────────────────────────────
    await conn.execute(
        """
        ALTER TABLE executions
            ADD COLUMN IF NOT EXISTS scenario_version_id VARCHAR(36)
            REFERENCES scenario_versions(id) ON DELETE SET NULL;
        """
    )

    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_executions_sv ON executions(scenario_version_id);"
    )
