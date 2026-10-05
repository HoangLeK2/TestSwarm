"""Make checkout intent reuse explicit and persist sanitized dispatch state."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE payment_reconciliation_jobs
                ADD COLUMN IF NOT EXISTS provider_lookup_key VARCHAR(128) NULL
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE payment_intents
                ADD COLUMN IF NOT EXISTS last_error_code VARCHAR(128) NULL,
                ADD COLUMN IF NOT EXISTS checkout_expires_at TIMESTAMPTZ NULL,
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'uq_payment_intents_order'
                ) THEN
                    ALTER TABLE payment_intents
                    ADD CONSTRAINT uq_payment_intents_order UNIQUE (org_id, order_id);
                END IF;
            END
            $$
            """
        )
    )
