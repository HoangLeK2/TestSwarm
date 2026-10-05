"""Create durable farm delivery and evidence manifest tables."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS farm_jobs (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            run_attempt_id VARCHAR(36) NOT NULL REFERENCES run_attempts(id) ON DELETE RESTRICT,
            reservation_id VARCHAR(36) NOT NULL REFERENCES device_reservations(id) ON DELETE RESTRICT,
            scenario_approval_id VARCHAR(36) NOT NULL REFERENCES scenario_approvals(id) ON DELETE RESTRICT,
            schema_version VARCHAR(32) NOT NULL, idempotency_key VARCHAR(128) NOT NULL,
            device_id VARCHAR(36) NOT NULL, deadline_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending', verdict VARCHAR(32) NULL,
            terminal_reason VARCHAR(128) NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_farm_jobs_org_id UNIQUE (org_id,id),
            CONSTRAINT uq_farm_jobs_attempt UNIQUE (org_id,run_attempt_id),
            CONSTRAINT uq_farm_jobs_idempotency UNIQUE (org_id,idempotency_key)
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS farm_job_outbox (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            job_id VARCHAR(36) NOT NULL REFERENCES farm_jobs(id) ON DELETE RESTRICT,
            status VARCHAR(32) NOT NULL DEFAULT 'pending', available_at TIMESTAMPTZ NOT NULL,
            lease_until TIMESTAMPTZ NULL, delivery_attempts INTEGER NOT NULL DEFAULT 0,
            last_error_code VARCHAR(128) NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_farm_job_outbox_job UNIQUE (org_id,job_id)
        )
    """)
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_farm_job_outbox_delivery ON farm_job_outbox(status,available_at)"
        )
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS farm_event_inbox (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            job_id VARCHAR(36) NOT NULL, source VARCHAR(64) NOT NULL, event_id VARCHAR(128) NOT NULL,
            sequence INTEGER NULL, event_type VARCHAR(64) NOT NULL, reason_code VARCHAR(128) NULL,
            assertion_passed BOOLEAN NULL, step_path VARCHAR(255) NULL, step_attempt_index INTEGER NULL,
            artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb, occurred_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_farm_event_source_id UNIQUE(source,event_id),
            CONSTRAINT fk_farm_event_job_org FOREIGN KEY(org_id,job_id) REFERENCES farm_jobs(org_id,id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_farm_event_job_time ON farm_event_inbox(job_id,occurred_at,received_at)"
        )
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS evidence_items (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            run_attempt_id VARCHAR(36) NOT NULL REFERENCES run_attempts(id) ON DELETE RESTRICT,
            execution_id VARCHAR(36) NOT NULL REFERENCES executions(id) ON DELETE RESTRICT,
            step_path VARCHAR(255) NOT NULL, step_attempt_index INTEGER NOT NULL, kind VARCHAR(32) NOT NULL,
            object_key VARCHAR(1024) NULL, content_type VARCHAR(128) NULL, captured_at TIMESTAMPTZ NOT NULL,
            checksum_sha256 VARCHAR(64) NULL, capture_error_code VARCHAR(128) NULL, status VARCHAR(32) NOT NULL,
            retention_until TIMESTAMPTZ NOT NULL, pinned_by_report BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMPTZ NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_evidence_items_org_id UNIQUE(org_id,id),
            CONSTRAINT uq_evidence_item_step_kind UNIQUE(org_id,run_attempt_id,step_path,step_attempt_index,kind)
        )
    """)
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_evidence_items_attempt ON evidence_items(run_attempt_id,captured_at)"
        )
    )
    await conn.execute(
        text("DROP TRIGGER IF EXISTS farm_event_inbox_immutable ON farm_event_inbox")
    )
    await conn.execute(
        text("""
        CREATE TRIGGER farm_event_inbox_immutable BEFORE UPDATE OR DELETE ON farm_event_inbox
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
