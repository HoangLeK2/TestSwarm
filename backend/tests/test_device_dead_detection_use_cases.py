"""End-to-end use-case tests: dead detection worker + revive + fleet stats + lifecycle WS (DF-T-02-005).

Each test maps to an operator-facing journey (UC-DEAD-XX), not a single assertion.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.device import create_device
from db.crud.fleet_stats import query_fleet_stats
from db.crud.tenant_settings import upsert_dead_threshold_sec
from db.models import Organization, User
from db.models.activity import ActivityLog
from db.models.device_fsm import DeviceFsmSnapshot, DeviceStateTransition
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from fastapi import FastAPI
from services.device_state.dead_detector import run_dead_detection_once
from services.device_state.lifecycle_schema import LifecycleEventType
from services.device_state.service import ApplyOutcome, DeviceStateService
from services.device_state.ws_publisher import DEBOUNCE_MS, DeviceLifecyclePublisher
from tenancy.context import set_current_org_id, tenant_context

USER_ID = "user-dead-uc"
ADMIN_ID = "admin-dead-uc"
ORG_ID = "org-dead-uc"
ORG_SLOW = "org-dead-uc-slow"


# ── Shared fixtures & helpers ─────────────────────────────────────────────────


@pytest_asyncio.fixture
async def dead_uc_seed(tenancy_session_factory):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Dead UC Org",
                business_email="dead-uc@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            Organization(
                id=ORG_SLOW,
                business_name="Slow Net Org",
                business_email="slow-uc@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="operator@dead-uc.local",
                name="Operator",
                hashed_password="hashed",
                role="operator",
                org_id=ORG_ID,
            )
        )
        db.add(
            User(
                id=ADMIN_ID,
                email="admin@dead-uc.local",
                name="Admin",
                hashed_password="hashed",
                role="admin",
                org_id=ORG_ID,
            )
        )
        await upsert_dead_threshold_sec(db, ORG_SLOW, 1800)
        await db.commit()
    set_current_org_id(ORG_ID)


@pytest_asyncio.fixture
async def dead_uc_worker(tenancy_session_factory):
    with patch(
        "services.device_state.dead_detector.AsyncSessionLocal",
        tenancy_session_factory,
    ):
        yield


async def _online_device(
    db: AsyncSession,
    svc: DeviceStateService,
    *,
    serial: str = "uc-001",
    org_id: str = ORG_ID,
) -> object:
    dev = await create_device(db, serial=serial, user_id=USER_ID, org_id=org_id)
    await svc.apply_event(
        db, dev.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id=f"a-{serial}"
    )
    await svc.apply_event(
        db, dev.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id=f"o-{serial}"
    )
    return dev


async def _reconnecting_stale(
    db: AsyncSession,
    svc: DeviceStateService,
    *,
    serial: str = "uc-rec",
    org_id: str = ORG_ID,
    age_seconds: int = 700,
    session_id: str | None = None,
):
    dev = await _online_device(db, svc, serial=serial, org_id=org_id)
    if session_id:
        await svc.claim(db, dev.id, session_id, event_id=f"c-{serial}")
    await svc.apply_event(
        db,
        dev.id,
        event=DeviceFsmEvent.RECONNECTING.value,
        source="agent",
        event_id=f"r-{serial}",
    )
    snap = await db.get(DeviceFsmSnapshot, dev.id)
    assert snap is not None
    snap.reconnecting_since = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return dev


def _api_app(session_factory, *, user_id: str = ADMIN_ID, role: str = "admin") -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    async def _db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _user():
        return SimpleNamespace(
            id=user_id,
            email=f"{user_id}@test.local",
            name="Tester",
            role=role,
            is_active=True,
            org_id=ORG_ID,
        )

    app.dependency_overrides[_get_db] = _db
    app.dependency_overrides[_get_current_user] = _user
    return app


async def _fleet(db: AsyncSession, org_id: str = ORG_ID):
    with tenant_context(org_id):
        return await query_fleet_stats(db, org_id=org_id)


# ── UC-DEAD-01: Worker marks stale RECONNECTING → DEAD, fleet stats update ────


@pytest.mark.asyncio
async def test_uc_dead_01_worker_updates_fleet_stats(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-01: Background scan transitions stale device; fleet counts move reconnecting→dead."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-fleet-1")
        await db.commit()

    async with tenancy_session_factory() as db:
        before = await _fleet(db)
        assert before.devices_by_state["reconnecting"] == 1
        assert before.devices_by_state["dead"] == 0

    with patch("services.device_state.events._schedule_redis_publish"):
        marked = await run_dead_detection_once()
    assert marked == 1

    async with tenancy_session_factory() as db:
        after = await _fleet(db)
        assert after.devices_by_state["reconnecting"] == 0
        assert after.devices_by_state["dead"] == 1
        assert await svc.get_state(db, dev.id) == DeviceFsmState.DEAD


# ── UC-DEAD-02: Session held during RECONNECTING released on dead ────────────


@pytest.mark.asyncio
async def test_uc_dead_02_session_released_when_marked_dead(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-02: Execution session on reconnecting device is force-released when worker marks DEAD."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(
            db, svc, serial="uc-sess", session_id="exec:uc-run-42"
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        snap = await db.get(DeviceFsmSnapshot, dev.id)
        assert snap is not None
        assert snap.state == DeviceFsmState.RECONNECTING.value
        assert snap.session_id == "exec:uc-run-42"
        stats = await _fleet(db)
        assert stats.devices_by_state["reconnecting"] == 1

    with patch("services.device_state.events._schedule_redis_publish"), patch(
        "services.device_state.service.DeviceStateService._notify_session_lost",
        new_callable=AsyncMock,
    ):
        await run_dead_detection_once()

    async with tenancy_session_factory() as db:
        snap = await db.get(DeviceFsmSnapshot, dev.id)
        assert snap is not None
        assert snap.state == DeviceFsmState.DEAD.value
        assert snap.session_id is None
        stats = await _fleet(db)
        assert stats.devices_by_state["dead"] == 1
        assert stats.devices_by_state["reconnecting"] == 0
        lost = (
            await db.execute(
                select(DeviceStateTransition).where(
                    DeviceStateTransition.device_id == dev.id,
                    DeviceStateTransition.event == DeviceFsmEvent.SESSION_LOST.value,
                )
            )
        ).scalars().all()
        assert len(lost) == 1
        assert lost[0].from_state == DeviceFsmState.RECONNECTING.value


# ── UC-DEAD-03: Admin HTTP revive after worker DEAD ──────────────────────────


@pytest.mark.asyncio
async def test_uc_dead_03_admin_revive_after_worker(
    tenancy_session_factory, dead_uc_seed,
):
    """UC-DEAD-03: Admin POST /revive moves DEAD→CONNECTING with audit trail."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-revive")
        await svc.mark_dead_reconnect_timeout(db, dev.id, device_serial=dev.serial)
        await db.commit()

    app = _api_app(tenancy_session_factory)
    with patch("services.device_state.events._schedule_redis_publish"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/devices/{dev.id}/revive")

    assert resp.status_code == 200
    body = resp.json()
    assert body["from_state"] == DeviceFsmState.DEAD.value
    assert body["to_state"] == DeviceFsmState.CONNECTING.value
    assert body["actor"] == ADMIN_ID

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.CONNECTING
        audit = (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == dev.id,
                    ActivityLog.action == "device.revived",
                )
            )
        ).scalars().first()
        assert audit is not None
        assert audit.user_id == ADMIN_ID


