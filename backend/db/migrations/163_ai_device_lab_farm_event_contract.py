"""Version and bind farm events to one execution without rewriting migration 154."""

from __future__ import annotations

from sqlalchemy import text


def _dialect(conn) -> str:
    for target in (conn, getattr(conn, "_conn", None), getattr(conn, "engine", None)):
        name = getattr(getattr(target, "dialect", None), "name", None)
        if name:
            return str(name)
    return ""


async def _existing_columns(conn, dialect: str) -> set[str]:
    if dialect.startswith("sqlite"):
        rows = (await conn.execute(text("PRAGMA table_info(farm_event_inbox)"))).all()
        return {str(row[1]) for row in rows}
    rows = (
        await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'farm_event_inbox'"
            )
        )
    ).all()
    return {str(row[0]) for row in rows}


async def upgrade(conn) -> None:
    dialect = _dialect(conn)
    present = await _existing_columns(conn, dialect)
    for column, column_type in (
        ("schema_version", "VARCHAR(32)"),
        ("execution_id", "VARCHAR(36)"),
    ):
        if column not in present:
            await conn.execute(
                text(f"ALTER TABLE farm_event_inbox ADD COLUMN {column} {column_type}")
            )
    if dialect.startswith("postgres"):
        await conn.execute(text("DROP TRIGGER IF EXISTS farm_event_inbox_immutable ON farm_event_inbox"))
        execution_expr = "job.payload->>'execution_id'"
    else:
        execution_expr = "json_extract(job.payload, '$.execution_id')"
    await conn.execute(
        text(
            f"""
            UPDATE farm_event_inbox AS event
            SET schema_version = COALESCE(event.schema_version, 'adl-farm-event-v1'),
                execution_id = COALESCE(event.execution_id, {execution_expr})
            FROM farm_jobs AS job
            WHERE event.job_id = job.id
              AND (event.schema_version IS NULL OR event.execution_id IS NULL)
            """
        )
    )
    if dialect.startswith("postgres"):
        await conn.execute(text("ALTER TABLE farm_event_inbox ALTER COLUMN schema_version SET NOT NULL"))
        await conn.execute(text("ALTER TABLE farm_event_inbox ALTER COLUMN execution_id SET NOT NULL"))
        await conn.execute(
            text(
                """
                CREATE TRIGGER farm_event_inbox_immutable
                BEFORE UPDATE OR DELETE ON farm_event_inbox
                FOR EACH ROW EXECUTE FUNCTION reject_ai_lab_immutable_update()
                """
            )
        )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_farm_event_execution "
            "ON farm_event_inbox(org_id, execution_id, occurred_at)"
        )
    )
