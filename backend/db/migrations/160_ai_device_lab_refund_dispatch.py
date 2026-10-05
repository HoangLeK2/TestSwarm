"""Create the fenced refund dispatch outbox."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_service_refunds_org_id'
                ) THEN
                    ALTER TABLE service_refunds
                    ADD CONSTRAINT uq_service_refunds_org_id UNIQUE (org_id, id);
                END IF;
            END
            $$
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS refund_dispatch_jobs (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                refund_id VARCHAR(36) NOT NULL,
                order_id VARCHAR(36) NOT NULL,
                provider VARCHAR(32) NOT NULL,
                payment_reference VARCHAR(255) NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                available_at TIMESTAMPTZ NOT NULL,
                lease_until TIMESTAMPTZ NULL,
                lease_token VARCHAR(64) NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error_code VARCHAR(128) NULL,
                delivered_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_refund_dispatch_refund UNIQUE (org_id, refund_id),
                CONSTRAINT fk_refund_dispatch_refund_org
                    FOREIGN KEY (org_id, refund_id)
                    REFERENCES service_refunds(org_id, id) ON DELETE RESTRICT,
                CONSTRAINT fk_refund_dispatch_order_org
                    FOREIGN KEY (org_id, order_id)
                    REFERENCES service_orders(org_id, id) ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_refund_dispatch_delivery "
            "ON refund_dispatch_jobs(status, available_at, lease_until)"
        )
    )
