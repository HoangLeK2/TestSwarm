"""DF-004: Device tags + group target on campaigns."""
from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS tags VARCHAR(500) DEFAULT ''")
    )
    await conn.execute(
        text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS target_group_id VARCHAR(36) NULL")
    )
