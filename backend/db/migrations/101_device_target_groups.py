"""Persist operator-prepared Facebook Group targets per device."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_org_id ON devices (org_id, id)"
    ))
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS device_target_groups (
            id VARCHAR(36) PRIMARY KEY,
            org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            device_id VARCHAR(36) NOT NULL,
            external_entity_id VARCHAR(36) NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            assigned_by VARCHAR(36) NULL REFERENCES users(id) ON DELETE SET NULL,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_device_target_groups_org_entity
                FOREIGN KEY (org_id, external_entity_id)
                REFERENCES external_entities(org_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_device_target_groups_org_device
                FOREIGN KEY (org_id, device_id)
                REFERENCES devices(org_id, id) ON DELETE CASCADE,
            CONSTRAINT uq_device_target_groups_device_entity
                UNIQUE (org_id, device_id, external_entity_id)
        )
    """))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_target_groups_device "
        "ON device_target_groups (org_id, device_id, position)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_target_groups_entity "
        "ON device_target_groups (org_id, external_entity_id)"
    ))


async def downgrade(conn) -> None:
    await conn.execute(text("DROP TABLE IF EXISTS device_target_groups"))
