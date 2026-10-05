"""Create issue and retest lineage records."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'run_attempts'::regclass
                  AND conname = 'uq_run_attempts_org_id'
            ) THEN
                ALTER TABLE run_attempts
                ADD CONSTRAINT uq_run_attempts_org_id UNIQUE (org_id, id);
            END IF;
        END
        $$
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS app_issues (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL, source_attempt_id VARCHAR(36) NOT NULL,
            source_build_id VARCHAR(36) NOT NULL REFERENCES app_builds(id) ON DELETE RESTRICT,
            source_scenario_version_id VARCHAR(36) NOT NULL REFERENCES scenario_versions(id) ON DELETE RESTRICT,
            severity VARCHAR(32) NOT NULL, assertion_key VARCHAR(255) NOT NULL, expected TEXT NOT NULL,
            actual TEXT NOT NULL, reproduction JSONB NOT NULL, fingerprint VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'open', created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), CONSTRAINT uq_app_issues_org_id UNIQUE(org_id,id),
            CONSTRAINT fk_app_issue_source_attempt_org FOREIGN KEY(org_id,source_attempt_id)
                REFERENCES run_attempts(org_id,id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS retest_requests (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            issue_id VARCHAR(36) NOT NULL, source_attempt_id VARCHAR(36) NOT NULL REFERENCES run_attempts(id) ON DELETE RESTRICT,
            target_build_id VARCHAR(36) NOT NULL REFERENCES app_builds(id) ON DELETE RESTRICT,
            target_scenario_version_id VARCHAR(36) NOT NULL REFERENCES scenario_versions(id) ON DELETE RESTRICT,
            lane_scope JSONB NOT NULL, idempotency_key VARCHAR(128) NOT NULL, consent_snapshot JSONB NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'requested', new_attempt_id VARCHAR(36) NULL REFERENCES run_attempts(id) ON DELETE RESTRICT,
            verdict VARCHAR(32) NULL, verdict_reason VARCHAR(128) NULL,
            requested_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), CONSTRAINT uq_retest_requests_org_id UNIQUE(org_id,id),
            CONSTRAINT uq_retest_requests_idempotency UNIQUE(org_id,idempotency_key),
            CONSTRAINT fk_retest_request_issue_org FOREIGN KEY(org_id,issue_id) REFERENCES app_issues(org_id,id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS issue_transitions (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            issue_id VARCHAR(36) NOT NULL REFERENCES app_issues(id) ON DELETE RESTRICT,
            from_status VARCHAR(32) NOT NULL, to_status VARCHAR(32) NOT NULL,
            actor_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            reason TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
