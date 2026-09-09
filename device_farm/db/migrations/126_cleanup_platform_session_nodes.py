"""126 — remove user-facing platform session guard nodes from saved flows.

Normal scenarios should express login/session dependency as metadata, not as
visible ``platform_session_gate`` + ``if PLATFORM_SESSION_READY`` nodes. Login
scenarios remain authored flows and keep their explicit session/login guards.

This is a forward-only data migration. It is intentionally idempotent so it can
run after the manual cleanup script without changing already-clean rows.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

log = logging.getLogger(__name__)

_REQUIREMENT_TAG_PREFIX = "requires-platform-session:"


def _json_copy(payload: object) -> object:
    return json.loads(json.dumps(payload))


def _requirement_tag_present(tags: str) -> bool:
    return any(
        token.strip().startswith(_REQUIREMENT_TAG_PREFIX)
        for token in str(tags or "").split(",")
    )


def _strip_requirement_tag(tags: str) -> tuple[str, bool]:
    tokens = [token.strip() for token in str(tags or "").split(",") if token.strip()]
    kept = [token for token in tokens if not token.startswith(_REQUIREMENT_TAG_PREFIX)]
    return ",".join(kept), kept != tokens


def _graph_has_session_nodes(nodes: object) -> bool:
    from services.scenario_migrations.platform_session_cleanup import (
        SESSION_GATE_TYPE,
        SESSION_READY_VARIABLE,
    )

    if not isinstance(nodes, list):
        return False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("type") == SESSION_GATE_TYPE:
            return True
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if node.get("type") == "if_variable" and config.get("name") == SESSION_READY_VARIABLE:
            return True
    return False


def _body_steps(body: dict[str, Any]) -> list[dict[str, Any]]:
    steps = body.get("steps")
    return steps if isinstance(steps, list) else []


def _cleanup_body_payload(
    payload: object,
    *,
    name: str = "",
    tags: str = "",
) -> tuple[dict[str, Any], str, bool]:
    from services.scenario_migrations.platform_session_cleanup import (
        cleanup_platform_session_body,
    )

    if not isinstance(payload, dict):
        return {}, "unchanged", False
    result = cleanup_platform_session_body(
        _json_copy(payload),
        name=name,
        tags=tags,
    )
    return result.body, result.classification, result.changed


def _cleanup_steps_payload(
    payload: object,
    *,
    name: str = "",
    tags: str = "",
) -> tuple[list[dict[str, Any]], str, int, int]:
    from services.scenario_migrations.platform_session_cleanup import (
        cleanup_platform_session_body,
    )

    steps = payload if isinstance(payload, list) else []
    result = cleanup_platform_session_body(
        {"steps": _json_copy(steps)},
        name=name,
        tags=tags,
    )
    return (
        _body_steps(result.body),
        result.classification,
        result.removed_gate_count,
        result.removed_ready_condition_count,
    )


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


async def _table_has_columns(conn, table: str, columns: tuple[str, ...]) -> bool:
    for column in columns:
        if not await _table_has_column(conn, table, column):
            return False
    return True


async def _update_json_column(
    conn,
    *,
    table: str,
    id_col: str,
    json_col: str,
    row_id: object,
    payload: object,
) -> None:
    await conn.execute(
        text(
            f"UPDATE {table} SET {json_col} = CAST(:payload AS JSONB) "
            f"WHERE {id_col} = :row_id"
        ),
        {"payload": json.dumps(payload), "row_id": row_id},
    )


async def _migrate_graph_table(
    conn,
    *,
    table: str,
    name_sql: str,
    where_sql: str = "",
) -> int:
    from common.graph_compiler import steps_to_graph

    if not await _table_has_columns(conn, table, ("id", "steps", "nodes", "edges")):
        return 0

    where_clause = f"WHERE {where_sql}" if where_sql else ""
    result = await conn.execute(
        text(f"SELECT id, {name_sql} AS flow_name, steps, nodes FROM {table} {where_clause}")
    )
    updated = 0
    for row in result.fetchall():
        if row.steps is None:
            continue
        new_steps, _classification, removed_gate_count, removed_ready_count = (
            _cleanup_steps_payload(row.steps, name=row.flow_name or "")
        )
        graph_dirty = _graph_has_session_nodes(row.nodes)
        if not (removed_gate_count or removed_ready_count or graph_dirty):
            continue
        nodes, edges = steps_to_graph(new_steps)
        await conn.execute(
            text(
                f"""
                UPDATE {table}
                SET steps = CAST(:steps AS JSONB),
                    nodes = CAST(:nodes AS JSONB),
                    edges = CAST(:edges AS JSONB)
                WHERE id = :row_id
                """
            ),
            {
                "steps": json.dumps(new_steps),
                "nodes": json.dumps(nodes),
                "edges": json.dumps(edges),
                "row_id": row.id,
            },
        )
        updated += 1
    return updated


async def _migrate_scenario_versions(conn) -> int:
    from common.graph_compiler import steps_to_graph

    if not await _table_has_columns(
        conn,
        "scenario_versions",
        ("id", "scenario_id", "steps", "nodes", "edges"),
    ):
        return 0

    result = await conn.execute(
        text(
            """
            SELECT sv.id, COALESCE(s.name, '') AS flow_name, sv.steps, sv.nodes
            FROM scenario_versions sv
            LEFT JOIN scenarios s ON s.id = sv.scenario_id
            WHERE sv.steps IS NOT NULL
            """
        )
    )
    updated = 0
    for row in result.fetchall():
        new_steps, _classification, removed_gate_count, removed_ready_count = (
            _cleanup_steps_payload(row.steps, name=row.flow_name or "")
        )
        graph_dirty = _graph_has_session_nodes(row.nodes)
        if not (removed_gate_count or removed_ready_count or graph_dirty):
            continue
        nodes, edges = steps_to_graph(new_steps)
        await conn.execute(
            text(
                """
                UPDATE scenario_versions
                SET steps = CAST(:steps AS JSONB),
                    nodes = CAST(:nodes AS JSONB),
                    edges = CAST(:edges AS JSONB)
                WHERE id = :row_id
                """
            ),
            {
                "steps": json.dumps(new_steps),
                "nodes": json.dumps(nodes),
                "edges": json.dumps(edges),
                "row_id": row.id,
            },
        )
        updated += 1
    return updated


async def _migrate_templates(conn) -> int:
    from common.graph_compiler import steps_to_graph

    if not await _table_has_columns(
        conn,
        "scenario_templates",
        ("id", "name", "tags", "steps", "nodes", "edges"),
    ):
        return 0

    result = await conn.execute(
        text(
            """
            SELECT id, name, tags, steps, nodes
            FROM scenario_templates
            WHERE steps IS NOT NULL
            """
        )
    )
    updated = 0
    for row in result.fetchall():
        existing_tags = row.tags or ""
        new_steps, classification, removed_gate_count, removed_ready_count = (
            _cleanup_steps_payload(
                row.steps,
                name=row.name or "",
                tags=existing_tags,
            )
        )
        if classification == "auth_required_rewrite":
            new_tags = existing_tags
            tag_changed = False
            if not _requirement_tag_present(existing_tags):
                new_tags = ",".join(
                    token
                    for token in (existing_tags, "requires-platform-session:facebook")
                    if token
                )
                tag_changed = True
        else:
            new_tags, tag_changed = _strip_requirement_tag(existing_tags)

        graph_dirty = _graph_has_session_nodes(row.nodes)
        if not (removed_gate_count or removed_ready_count or graph_dirty or tag_changed):
            continue
        nodes, edges = steps_to_graph(new_steps)
        await conn.execute(
            text(
                """
                UPDATE scenario_templates
                SET steps = CAST(:steps AS JSONB),
                    nodes = CAST(:nodes AS JSONB),
                    edges = CAST(:edges AS JSONB),
                    tags = :tags
                WHERE id = :row_id
                """
            ),
            {
                "steps": json.dumps(new_steps),
                "nodes": json.dumps(nodes),
                "edges": json.dumps(edges),
                "tags": new_tags,
                "row_id": row.id,
            },
        )
        updated += 1
    return updated


async def _migrate_org_scenarios(conn) -> int:
    if not await _table_has_columns(
        conn,
        "org_scenarios",
        ("id", "name", "scenario_version", "body_json"),
    ):
        return 0

    tag_rows = []
    if await _table_has_columns(conn, "org_scenario_tags", ("org_scenario_id", "tag")):
        tag_rows = (
            await conn.execute(
                text("SELECT org_scenario_id, tag FROM org_scenario_tags")
            )
        ).fetchall()
    tags_by_scenario: dict[str, list[str]] = {}
    for row in tag_rows:
        tags_by_scenario.setdefault(str(row.org_scenario_id), []).append(row.tag)

    result = await conn.execute(
        text(
            """
            SELECT id, name, scenario_version, body_json
            FROM org_scenarios
            WHERE deleted_at IS NULL AND body_json IS NOT NULL
            """
        )
    )
    updated = 0
    for row in result.fetchall():
        body, _classification, body_changed = _cleanup_body_payload(
            row.body_json,
            name=row.name or "",
            tags=",".join(tags_by_scenario.get(str(row.id), [])),
        )
        if not body_changed:
            continue
        await conn.execute(
            text(
                """
                UPDATE org_scenarios
                SET body_json = CAST(:body_json AS JSONB),
                    scenario_version = :scenario_version,
                    updated_at = NOW(),
                    last_validation_summary = NULL,
                    last_validated_at = NULL
                WHERE id = :row_id
                """
            ),
            {
                "body_json": json.dumps(body),
                "scenario_version": int(row.scenario_version or 1) + 1,
                "row_id": row.id,
            },
        )
        updated += 1
    return updated


async def _migrate_campaign_blobs(conn) -> int:
    if not await _table_has_columns(conn, "campaigns", ("id", "name", "scenario")):
        return 0

    result = await conn.execute(
        text(
            """
            SELECT id, name, scenario
            FROM campaigns
            WHERE scenario IS NOT NULL
            """
        )
    )
    updated = 0
    for row in result.fetchall():
        body, _classification, body_changed = _cleanup_body_payload(
            row.scenario,
            name=row.name or "",
        )
        if not body_changed:
            continue
        await _update_json_column(
            conn,
            table="campaigns",
            id_col="id",
            json_col="scenario",
            row_id=row.id,
            payload=body,
        )
        updated += 1
    return updated


async def upgrade(conn) -> None:
    counts = {
        "scenario_templates": await _migrate_templates(conn),
        "org_scenarios": await _migrate_org_scenarios(conn),
        "scenarios": await _migrate_graph_table(
            conn,
            table="scenarios",
            name_sql="name",
        ),
        "scenario_versions": await _migrate_scenario_versions(conn),
        "campaigns": await _migrate_campaign_blobs(conn),
    }
    for table, count in counts.items():
        if count:
            log.info("migration 126: updated %s rows in %s", count, table)


async def downgrade(conn) -> None:
    # One-way data cleanup: removed visual guard nodes cannot be reconstructed
    # without guessing original branch structure.
    del conn
