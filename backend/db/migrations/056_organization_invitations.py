"""056 — Pending organization invitations (email invite flow)."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS organization_invitations (
                id VARCHAR(36) PRIMARY KEY,
                organization_id VARCHAR(36) NOT NULL
                    REFERENCES organizations(id) ON DELETE CASCADE,
                email VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'member',
                token VARCHAR(128) NOT NULL UNIQUE,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                invited_by_user_id VARCHAR(36)
                    REFERENCES users(id) ON DELETE SET NULL,
                accepted_by_user_id VARCHAR(36)
                    REFERENCES users(id) ON DELETE SET NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                accepted_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_org_invitations_org_email
            ON organization_invitations (organization_id, lower(email));
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_org_invitations_token
            ON organization_invitations (token);
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_org_invitations_pending_email
            ON organization_invitations (organization_id, lower(email))
            WHERE status = 'pending';
            """
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS uq_org_invitations_pending_email"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_org_invitations_token"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_org_invitations_org_email"))
    await conn.execute(text("DROP TABLE IF EXISTS organization_invitations"))
