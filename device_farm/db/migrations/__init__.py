"""
db/migrations — incremental schema migrations.

Each file is named NNN_description.py and exposes:
    async def upgrade(conn) -> None

The runner applies them in filename order. All migrations must be idempotent
(use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent


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
    """Run all migration files in order."""
    compat_conn = _CompatConn(conn)
    files = sorted(
        f for f in _MIGRATIONS_DIR.glob("[0-9]*.py")
        if f.name != "__init__.py"
    )
    for f in files:
        module_name = f"db.migrations.{f.stem}"
        try:
            mod = importlib.import_module(module_name)
            await mod.upgrade(compat_conn)
            log.debug("migration applied: %s", f.name)
        except Exception as exc:
            log.error("migration failed: %s — %s", f.name, exc)
            raise
