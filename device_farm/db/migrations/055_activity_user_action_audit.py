"""055 — Extend activity_log for user action audit trail."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS org_id VARCHAR(36)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS method VARCHAR(10)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS path VARCHAR(255)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS route_template VARCHAR(255)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS status_code INTEGER"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS request_id VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS ip_address VARCHAR(64)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS user_agent VARCHAR(255)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS outcome VARCHAR(20)"))
    await conn.execute(text("ALTER TABLE activity_log ADD COLUMN IF NOT EXISTS duration_ms INTEGER"))
    await conn.execute(text(
        "ALTER TABLE activity_log DROP CONSTRAINT IF EXISTS activity_log_user_id_fkey"
    ))
    await conn.execute(text(
        "ALTER TABLE activity_log ADD CONSTRAINT activity_log_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL"
    ))

    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_org_created "
        "ON activity_log (org_id, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_org_action_created "
        "ON activity_log (org_id, action, created_at DESC)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_route_template "
        "ON activity_log (route_template)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_request_id "
        "ON activity_log (request_id)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_activity_outcome "
        "ON activity_log (outcome)"
    ))


async def downgrade(conn) -> None:
    await conn.execute(text(
        "ALTER TABLE activity_log DROP CONSTRAINT IF EXISTS activity_log_user_id_fkey"
    ))
    await conn.execute(text(
        "ALTER TABLE activity_log ADD CONSTRAINT activity_log_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
    ))
    await conn.execute(text("DROP INDEX IF EXISTS idx_activity_outcome"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_activity_request_id"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_activity_route_template"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_activity_org_action_created"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_activity_org_created"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS duration_ms"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS outcome"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS user_agent"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS ip_address"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS request_id"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS status_code"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS route_template"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS path"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS method"))
    await conn.execute(text("ALTER TABLE activity_log DROP COLUMN IF EXISTS org_id"))
