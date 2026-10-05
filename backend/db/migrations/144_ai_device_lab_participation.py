"""Create append-only Play-track participation evidence tables."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS track_participations (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            package_name VARCHAR(255) NOT NULL,
            track_name VARCHAR(64) NOT NULL,
            pseudonymous_account_ref VARCHAR(128) NOT NULL,
            masked_label VARCHAR(128) NOT NULL,
            current_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
            evidence_grade VARCHAR(32) NOT NULL DEFAULT 'none',
            active_segment_no INTEGER NOT NULL DEFAULT 0 CHECK (active_segment_no >= 0),
            last_observed_at TIMESTAMPTZ NULL,
            gap_reason VARCHAR(128) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_track_participations_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_track_participations_identity UNIQUE (
                org_id, package_name, track_name, pseudonymous_account_ref
            )
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_track_participations_campaign_status
        ON track_participations (service_campaign_id, current_status)
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS participation_events (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            participation_id VARCHAR(36) NOT NULL,
            event_type VARCHAR(32) NOT NULL,
            source_type VARCHAR(32) NOT NULL,
            source_ref VARCHAR(255) NULL,
            evidence_ref VARCHAR(255) NULL,
            evidence_grade VARCHAR(32) NOT NULL,
            review_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            observed_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            recorded_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            reviewed_by VARCHAR(36) NULL REFERENCES users(id) ON DELETE RESTRICT,
            reviewed_at TIMESTAMPTZ NULL,
            segment_no INTEGER NOT NULL DEFAULT 0 CHECK (segment_no >= 0),
            correction_of_id VARCHAR(36) NULL REFERENCES participation_events(id) ON DELETE RESTRICT,
            limitations TEXT NULL,
            CONSTRAINT uq_participation_events_org_id UNIQUE (org_id, id),
            CONSTRAINT fk_participation_events_identity_org
                FOREIGN KEY (org_id, participation_id)
                REFERENCES track_participations (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE INDEX IF NOT EXISTS idx_participation_events_identity_time
        ON participation_events (participation_id, observed_at, recorded_at)
    """)
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS participation_events_immutable ON participation_events"
        )
    )
    await conn.execute(
        text("""
        CREATE TRIGGER participation_events_immutable
        BEFORE UPDATE OR DELETE ON participation_events
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
