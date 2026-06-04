"""062 — Epic 04 Phase A: org-scoped scenario library entity (DF-T-04-001)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS org_scenarios (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                name VARCHAR(255) NOT NULL,
                name_lower VARCHAR(255) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                kind VARCHAR(20) NOT NULL DEFAULT 'sequence',
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                scenario_version INTEGER NOT NULL DEFAULT 1,
                body_json JSONB,
                created_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                deleted_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_org_scenarios_org_status
            ON org_scenarios (org_id, status);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_org_scenarios_org_name_active
            ON org_scenarios (org_id, name_lower)
            WHERE deleted_at IS NULL AND status != 'archived';
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS org_scenario_tags (
                id VARCHAR(36) PRIMARY KEY,
                org_scenario_id VARCHAR(36) NOT NULL
                    REFERENCES org_scenarios(id) ON DELETE CASCADE,
                tag VARCHAR(100) NOT NULL,
                CONSTRAINT uq_org_scenario_tags UNIQUE (org_scenario_id, tag)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_org_scenario_tags_scenario
            ON org_scenario_tags (org_scenario_id);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS campaign_org_scenario_refs (
                id VARCHAR(36) PRIMARY KEY,
                campaign_id VARCHAR(36) NOT NULL
                    REFERENCES campaigns(id) ON DELETE CASCADE,
                org_scenario_id VARCHAR(36) NOT NULL
                    REFERENCES org_scenarios(id) ON DELETE CASCADE,
                pinned_version INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_campaign_org_scenario UNIQUE (campaign_id, org_scenario_id)
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_campaign_org_scenario_refs_scenario
            ON campaign_org_scenario_refs (org_scenario_id);
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP TABLE IF EXISTS campaign_org_scenario_refs"))
    await conn.execute(text("DROP TABLE IF EXISTS org_scenario_tags"))
    await conn.execute(text("DROP INDEX IF EXISTS uq_org_scenarios_org_name_active"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_org_scenarios_org_status"))
    await conn.execute(text("DROP TABLE IF EXISTS org_scenarios"))
