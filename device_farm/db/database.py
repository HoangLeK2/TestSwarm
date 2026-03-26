"""
db/database.py — Async SQLAlchemy engine + session factory.

Usage in FastAPI:
    async with get_db() as db:
        result = await db.execute(...)
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text
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

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


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
    """Create all tables in Postgres on startup (idempotent — safe to call every run)."""
    from db import models  # noqa: F401 — ensure models are registered
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
        # Lightweight compatibility migration for existing databases that
        # already have crawl_jobs without the new campaign_id column.
        await conn.execute(
            text(
                """
                ALTER TABLE crawl_jobs
                ADD COLUMN IF NOT EXISTS campaign_id VARCHAR(36) NULL
                """
            )
        )
        await conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'fk_crawl_jobs_campaign_id'
                    ) THEN
                        ALTER TABLE crawl_jobs
                        ADD CONSTRAINT fk_crawl_jobs_campaign_id
                        FOREIGN KEY (campaign_id)
                        REFERENCES campaigns(id)
                        ON DELETE SET NULL;
                    END IF;
                END
                $$;
                """
            )
        )
