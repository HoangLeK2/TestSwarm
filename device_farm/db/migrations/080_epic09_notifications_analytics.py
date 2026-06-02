"""080 — Epic 09 notification analytics tables and read timestamps."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ"))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS metric_rollup_daily (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            bucket_date DATE NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            resource_id VARCHAR(100),
            event_type VARCHAR(100) NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            latency_p50 DOUBLE PRECISION,
            latency_p95 DOUBLE PRECISION,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_metric_rollup_daily_natural
                UNIQUE (org_id, bucket_date, resource_type, resource_id, event_type)
        )
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS metric_rollup_weekly (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            week_start DATE NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            resource_id VARCHAR(100),
            event_type VARCHAR(100) NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            latency_p50 DOUBLE PRECISION,
            latency_p95 DOUBLE PRECISION,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_metric_rollup_weekly_natural
                UNIQUE (org_id, week_start, resource_type, resource_id, event_type)
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_metric_daily_org_date_type ON metric_rollup_daily (org_id, bucket_date, resource_type)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_metric_daily_org_resource_date ON metric_rollup_daily (org_id, resource_id, bucket_date)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_metric_weekly_org_week_type ON metric_rollup_weekly (org_id, week_start, resource_type)"))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_rules (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36),
            event_type VARCHAR(100) NOT NULL,
            recipient_resolver VARCHAR(100) NOT NULL,
            channel_list JSONB NOT NULL DEFAULT '[]'::jsonb,
            priority INTEGER NOT NULL DEFAULT 0,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notification_rules_org_event ON notification_rules (org_id, event_type)"))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            persona VARCHAR(50),
            user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
            channel VARCHAR(30) NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            source VARCHAR(20) NOT NULL DEFAULT 'user',
            reason VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_notification_preference_scope
                UNIQUE (org_id, persona, user_id, channel, event_type)
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_notification_preferences_org_user ON notification_preferences (org_id, user_id)"))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS webhook_delivery_log (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36),
            channel_id VARCHAR(36) REFERENCES notification_channels(id) ON DELETE SET NULL,
            event_id VARCHAR(100),
            event_type VARCHAR(100) NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(30) NOT NULL,
            status_code INTEGER,
            latency_ms INTEGER,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_webhook_delivery_channel_created ON webhook_delivery_log (channel_id, created_at)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_webhook_delivery_org_status ON webhook_delivery_log (org_id, status)"))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS webhook_dlq (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36),
            channel_id VARCHAR(36) REFERENCES notification_channels(id) ON DELETE SET NULL,
            event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            final_status VARCHAR(30) NOT NULL,
            last_error TEXT,
            last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            name VARCHAR(255) NOT NULL,
            metric VARCHAR(100) NOT NULL,
            comparator VARCHAR(10) NOT NULL,
            threshold DOUBLE PRECISION NOT NULL,
            window_minutes INTEGER NOT NULL DEFAULT 60,
            severity VARCHAR(20) NOT NULL DEFAULT 'warning',
            target_personas JSONB NOT NULL DEFAULT '[]'::jsonb,
            escalation_minutes INTEGER NOT NULL DEFAULT 15,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alert_rules_org_enabled ON alert_rules (org_id, is_enabled)"))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alerts (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            rule_id VARCHAR(36) REFERENCES alert_rules(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            severity VARCHAR(20) NOT NULL DEFAULT 'warning',
            title VARCHAR(255) NOT NULL,
            body TEXT,
            observed_value DOUBLE PRECISION,
            ack_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            ack_at TIMESTAMPTZ,
            ack_reason VARCHAR(500),
            escalated_at TIMESTAMPTZ,
            escalated_to VARCHAR(36),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alerts_org_status_created ON alerts (org_id, status, created_at)"))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alert_decisions (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            notification_id VARCHAR(36),
            rule_id VARCHAR(36),
            suppressed BOOLEAN NOT NULL DEFAULT FALSE,
            digested BOOLEAN NOT NULL DEFAULT FALSE,
            reason VARCHAR(255),
            next_delivery_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS analytics_retention_policies (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL,
            data_type VARCHAR(50) NOT NULL,
            retention_days INTEGER NOT NULL DEFAULT 180,
            action VARCHAR(20) NOT NULL DEFAULT 'purge',
            legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_retention_policy_org_type UNIQUE (org_id, data_type)
        )
    """))
