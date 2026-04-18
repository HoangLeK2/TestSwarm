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

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase

from core.config import load_config
from core.env import farm_config_path


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

# Main engine — pooled, used by FastAPI (single event loop).
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    # NOTE: keep pre_ping off for asyncpg stability on some macOS builds.
    # We rely on normal query retry/error handling instead of ping-on-checkout.
    pool_pre_ping=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def activity_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Session factory for Temporal activities (or any code running in a
    separate thread/event loop from the main FastAPI process).

    Uses NullPool so each connection is created fresh in the caller's event
    loop — avoids the "Future attached to a different loop" error that occurs
    when the pooled engine's connections are borrowed across loop boundaries.
    """
    act_engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)
    act_session_factory = async_sessionmaker(
        act_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with act_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await act_engine.dispose()


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
    """Create all tables then run incremental migrations on startup."""
    from db import models  # noqa: F401 — ensure models are registered
    from db.migrations import run_migrations

    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
        await run_migrations(conn)

    # Seed builtin scenario templates (idempotent)
    async with AsyncSessionLocal() as seed_db:
        from db.seeds.scenario_templates import seed_builtin_templates
        await seed_builtin_templates(seed_db)
