"""074 — Epic 04 execution_steps subtable with artifacts_json (DF-T-04-010 / DF-T-04-014)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS execution_steps (
                id                    VARCHAR(36)  PRIMARY KEY,
                execution_id          VARCHAR(36)  NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                step_index            INTEGER      NOT NULL,
                step_id               VARCHAR(128),
                step_type             VARCHAR(64),
                status                VARCHAR(20)  NOT NULL,
                started_at            TIMESTAMPTZ,
                ended_at              TIMESTAMPTZ,
                duration_ms           DOUBLE PRECISION,
                error_json            JSONB        NOT NULL DEFAULT '{}'::jsonb,
                effective_config_json JSONB        NOT NULL DEFAULT '{}'::jsonb,
                artifacts_json        JSONB        NOT NULL DEFAULT '[]'::jsonb,
                attempts_json         JSONB        NOT NULL DEFAULT '[]'::jsonb,
                marked_ignored        BOOLEAN      NOT NULL DEFAULT FALSE,
                message               TEXT,
                created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                UNIQUE (execution_id, step_index)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_steps_exec_index
            ON execution_steps (execution_id, step_index);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_steps_exec_status
            ON execution_steps (execution_id, status);
            """
        )
    )
