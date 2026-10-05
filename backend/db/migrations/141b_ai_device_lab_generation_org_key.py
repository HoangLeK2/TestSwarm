"""Add the tenant candidate key required by scenario approval references.

The filename intentionally sorts after migration 141 and before migration 142.
That preserves immutable historical migration checksums while allowing both a
fresh migration-only database and an existing installation to acquire the key.
"""

from __future__ import annotations

from sqlalchemy import text


async def upgrade(conn) -> None:
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conrelid = 'scenario_generation_operations'::regclass
                      AND conname = 'uq_scenario_generation_operations_org_id'
                ) THEN
                    ALTER TABLE scenario_generation_operations
                    ADD CONSTRAINT uq_scenario_generation_operations_org_id
                    UNIQUE (org_id, id);
                END IF;
            END
            $$
            """
        )
    )
