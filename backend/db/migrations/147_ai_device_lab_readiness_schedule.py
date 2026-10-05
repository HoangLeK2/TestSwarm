"""Create readiness, durable start intent, and quota ledger tables."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS readiness_snapshots (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            policy_version VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_readiness_snapshots_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_readiness_snapshot_revision UNIQUE (org_id, service_campaign_id, revision),
            CONSTRAINT fk_readiness_snapshot_campaign_org FOREIGN KEY (org_id, service_campaign_id)
                REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS readiness_checks (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            snapshot_id VARCHAR(36) NOT NULL,
            check_key VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL,
            required BOOLEAN NOT NULL,
            reason_code VARCHAR(128) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            source_type VARCHAR(64) NOT NULL,
            source_ref VARCHAR(255) NULL,
            source_version VARCHAR(64) NULL,
            owner VARCHAR(64) NOT NULL,
            next_action TEXT NULL,
            CONSTRAINT uq_readiness_check_key UNIQUE (snapshot_id, check_key),
            CONSTRAINT fk_readiness_check_snapshot_org FOREIGN KEY (org_id, snapshot_id)
                REFERENCES readiness_snapshots (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS scheduling_intents (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL,
            intent_kind VARCHAR(32) NOT NULL DEFAULT 'start',
            idempotency_key VARCHAR(128) NOT NULL,
            readiness_snapshot_id VARCHAR(36) NOT NULL REFERENCES readiness_snapshots(id) ON DELETE RESTRICT,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_scheduling_intents_key UNIQUE (org_id, idempotency_key),
            CONSTRAINT uq_scheduling_intent_campaign_kind UNIQUE (org_id, service_campaign_id, intent_kind),
            CONSTRAINT fk_scheduling_intent_campaign_org FOREIGN KEY (org_id, service_campaign_id)
                REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS quota_ledger_entries (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL,
            run_attempt_id VARCHAR(36) NULL REFERENCES run_attempts(id) ON DELETE RESTRICT,
            charge_key VARCHAR(128) NOT NULL,
            entry_type VARCHAR(32) NOT NULL,
            resource_type VARCHAR(32) NOT NULL,
            quantity BIGINT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            occurred_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_quota_ledger_charge_key UNIQUE (org_id, charge_key),
            CONSTRAINT fk_quota_ledger_campaign_org FOREIGN KEY (org_id, service_campaign_id)
                REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("DROP TRIGGER IF EXISTS readiness_checks_immutable ON readiness_checks")
    )
    await conn.execute(
        text("""
        CREATE TRIGGER readiness_checks_immutable BEFORE UPDATE OR DELETE ON readiness_checks
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS quota_ledger_entries_immutable ON quota_ledger_entries"
        )
    )
    await conn.execute(
        text("""
        CREATE TRIGGER quota_ledger_entries_immutable BEFORE UPDATE OR DELETE ON quota_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
