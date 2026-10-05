"""Create physical hygiene and long-lived reservation records."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS device_hygiene_states (
            device_id VARCHAR(36) PRIMARY KEY REFERENCES devices(id) ON DELETE RESTRICT,
            state VARCHAR(32) NOT NULL DEFAULT 'dirty',
            protocol_version VARCHAR(64) NOT NULL,
            last_service_campaign_id VARCHAR(36) NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            verification_evidence_ref VARCHAR(255) NULL,
            completed_at TIMESTAMPTZ NULL,
            verified_by VARCHAR(36) NULL REFERENCES users(id) ON DELETE RESTRICT,
            reason_code VARCHAR(128) NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS device_hygiene_audits (
            id VARCHAR(36) PRIMARY KEY,
            device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
            actor_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            from_state VARCHAR(32) NOT NULL,
            to_state VARCHAR(32) NOT NULL,
            protocol_version VARCHAR(64) NOT NULL,
            evidence_ref VARCHAR(255) NULL,
            reason_code VARCHAR(128) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_hygiene_audits_device_time
        ON device_hygiene_audits (device_id, created_at)
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS device_reservations (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL,
            lane_id VARCHAR(36) NOT NULL,
            device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
            starts_at TIMESTAMPTZ NOT NULL,
            ends_at TIMESTAMPTZ NOT NULL,
            state VARCHAR(32) NOT NULL DEFAULT 'active',
            created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            release_reason TEXT NULL,
            released_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT chk_device_reservation_interval CHECK (starts_at < ends_at),
            CONSTRAINT uq_device_reservations_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_reservation_lane UNIQUE (org_id, service_campaign_id, lane_id),
            CONSTRAINT fk_device_reservation_campaign_org FOREIGN KEY (org_id, service_campaign_id)
                REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT,
            CONSTRAINT fk_device_reservation_lane_org FOREIGN KEY (org_id, lane_id, service_campaign_id)
                REFERENCES service_lanes (org_id, id, service_campaign_id) ON DELETE RESTRICT,
            CONSTRAINT ex_device_reservation_overlap EXCLUDE USING gist (
                device_id WITH =,
                tstzrange(starts_at, ends_at, '[)') WITH &&
            ) WHERE (state IN ('active', 'draining'))
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_device_reservations_device_interval
        ON device_reservations (device_id, starts_at, ends_at)
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS reservation_audits (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            reservation_id VARCHAR(36) NOT NULL,
            actor_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            action VARCHAR(32) NOT NULL,
            reason TEXT NOT NULL,
            outcome VARCHAR(32) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_reservation_audit_reservation_org FOREIGN KEY (org_id, reservation_id)
                REFERENCES device_reservations (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_reservation_audits_reservation_time
        ON reservation_audits (reservation_id, created_at)
    """)
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS device_hygiene_audits_immutable ON device_hygiene_audits"
        )
    )
    await conn.execute(
        text("""
        CREATE TRIGGER device_hygiene_audits_immutable
        BEFORE UPDATE OR DELETE ON device_hygiene_audits
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS reservation_audits_immutable ON reservation_audits"
        )
    )
    await conn.execute(
        text("""
        CREATE TRIGGER reservation_audits_immutable
        BEFORE UPDATE OR DELETE ON reservation_audits
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
