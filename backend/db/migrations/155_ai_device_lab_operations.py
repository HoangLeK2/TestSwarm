"""Add operational target and dependency readiness records."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""CREATE TABLE IF NOT EXISTS operational_targets (
        id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
        version VARCHAR(64) NOT NULL, capacity JSONB NOT NULL, slo JSONB NOT NULL,
        recovery JSONB NOT NULL, alerting JSONB NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'signed',
        signed_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT, signed_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(org_id,id), UNIQUE(org_id,version))"""))
    await conn.execute(text("""CREATE TABLE IF NOT EXISTS operational_readiness_assessments (
        id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
        target_id VARCHAR(36) NOT NULL, status VARCHAR(32) NOT NULL, checks JSONB NOT NULL,
        build_ref VARCHAR(128) NOT NULL, schema_version VARCHAR(64) NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        FOREIGN KEY(org_id,target_id) REFERENCES operational_targets(org_id,id) ON DELETE RESTRICT)"""))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_operational_assessment_latest ON operational_readiness_assessments(org_id,observed_at)"))
