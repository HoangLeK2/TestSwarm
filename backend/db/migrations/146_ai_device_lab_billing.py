"""Create provider-neutral AI Device Lab billing ledger."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS service_orders (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            plan_version VARCHAR(64) NOT NULL,
            pricing_version VARCHAR(64) NOT NULL,
            policy_version VARCHAR(64) NOT NULL,
            quota_snapshot JSONB NOT NULL,
            amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
            currency CHAR(3) NOT NULL CHECK (currency = UPPER(currency)),
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            paid_at TIMESTAMPTZ NULL,
            refunded_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_service_orders_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_service_orders_idempotency UNIQUE (org_id, idempotency_key),
            CONSTRAINT fk_service_orders_campaign_org FOREIGN KEY (org_id, service_campaign_id)
                REFERENCES service_campaigns (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS payment_intents (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            order_id VARCHAR(36) NOT NULL,
            provider VARCHAR(32) NOT NULL,
            provider_reference VARCHAR(255) NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            amount_minor BIGINT NOT NULL,
            currency CHAR(3) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'created',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_payment_intents_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_payment_intents_provider_ref UNIQUE (provider, provider_reference),
            CONSTRAINT uq_payment_intents_idempotency UNIQUE (org_id, idempotency_key),
            CONSTRAINT fk_payment_intents_order_org FOREIGN KEY (org_id, order_id)
                REFERENCES service_orders (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS payment_events (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            order_id VARCHAR(36) NOT NULL,
            provider VARCHAR(32) NOT NULL,
            provider_event_id VARCHAR(255) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            amount_minor BIGINT NULL,
            currency CHAR(3) NULL,
            signature_verified BOOLEAN NOT NULL,
            source_occurred_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processing_state VARCHAR(32) NOT NULL DEFAULT 'accepted',
            reason_code VARCHAR(128) NULL,
            CONSTRAINT uq_payment_events_provider_event UNIQUE (provider, provider_event_id),
            CONSTRAINT fk_payment_events_order_org FOREIGN KEY (org_id, order_id)
                REFERENCES service_orders (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS service_entitlements (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            order_id VARCHAR(36) NOT NULL,
            service_campaign_id VARCHAR(36) NOT NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            state VARCHAR(32) NOT NULL DEFAULT 'active',
            granted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ NULL,
            revoke_reason TEXT NULL,
            CONSTRAINT uq_service_entitlements_org_id UNIQUE (org_id, id),
            CONSTRAINT uq_service_entitlements_order UNIQUE (org_id, order_id),
            CONSTRAINT fk_service_entitlements_order_org FOREIGN KEY (org_id, order_id)
                REFERENCES service_orders (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS service_refunds (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            order_id VARCHAR(36) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL,
            provider_reference VARCHAR(255) NULL,
            amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
            reason TEXT NOT NULL,
            actor_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_service_refunds_idempotency UNIQUE (org_id, idempotency_key),
            CONSTRAINT fk_service_refunds_order_org FOREIGN KEY (org_id, order_id)
                REFERENCES service_orders (org_id, id) ON DELETE RESTRICT
        )
    """)
    )
    await conn.execute(
        text("DROP TRIGGER IF EXISTS payment_events_immutable ON payment_events")
    )
    await conn.execute(
        text("""
        CREATE TRIGGER payment_events_immutable
        BEFORE UPDATE OR DELETE ON payment_events
        FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
    """)
    )
