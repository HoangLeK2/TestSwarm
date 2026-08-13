"""DF-T-04-013 — execution event stream (outbox, SSE, catch-up)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql
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
    STEP_FAILED,
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
async def test_outbox_claim_query_skips_rows_locked_by_another_poller():
    from db.crud.execution_events import claim_unpublished_events

    class EmptyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class CaptureSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    db = CaptureSession()
    await claim_unpublished_events(
        db,
        limit=200,
        now=datetime.now(timezone.utc),
    )

    sql = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "publish_claimed_at" in sql


@pytest.mark.asyncio
async def test_outbox_live_lease_prevents_duplicate_claim_and_expired_lease_recovers(
    session_factory,
):
    from db.crud.execution import get_execution
    from db.crud.execution_events import claim_unpublished_events

    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
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

    claimed_at = datetime.now(timezone.utc)
    async with session_factory() as first:
        first_claim = await claim_unpublished_events(
            first,
            limit=10,
            lease_seconds=30,
            now=claimed_at,
        )
        assert len(first_claim.rows) == 1
        await first.commit()

    async with session_factory() as second:
        live_claim = await claim_unpublished_events(
            second,
            limit=10,
            lease_seconds=30,
            now=claimed_at + timedelta(seconds=29),
        )
        assert live_claim.rows == ()
        await second.commit()

    async with session_factory() as third:
        recovered = await claim_unpublished_events(
            third,
            limit=10,
            lease_seconds=30,
            now=claimed_at + timedelta(seconds=31),
        )
        assert len(recovered.rows) == 1
        assert recovered.token != first_claim.token
        await third.rollback()


@pytest.mark.asyncio
async def test_outbox_publishes_outside_claim_transaction(session_factory, monkeypatch):
    from db.crud.execution import get_execution

    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
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

    transaction_states: list[bool] = []
    async with session_factory() as db:
        async def publish(envelope):
            transaction_states.append(db.in_transaction())

        monkeypatch.setattr(
            "services.execution.event_publisher.publish_row_to_broker",
            publish,
        )
        published = await process_outbox_batch(db)

    assert published == 1
    assert transaction_states == [False]


def test_outbox_lease_timeout_env_is_configurable_and_safely_bounded(monkeypatch):
    from services.execution.outbox_poller import _lease_seconds

    monkeypatch.setenv("EXECUTION_EVENT_OUTBOX_LEASE_SECONDS", "45.5")
    assert _lease_seconds() == 45.5

    monkeypatch.setenv("EXECUTION_EVENT_OUTBOX_LEASE_SECONDS", "1")
    assert _lease_seconds() == 5.0

    monkeypatch.setenv("EXECUTION_EVENT_OUTBOX_LEASE_SECONDS", "invalid")
    assert _lease_seconds() == 30.0


@pytest.mark.asyncio
async def test_outbox_failed_publish_releases_lease_for_immediate_retry(
    session_factory,
    monkeypatch,
):
    from db.crud.execution import get_execution
    from db.crud.execution_events import list_execution_events

    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
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

    async def fail_publish(envelope):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "services.execution.event_publisher.publish_row_to_broker",
        fail_publish,
    )
    async with session_factory() as db:
        assert await process_outbox_batch(db) == 0

    async with session_factory() as db:
        rows = await list_execution_events(db, exec_id)
        assert rows[0].published_at is None
        assert rows[0].publish_claim_token is None
        assert rows[0].publish_claimed_at is None
        assert rows[0].publish_attempts == 1

    async def publish(envelope):
        return None

    monkeypatch.setattr(
        "services.execution.event_publisher.publish_row_to_broker",
        publish,
    )
    async with session_factory() as db:
        assert await process_outbox_batch(db) == 1


@pytest.mark.asyncio
async def test_outbox_stats_report_oldest_unpublished_event_age(session_factory):
    from db.crud.execution_events import get_unpublished_event_stats

    exec_id = await _seed_campaign_execution(session_factory)
    occurred_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    async with session_factory() as db:
        with tenant_context("org-1"):
            await enqueue_execution_event(
                db,
                event_type=EXECUTION_CREATED,
                execution_id=exec_id,
                organization_id="org-1",
                campaign_id="camp-1",
                occurred_at=occurred_at,
            )
        await db.commit()

    async with session_factory() as db:
        stats = await get_unpublished_event_stats(db)

    assert stats.count == 1
    assert 4.0 <= stats.oldest_age_seconds <= 10.0


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
    trace_context = {
        "execution_id": exec_id,
        "campaign_id": "camp-1",
        "device_serial": "phone-001",
        "account_id": "acc-1",
        "scenario_name": "Trace Scenario",
        "password": "must-not-leak",
    }
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
                trace_context=trace_context,
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
                    "duration_ms": 123.4,
                    "extra_data_total_ms": 55.0,
                    "extra_data_dump_ms": 40.0,
                    "extra_data_parse_ms": 3.5,
                    "extra_data_click_ms": 0.0,
                    "extra_data_wait_ms": 12.5,
                    "extra_data_sleep_ms": 0.0,
                    "extra_data_steps": 1,
                    "scroll_to_flow_ms": 321.0,
                    "scroll_to_swipes": 4,
                    "account_action_id": "action-1",
                    "outcome": "applied",
                    "action_performed": True,
                    "retry_attempts": [
                        {"attempt": 1, "error_reason": "stale_frame", "wait_ms_before_next": 100},
                        {"attempt": 2, "error_reason": None, "wait_ms_before_next": None},
                    ],
                },
                trace_context=trace_context,
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
    assert rows[0].payload["trace"]["device_serial"] == "phone-001"
    assert rows[0].payload["trace"]["account_id"] == "acc-1"
    assert rows[0].payload["trace"]["scenario_name"] == "Trace Scenario"
    assert "password" not in rows[0].payload["trace"]
    assert rows[2].payload["depth"] == 2
    assert rows[2].payload["trace"]["action"]["account_action_id"] == "action-1"
    assert rows[2].payload["trace"]["action"]["outcome"] == "applied"
    assert rows[2].payload["duration_ms"] == 123.4
    assert rows[2].payload["extra_data_total_ms"] == 55.0
    assert rows[2].payload["extra_data_dump_ms"] == 40.0
    assert rows[2].payload["extra_data_parse_ms"] == 3.5
    assert rows[2].payload["extra_data_click_ms"] == 0.0
    assert rows[2].payload["extra_data_wait_ms"] == 12.5
    assert rows[2].payload["extra_data_sleep_ms"] == 0.0
    assert rows[2].payload["extra_data_steps"] == 1
    assert rows[2].payload["scroll_to_flow_ms"] == 321.0
    assert rows[2].payload["scroll_to_swipes"] == 4


@pytest.mark.asyncio
async def test_step_failed_event_includes_nested_extra_data_diagnostic(session_factory):
    exec_id = await _seed_campaign_execution(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            await emit_step_finished(
                db,
                execution_id=exec_id,
                org_id="org-1",
                campaign_id="camp-1",
                step={"type": "run_scenario", "id": "sub"},
                step_index=3,
                depth=0,
                step_result={
                    "ok": False,
                    "message": "run_scenario failed: edge extra_data failed",
                    "edge_extra_summary": {
                        "diagnostic": {
                            "reason_code": "post_open_target_not_found",
                            "timing": {"total_ms": 42.0},
                        }
                    },
                    "nested_failure": {
                        "step_index": 0,
                        "step_type": "extract",
                        "message": "edge extra_data failed",
                    },
                    "extra_data_total_ms": 42.0,
                },
            )
        await db.commit()

    async with session_factory() as db:
        from db.crud.execution_events import list_execution_events

        rows = await list_execution_events(db, exec_id)

    assert len(rows) == 1
    assert rows[0].event_type == STEP_FAILED
    assert rows[0].payload["edge_extra_summary"]["diagnostic"]["reason_code"] == "post_open_target_not_found"
    assert rows[0].payload["edge_extra_summary"]["diagnostic"]["timing"]["total_ms"] == 42.0
    assert rows[0].payload["nested_failure"]["step_type"] == "extract"
    assert rows[0].payload["extra_data_total_ms"] == 42.0


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
