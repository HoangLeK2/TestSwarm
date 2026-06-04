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
import logging
import os
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Dict

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from core.config import load_config
from core.env import farm_config_path
from tenancy.sqlalchemy import init_tenant_scoping

log = logging.getLogger(__name__)

# None = not initialized yet; True after init_db(); False when init_db() failed.
schema_init_ok: bool | None = None


def _build_url() -> str:
    cfg = load_config(farm_config_path()).database
    if cfg.url:
        url = cfg.url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    # Build directly from YAML config.
    host = cfg.host
    port = str(cfg.port)
    name = cfg.name
    user = cfg.user
    password = cfg.password
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


DATABASE_URL = _build_url()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


# Main engine — pooled, used by FastAPI (single event loop).
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=max(1, _env_int("DB_POOL_SIZE", 5)),
    max_overflow=max(0, _env_int("DB_MAX_OVERFLOW", 5)),
    pool_timeout=max(1, _env_int("DB_POOL_TIMEOUT", 10)),
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
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
            pool_size=max(1, _env_int("DB_ACTIVITY_POOL_SIZE", 2)),
            max_overflow=max(0, _env_int("DB_ACTIVITY_MAX_OVERFLOW", 2)),
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


def run_activity_coro(coro):
    """
    Run an async activity coroutine from sync code and dispose the loop-scoped
    SQLAlchemy engine before asyncio.run() closes the event loop.

    Without this, one-off worker threads that call asyncio.run(activity_session)
    leave pooled asyncpg connections attached to closed event loops, eventually
    exhausting Postgres with "too many clients already".
    """
    return asyncio.run(_run_activity_coro(coro))


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
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
        else:
            log.info(
                "Skipping SQLAlchemy create_all in production/staging; "
                "schema changes must come from migrations."
            )
        await run_migrations(conn)

    # Seed builtin scenario templates (idempotent)
    async with AsyncSessionLocal() as seed_db:
        from db.superadmin import ensure_superadmin_from_env
        from db.seeds.scenario_templates import seed_builtin_templates

        await ensure_superadmin_from_env(seed_db)
        await seed_builtin_templates(seed_db)
        await seed_db.commit()

    schema_init_ok = True


def _auto_create_schema_enabled() -> bool:
    raw = os.environ.get("FARM_DB_AUTO_CREATE_SCHEMA")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    env_name = os.environ.get("DEVICE_FARM_ENV", "").strip().lower()
    return env_name not in {"prod", "production", "staging"}
