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

log = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).parent


async def run_migrations(conn) -> None:
    """Run all migration files in order."""
    files = sorted(
        f for f in _MIGRATIONS_DIR.glob("[0-9]*.py")
        if f.name != "__init__.py"
    )
    for f in files:
        module_name = f"db.migrations.{f.stem}"
        try:
            mod = importlib.import_module(module_name)
            await mod.upgrade(conn)
            log.debug("migration applied: %s", f.name)
        except Exception as exc:
            log.error("migration failed: %s — %s", f.name, exc)
            raise
