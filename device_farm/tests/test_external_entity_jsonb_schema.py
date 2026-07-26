import importlib

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from db.models.external_entity import (
    ExecutionEntityAssignment,
    ExternalEntity,
    ExternalEntityDiscovery,
    ExternalEntityObservation,
)


def test_external_entity_json_columns_use_jsonb_on_postgresql() -> None:
    columns = (
        ExternalEntity.current_attributes,
        ExternalEntity.current_metrics,
        ExternalEntityObservation.attributes,
        ExternalEntityObservation.metrics,
        ExternalEntityObservation.raw_data,
        ExternalEntityDiscovery.context,
        ExecutionEntityAssignment.snapshot,
    )
    dialect = postgresql.dialect()

    assert all(
        isinstance(column.type.dialect_impl(dialect), JSONB)
        for column in columns
    )


@pytest.mark.asyncio
async def test_jsonb_migration_converts_every_external_entity_document_column() -> None:
    migration = importlib.import_module(
        "db.migrations.093_external_entity_jsonb"
    )

    class _Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement) -> None:
            self.statements.append(str(statement))

    conn = _Connection()
    await migration.upgrade(conn)
    sql = "\n".join(conn.statements)
    normalized_sql = " ".join(sql.split())

    assert "udt_name = 'json'" in sql
    for table, column in (
        ("external_entities", "current_attributes"),
        ("external_entities", "current_metrics"),
        ("external_entity_observations", "attributes"),
        ("external_entity_observations", "metrics"),
        ("external_entity_observations", "raw_data"),
        ("external_entity_discoveries", "context"),
        ("execution_entity_assignments", "snapshot"),
    ):
        assert (
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE JSONB "
            f"USING {column}::jsonb"
        ) in normalized_sql


@pytest.mark.asyncio
async def test_group_locator_migration_backfills_only_missing_facebook_groups() -> None:
    migration = importlib.import_module(
        "db.migrations.094_external_entity_group_locators"
    )

    class _Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement) -> None:
            self.statements.append(str(statement))

    conn = _Connection()
    await migration.upgrade(conn)
    sql = " ".join("\n".join(conn.statements).split())

    assert "WHERE platform = 'facebook'" in sql
    assert "AND entity_type = 'group'" in sql
    assert "? 'locator'" in sql
    assert "'by', 'descriptionStartsWith'" in sql
    assert "'by', 'descriptionContains'" in sql
    assert "'value', display_name || ','" in sql
