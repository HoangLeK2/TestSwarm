"""042 — Optional account FK on executions for analytics joins."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE executions
        ADD COLUMN IF NOT EXISTS account_id VARCHAR(36)
        REFERENCES accounts(id) ON DELETE SET NULL
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_executions_account "
        "ON executions (account_id) WHERE account_id IS NOT NULL"
    ))
