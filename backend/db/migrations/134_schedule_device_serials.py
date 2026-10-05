"""Schedule can target explicit device serials instead of a device group."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE schedules ADD COLUMN IF NOT EXISTS "
            "device_serials JSON DEFAULT '[]'"
        )
    )
