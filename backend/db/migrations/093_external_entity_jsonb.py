"""093 — align external-entity document columns with JSONB writer semantics."""
from __future__ import annotations

from sqlalchemy import text


_JSON_COLUMNS = (
    ("external_entities", "current_attributes"),
    ("external_entities", "current_metrics"),
    ("external_entity_observations", "attributes"),
    ("external_entity_observations", "metrics"),
    ("external_entity_observations", "raw_data"),
    ("external_entity_discoveries", "context"),
    ("execution_entity_assignments", "snapshot"),
)


async def upgrade(conn) -> None:
    for table, column in _JSON_COLUMNS:
        await conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = '{table}'
                          AND column_name = '{column}'
                          AND udt_name = 'json'
                    ) THEN
                        ALTER TABLE {table}
                        ALTER COLUMN {column} TYPE JSONB
                        USING {column}::jsonb;
                    END IF;
                END
                $$;
                """
            )
        )
