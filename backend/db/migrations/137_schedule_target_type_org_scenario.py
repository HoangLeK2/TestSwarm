"""Allow schedule target_type to include org_scenario."""
from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            ALTER TABLE schedules
            DROP CONSTRAINT IF EXISTS check_schedule_target_type
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE schedules
            ADD CONSTRAINT check_schedule_target_type
            CHECK (target_type IN ('campaign', 'template', 'org_scenario', 'fleet'))
            """
        )
    )
