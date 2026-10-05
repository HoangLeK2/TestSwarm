"""Create encrypted secret references and exact job capabilities."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS secret_records (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL,
            opaque_ref VARCHAR(128) NOT NULL,
            secret_type VARCHAR(64) NOT NULL,
            ciphertext TEXT NOT NULL,
            key_version VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NULL,
            revoked_at TIMESTAMPTZ NULL,
            retention_policy VARCHAR(64) NOT NULL,
            created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_secret_records_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_secret_records_opaque_ref UNIQUE (opaque_ref),
            CONSTRAINT fk_secret_records_campaign_org FOREIGN KEY (org_id, service_campaign_id)
                REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS job_secret_capabilities (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            capability_ref VARCHAR(128) NOT NULL,
            secret_record_id VARCHAR(36) NOT NULL,
            service_campaign_id VARCHAR(36) NOT NULL,
            lane_id VARCHAR(36) NOT NULL,
            run_attempt_id VARCHAR(36) NOT NULL REFERENCES run_attempts(id) ON DELETE RESTRICT,
            device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
            worker_principal VARCHAR(255) NOT NULL,
            allowed_operation VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            max_resolves INTEGER NOT NULL DEFAULT 1 CHECK (max_resolves BETWEEN 1 AND 3),
            resolve_count INTEGER NOT NULL DEFAULT 0 CHECK (resolve_count >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_job_secret_capability_ref UNIQUE (org_id, capability_ref),
            CONSTRAINT fk_job_secret_capability_secret_org FOREIGN KEY (org_id, secret_record_id)
                REFERENCES secret_records (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_job_secret_capability_attempt
        ON job_secret_capabilities (run_attempt_id, expires_at)
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS secret_access_audits (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            capability_id VARCHAR(36) NOT NULL REFERENCES job_secret_capabilities(id) ON DELETE RESTRICT,
            worker_principal VARCHAR(255) NOT NULL,
            action VARCHAR(32) NOT NULL,
            outcome VARCHAR(32) NOT NULL,
            reason_code VARCHAR(128) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_secret_access_audits_capability_time
        ON secret_access_audits (capability_id, created_at)
    """)
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS secret_access_audits_immutable ON secret_access_audits"
        )
    )
    await conn.execute(
        text("""
        CREATE TRIGGER secret_access_audits_immutable BEFORE UPDATE OR DELETE ON secret_access_audits
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
