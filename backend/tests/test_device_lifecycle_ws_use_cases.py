"""DF-T-02-015 — Device lifecycle WebSocket end-to-end use-case tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from auth.secret_versioning import JwtKeyMaterial
from db.crud.device import create_device
from db.models import Organization, OrganizationMember, User
from db.models.enums import DeviceFsmEvent, DeviceFsmState
from services.device_state.lifecycle_schema import LifecycleEventType
from services.device_state.replay_store import replay_store
from services.device_state.service import DeviceStateService
from services.device_state.ws_publisher import DEBOUNCE_MS, DeviceLifecyclePublisher
from tenancy.context import tenant_context
from web.ws_lifecycle import DeviceLifecycleWsManager

_SECRET = "test-secret-key-long-enough-for-hs256-tests"
_ALG = "HS256"
ORG_A = "org-lifecycle-uc-a"
ORG_B = "org-lifecycle-uc-b"
USER_A = "user-lifecycle-uc-a"
USER_B = "user-lifecycle-uc-b"
USER_DENIED = "user-lifecycle-denied"


def _token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    org_id = ORG_A if user_id in {USER_A, USER_DENIED} else ORG_B
    return jwt.encode(
        {"sub": user_id, "type": "access", "org_id": org_id, "exp": exp},
        _SECRET,
        algorithm=_ALG,
    )


@pytest.fixture
def jwt_patch():
    with (
        patch(
            "api.auth.context.all_verify_materials",
            return_value=[JwtKeyMaterial(kid="v1", secret=_SECRET)],
        ),
        patch("api.auth.context.jwt_algorithm", return_value=_ALG),
    ):
        yield


async def _seed_lifecycle_orgs(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        db.add_all(
            [
                Organization(
                    id=ORG_A,
                    business_name="Org A",
                    business_email="a@uc.test",
                    status="active",
                    plan="standard",
                    created_at=now,
                ),
                Organization(
                    id=ORG_B,
                    business_name="Org B",
                    business_email="b@uc.test",
                    status="active",
                    plan="standard",
                    created_at=now,
                ),
            ]
        )
        db.add_all(
            [
                User(
                    id=USER_A,
                    email="a@uc.test",
                    name="User A",
                    hashed_password="x",
                    org_id=ORG_A,
                    role="operator",
                ),
                User(
                    id=USER_B,
                    email="b@uc.test",
                    name="User B",
                    hashed_password="x",
                    org_id=ORG_B,
                    role="operator",
                ),
                User(
                    id=USER_DENIED,
                    email="denied@uc.test",
                    name="Denied",
                    hashed_password="x",
                    org_id=ORG_A,
                    role="viewer",
                ),
            ]
        )
        await db.flush()
        db.add_all(
            [
                OrganizationMember(
                    id="mem-a",
                    organization_id=ORG_A,
                    user_id=USER_A,
                    role="member",
                    created_at=now,
                ),
                OrganizationMember(
                    id="mem-b",
                    organization_id=ORG_B,
                    user_id=USER_B,
                    role="member",
                    created_at=now,
                ),
            ]
        )
        dev_a = await create_device(db, serial="uc-a-1", user_id=USER_A, org_id=ORG_A)
        dev_b = await create_device(db, serial="uc-b-1", user_id=USER_B, org_id=ORG_B)
        await db.commit()

    svc = DeviceStateService()
    async with session_factory() as db:
        with tenant_context(ORG_A):
            await svc.apply_event(
                db,
                dev_a.id,
                event=DeviceFsmEvent.ATTACHED.value,
                source="agent",
                event_id="uc-a-attach",
            )
            await svc.apply_event(
                db,
                dev_a.id,
                event=DeviceFsmEvent.ONLINE.value,
                source="agent",
                event_id="uc-a-online",
            )
        with tenant_context(ORG_B):
            await svc.apply_event(
                db,
                dev_b.id,
                event=DeviceFsmEvent.ATTACHED.value,
                source="agent",
                event_id="uc-b-attach",
            )
        await db.commit()

    return {"dev_a": dev_a.id, "dev_b": dev_b.id}


def _lifecycle_app(session_factory: async_sessionmaker[AsyncSession]) -> tuple[FastAPI, DeviceLifecycleWsManager, DeviceLifecyclePublisher]:
    app = FastAPI()
    manager = DeviceLifecycleWsManager()
    publisher = DeviceLifecyclePublisher()
    manager.bind_publisher(publisher)

    @app.websocket("/ws/lifecycle")
    async def _ws_lifecycle(ws: WebSocket):
        await manager.connect(ws)

    return app, manager, publisher


class TestLifecycleWsUseCases:
    def test_uc_be_01_connect_receives_snapshot_with_device_states(
        self, tenancy_session_factory, jwt_patch
    ):
        async def _run():
            return await _seed_lifecycle_orgs(tenancy_session_factory)

        ids = asyncio.run(_run())
        replay_store._orgs.clear()

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory), patch(
            "services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory
        ):
            app, _, _ = _lifecycle_app(tenancy_session_factory)
            with TestClient(app) as client:
                with client.websocket_connect(
                    f"/ws/lifecycle?token={_token(USER_A)}"
                ) as ws:
                    msg = ws.receive_json()
                    assert msg["type"] == "lifecycle.snapshot"
                    assert msg["organization_id"] == ORG_A
                    states = {d["device_id"]: d["state"] for d in msg["devices"]}
                    assert states[ids["dev_a"]] == DeviceFsmState.ONLINE.value
                    assert isinstance(msg["replay"], list)

    def test_uc_be_02_denied_without_devices_read_permission(
        self, tenancy_session_factory, jwt_patch
    ):
        async def _run():
            return await _seed_lifecycle_orgs(tenancy_session_factory)

        asyncio.run(_run())

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory):
            app, _, _ = _lifecycle_app(tenancy_session_factory)
            with TestClient(app) as client:
                with pytest.raises(Exception):
                    with client.websocket_connect(
                        f"/ws/lifecycle?token={_token(USER_DENIED)}"
                    ):
                        pass

    def test_uc_be_03_ping_receives_pong(self, tenancy_session_factory, jwt_patch):
        async def _run():
            return await _seed_lifecycle_orgs(tenancy_session_factory)

        asyncio.run(_run())

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory), patch(
            "services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory
        ):
            app, _, _ = _lifecycle_app(tenancy_session_factory)
            with TestClient(app) as client:
                with client.websocket_connect(
                    f"/ws/lifecycle?token={_token(USER_A)}"
                ) as ws:
                    _ = ws.receive_json()
                    ws.send_text("ping")
                    pong = ws.receive_json()
                    assert pong == {"type": "pong"}

    def test_uc_be_04_org_isolation_two_clients(
        self, tenancy_session_factory, jwt_patch
    ):
        async def _run():
            return await _seed_lifecycle_orgs(tenancy_session_factory)

        ids = asyncio.run(_run())

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory), patch(
            "services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory
        ):
            app, manager, publisher = _lifecycle_app(tenancy_session_factory)
            publisher._org_device_cache[ids["dev_a"]] = (ORG_A, 0.0)
            publisher._org_device_cache[ids["dev_b"]] = (ORG_B, 0.0)

            with TestClient(app) as client:
                with client.websocket_connect(
                    f"/ws/lifecycle?token={_token(USER_A)}"
                ) as ws_a:
                    _ = ws_a.receive_json()
                    with client.websocket_connect(
                        f"/ws/lifecycle?token={_token(USER_B)}"
                    ) as ws_b:
                        _ = ws_b.receive_json()

                        asyncio.run(
                            manager.broadcast_to_org(
                                ORG_A,
                                {
                                    "type": "lifecycle.event",
                                    "event": {
                                        "type": LifecycleEventType.DEVICE_STATE_CHANGED,
                                        "event_id": "iso-a",
                                        "organization_id": ORG_A,
                                        "device_id": ids["dev_a"],
                                        "from_state": "online",
                                        "to_state": "busy",
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                    },
                                },
                            )
                        )

                        a_msg = ws_a.receive_json()
                        assert a_msg["type"] == "lifecycle.event"
                        assert a_msg["event"]["device_id"] == ids["dev_a"]
                        # Org B client must not receive org A broadcast (no second frame).

    @pytest.mark.asyncio
    async def test_uc_be_05_publisher_live_event_reaches_connected_client(
        self, tenancy_session_factory, jwt_patch
    ):
        ids = await _seed_lifecycle_orgs(tenancy_session_factory)

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory), patch(
            "services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory
        ):
            app, _, publisher = _lifecycle_app(tenancy_session_factory)
            publisher.set_event_loop(asyncio.get_running_loop())
            publisher._org_device_cache[ids["dev_a"]] = (ORG_A, 0.0)

            with TestClient(app) as client:
                with client.websocket_connect(
                    f"/ws/lifecycle?token={_token(USER_A)}"
                ) as ws:
                    _ = ws.receive_json()
                    from services.device_state.events import DeviceStateChangedEvent

                    await publisher._enqueue_fsm_event(
                        DeviceStateChangedEvent(
                            device_id=ids["dev_a"],
                            from_state="online",
                            to_state="busy",
                            event=DeviceFsmEvent.SESSION_CLAIM.value,
                            source="claim",
                            event_id="uc-claim-1",
                            session_id="exec:uc-1",
                        )
                    )
                    await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.08)
                    live = ws.receive_json()
                    assert live["type"] == "lifecycle.event"
                    assert live["event"]["type"] == LifecycleEventType.SESSION_CLAIMED
                    assert live["event"]["session_id"] == "exec:uc-1"

    @pytest.mark.asyncio
    async def test_uc_be_06_unpair_event_broadcast(
        self, tenancy_session_factory, jwt_patch
    ):
        ids = await _seed_lifecycle_orgs(tenancy_session_factory)

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory), patch(
            "services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory
        ):
            app, _, publisher = _lifecycle_app(tenancy_session_factory)

            with TestClient(app) as client:
                with client.websocket_connect(
                    f"/ws/lifecycle?token={_token(USER_A)}"
                ) as ws:
                    _ = ws.receive_json()
                    await publisher.publish_unpaired(
                        device_id=ids["dev_a"],
                        organization_id=ORG_A,
                        from_state="online",
                        session_id=None,
                    )
                    msg = ws.receive_json()
                    assert msg["event"]["type"] == LifecycleEventType.DEVICE_UNPAIRED
                    assert msg["event"]["device_id"] == ids["dev_a"]

    @pytest.mark.asyncio
    async def test_uc_be_07_snapshot_replay_contains_recent_published_events(
        self, tenancy_session_factory, jwt_patch
    ):
        ids = await _seed_lifecycle_orgs(tenancy_session_factory)
        replay_store._orgs.clear()

        with patch("web.ws_lifecycle.AsyncSessionLocal", tenancy_session_factory), patch(
            "services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory
        ):
            app, _, publisher = _lifecycle_app(tenancy_session_factory)
            publisher.set_event_loop(asyncio.get_running_loop())
            publisher._org_device_cache[ids["dev_a"]] = (ORG_A, 0.0)

            from services.device_state.events import DeviceStateChangedEvent

            await publisher._enqueue_fsm_event(
                DeviceStateChangedEvent(
                    device_id=ids["dev_a"],
                    from_state="online",
                    to_state="reconnecting",
                    event=DeviceFsmEvent.RECONNECTING.value,
                    source="agent",
                    event_id="uc-replay-1",
                )
            )
            await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.08)

            snapshot = await publisher.build_snapshot(ORG_A)
            replay_ids = {e["event_id"] for e in snapshot.replay}
            assert "uc-replay-1" in replay_ids

    @pytest.mark.asyncio
    async def test_uc_be_08_debounced_batch_coalesces_same_org(
        self, tenancy_session_factory, jwt_patch
    ):
        ids = await _seed_lifecycle_orgs(tenancy_session_factory)

        async with tenancy_session_factory() as db:
            dev_a2 = await create_device(db, serial="uc-a-2", user_id=USER_A, org_id=ORG_A)
            await db.commit()

        with patch("services.device_state.ws_publisher.AsyncSessionLocal", tenancy_session_factory):
            publisher = DeviceLifecyclePublisher()
            received: list[dict] = []

            class _Capture:
                async def broadcast_to_org(self, org_id: str, message: dict) -> None:
                    received.append(message)

            cap = _Capture()
            publisher.bind_ws_manager(cap)
            publisher.set_event_loop(asyncio.get_running_loop())
            publisher._org_device_cache[ids["dev_a"]] = (ORG_A, 0.0)
            publisher._org_device_cache[dev_a2.id] = (ORG_A, 0.0)

            from services.device_state.events import DeviceStateChangedEvent

            await publisher._enqueue_fsm_event(
                DeviceStateChangedEvent(
                    device_id=ids["dev_a"],
                    from_state="online",
                    to_state="reconnecting",
                    event=DeviceFsmEvent.RECONNECTING.value,
                    source="agent",
                    event_id="batch-1",
                )
            )
            await publisher._enqueue_fsm_event(
                DeviceStateChangedEvent(
                    device_id=dev_a2.id,
                    from_state="unknown",
                    to_state="connecting",
                    event=DeviceFsmEvent.ATTACHED.value,
                    source="agent",
                    event_id="batch-2",
                )
            )
            await asyncio.sleep(DEBOUNCE_MS / 1000.0 + 0.08)
            assert len(received) == 1
            assert received[0]["type"] == "lifecycle.batch"
            assert len(received[0]["events"]) == 2
