"""DF-T-04-012 — DLQ open / replay / close lifecycle."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.deps import _get_current_user, _get_db
from api.routes.executions import router as executions_router
from db.crud.execution_dlq import create_dlq_entry
from db.database import Base
from db.models.campaign import Campaign
from db.models.device import Device
from db.models.execution import Execution
from db.models.enums import ExecutionStatus
from services.campaign.dlq_errors import DLQAlreadyClosedError, DLQRetryInProgressError
from services.campaign.dlq_service import (
    close_dlq_entry,
    open_dlq_for_failed_execution,
    replay_dlq_entry,
    uses_epic04_replay,
)
from services.campaign.execution_runtime import DISPATCH_SOURCE_TEMPORAL
from tenancy.context import set_current_org_id, tenant_context


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


def _build_app(session_factory, user_id: str = "u1") -> FastAPI:
    app = FastAPI()
    app.include_router(executions_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    async def _user_override():
        set_current_org_id("org-1")
        return SimpleNamespace(
            id=user_id,
            role="operator",
            org_role="owner",
            is_active=True,
            org_id="org-1",
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    fake_scheduler = SimpleNamespace(_client=AsyncMock(), _cfg=SimpleNamespace(enabled=True))
    app.state.scheduler = fake_scheduler
    app.state.manager = None
    return app


async def _seed_epic04_execution(
    session_factory,
    *,
    exec_id: str,
    campaign_id: str = "camp-1",
    checkpoint: int = 2,
) -> str:
    async with session_factory() as s:
        with tenant_context("org-1"):
            if await s.get(Campaign, campaign_id) is None:
                s.add(
                    Campaign(
                        id=campaign_id,
                        name=f"Campaign {campaign_id}",
                        name_lower=f"campaign {campaign_id}".lower(),
                        user_id="u1",
                        org_id="org-1",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            s.add(
                Device(
                    id="dev-sn1",
                    serial="SN1",
                    user_id="u1",
                    org_id="org-1",
                    last_seen=datetime.now(timezone.utc),
                )
            )
            s.add(
                Execution(
                    id=exec_id,
                    run_type="campaign_device",
                    status=ExecutionStatus.DLQ_OPEN.value,
                    campaign_id=campaign_id,
                    user_id="u1",
                    checkpoint_step=checkpoint,
                    meta={
                        "dispatch_source": DISPATCH_SOURCE_TEMPORAL,
                        "org_scenario_refs": [{"scenario_id": "sc-1"}],
                    },
                    created_at=datetime.now(timezone.utc),
                )
            )
        await s.commit()
    return exec_id


@pytest.mark.asyncio
async def test_open_dlq_sets_execution_dlq_open(session_factory):
    async with session_factory() as db:
        with tenant_context("org-1"):
            db.add(
                Execution(
                    id="exec-fail",
                    run_type="campaign_device",
                    status=ExecutionStatus.FAILED.value,
                    campaign_id="camp-1",
                    user_id="u1",
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db.flush()
            entry = await open_dlq_for_failed_execution(
                db,
                execution_id="exec-fail",
                device_serial="SN1",
                step_results=[{"ok": True}, {"ok": False, "step_id": "3", "message": "tap failed"}],
                org_id="org-1",
                user_id="u1",
            )
            ex = await db.get(Execution, "exec-fail")
        await db.commit()

    assert entry.failed_step_id == "3"
    assert entry.failure_reason == "tap failed"
    assert ex.status == ExecutionStatus.DLQ_OPEN.value


@pytest.mark.asyncio
async def test_uses_epic04_replay_detects_dispatch_source():
    ex = SimpleNamespace(meta={"dispatch_source": DISPATCH_SOURCE_TEMPORAL})
    assert uses_epic04_replay(ex) is True
    assert uses_epic04_replay(SimpleNamespace(meta={})) is False


@pytest.mark.asyncio
async def test_close_dlq_marks_closed_and_execution_dlq_closed(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-close")
    async with session_factory() as db:
        with tenant_context("org-1"):
            entry = await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                failed_step_id="3",
                campaign_id="camp-1",
            )
            await db.commit()
            dlq_id = entry.id

    async with session_factory() as db:
        with tenant_context("org-1"):
            with patch(
                "services.campaign.aggregator_scheduler.request_campaign_status_evaluation",
                new=AsyncMock(),
            ):
                closed = await close_dlq_entry(
                    db,
                    dlq_id=dlq_id,
                    user_id="u1",
                    org_id="org-1",
                    closed_by="u1",
                    close_reason="scenario logic bug",
                )
            ex = await db.get(Execution, exec_id)
        await db.commit()

    assert closed.status == "closed"
    assert closed.close_reason == "scenario logic bug"
    assert ex.status == ExecutionStatus.DLQ_CLOSED.value


@pytest.mark.asyncio
async def test_replay_already_closed_raises(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-closed")
    async with session_factory() as db:
        with tenant_context("org-1"):
            entry = await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                campaign_id="camp-1",
            )
            entry.status = "closed"
            await db.commit()
            dlq_id = entry.id

    async with session_factory() as db:
        with tenant_context("org-1"):
            with pytest.raises(DLQAlreadyClosedError):
                await replay_dlq_entry(
                    db,
                    dlq_id=dlq_id,
                    user_id="u1",
                    org_id="org-1",
                    actor_user_id="u1",
                )


@pytest.mark.asyncio
async def test_replay_retry_in_progress_when_already_retrying(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-retrying")
    async with session_factory() as db:
        with tenant_context("org-1"):
            entry = await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                campaign_id="camp-1",
            )
            entry.status = "retrying"
            await db.commit()
            dlq_id = entry.id

    async with session_factory() as db:
        with tenant_context("org-1"):
            with pytest.raises(DLQRetryInProgressError):
                await replay_dlq_entry(
                    db,
                    dlq_id=dlq_id,
                    user_id="u1",
                    org_id="org-1",
                    actor_user_id="u1",
                )


@pytest.mark.asyncio
async def test_get_dlq_by_execution_route(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-detail")
    async with session_factory() as db:
        with tenant_context("org-1"):
            await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                failed_step_id="step-3",
                failure_reason="timeout",
                campaign_id="camp-1",
                artifact_refs={"url": "https://example/shot.png"},
            )
        await db.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(f"/api/executions/dlq/executions/{exec_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["execution_id"] == exec_id
        assert body["failed_step_id"] == "step-3"
        assert body["artifact_refs"]["url"] == "https://example/shot.png"


@pytest.mark.asyncio
async def test_close_dlq_route(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-close-route")
    async with session_factory() as db:
        with tenant_context("org-1"):
            entry = await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                campaign_id="camp-1",
            )
        await db.commit()
        dlq_id = entry.id

    app = _build_app(session_factory)
    with patch(
        "services.campaign.aggregator_scheduler.request_campaign_status_evaluation",
        new=AsyncMock(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(
                f"/api/executions/dlq/{dlq_id}/close",
                json={"reason": "won't fix"},
            )
            assert r.status_code == 200
            assert r.json()["status"] == "closed"


@pytest.mark.asyncio
async def test_list_dlq_status_open_alias(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-open-filter")
    async with session_factory() as db:
        with tenant_context("org-1"):
            await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                campaign_id="camp-1",
            )
        await db.commit()

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/executions/dlq", params={"status": "open"})
        assert r.status_code == 200
        assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_epic04_replay_checkpoint_creates_linked_execution(session_factory):
    exec_id = await _seed_epic04_execution(session_factory, exec_id="exec-replay", checkpoint=2)
    async with session_factory() as db:
        with tenant_context("org-1"):
            entry = await create_dlq_entry(
                db,
                execution_id=exec_id,
                device_serial="SN1",
                campaign_id="camp-1",
            )
        await db.commit()
        dlq_id = entry.id

    view = SimpleNamespace(
        execution_id="new-exec",
        device_id="dev-sn1",
        status=ExecutionStatus.RUNNING.value,
        failure_reason=None,
    )

    with patch(
        "services.campaign.dispatcher.CampaignDispatcher.activate_queued_execution",
        new=AsyncMock(return_value=view),
    ), patch(
        "services.campaign.execution_runtime.start_execution_runtime",
        new=AsyncMock(return_value={"temporal": 1, "fallback": 0}),
    ):
        async with session_factory() as db:
            with tenant_context("org-1"):
                entry, new_ex, changed = await replay_dlq_entry(
                    db,
                    dlq_id=dlq_id,
                    user_id="u1",
                    org_id="org-1",
                    actor_user_id="u1",
                    from_checkpoint=True,
                    temporal_client=AsyncMock(),
                    temporal_config=SimpleNamespace(enabled=True),
                )
            await db.commit()

    assert changed is True
    assert entry.status == "replayed"
    assert new_ex.meta["replayed_from"] == exec_id
    assert new_ex.meta["start_step"] == 2
    assert new_ex.checkpoint_step == 2
