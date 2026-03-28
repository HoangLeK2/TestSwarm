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
        # DF-001: Variable System — add variables column to campaigns + scenarios
        await conn.execute(
            text(
                "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS variables JSON DEFAULT '{}'"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS variables JSON DEFAULT '{}'"
            )
        )
        # DF-004: Device tags + group target on campaigns
        await conn.execute(
            text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS tags VARCHAR(500) DEFAULT ''")
        )
        await conn.execute(
            text(
                "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS target_group_id VARCHAR(36) NULL"
            )
        )
        # DF-006: Enrichment columns for crawl_posts
        await conn.execute(
            text("ALTER TABLE crawl_posts ADD COLUMN IF NOT EXISTS post_type VARCHAR(50) NULL")
        )
        await conn.execute(
            text("ALTER TABLE crawl_posts ADD COLUMN IF NOT EXISTS image_desc TEXT NULL")
        )
        await conn.execute(
            text("ALTER TABLE crawl_posts ADD COLUMN IF NOT EXISTS comment_preview TEXT NULL")
        )
        # DF-007: Account & Profile Manager — accounts + device_accounts tables
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id VARCHAR(36) PRIMARY KEY,
                    platform VARCHAR(50) NOT NULL,
                    username VARCHAR(255) NOT NULL,
                    password_encrypted VARCHAR(500),
                    display_name VARCHAR(255) DEFAULT '',
                    status VARCHAR(20) DEFAULT 'active',
                    cooldown_until TIMESTAMPTZ,
                    proxy_id VARCHAR(36),
                    metadata JSON DEFAULT '{}',
                    notes TEXT DEFAULT '',
                    tags VARCHAR(500) DEFAULT '',
                    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    last_used_at TIMESTAMPTZ,
                    total_usage_minutes FLOAT DEFAULT 0,
                    usage_today_minutes FLOAT DEFAULT 0,
                    usage_reset_date DATE,
                    CONSTRAINT uq_accounts_platform_username UNIQUE (platform, username)
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform)"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS device_accounts (
                    id VARCHAR(36) PRIMARY KEY,
                    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                    account_id VARCHAR(36) NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
                    is_primary BOOLEAN DEFAULT FALSE,
                    assigned_at TIMESTAMPTZ DEFAULT NOW(),
                    CONSTRAINT uq_da_device_account UNIQUE (device_id, account_id)
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_da_device ON device_accounts(device_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_da_account ON device_accounts(account_id)"
            )
        )

    # DF-003: seed builtin scenario templates (idempotent)
    async with AsyncSessionLocal() as seed_db:
        from db.seeds.scenario_templates import seed_builtin_templates
        await seed_builtin_templates(seed_db)
