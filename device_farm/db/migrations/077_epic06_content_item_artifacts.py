"""077 — Epic 06: content item extensions + execution_artifacts (DF-T-06-002)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    for col, ddl in (
        ("external_id", "VARCHAR(255)"),
        ("scenario_id", "VARCHAR(36)"),
        ("device_id", "VARCHAR(36)"),
        ("account_id", "VARCHAR(36)"),
        ("deleted_at", "TIMESTAMPTZ"),
        ("updated_at", "TIMESTAMPTZ DEFAULT NOW()"),
    ):
        await conn.execute(
            text(
                f"""
                ALTER TABLE content_items
                ADD COLUMN IF NOT EXISTS {col} {ddl};
                """
            )
        )

    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_ci_collection_type_extracted
            ON content_items (collection, content_type, extracted_at DESC);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_ci_campaign_extracted
            ON content_items (campaign_id, extracted_at DESC);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_ci_org_platform_external
            ON content_items (org_id, collection, platform, external_id)
            WHERE external_id IS NOT NULL AND deleted_at IS NULL;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_ci_org_collection_platform_external
            ON content_items (org_id, collection, platform, external_id)
            WHERE external_id IS NOT NULL AND deleted_at IS NULL;
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS execution_artifacts (
                id VARCHAR(36) PRIMARY KEY,
                execution_id VARCHAR(36) NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                step_index INTEGER NOT NULL DEFAULT 0,
                kind VARCHAR(32) NOT NULL,
                object_key VARCHAR(512) NOT NULL,
                content_type_mime VARCHAR(128) NOT NULL DEFAULT 'image/jpeg',
                size_bytes BIGINT NOT NULL DEFAULT 0,
                sha256 VARCHAR(64) NOT NULL DEFAULT '',
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                retention_class VARCHAR(32) NOT NULL DEFAULT 'standard',
                object_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_execution_artifacts_exec_step
            ON execution_artifacts (execution_id, step_index);
            """
        )
    )
