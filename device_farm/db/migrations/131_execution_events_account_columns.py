"""Make execution_events answerable by account.

execution_events is the only place that records every step at every depth:
_execute_child_steps re-enters run() at depth+1 inside the same workflow
(workflows.py:1664) and buffers events for all depths, while
persist_step_checkpoint only ever runs at depth 0. So execution_steps holds the
top-level steps and execution_events holds the whole tree.

The identity that makes those events useful — which account, which phone, and
where in the scenario tree — was written only inside the JSON payload under
`trace`. Nothing could index it, so "what did this account do before it was
banned" had no query. These three columns lift it out, and the two indexes make
the question cheap.

Nullable with no default: on PostgreSQL 11+ that is a catalog-only ALTER, no
table rewrite. Rows written before this migration keep NULL where the payload
had nothing to give.
"""

from __future__ import annotations

from sqlalchemy import text

# Backfill in id ranges rather than one statement: execution_events is the
# outbox, written to continuously, and a single UPDATE over the whole table
# would hold row locks for its entire duration.
_BATCH = 5000


_COLUMNS = (
    ("account_id", "VARCHAR(36)"),
    ("device_serial", "VARCHAR(128)"),
    ("step_path", "VARCHAR(512)"),
)


def _dialect(conn) -> str:
    """Dialect name through whichever wrapper the migration runner passed."""
    for target in (conn, getattr(conn, "_conn", None), getattr(conn, "engine", None)):
        dialect = getattr(target, "dialect", None)
        name = getattr(dialect, "name", None)
        if name:
            return str(name)
    return ""


async def _existing_columns(conn, dialect: str) -> set[str]:
    if dialect.startswith("sqlite"):
        rows = (await conn.execute(text("PRAGMA table_info(execution_events)"))).all()
        return {str(row[1]) for row in rows}
    rows = (
        await conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'execution_events'"
            )
        )
    ).all()
    return {str(row[0]) for row in rows}


async def upgrade(conn) -> None:
    dialect = _dialect(conn)
    # SQLite has no ADD COLUMN IF NOT EXISTS, and the test suite runs migrations
    # against it. Ask what is already there instead of relying on syntax only
    # one dialect has.
    present = await _existing_columns(conn, dialect)
    for column, column_type in _COLUMNS:
        if column not in present:
            await conn.execute(
                text(f"ALTER TABLE execution_events ADD COLUMN {column} {column_type}")
            )

    if dialect.startswith("postgres"):
        await _backfill_postgres(conn)

    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_execution_events_org_account_time "
            "ON execution_events (org_id, account_id, occurred_at)"
        )
    )
    await conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_execution_events_exec_path "
            "ON execution_events (execution_id, step_path)"
        )
    )


async def _backfill_postgres(conn) -> None:
    bounds = (
        await conn.execute(text("SELECT MIN(id), MAX(id) FROM execution_events"))
    ).first()
    if not bounds or bounds[0] is None:
        return
    lo, hi = int(bounds[0]), int(bounds[1])
    # json -> jsonb per row; the column is `json`, which has no -> operator
    # chain that reads as cleanly, and the cast is cheap next to the write.
    statement = text(
        """
        UPDATE execution_events SET
            account_id    = NULLIF(payload::jsonb -> 'trace' ->> 'account_id', ''),
            device_serial = NULLIF(payload::jsonb -> 'trace' ->> 'device_serial', ''),
            step_path     = NULLIF(payload::jsonb -> 'trace' ->> 'step_path', '')
        WHERE id >= :lo AND id < :hi
          AND account_id IS NULL AND device_serial IS NULL AND step_path IS NULL
        """
    )
    start = lo
    while start <= hi:
        await conn.execute(statement, {"lo": start, "hi": start + _BATCH})
        start += _BATCH


async def downgrade(conn) -> None:
    await conn.execute(text("DROP INDEX IF EXISTS idx_execution_events_exec_path"))
    await conn.execute(text("DROP INDEX IF EXISTS idx_execution_events_org_account_time"))
    for column in ("step_path", "device_serial", "account_id"):
        await conn.execute(
            text(f"ALTER TABLE execution_events DROP COLUMN IF EXISTS {column}")
        )
