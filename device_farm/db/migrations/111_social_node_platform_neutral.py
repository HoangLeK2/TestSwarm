"""111 — rewrite stored scenarios to platform-neutral node names.

Removes the Facebook-specific step types (fb_*, facebook_session_gate) in favour
of the social_*/platform_* vocabulary, and splits `extract.strategy` into
`entity` + `platform`. No runtime aliases exist, so this migration is what keeps
already-saved scenarios working.

Unlike migration 078 this also rewrites the `nodes` JSONB columns — the visual
editor reads node["type"]/node["config"], which 078 left untouched.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)

# (table, id column, json column, kind) — kind picks the rewrite shape.
_TARGETS = (
    ("scenarios", "id", "steps", "steps"),
    ("scenarios", "id", "nodes", "nodes"),
    ("scenario_versions", "id", "steps", "steps"),
    ("scenario_templates", "id", "steps", "steps"),
    ("scenario_templates", "id", "nodes", "nodes"),
    ("org_scenarios", "id", "body_json", "blob"),
    ("campaigns", "id", "scenario", "blob"),
)


def _rewrite(payload: object, kind: str) -> tuple[object, bool]:
    from services.scenario_migrations.social_node_rename import (
        migrate_graph_nodes,
        migrate_scenario_blob,
        migrate_step_types,
    )

    # Deep copy through JSON so we never mutate the driver's buffer in place.
    data = json.loads(json.dumps(payload))
    if kind == "steps":
        return data, migrate_step_types(data)
    if kind == "nodes":
        return data, migrate_graph_nodes(data)
    return data, migrate_scenario_blob(data)


async def _table_has_column(conn, table: str, column: str) -> bool:
    result = await conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table AND column_name = :column
            """
        ),
        {"table": table, "column": column},
    )
    return result.first() is not None


async def _migrate_json_column(
    conn, *, table: str, id_col: str, json_col: str, kind: str
) -> int:
    if not await _table_has_column(conn, table, json_col):
        return 0

    result = await conn.execute(
        text(f"SELECT {id_col}, {json_col} FROM {table} WHERE {json_col} IS NOT NULL")
    )
    updated = 0
    for row_id, payload in result.fetchall():
        if payload is None:
            continue
        migrated, changed = _rewrite(payload, kind)
        if not changed:
            continue
        await conn.execute(
            text(
                f"UPDATE {table} SET {json_col} = CAST(:payload AS JSONB) "
                f"WHERE {id_col} = :row_id"
            ),
            {"payload": json.dumps(migrated), "row_id": row_id},
        )
        updated += 1
    return updated


async def upgrade(conn) -> None:
    for table, id_col, json_col, kind in _TARGETS:
        count = await _migrate_json_column(
            conn, table=table, id_col=id_col, json_col=json_col, kind=kind
        )
        if count:
            log.info(
                "migration 111: updated %s rows in %s.%s", count, table, json_col
            )


async def downgrade(conn) -> None:
    # One-way: the merged social_select_target cannot be split back without
    # guessing, and no runtime reads the old names any more.
    del conn
