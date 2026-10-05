"""Regression: streaming routes must not exhaust the SQLAlchemy connection pool."""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.deps_streaming import resolve_user_for_streaming
from api.routes.content import router as content_router
from api.routes.executions import router as executions_router
from db.crud.execution import create_execution
from db.database import Base
from db.models.campaign import Campaign
from db.models.content import ContentItem
from services.execution.event_publisher import enqueue_execution_event, process_outbox_batch
from services.execution.event_types import EXECUTION_CREATED
from tenancy.context import set_current_org_id, tenant_context


@pytest.fixture(autouse=True)
def _csv_casbin_enforcer(monkeypatch):
    from api.auth import rbac

    async def _fake_enforcer(user, db, domain=None):
        effective = (domain or rbac.permission_domain(user)).strip() or "global"
        return rbac.build_enforcer_for_user(user, domain=effective)

    monkeypatch.setattr(
        "api.deps_streaming.build_enforcer_for_user_from_db",
        _fake_enforcer,
    )
    monkeypatch.setattr("api.deps.build_enforcer_for_user_from_db", _fake_enforcer)


@pytest_asyncio.fixture
async def tiny_pool_env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)
    for target in (
        "db.database.AsyncSessionLocal",
        "api.deps_streaming.AsyncSessionLocal",
        "api.routes.content.AsyncSessionLocal",
    ):
        monkeypatch.setattr(target, factory)

    yield factory
    await eng.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


def _user(org_id: str = "org-1") -> SimpleNamespace:
    return SimpleNamespace(
        id="u1",
        role="operator",
        org_role="owner",
        is_active=True,
        org_id=org_id,
    )


def _db_override_factory(factory):
    async def _db_override():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _db_override


def _build_executions_app(factory) -> FastAPI:
    app = FastAPI()
    app.include_router(executions_router, prefix="/api")

    async def _user_override() -> SimpleNamespace:
        set_current_org_id("org-1")
        return _user()

    app.dependency_overrides[resolve_user_for_streaming] = _user_override
    app.dependency_overrides[_get_current_user] = _user_override
    app.dependency_overrides[_get_db] = _db_override_factory(factory)
    return app


def _build_content_app(factory) -> FastAPI:
    app = FastAPI()
    app.include_router(content_router, prefix="/api")

    async def _user_override() -> SimpleNamespace:
        set_current_org_id("org-1")
        return _user()

    app.dependency_overrides[resolve_user_for_streaming] = _user_override
    app.dependency_overrides[_get_current_user] = _user_override
    app.dependency_overrides[_get_db] = _db_override_factory(factory)
    return app


async def _seed_execution(factory) -> str:
    async with factory() as db:
        with tenant_context("org-1"):
            db.add(
                Campaign(
                    id="camp-1",
                    name="Campaign camp-1",
                    name_lower="campaign camp-1",
                    user_id="u1",
                    org_id="org-1",
                    created_at=datetime.now(timezone.utc),
                )
            )
            ex = await create_execution(
                db,
                run_type="campaign_device",
                campaign_id="camp-1",
                user_id="u1",
                status="running",
            )
            exec_id = ex.id
        await db.commit()
    return exec_id


async def _seed_content(factory, *, count: int = 3) -> None:
    async with factory() as db:
        with tenant_context("org-1"):
            for i in range(count):
                db.add(
                    ContentItem(
                        id=f"item-{i}",
                        org_id="org-1",
                        collection="default",
                        platform="instagram",
                        content_type="post",
                        body=f"body-{i}",
                        content_hash=f"hash-{i}",
                        user_id="u1",
                    )
                )
        await db.commit()


async def _hold_sse_seconds(exec_id: str, seconds: float, factory) -> None:
    async with AsyncClient(transport=ASGITransport(app=_build_executions_app(factory)), base_url="http://t") as client:
        async with client.stream(
            "GET", f"/api/executions/{exec_id}/events/stream"
        ) as resp:
            assert resp.status_code == 200
            await asyncio.sleep(seconds)


async def _hold_export_seconds(seconds: float, factory) -> None:
    async with AsyncClient(transport=ASGITransport(app=_build_content_app(factory)), base_url="http://t") as client:
        async with client.stream(
            "GET", "/api/content/export/stream", params={"format": "csv"}
        ) as resp:
            assert resp.status_code == 200
            await asyncio.sleep(seconds)


@pytest.mark.asyncio
async def test_execution_sse_does_not_block_catchup_with_tiny_pool(tiny_pool_env):
    factory = tiny_pool_env
    exec_id = await _seed_execution(factory)
    holders = [
        asyncio.create_task(_hold_sse_seconds(exec_id, 2.5, factory)),
        asyncio.create_task(_hold_sse_seconds(exec_id, 2.5, factory)),
    ]
    await asyncio.sleep(0.5)
    async with AsyncClient(
        transport=ASGITransport(app=_build_executions_app(factory)), base_url="http://t"
    ) as client:
        r = await asyncio.wait_for(
            client.get(f"/api/executions/{exec_id}/events"),
            timeout=5.0,
        )
    for task in holders:
        task.cancel()
    await asyncio.gather(*holders, return_exceptions=True)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_execution_events_catchup_after_outbox_publish(tiny_pool_env):
    factory = tiny_pool_env
    exec_id = await _seed_execution(factory)

    async with factory() as db:
        with tenant_context("org-1"):
            from db.crud.execution import get_execution

            ex = await get_execution(db, exec_id)
            await enqueue_execution_event(
                db,
                event_type=EXECUTION_CREATED,
                execution_id=exec_id,
                organization_id="org-1",
                campaign_id="camp-1",
                execution=ex,
            )
        await db.commit()
    async with factory() as db:
        published = await process_outbox_batch(db)
        await db.commit()
    assert published == 1

    async with AsyncClient(
        transport=ASGITransport(app=_build_executions_app(factory)), base_url="http://t"
    ) as client:
        catchup = await asyncio.wait_for(
            client.get(f"/api/executions/{exec_id}/events"),
            timeout=5.0,
        )
        assert catchup.status_code == 200
        assert catchup.json()["items"][0]["event_type"] == EXECUTION_CREATED


@pytest.mark.asyncio
async def test_content_export_does_not_block_list_with_tiny_pool(tiny_pool_env):
    factory = tiny_pool_env
    await _seed_content(factory)
    holders = [
        asyncio.create_task(_hold_export_seconds(2.5, factory)),
        asyncio.create_task(_hold_export_seconds(2.5, factory)),
    ]
    await asyncio.sleep(0.5)
    async with AsyncClient(
        transport=ASGITransport(app=_build_content_app(factory)), base_url="http://t"
    ) as client:
        r = await asyncio.wait_for(
            client.get("/api/content", params={"limit": 10, "offset": 0}),
            timeout=5.0,
        )
    for task in holders:
        task.cancel()
    await asyncio.gather(*holders, return_exceptions=True)
    assert r.status_code == 200
    assert r.json()["total"] >= 3


@pytest.mark.asyncio
async def test_content_csv_export_streams_rows(tiny_pool_env):
    factory = tiny_pool_env
    await _seed_content(factory, count=2)
    app = _build_content_app(factory)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/api/content/export/stream", params={"format": "csv"})
    assert resp.status_code == 200
    text = resp.text
    assert "content_hash" in text.splitlines()[0]
    assert text.count("\n") >= 3
