"""Add versioned AI Device Lab KPI measurement records."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS kpi_measurement_definitions (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            version VARCHAR(64) NOT NULL, definitions JSONB NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'draft',
            signed_by VARCHAR(36) NULL REFERENCES users(id) ON DELETE RESTRICT, signed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(org_id,id), UNIQUE(org_id,version))""",
        """CREATE TABLE IF NOT EXISTS kpi_cohorts (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            cohort_key VARCHAR(128) NOT NULL, definition_id VARCHAR(36) NOT NULL, source_kind VARCHAR(16) NOT NULL,
            window_start TIMESTAMPTZ NOT NULL, window_end TIMESTAMPTZ NOT NULL, timezone VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'draft', frozen_at TIMESTAMPTZ NULL,
            created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(org_id,id), UNIQUE(org_id,cohort_key),
            FOREIGN KEY(org_id,definition_id) REFERENCES kpi_measurement_definitions(org_id,id) ON DELETE RESTRICT)""",
        """CREATE TABLE IF NOT EXISTS kpi_cohort_members (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            cohort_id VARCHAR(36) NOT NULL, service_campaign_id VARCHAR(36) NOT NULL,
            eligible BOOLEAN NOT NULL DEFAULT TRUE, exclusion_reason TEXT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(org_id,cohort_id,service_campaign_id),
            FOREIGN KEY(org_id,cohort_id) REFERENCES kpi_cohorts(org_id,id) ON DELETE RESTRICT,
            FOREIGN KEY(org_id,service_campaign_id) REFERENCES service_campaigns(org_id,id) ON DELETE RESTRICT)""",
        """CREATE TABLE IF NOT EXISTS kpi_assistance_events (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            event_id VARCHAR(128) NOT NULL, service_campaign_id VARCHAR(36) NOT NULL,
            actor_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            assistance_type VARCHAR(64) NOT NULL, classification VARCHAR(32) NOT NULL, reason TEXT NOT NULL,
            occurred_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(org_id,event_id),
            FOREIGN KEY(org_id,service_campaign_id) REFERENCES service_campaigns(org_id,id) ON DELETE RESTRICT)""",
        "CREATE INDEX IF NOT EXISTS idx_kpi_assistance_campaign_time ON kpi_assistance_events(service_campaign_id,occurred_at)",
        """CREATE TABLE IF NOT EXISTS kpi_snapshots (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            cohort_id VARCHAR(36) NOT NULL, query_version VARCHAR(64) NOT NULL, source_kind VARCHAR(16) NOT NULL,
            result_status VARCHAR(32) NOT NULL, self_serve_numerator INTEGER NOT NULL,
            self_serve_denominator INTEGER NOT NULL, trace_numerator INTEGER NOT NULL, trace_denominator INTEGER NOT NULL,
            details JSONB NOT NULL, data_freshness_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(org_id,cohort_id,query_version),
            FOREIGN KEY(org_id,cohort_id) REFERENCES kpi_cohorts(org_id,id) ON DELETE RESTRICT)""",
    ]
    for statement in statements:
        await conn.execute(text(statement))
