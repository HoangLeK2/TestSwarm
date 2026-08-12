"""Allow the same target to be assigned to different devices in one dispatch."""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            "ALTER TABLE execution_entity_assignments "
            "DROP CONSTRAINT IF EXISTS uq_execution_entity_assignments_dispatch_entity"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_execution_entity_assignments_dispatch_device_entity "
            "ON execution_entity_assignments "
            "(org_id, dispatch_id, device_id, external_entity_id)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_device_target_groups_frontier "
            "ON device_target_groups (org_id, position, device_id, id)"
        )
    )


async def downgrade(conn) -> None:
    await conn.execute(
        text("DROP INDEX IF EXISTS idx_device_target_groups_frontier")
    )
    await conn.execute(
        text(
            "DROP INDEX IF EXISTS "
            "uq_execution_entity_assignments_dispatch_device_entity"
        )
    )
    await conn.execute(
        text(
            "ALTER TABLE execution_entity_assignments "
            "ADD CONSTRAINT uq_execution_entity_assignments_dispatch_entity "
            "UNIQUE (org_id, dispatch_id, external_entity_id)"
        )
    )
