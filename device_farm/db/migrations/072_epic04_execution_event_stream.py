"""072 — Epic 04 execution event outbox + archive (DF-T-04-013)."""
from __future__ import annotations

from sqlalchemy import text


async def _normalize_execution_events_org_column(conn) -> str:
    """Ensure execution_events has org_id (create_all may have created org_id already)."""
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                     WHERE table_schema = 'public' AND table_name = 'execution_events'
                ) THEN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                         WHERE table_name = 'execution_events' AND column_name = 'organization_id'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                         WHERE table_name = 'execution_events' AND column_name = 'org_id'
                    ) THEN
                        ALTER TABLE execution_events
                            RENAME COLUMN organization_id TO org_id;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                         WHERE table_name = 'execution_events'
                           AND column_name IN ('org_id', 'organization_id')
                    ) THEN
                        ALTER TABLE execution_events
                            ADD COLUMN org_id VARCHAR(36);
                    END IF;
                END IF;
            END $$;
            """
        )
    )
    result = await conn.execute(
        text(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name = 'execution_events'
               AND column_name IN ('org_id', 'organization_id')
             ORDER BY CASE column_name WHEN 'org_id' THEN 0 ELSE 1 END
             LIMIT 1
            """
        )
    )
    row = result.first()
    return row[0] if row is not None else "org_id"


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS execution_events (
                id               BIGSERIAL PRIMARY KEY,
                event_id         VARCHAR(36)  NOT NULL UNIQUE,
                event_type       VARCHAR(64)  NOT NULL,
                schema_version   VARCHAR(16)  NOT NULL DEFAULT '1',
                org_id           VARCHAR(36)  NOT NULL,
                campaign_id      VARCHAR(36),
                execution_id     VARCHAR(36)  NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                step_id          VARCHAR(128),
                payload          JSONB        NOT NULL DEFAULT '{}'::jsonb,
                occurred_at      TIMESTAMPTZ  NOT NULL,
                published_at     TIMESTAMPTZ,
                publish_attempts INTEGER      NOT NULL DEFAULT 0,
                created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    org_column = await _normalize_execution_events_org_column(conn)
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_events_exec_id
            ON execution_events (execution_id, id);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_events_outbox
            ON execution_events (occurred_at)
            WHERE published_at IS NULL;
            """
        )
    )
    await conn.execute(
        text(
            f"""
            CREATE INDEX IF NOT EXISTS idx_execution_events_org_type
            ON execution_events ({org_column}, event_type, occurred_at DESC);
            """
        )
    )
