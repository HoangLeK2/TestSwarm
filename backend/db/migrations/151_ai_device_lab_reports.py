"""Create immutable report snapshot manifests."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS report_snapshots (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL, version INTEGER NOT NULL CHECK(version >= 1),
            idempotency_key VARCHAR(128) NOT NULL, schema_version VARCHAR(64) NOT NULL,
            cutoff_at TIMESTAMPTZ NOT NULL, builder_version VARCHAR(64) NOT NULL,
            manifest JSONB NOT NULL, manifest_sha256 VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'ready', pdf_object_key VARCHAR(1024) NULL,
            pdf_sha256 VARCHAR(64) NULL, created_by VARCHAR(36) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_report_snapshots_org_id UNIQUE(org_id,id),
            CONSTRAINT uq_report_snapshot_version UNIQUE(org_id,service_campaign_id,version),
            CONSTRAINT uq_report_snapshot_key UNIQUE(org_id,service_campaign_id,idempotency_key),
            CONSTRAINT fk_report_snapshot_campaign_org FOREIGN KEY(org_id,service_campaign_id)
                REFERENCES service_campaigns(org_id,id) ON DELETE RESTRICT
        )
    """))
