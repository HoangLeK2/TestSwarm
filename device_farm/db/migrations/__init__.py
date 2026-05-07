"""
db/migrations — incremental schema migrations.

Each file is named NNN_description.py and exposes:
    async def upgrade(conn) -> None

The runner applies them in filename order. All migrations must be idempotent
(use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
from __future__ import annotations

import hashlib
import importlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

log = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent
_MIGRATION_TABLE = "schema_migrations"


class _CompatConn:
    """Compatibility adapter for legacy migrations.

    Older migrations call `conn.execute(<raw_sql_string>)`, which is no longer
    executable in SQLAlchemy 2.x async connections. This adapter keeps both
    styles working:
      - ClauseElement / TextClause -> conn.execute(...)
      - raw SQL string            -> conn.exec_driver_sql(...)
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def execute(self, statement: Any, *args: Any, **kwargs: Any):
        if isinstance(statement, str):
            return await self._conn.exec_driver_sql(statement, *args, **kwargs)
        return await self._conn.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


async def run_migrations(conn) -> None:
    """Run unapplied migration files in order.

    Production safety hinges on migration state being explicit. Earlier code
    reran every idempotent migration on every startup, which made it hard to
    distinguish a clean deploy from a half-applied migration and allowed edited
    historical migrations to slip through silently. The schema_migrations table
    records the exact file checksum that was applied and fails fast if an
    already-applied file changes.
    """
    compat_conn = _CompatConn(conn)
    await _ensure_migration_table(compat_conn)
    applied = await _load_applied_migrations(compat_conn)
    files = sorted(
        f for f in _MIGRATIONS_DIR.glob("[0-9]*.py")
        if f.name != "__init__.py"
    )
    for f in files:
        checksum = _checksum(f)
        applied_checksum = applied.get(f.name)
        if applied_checksum is not None:
            if applied_checksum != checksum:
                raise RuntimeError(
                    f"Applied migration {f.name} checksum mismatch. "
                    "Do not edit historical migrations after production apply; "
                    "create a new migration instead."
                )
            log.debug("migration skipped: %s", f.name)
            continue

        module_name = f"db.migrations.{f.stem}"
        try:
            mod = importlib.import_module(module_name)
            await mod.upgrade(compat_conn)
            await _record_applied_migration(compat_conn, f.name, checksum)
            applied[f.name] = checksum
            log.info("migration applied: %s", f.name)
        except Exception as exc:
            log.error("migration failed: %s — %s", f.name, exc)
            raise


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _ensure_migration_table(conn: _CompatConn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename   VARCHAR(255) PRIMARY KEY,
            checksum   CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


async def _load_applied_migrations(conn: _CompatConn) -> dict[str, str]:
    result = await conn.execute(
        f"SELECT filename, checksum FROM {_MIGRATION_TABLE};"
    )
    return {str(row[0]): str(row[1]) for row in result.fetchall()}


async def _record_applied_migration(
    conn: _CompatConn,
    filename: str,
    checksum: str,
) -> None:
    await conn.execute(
        text(f"""
        INSERT INTO {_MIGRATION_TABLE} (filename, checksum)
        VALUES (:filename, :checksum)
        ON CONFLICT (filename) DO UPDATE
        SET checksum = EXCLUDED.checksum,
            applied_at = NOW();
        """),
        {"filename": filename, "checksum": checksum},
    )
