"""DF-T-02-005 — Dead detection: RECONNECTING → DEAD + admin revive."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.device import create_device
from db.crud.tenant_settings import upsert_dead_threshold_sec
from db.models import Organization, User
from db.models.activity import ActivityLog
from db.models.device_fsm import DeviceFsmSnapshot, DeviceStateTransition
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from fastapi import FastAPI
from services.device_state.dead_detector import run_dead_detection_once
from services.device_state.events import (
    DeviceDeadEvent,
    DeviceRevivedEvent,
    SessionLostDeviceEvent,
)
from services.device_state.service import (
    ApplyOutcome,
    DeviceStateService,
    filter_past_dead_threshold,
    list_reconnecting_candidates,
    list_stale_reconnecting_candidates,
)
from tenancy.context import set_current_org_id

USER_ID = "user-dead-det"
ADMIN_ID = "admin-dead-det"
ORG_ID = "org-dead-det"
ORG_SLOW = "org-slow-net"


async def _seed_org(
    db: AsyncSession,
    org_id: str = ORG_ID,
    user_id: str = USER_ID,
    *,
    admin_id: str | None = ADMIN_ID,
) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        Organization(
            id=org_id,
            business_name=f"Org {org_id}",
            business_email=f"{org_id}@org.local",
            status="active",
            plan="standard",
            created_at=now,
        )
    )
    db.add(
        User(
            id=user_id,
            email=f"{user_id}@test.local",
            name="Operator",
            hashed_password="hashed",
            role="operator",
            org_id=org_id,
        )
    )
    if admin_id:
        db.add(
            User(
                id=admin_id,
                email=f"{admin_id}@test.local",
                name="Admin",
                hashed_password="hashed",
                role="admin",
                org_id=org_id,
            )
        )


async def _device_reconnecting(
    db: AsyncSession,
    svc: DeviceStateService,
    *,
    serial: str = "df-001",
    org_id: str = ORG_ID,
    age_seconds: int = 700,
    session_id: str | None = None,
):
    device = await create_device(db, serial=serial, user_id=USER_ID, org_id=org_id)
    await svc.apply_event(
        db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id=f"a-{serial}"
    )
    await svc.apply_event(
        db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id=f"o-{serial}"
    )
    if session_id:
        await svc.claim(db, device.id, session_id, event_id=f"c-{serial}")
    await svc.apply_event(
        db,
        device.id,
        event=DeviceFsmEvent.RECONNECTING.value,
        source="agent",
        event_id=f"r-{serial}",
    )
    snap = await db.get(DeviceFsmSnapshot, device.id)
    assert snap is not None
    snap.reconnecting_since = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return device, snap


def _build_app(session_factory, user_id: str = ADMIN_ID, role: str = "admin"):
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


@pytest_asyncio.fixture
async def dead_detector_db(tenancy_session_factory):
    with patch(
        "services.device_state.dead_detector.AsyncSessionLocal",
        tenancy_session_factory,
    ):
        yield


@pytest_asyncio.fixture
async def dead_seed(tenancy_session_factory):
    async with tenancy_session_factory() as db:
        await _seed_org(db)
        now = datetime.now(timezone.utc)
        db.add(
            Organization(
                id=ORG_SLOW,
                business_name="Slow Net Org",
                business_email="slow@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        await upsert_dead_threshold_sec(db, ORG_SLOW, 1800)
        await db.commit()
    set_current_org_id(ORG_ID)


# ── AC-1: RECONNECTING 700s → DEAD ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac1_reconnecting_past_threshold_marked_dead(
    tenancy_session_factory, dead_seed, dead_detector_db
):
    svc = DeviceStateService()
    dead_events: list[DeviceDeadEvent] = []

    def _capture_dead(channel, payload):
        if channel != "device.dead":
            return
        dead_events.append(
            DeviceDeadEvent(
                device_id=payload["device_id"],
                reason=payload["reason"],
                last_known_state=payload["last_known_state"],
                entered_reconnect_at=payload.get("entered_reconnect_at"),
                session_id=payload.get("session_id"),
            )
        )

    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(db, svc, age_seconds=700)
        await db.commit()

    with patch(
        "services.device_state.events._schedule_redis_publish",
        side_effect=_capture_dead,
    ):
        marked = await run_dead_detection_once()
    assert marked == 1
    assert len(dead_events) == 1
    assert dead_events[0].reason == "reconnect_timeout"

    async with tenancy_session_factory() as db:
        state = await svc.get_state(db, device.id)
        assert state == DeviceFsmState.DEAD
        audit = (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == device.id,
                    ActivityLog.action == "device.dead",
                )
            )
        ).scalars().first()
        assert audit is not None


# ── AC-2: Recovery before threshold — worker must not mark DEAD ───────────────


@pytest.mark.asyncio
async def test_ac2_online_before_worker_skips_dead(
    tenancy_session_factory, dead_seed, dead_detector_db
):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(db, svc, age_seconds=300)
        await svc.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="online-recover",
        )
        await db.commit()

    marked = await run_dead_detection_once()
    assert marked == 0

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, device.id) == DeviceFsmState.ONLINE


# ── AC-3: Tenant override threshold ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac3_tenant_threshold_1800_skips_700s(
    tenancy_session_factory, dead_seed, dead_detector_db
):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(
            db, svc, serial="slow-001", org_id=ORG_SLOW, age_seconds=700, session_id=None
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        candidates = await list_reconnecting_candidates(db)
        stale = await filter_past_dead_threshold(db, candidates)
        assert not any(c.snapshot.device_id == device.id for c in stale)

    marked = await run_dead_detection_once()
    assert marked == 0


@pytest.mark.asyncio
async def test_stale_query_skips_slow_org_head_of_line(
    tenancy_session_factory, dead_seed, dead_detector_db, monkeypatch,
):
    """Slow-threshold org must not block stale devices from other orgs."""
    svc = DeviceStateService()
    monkeypatch.setattr(
        "services.device_state.dead_detector.DEAD_DETECTION_SCAN_LIMIT",
        20,
    )
    async with tenancy_session_factory() as db:
        for i in range(25):
            await _device_reconnecting(
                db,
                svc,
                serial=f"slow-{i}",
                org_id=ORG_SLOW,
                age_seconds=1000,
            )
        for i in range(5):
            await _device_reconnecting(db, svc, serial=f"fast-{i}", age_seconds=700)
        await db.commit()

    async with tenancy_session_factory() as db:
        stale = await list_stale_reconnecting_candidates(db, limit=20)
        assert len(stale) == 5
        assert all(c.org_id == ORG_ID for c in stale)

    marked = await run_dead_detection_once()
    assert marked == 5


@pytest.mark.asyncio
async def test_dead_detection_skipped_when_advisory_lock_held(
    tenancy_session_factory, dead_seed, dead_detector_db, monkeypatch,
):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        await _device_reconnecting(db, svc, age_seconds=700)
        await db.commit()

    monkeypatch.setattr(
        "services.device_state.dead_detector._try_advisory_lock",
        AsyncMock(return_value=False),
    )
    assert await run_dead_detection_once() == 0


# ── AC-4: Force-release session when RECONNECTING + active session ───────────


@pytest.mark.asyncio
async def test_ac4_force_release_session_on_dead(
    tenancy_session_factory, dead_seed, dead_detector_db
):
    svc = DeviceStateService()
    session_events: list[SessionLostDeviceEvent] = []

    def _capture_session(channel, payload):
        if channel != "session.lost_device":
            return
        session_events.append(
            SessionLostDeviceEvent(
                device_id=payload["device_id"],
                session_id=payload["session_id"],
                reason=payload["reason"],
                owner_user_id=payload.get("owner_user_id"),
            )
        )

    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(
            db, svc, age_seconds=700, session_id="S1"
        )
        await db.commit()

    with patch(
        "services.device_state.events._schedule_redis_publish",
        side_effect=_capture_session,
    ), patch(
        "services.device_state.service.DeviceStateService._notify_session_lost",
        new_callable=AsyncMock,
    ):
        await run_dead_detection_once()

    assert len(session_events) == 1
    assert session_events[0].session_id == "S1"
    assert session_events[0].reason == "device_lost"

    async with tenancy_session_factory() as db:
        snap = await db.get(DeviceFsmSnapshot, device.id)
        assert snap is not None
        assert snap.state == DeviceFsmState.DEAD.value
        assert snap.session_id is None
        lost_rows = (
            await db.execute(
                select(DeviceStateTransition).where(
                    DeviceStateTransition.device_id == device.id,
                    DeviceStateTransition.event == DeviceFsmEvent.SESSION_LOST.value,
                )
            )
        ).scalars().all()
        assert len(lost_rows) == 1
        assert lost_rows[0].from_state == DeviceFsmState.RECONNECTING.value


# ── AC-5: Admin revive DEAD → CONNECTING ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ac5_admin_revive(tenancy_session_factory, dead_seed):
    svc = DeviceStateService()
    revived: list[DeviceRevivedEvent] = []

    def _capture_revived(channel, payload):
        if channel != "device.revived":
            return
        revived.append(
            DeviceRevivedEvent(
                device_id=payload["device_id"],
                actor=payload["actor"],
            )
        )

    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(db, svc, age_seconds=700)
        await svc.mark_dead_reconnect_timeout(db, device.id, device_serial=device.serial)
        await db.commit()

    app = _build_app(tenancy_session_factory, user_id=ADMIN_ID, role="admin")
    with patch(
        "services.device_state.events._schedule_redis_publish",
        side_effect=_capture_revived,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/devices/{device.id}/revive")
    assert resp.status_code == 200
    body = resp.json()
    assert body["to_state"] == DeviceFsmState.CONNECTING.value
    assert body["actor"] == ADMIN_ID
    assert len(revived) == 1

    async with tenancy_session_factory() as db:
        assert await svc.get_state(db, device.id) == DeviceFsmState.CONNECTING
        audit = (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == device.id,
                    ActivityLog.action == "device.revived",
                )
            )
        ).scalars().first()
        assert audit is not None
        assert audit.user_id == ADMIN_ID


# ── Negative / edge cases ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tc04_online_device_skipped(
    tenancy_session_factory, dead_seed, dead_detector_db
):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await create_device(db, serial="online-skip", user_id=USER_ID, org_id=ORG_ID)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await db.commit()

    assert await run_dead_detection_once() == 0


@pytest.mark.asyncio
async def test_tc06_non_admin_revive_forbidden(tenancy_session_factory, dead_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(db, svc, age_seconds=700)
        await svc.mark_dead_reconnect_timeout(db, device.id)
        await db.commit()

    app = _build_app(tenancy_session_factory, user_id=USER_ID, role="operator")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(f"/api/devices/{device.id}/revive")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tc08_bulk_100_devices_marked_dead(
    tenancy_session_factory, dead_seed, dead_detector_db
):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        for i in range(100):
            await _device_reconnecting(db, svc, serial=f"bulk-{i}", age_seconds=700)
        await db.commit()

    started = time.perf_counter()
    marked = await run_dead_detection_once()
    elapsed = time.perf_counter() - started
    assert marked == 100
    assert elapsed < 10.0

    async with tenancy_session_factory() as db:
        dead_count = (
            await db.execute(
                select(func.count()).select_from(DeviceFsmSnapshot).where(
                    DeviceFsmSnapshot.state == DeviceFsmState.DEAD.value
                )
            )
        ).scalar_one()
        assert dead_count == 100


@pytest.mark.asyncio
async def test_dead_detection_drains_batches_over_limit(
    tenancy_session_factory, dead_seed, dead_detector_db, monkeypatch,
):
    """More than one scan batch must all transition to DEAD in a single worker run."""
    svc = DeviceStateService()
    monkeypatch.setattr(
        "services.device_state.dead_detector.DEAD_DETECTION_SCAN_LIMIT",
        50,
    )
    async with tenancy_session_factory() as db:
        for i in range(75):
            await _device_reconnecting(db, svc, serial=f"batch-{i}", age_seconds=700)
        await db.commit()

    marked = await run_dead_detection_once()
    assert marked == 75

    async with tenancy_session_factory() as db:
        dead_count = (
            await db.execute(
                select(func.count()).select_from(DeviceFsmSnapshot).where(
                    DeviceFsmSnapshot.state == DeviceFsmState.DEAD.value
                )
            )
        ).scalar_one()
        assert dead_count == 75


@pytest.mark.asyncio
async def test_agent_dead_force_releases_session(tenancy_session_factory, dead_seed):
    """Agent DEAD on BUSY device must force-release session via _commit_transition."""
    svc = DeviceStateService()
    session_events: list[SessionLostDeviceEvent] = []

    def _capture(channel, payload):
        if channel == "session.lost_device":
            session_events.append(
                SessionLostDeviceEvent(
                    device_id=payload["device_id"],
                    session_id=payload["session_id"],
                    reason=payload["reason"],
                    owner_user_id=payload.get("owner_user_id"),
                )
            )

    async with tenancy_session_factory() as db:
        device = await create_device(db, serial="busy-dead", user_id=USER_ID, org_id=ORG_ID)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await svc.claim(db, device.id, "S-busy", event_id="c1")
        await db.commit()

    with patch(
        "services.device_state.events._schedule_redis_publish",
        side_effect=_capture,
    ):
        async with tenancy_session_factory() as db:
            result = await svc.apply_event(
                db,
                device.id,
                event=DeviceFsmEvent.DEAD.value,
                source="agent",
                event_id="agent-dead-1",
            )
            await db.commit()

    assert result.outcome == ApplyOutcome.APPLIED
    assert len(session_events) == 1
    assert session_events[0].session_id == "S-busy"
    assert session_events[0].owner_user_id == USER_ID


@pytest.mark.asyncio
async def test_tc09_race_online_vs_dead_only_one_wins(tenancy_session_factory, dead_seed):
    """Concurrent ONLINE and DEAD: FSM row lock ensures one transition wins."""
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device, _ = await _device_reconnecting(db, svc, age_seconds=700)
        await db.commit()

    outcomes: list[str] = []

    async with tenancy_session_factory() as db1:
        async with tenancy_session_factory() as db2:
            r_online = await svc.apply_event(
                db1,
                device.id,
                event=DeviceFsmEvent.ONLINE.value,
                source="agent",
                event_id="race-online",
            )
            r_dead = await svc.mark_dead_reconnect_timeout(
                db2,
                device.id,
                event_id="race-dead",
            )
            await db1.commit()
            await db2.commit()
            outcomes.extend([r_online.outcome.value, r_dead.outcome.value])

    assert ApplyOutcome.APPLIED.value in outcomes
    async with tenancy_session_factory() as db:
        final = await svc.get_state(db, device.id)
        assert final in (DeviceFsmState.ONLINE, DeviceFsmState.DEAD)
