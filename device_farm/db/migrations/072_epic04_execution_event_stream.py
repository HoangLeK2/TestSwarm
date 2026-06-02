"""072 — Epic 04 execution event outbox + archive (DF-T-04-013)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS execution_events (
                id               BIGSERIAL PRIMARY KEY,
                event_id         VARCHAR(36)  NOT NULL UNIQUE,
                event_type       VARCHAR(64)  NOT NULL,
                schema_version   VARCHAR(16)  NOT NULL DEFAULT '1',
                organization_id  VARCHAR(36)  NOT NULL,
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
            """
            CREATE INDEX IF NOT EXISTS idx_execution_events_org_type
            ON execution_events (organization_id, event_type, occurred_at DESC);
            """
        )
    )
