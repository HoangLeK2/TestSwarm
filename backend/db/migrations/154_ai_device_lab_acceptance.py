"""Add immutable launch acceptance pack records."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    statements = [
        """CREATE TABLE IF NOT EXISTS acceptance_candidates (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            version VARCHAR(64) NOT NULL, source_kind VARCHAR(16) NOT NULL, environment VARCHAR(64) NOT NULL,
            commit_sha VARCHAR(64) NOT NULL, schema_version VARCHAR(64) NOT NULL, manifest_sha256 VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'draft',
            rollback_owner VARCHAR(255) NULL, oncall_owner VARCHAR(255) NULL,
            created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            frozen_at TIMESTAMPTZ NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(org_id,id), UNIQUE(org_id,version))""",
        """CREATE TABLE IF NOT EXISTS acceptance_requirements (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            candidate_id VARCHAR(36) NOT NULL, requirement_key VARCHAR(128) NOT NULL, adl_id VARCHAR(16) NOT NULL,
            acceptance_id VARCHAR(32) NOT NULL, test_id VARCHAR(32) NOT NULL, expected TEXT NOT NULL, observed TEXT NOT NULL,
            status VARCHAR(16) NOT NULL, required_evidence_level VARCHAR(16) NOT NULL,
            observed_evidence_level VARCHAR(16) NOT NULL, evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            reviewer_id VARCHAR(255) NULL, executed_at TIMESTAMPTZ NULL, blocker TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(org_id,candidate_id,requirement_key),
            FOREIGN KEY(org_id,candidate_id) REFERENCES acceptance_candidates(org_id,id) ON DELETE RESTRICT)""",
        "CREATE INDEX IF NOT EXISTS idx_acceptance_requirement_status ON acceptance_requirements(candidate_id,status)",
        """CREATE TABLE IF NOT EXISTS acceptance_decisions (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            candidate_id VARCHAR(36) NOT NULL, evaluation_key VARCHAR(128) NOT NULL, verdict VARCHAR(32) NOT NULL,
            blockers JSONB NOT NULL DEFAULT '[]'::jsonb, requirement_summary JSONB NOT NULL,
            pack_sha256 VARCHAR(64) NOT NULL, signer_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            rationale TEXT NOT NULL, evaluated_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(org_id,candidate_id,evaluation_key),
            FOREIGN KEY(org_id,candidate_id) REFERENCES acceptance_candidates(org_id,id) ON DELETE RESTRICT)""",
    ]
    for statement in statements:
        await conn.execute(text(statement))
