"""085 — Add revision tracking for cached Casbin policies."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS casbin_policy_revision (
            id SMALLINT PRIMARY KEY CHECK (id = 1),
            revision BIGINT NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    await conn.execute(text("""
        INSERT INTO casbin_policy_revision (id, revision)
        VALUES (1, 1)
        ON CONFLICT (id) DO NOTHING
    """))
    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION casbin_rule_touch_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    await conn.execute(text("""
        DROP TRIGGER IF EXISTS trg_casbin_rule_touch_updated_at ON casbin_rule
    """))
    await conn.execute(text("""
        CREATE TRIGGER trg_casbin_rule_touch_updated_at
        BEFORE UPDATE ON casbin_rule
        FOR EACH ROW
        EXECUTE FUNCTION casbin_rule_touch_updated_at()
    """))
    await conn.execute(text("""
        CREATE OR REPLACE FUNCTION casbin_policy_revision_bump()
        RETURNS trigger AS $$
        BEGIN
            UPDATE casbin_policy_revision
               SET revision = revision + 1,
                   updated_at = NOW()
             WHERE id = 1;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """))
    await conn.execute(text("""
        DROP TRIGGER IF EXISTS trg_casbin_policy_revision_bump ON casbin_rule
    """))
    await conn.execute(text("""
        CREATE TRIGGER trg_casbin_policy_revision_bump
        AFTER INSERT OR UPDATE OR DELETE ON casbin_rule
        FOR EACH STATEMENT
        EXECUTE FUNCTION casbin_policy_revision_bump()
    """))
