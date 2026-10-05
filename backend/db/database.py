"""
db/database.py — Async SQLAlchemy engine + session factory.

Usage in FastAPI:
    async with get_db() as db:
        result = await db.execute(...)

Usage in Temporal activities (separate thread/loop):
    async with activity_session() as db:
        result = await db.execute(...)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Dict
from urllib.parse import urlsplit

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from db.connection_budget import validate_connection_budget
from tenancy.sqlalchemy import init_tenant_scoping

log = logging.getLogger(__name__)

# None = not initialized yet; True after init_db(); False when init_db() failed.
schema_init_ok: bool | None = None


def _build_url() -> str:
    """Return the dedicated Platform Tester DSN and reject inherited storage.

    The old checkout accepted ``DATABASE_URL`` and YAML/``DB_*`` fallbacks. That
    could silently point this service at a Device Farm database. Requiring one
    project-specific variable keeps API, workers and migrations on the same
    independently named database.
    """
    url = (os.environ.get("ANDROID_PLATFORM_TESTER_DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "Set ANDROID_PLATFORM_TESTER_DATABASE_URL to the project's "
            "independent database; generic DATABASE_URL and DB_* are not fallbacks."
        )

    parsed = urlsplit(url)
    database_name = parsed.path.lstrip("/").split("/", 1)[0].lower()
    if not database_name.startswith("android_platform_tester"):
        raise RuntimeError(
            "ANDROID_PLATFORM_TESTER_DATABASE_URL must select an independent "
            "database named android_platform_tester (an optional suffix is allowed)."
        )

    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if not url.startswith("postgresql+asyncpg://"):
        raise RuntimeError(
            "ANDROID_PLATFORM_TESTER_DATABASE_URL must use PostgreSQL with asyncpg."
        )
    return url


DATABASE_URL = _build_url()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


_connection_budget = validate_connection_budget(os.environ)
if _connection_budget.limit is not None:
    log.info(
        "database connection budget validated: configured=%s reserve=%s limit=%s headroom=%s",
        _connection_budget.configured_demand,
        _connection_budget.reserve,
        _connection_budget.limit,
        _connection_budget.headroom,
    )


# Main engine — pooled, used by FastAPI (single event loop).
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=max(1, _env_int("DB_POOL_SIZE", 12)),
    max_overflow=max(0, _env_int("DB_MAX_OVERFLOW", 3)),
    pool_timeout=max(1, _env_int("DB_POOL_TIMEOUT", 5)),
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "server_settings": {
            "idle_in_transaction_session_timeout": str(
                _env_int("DB_IDLE_TRANSACTION_TIMEOUT_MS", 30_000)
            ),
        },
    },
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Edge ingestion runs on the farm's main event loop but uses an isolated pool so
# a burst of relay batches cannot consume the web/API pool.
edge_ingest_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=max(1, _env_int("EDGE_INGEST_POOL_SIZE", 4)),
    max_overflow=0,
    pool_timeout=max(1, _env_int("EDGE_INGEST_POOL_TIMEOUT", 10)),
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "server_settings": {
            "idle_in_transaction_session_timeout": str(
                _env_int("DB_IDLE_TRANSACTION_TIMEOUT_MS", 30_000)
            ),
        },
    },
)
EdgeIngestSessionLocal = async_sessionmaker(
    edge_ingest_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Install tenant scoping rules once at import time.
init_tenant_scoping()


# ── Per-event-loop engine cache ──────────────────────────────────────────────
# Creating a new engine + dispose on every activity_session() call caused
# connection churn on hot paths (checkpoint per step, loop_state per iter).
# We cache one pooled engine per running event loop so callers share a pool
# scoped to their loop — no cross-loop Future leakage, no per-call churn.
_loop_engines: Dict[int, tuple[AsyncEngine, async_sessionmaker]] = {}
_loop_engines_lock = threading.Lock()


def _engine_for_loop(loop: asyncio.AbstractEventLoop) -> tuple[AsyncEngine, async_sessionmaker]:
    key = id(loop)
    entry = _loop_engines.get(key)
    if entry is not None:
        return entry
    with _loop_engines_lock:
        entry = _loop_engines.get(key)
        if entry is not None:
            return entry
        act_engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=max(1, _env_int("DB_ACTIVITY_POOL_SIZE", 4)),
            max_overflow=max(0, _env_int("DB_ACTIVITY_MAX_OVERFLOW", 0)),
            pool_timeout=max(1, _env_int("DB_ACTIVITY_POOL_TIMEOUT", 10)),
            pool_pre_ping=True,
            pool_recycle=300,
        )
        factory = async_sessionmaker(act_engine, class_=AsyncSession, expire_on_commit=False)
        _loop_engines[key] = (act_engine, factory)
        return _loop_engines[key]


async def dispose_loop_engine() -> None:
    """Call on loop shutdown to release the loop-scoped engine."""
    loop = asyncio.get_running_loop()
    key = id(loop)
    with _loop_engines_lock:
        entry = _loop_engines.pop(key, None)
    if entry is not None:
        try:
            await entry[0].dispose()
        except Exception:
            pass


async def _run_activity_coro(coro):
    try:
        return await coro
    finally:
        await dispose_loop_engine()
        # Redis pools per loop too; leaving this loop's client behind hands the
        # next activity a connection bound to a closed loop.
        try:
            from services.redis_store import dispose_loop_client

            await dispose_loop_client()
        except Exception:
            pass


def run_activity_coro(coro):
    """
    Run an async activity coroutine from sync code and dispose the loop-scoped
    SQLAlchemy engine before asyncio.run() closes the event loop.

    Without this, one-off worker threads that call asyncio.run(activity_session)
    leave pooled asyncpg connections attached to closed event loops, eventually
    exhausting Postgres with "too many clients already".
    """
    return asyncio.run(_run_activity_coro(coro))


def run_activity_coro_blocking(coro, *, timeout: float = 30.0):
    """Run an activity coroutine from sync code, even inside a running loop.

    Fast path: no running loop in this thread -> asyncio.run directly.
    Fallback: offload to a dedicated thread so asyncio.run() is safe.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run_activity_coro(coro)

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(run_activity_coro, coro)
    try:
        return fut.result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


