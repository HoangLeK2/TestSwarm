from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(text("""
        ALTER TABLE devices
        ADD COLUMN IF NOT EXISTS adb_serial VARCHAR(128)
    """))
    await conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_devices_adb_serial
        ON devices (adb_serial)
    """))
