"""DF-012: Dead-letter queue + webhook config.

Creates:
  - execution_dlq  — DLQ rows for persistently failed executions

Adds columns to organizations:
  - webhook_url     — POST target URL
  - webhook_secret  — HMAC-SHA256 signing key
  - webhook_events  — comma-separated event names e.g. "task.complete,task.failed"
"""
from sqlalchemy import text


async def upgrade(conn) -> None:
    # ── execution_dlq ──────────────────────────────────────────────────────────
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS execution_dlq (
            id               VARCHAR(36)  PRIMARY KEY,
            execution_id     VARCHAR(36)  NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
            device_serial    VARCHAR(64)  NOT NULL,
            error            TEXT,
            retry_count      INTEGER      NOT NULL DEFAULT 0,
            status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
            last_attempt_at  TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_dlq_execution ON execution_dlq(execution_id)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_dlq_device    ON execution_dlq(device_serial)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_dlq_status    ON execution_dlq(status)"))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_dlq_created   ON execution_dlq(created_at)"))

    # ── organizations: webhook columns ─────────────────────────────────────────
    await conn.execute(text(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS webhook_url    VARCHAR(2048)"))
    await conn.execute(text(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS webhook_secret VARCHAR(255)"))
    await conn.execute(text(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS webhook_events VARCHAR(255) DEFAULT 'task.failed'"))


async def downgrade(conn) -> None:
    await conn.execute(text("DROP TABLE IF EXISTS execution_dlq"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS webhook_url"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS webhook_secret"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS webhook_events"))
