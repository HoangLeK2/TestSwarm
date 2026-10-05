"""DF-T-02-002 — Device FSM unit and integration tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.device import create_device
from db.models import Organization, User
from db.models.device_fsm import DeviceFsmSnapshot, DeviceStateTransition
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from services.device_state.events import DeviceStateChangedEvent, add_device_state_listener
from services.device_state.exceptions import DeviceNotAvailableError
from services.device_state.fsm import all_event_state_pairs, resolve_transition
from services.device_state.service import (
    ApplyOutcome,
    DeviceStateService,
    RECONNECTING_TTL_SECONDS,
    list_reconnecting_past_ttl,
)
from tenancy.context import set_current_org_id

USER_ID = "user-device-fsm"
ORG_ID = "org-device-fsm"


@pytest_asyncio.fixture
async def fsm_org_seed(tenancy_session_factory):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="Device FSM Org",
                business_email="fsm-devices@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="fsm-devices@test.local",
                name="Device FSM Tester",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        await db.commit()
    set_current_org_id(ORG_ID)


async def _new_device(db: AsyncSession, serial: str = "df-001"):
    return await create_device(db, serial=serial, user_id=USER_ID, org_id=ORG_ID)


# ── FSM matrix ────────────────────────────────────────────────────────────────


class TestDeviceFsmMatrix:
    def test_unknown_to_connecting_on_attached(self):
        assert (
            resolve_transition(DeviceFsmState.UNKNOWN, DeviceFsmEvent.ATTACHED, source="agent")
            == DeviceFsmState.CONNECTING
        )

    def test_unknown_busy_is_illegal(self):
        assert (
            resolve_transition(DeviceFsmState.UNKNOWN, DeviceFsmEvent.BUSY, source="agent")
            == "ILLEGAL"
        )

    def test_agent_busy_ignored_from_online(self):
        assert resolve_transition(DeviceFsmState.ONLINE, DeviceFsmEvent.BUSY, source="agent") == "IGNORE"

    def test_matrix_has_at_least_36_pairs(self):
        pairs = all_event_state_pairs()
        assert len(pairs) >= 36

    def test_dead_claim_illegal_via_service_resolution(self):
        assert (
            resolve_transition(DeviceFsmState.DEAD, DeviceFsmEvent.SESSION_CLAIM, source="claim")
            == "ILLEGAL"
        )


# ── Acceptance criteria ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac1_unknown_connecting_online(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await db.commit()

    async with tenancy_session_factory() as db:
        r1 = await svc.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="evt-1",
        )
        await db.commit()
        assert r1.outcome == ApplyOutcome.APPLIED
        assert r1.to_state == DeviceFsmState.CONNECTING

        r2 = await svc.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="evt-2",
        )
        await db.commit()
        assert r2.outcome == ApplyOutcome.APPLIED
        assert r2.to_state == DeviceFsmState.ONLINE

        rows = (
            await db.execute(
                select(DeviceStateTransition).where(
                    DeviceStateTransition.device_id == device.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert rows[0].from_state == DeviceFsmState.UNKNOWN.value
        assert rows[0].to_state == DeviceFsmState.CONNECTING.value
        assert rows[0].event == DeviceFsmEvent.ATTACHED.value


@pytest.mark.asyncio
async def test_ac2_illegal_transition_stays_unknown(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await db.commit()

    async with tenancy_session_factory() as db:
        result = await svc.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.BUSY.value,
            source="agent",
            event_id="evt-bad",
        )
        await db.commit()
        assert result.outcome == ApplyOutcome.ILLEGAL
        state = await svc.get_state(db, device.id)
        assert state == DeviceFsmState.UNKNOWN
        count = (
            await db.execute(
                select(func.count()).select_from(DeviceStateTransition).where(
                    DeviceStateTransition.device_id == device.id
                )
            )
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_ac3_busy_only_via_claim(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        claim = await svc.claim(db, device.id, "S1", event_id="claim-1")
        await db.commit()
        assert claim.to_state == DeviceFsmState.BUSY

        ignored = await svc.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.BUSY.value,
            source="agent",
            event_id="evt-agent-busy",
        )
        await db.commit()
        assert ignored.outcome == ApplyOutcome.IGNORED
        assert await svc.get_state(db, device.id) == DeviceFsmState.BUSY


@pytest.mark.asyncio
async def test_ac4_idempotent_event_id(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        outcomes = []
        for _ in range(5):
            result = await svc.apply_event(
                db,
                device.id,
                event=DeviceFsmEvent.ONLINE.value,
                source="agent",
                event_id="evt-123",
            )
            outcomes.append(result.outcome)
        await db.commit()
        assert outcomes[0] == ApplyOutcome.APPLIED
        assert all(o == ApplyOutcome.DEDUPED for o in outcomes[1:])
        count = (
            await db.execute(
                select(func.count()).select_from(DeviceStateTransition).where(
                    DeviceStateTransition.device_id == device.id,
                    DeviceStateTransition.event_id == "evt-123",
                )
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_ac5_release_busy_to_online(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await svc.claim(db, device.id, "S1", event_id="c1")
        await db.commit()

    async with tenancy_session_factory() as db:
        released = await svc.release(db, device.id, "S1", event_id="r1")
        await db.commit()
        assert released.to_state == DeviceFsmState.ONLINE
        row = (
            await db.execute(
                select(DeviceStateTransition)
                .where(DeviceStateTransition.device_id == device.id)
                .order_by(DeviceStateTransition.id.desc())
            )
        ).scalars().first()
        assert row is not None
        assert row.event == DeviceFsmEvent.SESSION_RELEASED.value


@pytest.mark.asyncio
async def test_ac6_state_persists_after_reload(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    device_id = None
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        device_id = device.id
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await svc.claim(db, device.id, "S1", event_id="c1")
        await db.commit()

    async with tenancy_session_factory() as db:
        state = await svc.get_state(db, device_id)
        assert state == DeviceFsmState.BUSY
        count = (
            await db.execute(
                select(func.count()).select_from(DeviceStateTransition).where(
                    DeviceStateTransition.device_id == device_id
                )
            )
        ).scalar_one()
        assert count == 3


@pytest.mark.asyncio
async def test_claim_on_dead_raises_not_available(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.DEAD.value, source="agent", event_id="d1"
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        with pytest.raises(DeviceNotAvailableError):
            await svc.claim(db, device.id, "S1")


@pytest.mark.asyncio
async def test_device_state_changed_event_emitted(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    captured: list[DeviceStateChangedEvent] = []
    unsub = add_device_state_listener(lambda e: captured.append(e))
    try:
        async with tenancy_session_factory() as db:
            device = await _new_device(db)
            await db.commit()

        async with tenancy_session_factory() as db:
            await svc.apply_event(
                db,
                device.id,
                event=DeviceFsmEvent.ATTACHED.value,
                source="agent",
                event_id="emit-1",
            )
            await db.commit()
        assert len(captured) == 1
        assert captured[0].event == DeviceFsmEvent.ATTACHED.value
        assert captured[0].to_state == DeviceFsmState.CONNECTING.value
    finally:
        unsub()


@pytest.mark.asyncio
async def test_reconnecting_past_ttl_hook(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await svc.apply_event(
            db,
            device.id,
            event=DeviceFsmEvent.RECONNECTING.value,
            source="agent",
            event_id="e3",
        )
        snap = await db.get(DeviceFsmSnapshot, device.id)
        assert snap is not None
        snap.reconnecting_since = datetime.now(timezone.utc) - timedelta(
            seconds=RECONNECTING_TTL_SECONDS + 10
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        stale = await list_reconnecting_past_ttl(db, ttl_seconds=RECONNECTING_TTL_SECONDS)
        assert any(row.device_id == device.id for row in stale)


@pytest.mark.asyncio
async def test_bulk_transitions_performance(tenancy_session_factory, fsm_org_seed):
    """1000 CONNECTING→ONLINE transitions complete in reasonable time."""
    import time

    svc = DeviceStateService()
    device_ids: list[str] = []
    async with tenancy_session_factory() as db:
        for i in range(1000):
            d = await _new_device(db, serial=f"perf-{i}")
            device_ids.append(d.id)
            await svc.apply_event(
                db,
                d.id,
                event=DeviceFsmEvent.ATTACHED.value,
                source="agent",
                event_id=f"a-{i}",
            )
        await db.commit()

    started = time.perf_counter()
    async with tenancy_session_factory() as db:
        for i, device_id in enumerate(device_ids):
            await svc.apply_event(
                db,
                device_id,
                event=DeviceFsmEvent.ONLINE.value,
                source="agent",
                event_id=f"o-{i}",
            )
        await db.commit()
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_stale_numeric_event_id_ignored(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="10"
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        stale = await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="9"
        )
        await db.commit()
        assert stale.outcome == ApplyOutcome.IGNORED
        assert await svc.get_state(db, device.id) == DeviceFsmState.CONNECTING


@pytest.mark.asyncio
async def test_claim_idempotent_same_event_id(tenancy_session_factory, fsm_org_seed):
    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        device = await _new_device(db)
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ATTACHED.value, source="agent", event_id="e1"
        )
        await svc.apply_event(
            db, device.id, event=DeviceFsmEvent.ONLINE.value, source="agent", event_id="e2"
        )
        await db.commit()

    async with tenancy_session_factory() as db:
        first = await svc.claim(db, device.id, "S1", event_id="claim-dup")
        second = await svc.claim(db, device.id, "S1", event_id="claim-dup")
        await db.commit()
        assert first.to_state == DeviceFsmState.BUSY
        assert second.outcome == ApplyOutcome.DEDUPED
        assert second.to_state == DeviceFsmState.BUSY