# ── UC-DEAD-04: Full recovery — revive then agent re-bootstrap ───────────────


@pytest.mark.asyncio
async def test_uc_dead_04_full_recovery_revive_then_agent_online(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-04: DEAD → admin revive → CONNECTING → agent attach+online → ONLINE."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-full")
        await db.commit()

    with patch("services.device_state.events._schedule_redis_publish"):
        await run_dead_detection_once()

    app = _api_app(tenancy_session_factory)
    with patch("services.device_state.events._schedule_redis_publish"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            revive = await client.post(f"/api/devices/{dev.id}/revive")
        assert revive.status_code == 200

    async with tenancy_session_factory() as db:
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="uc-reboot-attach",
        )
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="uc-reboot-online",
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE
        stats = await _fleet(db)
        assert stats.devices_by_state["online"] == 1
        assert stats.devices_by_state["dead"] == 0
        assert stats.devices_by_state["reconnecting"] == 0


# ── UC-DEAD-05: Lifecycle WS event on worker transition ──────────────────────


@pytest.mark.asyncio
async def test_uc_dead_05_worker_emits_lifecycle_ws_state_changed(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-05: Worker DEAD transition surfaces on lifecycle WS as device.state_changed."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-ws")
        await db.commit()

    ws_manager = AsyncMock()
    publisher = DeviceLifecyclePublisher()
    publisher.bind_ws_manager(ws_manager)
    publisher.set_event_loop(asyncio.get_running_loop())
    publisher.start()
    publisher._org_device_cache[dev.id] = (ORG_ID, 0.0)

    try:
        with patch("services.device_state.events._schedule_redis_publish"):
            await run_dead_detection_once()
        await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.08)

        ws_manager.broadcast_to_org.assert_awaited()
        msg = ws_manager.broadcast_to_org.await_args[0][1]
        assert msg["type"] == "lifecycle.event"
        event = msg["event"]
        assert event["type"] == LifecycleEventType.DEVICE_STATE_CHANGED
        assert event["device_id"] == dev.id
        assert event["from_state"] == DeviceFsmState.RECONNECTING.value
        assert event["to_state"] == DeviceFsmState.DEAD.value
        assert event["source"] == "system"
        assert event["payload"]["reason"] == "reconnect_timeout"
    finally:
        publisher.stop()


# ── UC-DEAD-06: Agent recovery before worker — device stays ONLINE ───────────


