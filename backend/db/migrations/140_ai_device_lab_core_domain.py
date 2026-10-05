"""AI Device Lab core service campaign, lane, slot, attempt and build domain."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS service_campaigns (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                runtime_campaign_id VARCHAR(36) NOT NULL REFERENCES campaigns(id) ON DELETE RESTRICT,
                owner_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                package_name VARCHAR(255) NOT NULL,
                timezone VARCHAR(64) NOT NULL,
                plan_version VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'draft',
                lock_version INTEGER NOT NULL DEFAULT 0,
                started_at TIMESTAMPTZ NULL,
                end_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_service_campaigns_org_id UNIQUE (org_id, id),
                CONSTRAINT uq_service_campaigns_runtime_campaign
                    UNIQUE (org_id, runtime_campaign_id)
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_service_campaigns_org_status
            ON service_campaigns (org_id, status)
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS service_lanes (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                service_campaign_id VARCHAR(36) NOT NULL,
                ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 12),
                tester_label VARCHAR(64) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_service_lanes_campaign_ordinal
                    UNIQUE (org_id, service_campaign_id, ordinal),
                CONSTRAINT uq_service_lanes_org_id_campaign
                    UNIQUE (org_id, id, service_campaign_id),
                CONSTRAINT fk_service_lanes_campaign_org
                    FOREIGN KEY (org_id, service_campaign_id)
                    REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT
            )
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS app_builds (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                package_name VARCHAR(255) NOT NULL,
                version_name VARCHAR(128) NOT NULL,
                version_code VARCHAR(64) NOT NULL,
                source_kind VARCHAR(32) NOT NULL,
                source_ref VARCHAR(512) NULL,
                checksum_sha256 VARCHAR(64) NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_app_builds_org_id UNIQUE (org_id, id),
                CONSTRAINT uq_app_builds_org_package_checksum
                    UNIQUE (org_id, package_name, checksum_sha256)
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_app_builds_org_package
            ON app_builds (org_id, package_name)
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS run_slots (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                service_campaign_id VARCHAR(36) NOT NULL,
                lane_id VARCHAR(36) NOT NULL,
                service_day INTEGER NOT NULL CHECK (service_day BETWEEN 1 AND 14),
                planned_at TIMESTAMPTZ NOT NULL,
                execution_status VARCHAR(32) NOT NULL DEFAULT 'planned',
                app_verdict VARCHAR(32) NULL,
                play_participation_state VARCHAR(32) NOT NULL DEFAULT 'unknown',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_run_slots_campaign_lane_day
                    UNIQUE (org_id, service_campaign_id, lane_id, service_day),
                CONSTRAINT uq_run_slots_org_identity
                    UNIQUE (org_id, id, service_campaign_id, lane_id),
                CONSTRAINT fk_run_slots_campaign_org
                    FOREIGN KEY (org_id, service_campaign_id)
                    REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT,
                CONSTRAINT fk_run_slots_lane_org_campaign
                    FOREIGN KEY (org_id, lane_id, service_campaign_id)
                    REFERENCES service_lanes (org_id, id, service_campaign_id)
                    ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_run_slots_campaign_status
            ON run_slots (service_campaign_id, execution_status)
            """
        )
    )

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS run_attempts (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                service_campaign_id VARCHAR(36) NOT NULL,
                lane_id VARCHAR(36) NOT NULL,
                slot_id VARCHAR(36) NOT NULL,
                attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
                execution_id VARCHAR(36) NOT NULL REFERENCES executions(id) ON DELETE RESTRICT,
                scenario_version_id VARCHAR(36) NOT NULL REFERENCES scenario_versions(id) ON DELETE RESTRICT,
                app_build_id VARCHAR(36) NOT NULL,
                idempotency_key VARCHAR(128) NOT NULL,
                reason VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'created',
                outcome VARCHAR(32) NULL,
                observed_build JSONB NOT NULL DEFAULT '{}'::jsonb,
                failure_reason TEXT NULL,
                started_at TIMESTAMPTZ NULL,
                finished_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_run_attempts_slot_number
                    UNIQUE (org_id, slot_id, attempt_no),
                CONSTRAINT uq_run_attempts_idempotency
                    UNIQUE (org_id, idempotency_key),
                CONSTRAINT fk_run_attempts_slot_identity
                    FOREIGN KEY (org_id, slot_id, service_campaign_id, lane_id)
                    REFERENCES run_slots (org_id, id, service_campaign_id, lane_id)
                    ON DELETE RESTRICT,
                CONSTRAINT fk_run_attempts_build_org
                    FOREIGN KEY (org_id, app_build_id)
                    REFERENCES app_builds (org_id, id) ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_run_attempts_slot_created
            ON run_attempts (slot_id, created_at)
            """
        )
    )
