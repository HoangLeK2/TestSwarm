"""
038_relay_agent_ownership — Add user ownership and enrollment tokens for relay agents.
"""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS relay_agent_tokens (
            id           VARCHAR(36)  PRIMARY KEY,
            user_id      VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name         VARCHAR(255) NOT NULL DEFAULT '',
            token_hash   CHAR(64)     NOT NULL UNIQUE,
            prefix       VARCHAR(24)  NOT NULL DEFAULT '',
            status       VARCHAR(16)  NOT NULL DEFAULT 'active',
            last_used_at TIMESTAMPTZ,
            revoked_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_tokens_user_id ON relay_agent_tokens (user_id)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_tokens_status ON relay_agent_tokens (status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agent_tokens_token_hash ON relay_agent_tokens (token_hash)"
    ))

    await conn.execute(text(
        "ALTER TABLE relay_agents ADD COLUMN IF NOT EXISTS user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL"
    ))
    await conn.execute(text(
        "ALTER TABLE relay_agents ADD COLUMN IF NOT EXISTS enrollment_token_id VARCHAR(36) REFERENCES relay_agent_tokens(id) ON DELETE SET NULL"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agents_user_id ON relay_agents (user_id)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_relay_agents_enrollment_token_id ON relay_agents (enrollment_token_id)"
    ))