@pytest.mark.asyncio
async def test_uc_dead_06_agent_recovery_before_worker(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-06: Agent ONLINE before scan → worker skips; fleet stays online."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-recover", age_seconds=300)
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="uc-back-online",
        )
        await db.commit()

    marked = await run_dead_detection_once()
    assert marked == 0

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE
        stats = await _fleet(db)
        assert stats.devices_by_state["online"] == 1
        assert stats.devices_by_state["dead"] == 0


# ── UC-DEAD-07: Tenant threshold protects slow-network org ───────────────────


@pytest.mark.asyncio
async def test_uc_dead_07_tenant_threshold_protects_slow_org(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-07: Org with 1800s threshold keeps 700s RECONNECTING device alive."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(
            db, svc, serial="uc-slow", org_id=ORG_SLOW, age_seconds=700
        )
        await db.commit()

    with patch("services.device_state.events._schedule_redis_publish"):
        marked = await run_dead_detection_once()
    assert marked == 0

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.RECONNECTING
        stats = await _fleet(db, org_id=ORG_SLOW)
        assert stats.devices_by_state["reconnecting"] == 1
        assert stats.devices_by_state["dead"] == 0


# ── UC-DEAD-08: Revive rejected for non-DEAD device ──────────────────────────


@pytest.mark.asyncio
async def test_uc_dead_08_revive_non_dead_returns_409(
    tenancy_session_factory, dead_uc_seed,
):
    """UC-DEAD-08: Revive on ONLINE device returns 409 — illegal transition."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _online_device(db, svc, serial="uc-online-revive")
        await db.commit()

    app = _api_app(tenancy_session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/devices/{dev.id}/revive")

    assert resp.status_code == 409
    assert "not DEAD" in resp.json()["detail"]

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.ONLINE


# ── UC-DEAD-09: Operator cannot revive ───────────────────────────────────────


@pytest.mark.asyncio
async def test_uc_dead_09_operator_revive_forbidden(
    tenancy_session_factory, dead_uc_seed,
):
    """UC-DEAD-09: Non-admin operator receives 403 on POST /revive."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-op")
        await svc.mark_dead_reconnect_timeout(db, dev.id)
        await db.commit()

    app = _api_app(tenancy_session_factory, user_id=USER_ID, role="operator")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/devices/{dev.id}/revive")

    assert resp.status_code == 403

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, dev.id) == DeviceFsmState.DEAD


# ── UC-DEAD-10: Second worker scan is idempotent ─────────────────────────────


@pytest.mark.asyncio
async def test_uc_dead_10_second_worker_scan_idempotent(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-10: Re-running worker after DEAD does not duplicate transitions."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        await _reconnecting_stale(db, svc, serial="uc-idem")
        await db.commit()

    with patch("services.device_state.events._schedule_redis_publish"):
        first = await run_dead_detection_once()
        second = await run_dead_detection_once()

    assert first == 1
    assert second == 0

    async with tenancy_session_factory() as db:
        dead_transitions = (
            await db.execute(
                select(DeviceStateTransition).where(
                    DeviceStateTransition.to_state == DeviceFsmState.DEAD.value,
                )
            )
        ).scalars().all()
        assert len(dead_transitions) == 1


# ── UC-DEAD-11: Mixed fleet — only stale devices die, others untouched ───────


@pytest.mark.asyncio
async def test_uc_dead_11_mixed_fleet_selective_dead(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-11: Online + fresh reconnecting + stale reconnecting → only stale becomes DEAD."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        online = await _online_device(db, svc, serial="uc-mix-online")
        fresh = await _reconnecting_stale(db, svc, serial="uc-mix-fresh", age_seconds=120)
        stale = await _reconnecting_stale(db, svc, serial="uc-mix-stale", age_seconds=800)
        await db.commit()

    with patch("services.device_state.events._schedule_redis_publish"):
        marked = await run_dead_detection_once()
    assert marked == 1

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, online.id) == DeviceFsmState.ONLINE
        assert await svc.get_state(db, fresh.id) == DeviceFsmState.RECONNECTING
        assert await svc.get_state(db, stale.id) == DeviceFsmState.DEAD
        stats = await _fleet(db)
        assert stats.devices_by_state["online"] == 1
        assert stats.devices_by_state["reconnecting"] == 1
        assert stats.devices_by_state["dead"] == 1


# ── UC-DEAD-12: Worker writes device.dead activity audit ───────────────────


@pytest.mark.asyncio
async def test_uc_dead_12_worker_writes_activity_audit(
    tenancy_session_factory, dead_uc_seed, dead_uc_worker,
):
    """UC-DEAD-12: Dead detection persists activity log for operator audit."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        dev = await _reconnecting_stale(db, svc, serial="uc-audit")
        await db.commit()

    with patch("services.device_state.events._schedule_redis_publish"):
        await run_dead_detection_once()

    async with tenancy_session_factory() as db:
        row = (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == dev.id,
                    ActivityLog.action == "device.dead",
                )
            )
        ).scalars().first()
        assert row is not None
        assert row.device_serial == dev.serial
        assert row.details["reason"] == "reconnect_timeout"
