"""Per-device preference: auto relay/scrcpy stream (grid + relay online)."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE devices ADD COLUMN IF NOT EXISTS "
            "relay_scrcpy_enabled BOOLEAN NOT NULL DEFAULT true"
        )
    )
