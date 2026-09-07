from __future__ import annotations

"""HTTP-level n2n tests for GET /api/executions/dlq with the campaign_id filter.

Verifies the route → CRUD wiring for the recently-added campaign scoping fix
(user-reported "DLQ entries from all campaigns merged together" bug).
"""

from datetime import datetime, timezone
from datetime import timedelta
from types import SimpleNamespace
from typing import AsyncIterator
from unittest.mock import AsyncMock

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
from tenancy.context import set_current_org_id, tenant_context
from tests.tenancy_test_support import seed_casbin_policy_tables


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await seed_casbin_policy_tables(conn)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _build_app(
    session_factory,
    user_id: str = "u1",
    *,
    org_role: str = "member",
    org_id: str | None = "org-1",
) -> FastAPI:
    app = FastAPI()
    app.include_router(executions_router, prefix="/api")

    async def _db_override() -> AsyncIterator[AsyncSession]:
        async with session_factory() as s:
            yield s

    async def _user_override():
        if org_id:
            set_current_org_id(org_id)
        return SimpleNamespace(
            id=user_id,
            role="operator",
            org_role=org_role,
            is_active=True,
            org_id=org_id,
        )

    app.dependency_overrides[_get_db] = _db_override
    app.dependency_overrides[_get_current_user] = _user_override
    return app


