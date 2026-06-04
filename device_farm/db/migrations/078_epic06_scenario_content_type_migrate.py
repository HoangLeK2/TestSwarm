"""078 — Epic 06: migrate legacy scenario/content_type values to platform-qualified codes."""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)


def _migrate_steps_json(raw: object) -> tuple[object, bool]:
    from services.content.legacy_type_map import migrate_content_type_in_steps

    if not isinstance(raw, list):
        return raw, False
    steps = json.loads(json.dumps(raw))
    changed = migrate_content_type_in_steps(steps)
    return steps, changed


def _migrate_scenario_blob(raw: object) -> tuple[object, bool]:
    from services.content.legacy_type_map import migrate_content_type_in_json

    if not isinstance(raw, dict):
        return raw, False
    blob = json.loads(json.dumps(raw))
    changed = migrate_content_type_in_json(blob)
    return blob, changed


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


async def _migrate_json_column(conn, *, table: str, id_col: str, json_col: str) -> int:
    if not await _table_has_column(conn, table, json_col):
        return 0

    result = await conn.execute(text(f"SELECT {id_col}, {json_col} FROM {table}"))
    rows = result.fetchall()
    updated = 0
    for row_id, payload in rows:
        if payload is None:
            continue
        if json_col == "steps":
            migrated, changed = _migrate_steps_json(payload)
        else:
            migrated, changed = _migrate_scenario_blob(payload)
        if not changed:
            continue
        await conn.execute(
            text(f"UPDATE {table} SET {json_col} = CAST(:payload AS JSONB) WHERE {id_col} = :row_id"),
            {"payload": json.dumps(migrated), "row_id": row_id},
        )
        updated += 1
    return updated


async def upgrade(conn) -> None:
    # Stored scenarios (campaign-embedded + version snapshots + templates).
    for table, id_col, json_col in (
        ("scenarios", "id", "steps"),
        ("scenario_versions", "id", "steps"),
        ("scenario_templates", "id", "steps"),
        ("org_scenarios", "id", "body_json"),
    ):
        count = await _migrate_json_column(conn, table=table, id_col=id_col, json_col=json_col)
        if count:
            log.info("migration 078: updated %s rows in %s.%s", count, table, json_col)

    if await _table_has_column(conn, "campaigns", "scenario"):
        result = await conn.execute(text("SELECT id, scenario FROM campaigns WHERE scenario IS NOT NULL"))
        updated = 0
        for campaign_id, scenario in result.fetchall():
            if scenario is None:
                continue
            migrated, changed = _migrate_scenario_blob(scenario)
            if not changed:
                continue
            await conn.execute(
                text("UPDATE campaigns SET scenario = CAST(:payload AS JSONB) WHERE id = :campaign_id"),
                {"payload": json.dumps(migrated), "campaign_id": campaign_id},
            )
            updated += 1
        if updated:
            log.info("migration 078: updated %s legacy campaigns.scenario rows", updated)

    # Content items written before registry gate (best-effort platform-aware remap).
    if await _table_has_column(conn, "content_items", "content_type"):
        content_type_updates = (
            """
            UPDATE content_items
            SET content_type = 'fb_post'
            WHERE content_type IN ('group_post', 'profile_post', 'group_comment')
               OR (content_type = 'post' AND COALESCE(platform, 'facebook') = 'facebook')
            """,
            """
            UPDATE content_items
            SET content_type = 'fb_comment'
            WHERE content_type = 'comment' AND COALESCE(platform, 'facebook') = 'facebook'
            """,
            """
            UPDATE content_items
            SET content_type = 'tiktok_video'
            WHERE content_type IN ('post', 'video') AND platform = 'tiktok'
            """,
            """
            UPDATE content_items
            SET content_type = 'tiktok_comment'
            WHERE content_type = 'comment' AND platform = 'tiktok'
            """,
            """
            UPDATE content_items
            SET content_type = 'ig_media'
            WHERE content_type IN ('post', 'media') AND platform = 'instagram'
            """,
            """
            UPDATE content_items
            SET content_type = 'ig_comment'
            WHERE content_type = 'comment' AND platform = 'instagram'
            """,
            """
            UPDATE content_items
            SET content_type = 'threads_post'
            WHERE content_type IN ('post', 'thread') AND platform = 'threads'
            """,
            """
            UPDATE content_items
            SET content_type = 'threads_comment'
            WHERE content_type = 'comment' AND platform = 'threads'
            """,
        )
        for statement in content_type_updates:
            await conn.execute(text(statement))
