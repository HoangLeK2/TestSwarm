"""DF-T-04-013 — execution event stream (outbox, SSE, catch-up)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.executions import router as executions_router
from db.crud.execution import create_execution
from db.database import Base
from db.models.campaign import Campaign
from services.execution.activity_events import emit_step_finished, emit_step_started
from services.execution.event_bus import get_execution_event_bus
from services.execution.event_publisher import enqueue_execution_event, process_outbox_batch
from services.execution.event_types import (
    EXECUTION_COMPLETED,
    EXECUTION_CREATED,
    STEP_COMPLETED,
    STEP_RETRIED,
    STEP_STARTED,
)
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
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _build_app(session_factory, user_id: str = "u1", org_id: str = "org-1") -> FastAPI:
    app = FastAPI()
    app.include_router(executions_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    async def _user_override():
        set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            role="operator",
            org_role="owner",
            is_active=True,
            org_id=org_id,
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


async def _seed_campaign_execution(session_factory) -> str:
    async with session_factory() as db:
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


@pytest.mark.asyncio
async def test_enqueue_and_outbox_publish(session_factory):
    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
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

    bus = get_execution_event_bus()
    received: list[dict] = []

    async def collect():
        async for envelope in bus.subscribe(exec_id):
            received.append(envelope)
            break

    import asyncio

    collector = asyncio.create_task(collect())
    await asyncio.sleep(0.05)

    async with session_factory() as db:
        published = await process_outbox_batch(db)
        await db.commit()
    assert published == 1
    await asyncio.wait_for(collector, timeout=2.0)
    assert received[0]["event_type"] == EXECUTION_CREATED


@pytest.mark.asyncio
async def test_catch_up_since_event_id(session_factory):
    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            from db.crud.execution import get_execution

            ex = await get_execution(db, exec_id)
            e1 = await enqueue_execution_event(
                db,
                event_type=EXECUTION_CREATED,
                execution_id=exec_id,
                organization_id="org-1",
                campaign_id="camp-1",
                execution=ex,
            )
            await enqueue_execution_event(
                db,
                event_type=EXECUTION_COMPLETED,
                execution_id=exec_id,
                organization_id="org-1",
                campaign_id="camp-1",
                execution=ex,
            )
        await db.commit()
        first_id = e1.event_id

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/executions/{exec_id}/events",
            params={"since": first_id},
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["event_type"] == EXECUTION_COMPLETED


@pytest.mark.asyncio
async def test_step_retried_events(session_factory):
    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            await emit_step_started(
                db,
                execution_id=exec_id,
                org_id="org-1",
                campaign_id="camp-1",
                step={"type": "tap", "id": "s1"},
                step_index=0,
                depth=2,
            )
            await emit_step_finished(
                db,
                execution_id=exec_id,
                org_id="org-1",
                campaign_id="camp-1",
                step={"type": "tap", "id": "s1"},
                step_index=0,
                depth=2,
                step_result={
                    "ok": True,
                    "retry_attempts": [
                        {"attempt": 1, "error_reason": "stale_frame", "wait_ms_before_next": 100},
                        {"attempt": 2, "error_reason": None, "wait_ms_before_next": None},
                    ],
                },
            )
        await db.commit()

    async with session_factory() as db:
        from db.crud.execution_events import list_execution_events

        rows = await list_execution_events(db, exec_id)
    types = [r.event_type for r in rows]
    assert types == [STEP_STARTED, STEP_RETRIED, STEP_COMPLETED]
    assert rows[0].step_id == "s1"
    assert rows[0].payload["step_id"] == "s1"
    assert rows[0].payload["depth"] == 2
    assert rows[2].payload["depth"] == 2


@pytest.mark.asyncio
async def test_resolve_execution_org_id_without_tenant_context(session_factory):
    """Temporal activities resolve org via execution/campaign without request tenant context."""
    exec_id = await _seed_campaign_execution(session_factory)
    from services.execution.event_publisher import (
        resolve_execution_event_context,
        resolve_execution_org_id,
    )

    async with session_factory() as db:
        org_id = await resolve_execution_org_id(db, exec_id)
        assert org_id == "org-1"
        row, ctx_org, camp_id = await resolve_execution_event_context(db, exec_id)
        assert row is not None
        assert ctx_org == "org-1"
        assert camp_id == "camp-1"


@pytest.mark.asyncio
async def test_cross_org_list_denied(session_factory):
    exec_id = await _seed_campaign_execution(session_factory)
    app = _build_app(session_factory, org_id="org-2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(f"/api/executions/{exec_id}/events")
        assert r.status_code == 404
