"""044 — Tenancy org_id scoping (foundation).

- Add organizations.slug/status/plan/updated_at
- Add users.org_id (current org) + backfill from organization_members
- Add org_id to devices/campaigns + backfill from users.org_id
- Switch campaigns unique constraint from (user_id, name) -> (org_id, name)
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    # ── organizations schema ──────────────────────────────────────────────────
    await conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS slug VARCHAR(120)"))
    await conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"))
    await conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS plan VARCHAR(20) NOT NULL DEFAULT 'standard'"))
    await conn.execute(text("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug_unique ON organizations(slug)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_organizations_created_at ON organizations(created_at)"))

    # Best-effort slug backfill (idempotent). If duplicate, append short suffix.
    await conn.execute(text(r"""
        WITH base AS (
            SELECT
                id,
                lower(regexp_replace(regexp_replace(coalesce(business_name,''), '[^a-zA-Z0-9]+', '-', 'g'), '(^-|-$)', '', 'g')) AS raw
            FROM organizations
        ),
        norm AS (
            SELECT
                id,
                CASE
                    WHEN raw = '' THEN 'org'
                    ELSE raw
                END AS slug0
            FROM base
        ),
        numbered AS (
            SELECT
                n.id,
                CASE
                    WHEN (SELECT count(1) FROM organizations o2 WHERE o2.slug = n.slug0) = 0 THEN n.slug0
                    ELSE n.slug0 || '-' || substring(n.id, 1, 6)
                END AS slug1
            FROM norm n
        )
        UPDATE organizations o
           SET slug = COALESCE(o.slug, numbered.slug1)
          FROM numbered
         WHERE o.id = numbered.id
           AND (o.slug IS NULL OR o.slug = '')
    """))

    # ── users.org_id ─────────────────────────────────────────────────────────
    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(org_id)"))

    # Backfill users.org_id from memberships (prefer owner, else earliest membership).
    await conn.execute(text(r"""
        WITH chosen AS (
            SELECT DISTINCT ON (m.user_id)
                m.user_id,
                m.organization_id
            FROM organization_members m
            ORDER BY
                m.user_id,
                (CASE WHEN m.role = 'owner' THEN 0 ELSE 1 END),
                m.created_at ASC
        )
        UPDATE users u
           SET org_id = COALESCE(u.org_id, chosen.organization_id)
          FROM chosen
         WHERE u.id = chosen.user_id
           AND (u.org_id IS NULL OR u.org_id = '')
    """))

    # Enforce NOT NULL only after backfill. If any rows still NULL, fail fast.
    missing = await conn.execute(text("SELECT count(1) FROM users WHERE org_id IS NULL OR org_id = ''"))
    if int(missing.scalar() or 0) > 0:
        raise RuntimeError("tenancy migration: users.org_id backfill incomplete (NULL rows remain)")

    await conn.execute(text("ALTER TABLE users ALTER COLUMN org_id SET NOT NULL"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_users_org_id'
            ) THEN
                ALTER TABLE users ADD CONSTRAINT fk_users_org_id
                FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE RESTRICT;
            END IF;
        END $$;
    """))

    # ── devices.org_id ────────────────────────────────────────────────────────
    await conn.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_devices_org_id_created_at ON devices(org_id, created_at)"))
    await conn.execute(text(r"""
        UPDATE devices d
           SET org_id = u.org_id
          FROM users u
         WHERE d.user_id = u.id
           AND (d.org_id IS NULL OR d.org_id = '')
    """))
    # Pending/unowned devices (user_id NULL) are not allowed in strict tenancy; keep nullable for now.

    # ── campaigns.org_id + uniqueness ─────────────────────────────────────────
    await conn.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_campaigns_org_id_created_at ON campaigns(org_id, created_at)"))
    await conn.execute(text(r"""
        UPDATE campaigns c
           SET org_id = u.org_id
          FROM users u
         WHERE c.user_id = u.id
           AND (c.org_id IS NULL OR c.org_id = '')
    """))

    # Legacy uniqueness was per user; org scope can collide across users in one org.
    # Keep the oldest campaign name; suffix duplicates with a short id fragment.
    await conn.execute(text(r"""
        WITH ranked AS (
            SELECT
                id,
                name,
                ROW_NUMBER() OVER (
                    PARTITION BY org_id, name
                    ORDER BY created_at ASC NULLS LAST, id ASC
                ) AS rn
            FROM campaigns
            WHERE org_id IS NOT NULL AND org_id <> ''
        )
        UPDATE campaigns c
           SET name = left(r.name, 247) || ' - ' || substring(c.id, 1, 6)
          FROM ranked r
         WHERE c.id = r.id
           AND r.rn > 1
    """))

    # Drop legacy unique(user_id, name) if present; add unique(org_id, name).
    await conn.execute(text("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_user_id_name_key"))
    await conn.execute(text("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS uq_campaign_user_name"))
    await conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_campaign_org_name'
            ) THEN
                ALTER TABLE campaigns ADD CONSTRAINT uq_campaign_org_name
                UNIQUE (org_id, name);
            END IF;
        END $$;
    """))


async def downgrade(conn) -> None:
    # Downgrade is best-effort; production does not rely on downgrades.
    await conn.execute(text("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS uq_campaign_org_name"))
    await conn.execute(text("ALTER TABLE campaigns DROP COLUMN IF EXISTS org_id"))
    await conn.execute(text("ALTER TABLE devices DROP COLUMN IF EXISTS org_id"))
    await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS fk_users_org_id"))
    await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS org_id"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_organizations_slug_unique"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS slug"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS status"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS plan"))
    await conn.execute(text("ALTER TABLE organizations DROP COLUMN IF EXISTS updated_at"))

