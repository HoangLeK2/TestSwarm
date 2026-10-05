"""Persist immutable approval snapshots for generated AI Device Lab scenarios."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS scenario_approvals (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                intake_id VARCHAR(36) NOT NULL,
                generation_operation_id VARCHAR(36) NOT NULL,
                scenario_version_id VARCHAR(36) NOT NULL
                    REFERENCES scenario_versions(id) ON DELETE RESTRICT,
                content_hash VARCHAR(64) NOT NULL,
                policy_version VARCHAR(64) NOT NULL,
                assertions JSONB NOT NULL DEFAULT '[]'::jsonb,
                allowed_operations JSONB NOT NULL DEFAULT '[]'::jsonb,
                package_name VARCHAR(255) NOT NULL,
                approved_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_scenario_approvals_org_id UNIQUE (org_id, id),
                CONSTRAINT uq_scenario_approvals_exact_snapshot UNIQUE (
                    org_id, scenario_version_id, content_hash, policy_version
                ),
                CONSTRAINT fk_scenario_approvals_intake_org
                    FOREIGN KEY (org_id, intake_id)
                    REFERENCES ai_lab_intakes (org_id, id) ON DELETE RESTRICT,
                CONSTRAINT fk_scenario_approvals_generation_org
                    FOREIGN KEY (org_id, generation_operation_id)
                    REFERENCES scenario_generation_operations (org_id, id)
                    ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_scenario_approvals_intake
            ON scenario_approvals (intake_id, approved_at)
            """
        )
    )
