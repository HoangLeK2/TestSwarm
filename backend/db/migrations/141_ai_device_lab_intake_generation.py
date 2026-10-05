"""Persist AI Device Lab intake and idempotent scenario generation operations."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_lab_intakes (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                owner_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                runtime_campaign_id VARCHAR(36) NOT NULL REFERENCES campaigns(id) ON DELETE RESTRICT,
                requested_build_id VARCHAR(36) NOT NULL,
                package_name VARCHAR(255) NOT NULL,
                closed_track_link TEXT NOT NULL,
                test_goal TEXT NOT NULL,
                test_environment JSONB NOT NULL DEFAULT '{}'::jsonb,
                status VARCHAR(32) NOT NULL DEFAULT 'draft',
                input_version INTEGER NOT NULL DEFAULT 1 CHECK (input_version >= 1),
                input_hash VARCHAR(64) NOT NULL,
                lock_version INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ai_lab_intakes_org_id UNIQUE (org_id, id),
                CONSTRAINT fk_ai_lab_intakes_build_org
                    FOREIGN KEY (org_id, requested_build_id)
                    REFERENCES app_builds (org_id, id) ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_lab_intakes_org_owner
            ON ai_lab_intakes (org_id, owner_id)
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS scenario_generation_operations (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                intake_id VARCHAR(36) NOT NULL,
                operation_id VARCHAR(128) NOT NULL,
                input_version INTEGER NOT NULL CHECK (input_version >= 1),
                input_hash VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                provider_request_ref VARCHAR(255) NULL,
                error_code VARCHAR(64) NULL,
                scenario_id VARCHAR(36) NULL REFERENCES scenarios(id) ON DELETE RESTRICT,
                scenario_version_id VARCHAR(36) NULL
                    REFERENCES scenario_versions(id) ON DELETE RESTRICT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ NULL,
                CONSTRAINT uq_scenario_generation_operation
                    UNIQUE (org_id, operation_id),
                CONSTRAINT fk_scenario_generation_intake_org
                    FOREIGN KEY (org_id, intake_id)
                    REFERENCES ai_lab_intakes (org_id, id) ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_scenario_generation_intake
            ON scenario_generation_operations (intake_id, created_at)
            """
        )
    )
