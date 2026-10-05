"""Create the fenced provider reconciliation queue."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS payment_reconciliation_jobs (
                id VARCHAR(36) PRIMARY KEY,
                org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
                order_id VARCHAR(36) NOT NULL,
                provider VARCHAR(32) NOT NULL,
                provider_reference VARCHAR(255) NULL,
                reason_code VARCHAR(128) NOT NULL,
                idempotency_key VARCHAR(128) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                available_at TIMESTAMPTZ NOT NULL,
                lease_until TIMESTAMPTZ NULL,
                lease_token VARCHAR(64) NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error_code VARCHAR(128) NULL,
                resolved_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_payment_reconciliation_idempotency
                    UNIQUE (org_id, idempotency_key),
                CONSTRAINT fk_payment_reconciliation_order_org
                    FOREIGN KEY (org_id, order_id)
                    REFERENCES service_orders(org_id, id) ON DELETE RESTRICT
            )
            """
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_payment_reconciliation_delivery "
            "ON payment_reconciliation_jobs(status, available_at, lease_until)"
        )
    )