@asynccontextmanager
async def activity_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Session factory for Temporal activities (or any code running in a
    separate thread/event loop from the main FastAPI process).

    Uses a per-event-loop pooled engine so checkpoint/loop-iter hot paths
    reuse connections instead of building/tearing a pool each call.
    """
    loop = asyncio.get_running_loop()
    _, factory = _engine_for_loop(loop)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def edge_ingest_session() -> AsyncGenerator[AsyncSession, None]:
    """Transaction-scoped session backed by the isolated edge-ingest pool."""
    async with EdgeIngestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_edge_ingest_engine() -> None:
    await edge_ingest_engine.dispose()


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database schema and run incremental migrations on startup."""
    global schema_init_ok
    schema_init_ok = None

    from db import models  # noqa: F401 — ensure models are registered
    from db.migrations import run_migrations

    async with engine.begin() as conn:
        if _auto_create_schema_enabled():
            await _ensure_create_all_prerequisites(conn)
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
        else:
            log.info(
                "Skipping SQLAlchemy create_all in production/staging; "
                "schema changes must come from migrations."
            )
        await _ensure_legacy_migration_prerequisites(conn)
        await run_migrations(conn)

    # Seed builtin scenario templates (idempotent)
    async with AsyncSessionLocal() as seed_db:
        from db.superadmin import ensure_superadmin_from_env
        from db.seeds.scenario_templates import seed_builtin_templates

        await ensure_superadmin_from_env(seed_db)
        await seed_builtin_templates(seed_db)
        await seed_db.commit()

    schema_init_ok = True


async def _ensure_legacy_migration_prerequisites(conn) -> None:
    """Bridge removed models that early immutable migrations still reference.

    Migrations 015, 016 and 021 index/constrain ``content_exports``; migration
    031 removes it after direct streaming replaced export jobs. Fresh installs
    no longer create the model before migrations, so provide only the columns
    those historical files need. Migration 031 removes the compatibility table
    in the same transaction, leaving no deprecated table in the final schema.
    """
    migration_table_exists = await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).has_table("schema_migrations")
    )
    if migration_table_exists:
        migration_031_applied = await conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM schema_migrations
                    WHERE filename = '031_drop_content_exports.py'
                )
                """
            )
        )
        if bool(migration_031_applied.scalar()):
            return

    await conn.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS content_exports (
            user_id UUID,
            status VARCHAR(32) NOT NULL DEFAULT 'pending'
        )
        """
    )


async def _ensure_create_all_prerequisites(conn) -> None:
    """Repair parent keys needed when create_all runs against a legacy schema."""
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))

    devices_exists = await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).has_table("devices")
    )
    if devices_exists:
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_org_id "
            "ON devices (org_id, id)"
        ))


def _auto_create_schema_enabled() -> bool:
    raw = os.environ.get("FARM_DB_AUTO_CREATE_SCHEMA")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    env_name = os.environ.get("DEVICE_FARM_ENV", "").strip().lower()
    return env_name not in {"prod", "production", "staging"}
