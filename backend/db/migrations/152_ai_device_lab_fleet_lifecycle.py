"""Enable reservation history and add recoverable fleet lifecycle records."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE device_reservations DROP CONSTRAINT IF EXISTS uq_reservation_lane"))
    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_active_reservation_lane
        ON device_reservations(org_id,service_campaign_id,lane_id)
        WHERE state IN ('active','draining')
    """))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS lane_device_assignments (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            lane_id VARCHAR(36) NOT NULL REFERENCES service_lanes(id) ON DELETE RESTRICT,
            reservation_id VARCHAR(36) NOT NULL, device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE RESTRICT,
            started_at TIMESTAMPTZ NOT NULL, ended_at TIMESTAMPTZ NULL,
            assigned_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT, reason TEXT NOT NULL,
            CONSTRAINT uq_lane_device_assignments_org_id UNIQUE(org_id,id),
            CONSTRAINT fk_lane_assignment_reservation_org FOREIGN KEY(org_id,reservation_id)
                REFERENCES device_reservations(org_id,id) ON DELETE RESTRICT
        )
    """))
    await conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_current_lane_device_assignment
        ON lane_device_assignments(org_id,service_campaign_id,lane_id) WHERE ended_at IS NULL
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_lane_assignments_history ON lane_device_assignments(lane_id,started_at)"))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS fleet_lifecycle_operations (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            lane_id VARCHAR(36) NULL REFERENCES service_lanes(id) ON DELETE RESTRICT,
            operation_type VARCHAR(32) NOT NULL, idempotency_key VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL, checkpoint VARCHAR(64) NOT NULL,
            old_reservation_id VARCHAR(36) NULL, new_reservation_id VARCHAR(36) NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb, actor_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            reason TEXT NOT NULL, error_code VARCHAR(128) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_fleet_operation_key UNIQUE(org_id,idempotency_key)
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fleet_operations_campaign_status ON fleet_lifecycle_operations(service_campaign_id,status)"))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS service_extensions (
            id VARCHAR(36) PRIMARY KEY, org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
            service_campaign_id VARCHAR(36) NOT NULL REFERENCES service_campaigns(id) ON DELETE RESTRICT,
            previous_end_at TIMESTAMPTZ NOT NULL, new_end_at TIMESTAMPTZ NOT NULL,
            added_service_days INTEGER NOT NULL CHECK(added_service_days > 0), consent_snapshot JSONB NOT NULL,
            order_id VARCHAR(36) NOT NULL, entitlement_id VARCHAR(36) NOT NULL,
            idempotency_key VARCHAR(128) NOT NULL, created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), CONSTRAINT uq_service_extension_key UNIQUE(org_id,idempotency_key),
            CONSTRAINT fk_service_extension_campaign_org FOREIGN KEY(org_id,service_campaign_id)
                REFERENCES service_campaigns(org_id,id) ON DELETE RESTRICT,
            CONSTRAINT fk_service_extension_order_org FOREIGN KEY(org_id,order_id)
                REFERENCES service_orders(org_id,id) ON DELETE RESTRICT,
            CONSTRAINT fk_service_extension_entitlement_org FOREIGN KEY(org_id,entitlement_id)
                REFERENCES service_entitlements(org_id,id) ON DELETE RESTRICT
        )
    """))