async def _seed(session_factory, exec_id: str, campaign_id: str, user_id: str = "u1"):
    async with session_factory() as s:
        with tenant_context("org-1"):
            if campaign_id is not None and await s.get(Campaign, campaign_id) is None:
                s.add(
                    Campaign(
                        id=campaign_id,
                        name=f"Campaign {campaign_id}",
                        name_lower=f"campaign {campaign_id}".lower(),
                        user_id=user_id,
                        org_id="org-1",
                        created_at=datetime.now(timezone.utc),
                    )
                )
            s.add(
                Execution(
                    id=exec_id,
                    run_type="campaign_run",
                    status="failed",
                    org_id="org-1",
                    campaign_id=campaign_id,
                    user_id=user_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
        await s.commit()


async def _seed_dlq(session_factory, exec_id: str, serial: str):
    async with session_factory() as s:
        await create_dlq_entry(s, execution_id=exec_id, device_serial=serial)
        await s.commit()


async def _seed_device(session_factory, serial: str, user_id: str = "u1", *, last_seen=None):
    async with session_factory() as s:
        s.add(
            Device(
                id=f"dev-{serial}",
                serial=serial,
                user_id=user_id,
                org_id="org-1",
                last_seen=last_seen,
            )
        )
        await s.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dlq_route_filters_by_campaign_id(session_factory):
    """The user-reported bug: without filter we saw entries from all campaigns merged."""
    await _seed(session_factory, "exec-A", "camp-A")
    await _seed(session_factory, "exec-B", "camp-B")
    await _seed_dlq(session_factory, "exec-A", "dev-A")
    await _seed_dlq(session_factory, "exec-B", "dev-B")

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Without filter — both campaigns' entries
        r_all = await ac.get("/api/executions/dlq")
        assert r_all.status_code == 200
        assert {e["execution_id"] for e in r_all.json()} == {"exec-A", "exec-B"}

        # Filtered to campA only
        r_a = await ac.get("/api/executions/dlq", params={"campaign_id": "camp-A"})
        assert r_a.status_code == 200
        assert {e["execution_id"] for e in r_a.json()} == {"exec-A"}

        # Filtered to campB only
        r_b = await ac.get("/api/executions/dlq", params={"campaign_id": "camp-B"})
        assert {e["execution_id"] for e in r_b.json()} == {"exec-B"}


@pytest.mark.asyncio
async def test_dlq_empty_string_campaign_id_falls_back_to_unfiltered(session_factory):
    """Defense: ?campaign_id= should NOT silently filter to []."""
    await _seed(session_factory, "exec-1", "camp-1")
    await _seed_dlq(session_factory, "exec-1", "dev-1")

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/executions/dlq", params={"campaign_id": ""})
        assert r.status_code == 200
        # Empty string must be coerced — entry is still returned
        assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_dlq_route_other_user_campaign_returns_empty(session_factory):
    """User-scoped DLQ: another user's campaign yields [] when not org-visible."""
    await _seed(session_factory, "exec-mine", "camp-mine", user_id="u1")
    async with session_factory() as s:
        with tenant_context("org-2"):
            s.add(
                Campaign(
                    id="camp-theirs",
                    name="Campaign camp-theirs",
                    name_lower="campaign camp-theirs",
                    user_id="u2",
                    org_id="org-2",
                    created_at=datetime.now(timezone.utc),
                )
            )
            s.add(
                    Execution(
                        id="exec-theirs",
                        run_type="campaign_run",
                        status="failed",
                        org_id="org-2",
                    campaign_id="camp-theirs",
                    user_id="u2",
                    created_at=datetime.now(timezone.utc),
                )
            )
        await s.commit()
    await _seed_dlq(session_factory, "exec-mine", "d1")
    await _seed_dlq(session_factory, "exec-theirs", "d2")

    app = _build_app(session_factory, user_id="u1", org_id="org-1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # u1 cannot see u2's campaign DLQ even with explicit campaign_id
        r = await ac.get("/api/executions/dlq", params={"campaign_id": "camp-theirs"})
        assert r.status_code == 200
        assert r.json() == []


@pytest.mark.asyncio
async def test_dlq_route_campaign_filter_combined_with_status(session_factory):
    await _seed(session_factory, "exec-X", "camp-X")
    await _seed_dlq(session_factory, "exec-X", "d1")

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/executions/dlq",
            params={"campaign_id": "camp-X", "status": "pending"},
        )
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["status"] == "pending"

        # Status that has no matches
        r2 = await ac.get(
            "/api/executions/dlq",
            params={"campaign_id": "camp-X", "status": "resolved"},
        )
        assert r2.status_code == 200
        assert r2.json() == []


@pytest.mark.asyncio
async def test_dlq_summary_alerts_when_pending_count_exceeds_threshold(session_factory):
    for idx in range(11):
        exec_id = f"exec-alert-{idx}"
        await _seed(session_factory, exec_id, "camp-alert")
        await _seed_dlq(session_factory, exec_id, f"dev-alert-{idx}")

    app = _build_app(session_factory)
    notification_service = SimpleNamespace(notify=AsyncMock())
    app.state.notification_service = notification_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/executions/dlq/summary", params={"campaign_id": "camp-alert"})
        assert r.status_code == 200
        body = r.json()
        assert body["pending_count"] == 11
        assert body["alert_threshold"] == 10
        assert body["alert"] is True
        notification_service.notify.assert_awaited_once()


# ── Retry path coverage ───────────────────────────────────────────────────────


def _build_app_with_temporal(session_factory, temporal_client, user_id: str = "u1", *, org_id: str | None = "org-1") -> FastAPI:
    """Variant that attaches a fake scheduler holding a Temporal client (or None)."""
    app = _build_app(session_factory, user_id=user_id, org_role="owner", org_id=org_id)
    fake_scheduler = SimpleNamespace(_client=temporal_client, _cfg=None)
    app.state.scheduler = fake_scheduler
    return app


@pytest.mark.asyncio
async def test_retry_no_temporal_returns_503_and_reverts_to_pending(session_factory):
    """When Temporal client is missing, retry must 503 and entry must be back to pending."""
    await _seed(session_factory, "exec-1", "camp-1")
    await _seed_dlq(session_factory, "exec-1", "d1")

    app = _build_app_with_temporal(session_factory, temporal_client=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Get the dlq id
        r = await ac.get("/api/executions/dlq")
        dlq_id = r.json()[0]["id"]

        retry = await ac.post(f"/api/executions/dlq/{dlq_id}/retry")
        assert retry.status_code == 503

        # Entry must NOT be stuck at 'retrying'
        after = await ac.get("/api/executions/dlq")
        body = after.json()
        assert len(body) == 1
        assert body[0]["status"] == "pending"
        assert body[0]["error"] and "Temporal" in body[0]["error"]


@pytest.mark.asyncio
async def test_retry_stale_offline_device_is_dismissed_without_enqueue(session_factory):
    await _seed(session_factory, "exec-offline", "camp-offline")
    await _seed_device(
        session_factory,
        "serial-offline",
        last_seen=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    await _seed_dlq(session_factory, "exec-offline", "serial-offline")

    fake_temporal = SimpleNamespace(start_workflow=AsyncMock())
    app = _build_app_with_temporal(session_factory, temporal_client=fake_temporal)
    async with session_factory() as s:
        from db.models.execution_dlq import ExecutionDLQ
        from sqlalchemy import select as _select

        dlq_id = (await s.execute(_select(ExecutionDLQ.id))).scalar_one()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        retry = await ac.post(f"/api/executions/dlq/{dlq_id}/retry")
        assert retry.status_code == 200
        assert retry.json()["status"] == "dismissed"

        fake_temporal.start_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_no_campaign_id_returns_400_and_reverts(session_factory):
    """Retry on a standalone (non-campaign) execution must 400 and revert to pending."""
    # Execution with campaign_id=None
    async with session_factory() as s:
        s.add(
                Execution(
                    id="exec-orphan",
                    run_type="test_run",
                    status="failed",
                    org_id="org-1",
                campaign_id=None,
                user_id="u1",
                created_at=datetime.now(timezone.utc),
            )
        )
        await s.commit()
    await _seed_dlq(session_factory, "exec-orphan", "d1")

    fake_temporal = SimpleNamespace()
    app = _build_app_with_temporal(session_factory, temporal_client=fake_temporal, org_id=None)
    async with session_factory() as s:
        from db.models.execution_dlq import ExecutionDLQ
        from sqlalchemy import select as _select

        dlq_id = (await s.execute(_select(ExecutionDLQ.id))).scalar_one()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        retry = await ac.post(f"/api/executions/dlq/{dlq_id}/retry")
        assert retry.status_code == 400
        detail = retry.json()["detail"]
        message = detail["message"] if isinstance(detail, dict) else detail
        assert "campaign" in message.lower()


@pytest.mark.asyncio
async def test_retry_idempotent_when_already_retrying(session_factory):
    """Two concurrent-style retries: only one transitions; second short-circuits."""
    await _seed(session_factory, "exec-1", "camp-1")
    await _seed_dlq(session_factory, "exec-1", "d1")

    # Manually flip to 'retrying' to simulate the second-call state.
    async with session_factory() as s:
        from db.models.execution_dlq import ExecutionDLQ
        from sqlalchemy import update
        await s.execute(
            update(ExecutionDLQ).values(status="retrying", retry_count=1)
        )
        await s.commit()

    fake_temporal = SimpleNamespace()
    app = _build_app_with_temporal(session_factory, temporal_client=fake_temporal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Find the entry by full status filter
        all_r = await ac.get("/api/executions/dlq")
        # Filter status returns 'pending' default — need no filter
        ids_all = [e["id"] for e in all_r.json()]
        # Default status filter is none → entries of any status. We seeded 1.
        # If list is empty, route filter excluded retrying — fall back to direct lookup.
        if not ids_all:
            async with session_factory() as s:
                from db.models.execution_dlq import ExecutionDLQ
                from sqlalchemy import select as _select
                row = (await s.execute(_select(ExecutionDLQ))).scalar_one()
                dlq_id = row.id
        else:
            dlq_id = ids_all[0]

        retry = await ac.post(f"/api/executions/dlq/{dlq_id}/retry")
        assert retry.status_code == 409
        assert retry.json()["detail"]["code"] == "DLQ_RETRY_IN_PROGRESS"


@pytest.mark.asyncio
async def test_retry_unknown_dlq_returns_404(session_factory):
    fake_temporal = SimpleNamespace()
    app = _build_app_with_temporal(session_factory, temporal_client=fake_temporal)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        retry = await ac.post("/api/executions/dlq/nonexistent-id/retry")
        assert retry.status_code == 404


@pytest.mark.asyncio
async def test_retry_other_users_dlq_returns_404(session_factory):
    """User u2 cannot retry u1's DLQ entry."""
    await _seed(session_factory, "exec-mine", "camp-mine", user_id="u1")
    await _seed_dlq(session_factory, "exec-mine", "d1")

    # Find dlq id as u1
    app1 = _build_app_with_temporal(session_factory, temporal_client=None, user_id="u1")
    async with AsyncClient(transport=ASGITransport(app=app1), base_url="http://t") as ac:
        dlq_id = (await ac.get("/api/executions/dlq")).json()[0]["id"]

    # Now try as u2 in a different org (user-scoped, no org_id)
    fake_temporal = SimpleNamespace()
    app2 = _build_app_with_temporal(session_factory, temporal_client=fake_temporal, user_id="u2", org_id=None)
    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://t") as ac:
        retry = await ac.post(f"/api/executions/dlq/{dlq_id}/retry")
        assert retry.status_code == 404

        # u1 retry_count must not have been bumped by u2's failed attempt
        async with session_factory() as s:
            from db.models.execution_dlq import ExecutionDLQ
            from sqlalchemy import select as _select
            row = (await s.execute(_select(ExecutionDLQ))).scalar_one()
            assert row.status == "pending"
            assert row.retry_count == 0


@pytest.mark.asyncio
async def test_dlq_route_limit_is_clamped(session_factory):
    """limit > 200 should be clamped; limit < 1 should be raised to 1."""
    for i in range(5):
        await _seed(session_factory, f"exec-{i}", "camp-1")
        await _seed_dlq(session_factory, f"exec-{i}", f"d{i}")

    app = _build_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        # Negative limit clamped to 1 — should not return empty/unbounded
        r = await ac.get("/api/executions/dlq", params={"limit": -1})
        assert r.status_code == 200
        assert len(r.json()) == 1

        # Huge limit allowed up to 200 — 5 rows fit
        r2 = await ac.get("/api/executions/dlq", params={"limit": 99999})
        assert r2.status_code == 200
        assert len(r2.json()) == 5
