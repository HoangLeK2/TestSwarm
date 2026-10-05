"""Create the append-only acquisition-to-readiness funnel ledger."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS ai_lab_funnel_events (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                service_campaign_id VARCHAR(36) NOT NULL,
                acquisition_id VARCHAR(128) NOT NULL,
                event_id VARCHAR(128) NOT NULL,
                event_name VARCHAR(32) NOT NULL,
                source_type VARCHAR(16) NOT NULL,
                source_ref VARCHAR(128) NULL,
                attribution JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_occurred_at TIMESTAMPTZ NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_ai_lab_funnel_event_id UNIQUE (org_id, event_id),
                CONSTRAINT uq_ai_lab_funnel_campaign_step
                    UNIQUE (org_id, service_campaign_id, event_name),
                CONSTRAINT fk_ai_lab_funnel_campaign_org
                    FOREIGN KEY (org_id, service_campaign_id)
                    REFERENCES service_campaigns(org_id, id) ON DELETE RESTRICT,
                CONSTRAINT chk_ai_lab_funnel_event_name CHECK (
                    event_name IN (
                        'landing_view', 'start_click', 'app_submitted',
                        'scenario_approved', 'payment_completed', 'readiness_started'
                    )
                ),
                CONSTRAINT chk_ai_lab_funnel_source_type CHECK (
                    source_type IN ('client', 'server')
                )
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_ai_lab_funnel_campaign_time "
            "ON ai_lab_funnel_events(org_id, service_campaign_id, source_occurred_at)"
        )
    )
    await conn.execute(
        text(
            "DROP TRIGGER IF EXISTS ai_lab_funnel_events_immutable ON ai_lab_funnel_events"
        )
    )
    await conn.execute(
        text(
            """
            CREATE TRIGGER ai_lab_funnel_events_immutable
            BEFORE UPDATE OR DELETE ON ai_lab_funnel_events
            FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
            """
        )
    )
