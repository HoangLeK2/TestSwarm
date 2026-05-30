"""DF-T-02-015 — Device lifecycle WebSocket stream tests."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from jose import jwt

from db.crud.device import create_device
from db.models import Organization, User
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from services.device_state.events import DeviceStateChangedEvent
from services.device_state.lifecycle_schema import (
    LifecycleEventType,
    map_fsm_event_type,
    new_lifecycle_event,
)
from services.device_state.replay_store import LifecycleReplayStore
from services.device_state.ws_publisher import DeviceLifecyclePublisher, DEBOUNCE_MS
from tenancy.context import set_current_org_id, tenant_context
from web.ws_lifecycle import DeviceLifecycleWsManager, QUEUE_MAX

_SECRET = "test-secret-key-long-enough-for-hs256-tests"
_ALG = "HS256"
USER_ID = "user-lifecycle-ws"
ORG_A = "org-lifecycle-a"
ORG_B = "org-lifecycle-b"


def _token(user_id: str = USER_ID) -> str:
    from datetime import timedelta

    exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    return jwt.encode({"sub": user_id, "type": "access", "exp": exp}, _SECRET, algorithm=_ALG)


@pytest.fixture
def jwt_patch():
    with (
        patch("api.auth.context.jwt_secret_key", return_value=_SECRET),
        patch("api.auth.context.jwt_algorithm", return_value=_ALG),
    ):
        yield


class TestLifecycleSchema:
    def test_map_session_claim_to_claimed(self):
        assert map_fsm_event_type(DeviceFsmEvent.SESSION_CLAIM.value) == LifecycleEventType.SESSION_CLAIMED

    def test_map_session_released(self):
        assert map_fsm_event_type(DeviceFsmEvent.SESSION_RELEASED.value) == LifecycleEventType.SESSION_RELEASED

    def test_map_online_to_state_changed(self):
        assert map_fsm_event_type(DeviceFsmEvent.ONLINE.value) == LifecycleEventType.DEVICE_STATE_CHANGED

    def test_event_payload_has_required_fields(self):
        ev = new_lifecycle_event(
            event_type=LifecycleEventType.DEVICE_STATE_CHANGED,
            organization_id=ORG_A,
            device_id="dev-1",
            from_state="unknown",
            to_state="online",
            session_id="sess-1",
            event_id="evt-1",
        )
        data = ev.to_dict()
        assert data["event_id"] == "evt-1"
        assert data["organization_id"] == ORG_A
        assert data["device_id"] == "dev-1"
        assert data["session_id"] == "sess-1"
        assert data["from_state"] == "unknown"
        assert data["to_state"] == "online"
        assert data["timestamp"]


class TestReplayStore:
    def test_recent_respects_ttl(self):
        store = LifecycleReplayStore()
        store._ttl = 0.05
        store.append(ORG_A, {"event_id": "e1"})
        assert len(store.recent(ORG_A)) == 1
        time.sleep(0.06)
        assert store.recent(ORG_A) == []

    def test_max_per_org_trim(self):
        store = LifecycleReplayStore()
        store._max = 3
        for i in range(5):
            store.append(ORG_A, {"event_id": f"e{i}"})
        recent = store.recent(ORG_A)
        assert len(recent) == 3
        assert recent[0]["event_id"] == "e2"


@pytest.mark.asyncio
async def test_publisher_debounce_batches_same_org(tenancy_session_factory, jwt_patch):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_A,
                business_name="Org A",
                business_email="a@test.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="lifecycle@test.local",
                name="Lifecycle",
                hashed_password="x",
                org_id=ORG_A,
            )
        )
        dev1 = await create_device(db, serial="lc-1", user_id=USER_ID, org_id=ORG_A)
        dev2 = await create_device(db, serial="lc-2", user_id=USER_ID, org_id=ORG_A)
        await db.commit()

    set_current_org_id(ORG_A)
    ws_manager = AsyncMock()
    publisher = DeviceLifecyclePublisher()
    publisher.bind_ws_manager(ws_manager)
    publisher.set_event_loop(asyncio.get_running_loop())
    publisher._org_device_cache[dev1.id] = (ORG_A, 0.0)
    publisher._org_device_cache[dev2.id] = (ORG_A, 0.0)

    await publisher._enqueue_fsm_event(
        DeviceStateChangedEvent(
            device_id=dev1.id,
            from_state="unknown",
            to_state="connecting",
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="e1",
        )
    )
    await publisher._enqueue_fsm_event(
        DeviceStateChangedEvent(
            device_id=dev2.id,
            from_state="unknown",
            to_state="connecting",
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="e2",
        )
    )
    await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.05)
    ws_manager.broadcast_to_org.assert_awaited()
    call_args = ws_manager.broadcast_to_org.await_args
    assert call_args[0][0] == ORG_A
    msg = call_args[0][1]
    assert msg["type"] == "lifecycle.batch"
    assert len(msg["events"]) == 2


@pytest.mark.asyncio
async def test_publisher_maps_session_claimed(tenancy_session_factory, jwt_patch):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_A,
                business_name="Org A",
                business_email="a@test.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        dev = await create_device(db, serial="lc-claim", user_id=USER_ID, org_id=ORG_A)
        await db.commit()

    ws_manager = AsyncMock()
    publisher = DeviceLifecyclePublisher()
    publisher.bind_ws_manager(ws_manager)
    publisher.set_event_loop(asyncio.get_running_loop())
    publisher._org_device_cache[dev.id] = (ORG_A, 0.0)

    await publisher._enqueue_fsm_event(
        DeviceStateChangedEvent(
            device_id=dev.id,
            from_state="online",
            to_state="busy",
            event=DeviceFsmEvent.SESSION_CLAIM.value,
            source="claim",
            event_id="claim-1",
            session_id="sess-1",
        )
    )
    await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.05)
    msg = ws_manager.broadcast_to_org.await_args[0][1]
    assert msg["event"]["type"] == LifecycleEventType.SESSION_CLAIMED


def test_lifecycle_ws_rejects_missing_token(jwt_patch):
    app = FastAPI()
    manager = DeviceLifecycleWsManager()

    @app.websocket("/ws/lifecycle")
    async def _ws(ws: WebSocket):
        await manager.connect(ws)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/lifecycle"):
                pass


def test_lifecycle_ws_rejects_invalid_token(jwt_patch):
    app = FastAPI()
    manager = DeviceLifecycleWsManager()

    @app.websocket("/ws/lifecycle")
    async def _ws(ws: WebSocket):
        await manager.connect(ws)

    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/lifecycle?token=not-a-jwt"):
                pass


@pytest.mark.asyncio
async def test_lifecycle_ws_org_isolation_on_broadcast():
    manager = DeviceLifecycleWsManager()
    q_a: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
    q_b: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
    manager._queues = {"a": q_a, "b": q_b}
    manager._org_ids = {"a": ORG_A, "b": ORG_B}

    await manager.broadcast_to_org(ORG_A, {"type": "lifecycle.event", "event": {"event_id": "x"}})
    assert not q_b.qsize()
    assert q_a.qsize() == 1


@pytest.mark.asyncio
async def test_lifecycle_ws_backpressure_increments_metric():
    from web.metrics import lifecycle_ws_backpressure_total

    manager = DeviceLifecycleWsManager()
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    q.put_nowait({"type": "lifecycle.event", "event": {"event_id": "old"}})
    manager._queues = {"c1": q}
    manager._org_ids = {"c1": ORG_A}

    before = lifecycle_ws_backpressure_total.labels(org_id=ORG_A)._value.get()
    await manager.broadcast_to_org(ORG_A, {"type": "lifecycle.event", "event": {"event_id": "new"}})
    after = lifecycle_ws_backpressure_total.labels(org_id=ORG_A)._value.get()
    assert after > before
    assert q.qsize() == 1
    assert q.get_nowait()["event"]["event_id"] == "new"


@pytest.mark.asyncio
async def test_lifecycle_ws_disconnect_idempotent():
    manager = DeviceLifecycleWsManager()
    manager._connections["c1"] = MagicMock()
    manager._queues["c1"] = asyncio.Queue()
    manager._org_ids["c1"] = ORG_A
    from web.metrics import lifecycle_ws_clients_connected

    before = lifecycle_ws_clients_connected._value.get()
    await manager._disconnect("c1")
    await manager._disconnect("c1")
    assert lifecycle_ws_clients_connected._value.get() == before - 1


@pytest.mark.asyncio
async def test_build_snapshot_includes_device_states(tenancy_session_factory, jwt_patch):
    from services.device_state.service import DeviceStateService

    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_A,
                business_name="Org A",
                business_email="a@test.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        dev = await create_device(db, serial="lc-snap", user_id=USER_ID, org_id=ORG_A)
        await db.commit()

    svc = DeviceStateService()
    async with tenancy_session_factory() as db:
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ATTACHED.value,
            source="agent",
            event_id="snap-1",
        )
        await svc.apply_event(
            db,
            dev.id,
            event=DeviceFsmEvent.ONLINE.value,
            source="agent",
            event_id="snap-2",
        )
        await db.commit()

    publisher = DeviceLifecyclePublisher()
    with patch("services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory):
        with tenant_context(ORG_A):
            snapshot = await publisher.build_snapshot(ORG_A)
    assert snapshot.organization_id == ORG_A
    states = {d.device_id: d.state for d in snapshot.devices}
    assert states[dev.id] == DeviceFsmState.ONLINE.value


@pytest.mark.asyncio
async def test_publish_unpaired_event(tenancy_session_factory):
    ws_manager = AsyncMock()
    publisher = DeviceLifecyclePublisher()
    publisher.bind_ws_manager(ws_manager)

    await publisher.publish_unpaired(
        device_id="dev-del",
        organization_id=ORG_A,
        from_state="online",
        session_id=None,
    )
    ws_manager.broadcast_to_org.assert_awaited_once()
    msg = ws_manager.broadcast_to_org.await_args[0][1]
    assert msg["event"]["type"] == LifecycleEventType.DEVICE_UNPAIRED
