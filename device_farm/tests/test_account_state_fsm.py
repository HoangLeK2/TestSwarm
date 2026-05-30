"""DF-T-07-005 — Account state FSM unit and API tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.account import create_account, list_active_account_ids, round_robin_assign
from db.crud.account_event import list_account_events
from db.crud.account_group import add_members, create_group, pick_next_batch
from db.models import Organization, User
from db.models.device import Device
from tenancy.context import clear_current_org_id, set_current_org_id
from db.models.enums import AccountEventType, AccountState
from db.models.utils import _uuid
from fastapi import FastAPI
from services.account_state.exceptions import InvalidStateTransitionError, InvalidTtlError
from services.account_state.fsm import all_transition_pairs, can_transition, transition_error_message
from services.account_state.service import AccountStateService, process_expired_cooldowns
from services.account_event_recorder import AccountEventRecorder, reset_account_event_recorder
from types import SimpleNamespace


USER_ID = "user-fsm-test"
ORG_ID = "org-fsm-test"


async def _new_account(db: AsyncSession, username: str):
    return await create_account(
        db,
        platform="facebook",
        username=username,
        user_id=USER_ID,
        org_id=ORG_ID,
    )


def _build_app(session_factory):
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
            id=USER_ID,
            email="fsm@test.local",
            name="FSM Tester",
            role="operator",
            org_role="owner",
            is_active=True,
            org_id=ORG_ID,
        )

    app.dependency_overrides[_get_db] = _db
    app.dependency_overrides[_get_current_user] = _user
    return app


@pytest_asyncio.fixture
async def fsm_seed(tenancy_session_factory):
    now = datetime.now(timezone.utc)
    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=ORG_ID,
                business_name="FSM Org",
                business_email="fsm@org.local",
                status="active",
                plan="standard",
                created_at=now,
            )
        )
        db.add(
            User(
                id=USER_ID,
                email="fsm@test.local",
                name="FSM Tester",
                hashed_password="hashed",
                org_id=ORG_ID,
            )
        )
        await db.commit()
    set_current_org_id(ORG_ID)


@pytest_asyncio.fixture
async def fsm_client(tenancy_session_factory, fsm_seed):
    app = _build_app(tenancy_session_factory)
    reset_account_event_recorder(AccountEventRecorder(enabled=True, max_pending=100))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tenancy_session_factory
    reset_account_event_recorder()


# ── FSM matrix ────────────────────────────────────────────────────────────────


class TestAccountStateFsmMatrix:
    def test_terminal_retired_blocks_all_exits(self):
        assert not can_transition(AccountState.RETIRED, AccountState.ACTIVE)
        assert "terminal" in transition_error_message(
            AccountState.RETIRED, AccountState.ACTIVE
        )

    def test_banned_only_retires(self):
        assert can_transition(AccountState.BANNED, AccountState.RETIRED)
        assert not can_transition(AccountState.BANNED, AccountState.ACTIVE)

    def test_active_to_cooldown_allowed(self):
        assert can_transition(AccountState.ACTIVE, AccountState.COOLDOWN)

    def test_full_matrix_snapshot(self):
        allowed = {(a.value, b.value) for a, b, ok in all_transition_pairs() if ok}
        assert ("active", "cooldown") in allowed
        assert ("cooldown", "active") in allowed
        assert ("banned", "retired") in allowed
        assert ("retired", "active") not in allowed


# ── Service ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transition_active_to_cooldown_sets_ttl(
    tenancy_session_factory, fsm_seed
):
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "cool1")
        await db.commit()
        svc = AccountStateService()
        updated = await svc.transition(
            db,
            acc.id,
            to=AccountState.COOLDOWN,
            reason="FB rate limit",
            ttl_seconds=3600,
            actor=USER_ID,
        )
        await db.commit()
        assert updated.state == "cooldown"
        assert updated.cooldown_until is not None
        assert updated.state_reason == "FB rate limit"


@pytest.mark.asyncio
async def test_invalid_ttl_rejected(tenancy_session_factory, fsm_seed):
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "badttl")
        await db.commit()
        svc = AccountStateService()
        with pytest.raises(InvalidTtlError):
            await svc.transition(
                db,
                acc.id,
                to=AccountState.COOLDOWN,
                reason="x",
                ttl_seconds=-1,
                actor=USER_ID,
            )


@pytest.mark.asyncio
async def test_process_expired_cooldowns_without_tenant_context(
    tenancy_session_factory, fsm_seed
):
    """Background/Temporal jobs run without request org context."""
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "expired-no-ctx")
        svc = AccountStateService()
        await svc.transition(
            db,
            acc.id,
            to=AccountState.COOLDOWN,
            reason="test",
            ttl_seconds=60,
            actor=USER_ID,
        )
        acc.cooldown_until = past
        await db.commit()

    clear_current_org_id()
    async with tenancy_session_factory() as db:
        n = await process_expired_cooldowns(db)
        await db.commit()
        assert n == 1
        from db.crud.account import get_account

        set_current_org_id(ORG_ID)
        row = await get_account(db, acc.id)
        assert row.state == "active"
        assert row.cooldown_until is None


@pytest.mark.asyncio
async def test_process_expired_cooldowns_auto_active(
    tenancy_session_factory, fsm_seed
):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "expired")
        svc = AccountStateService()
        await svc.transition(
            db,
            acc.id,
            to=AccountState.COOLDOWN,
            reason="test",
            ttl_seconds=60,
            actor=USER_ID,
        )
        acc.cooldown_until = past
        await db.commit()

    async with tenancy_session_factory() as db:
        n = await process_expired_cooldowns(db)
        await db.commit()
        assert n == 1
        from db.crud.account import get_account

        row = await get_account(db, acc.id)
        assert row.state == "active"
        assert row.cooldown_until is None


@pytest.mark.asyncio
async def test_retired_to_active_rejected(tenancy_session_factory, fsm_seed):
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "retired1")
        svc = AccountStateService()
        await svc.transition(
            db, acc.id, to=AccountState.RETIRED, reason="done", actor=USER_ID
        )
        with pytest.raises(InvalidStateTransitionError) as exc:
            await svc.transition(
                db, acc.id, to=AccountState.ACTIVE, reason="nope", actor=USER_ID
            )
        assert "terminal" in str(exc.value).lower()


# ── HTTP API ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_transition_cooldown(fsm_client):
    client, session_factory = fsm_client
    async with session_factory() as db:
        acc = await _new_account(db, "api1")
        await db.commit()
        aid = acc.id

    resp = await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "cooldown", "reason": "FB rate limit", "ttl_seconds": 86400},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "cooldown"
    assert body["cooldown_until"] is not None


@pytest.mark.asyncio
async def test_api_retired_to_active_422(fsm_client):
    client, session_factory = fsm_client
    async with session_factory() as db:
        acc = await _new_account(db, "api_ret")
        await db.commit()
        aid = acc.id

    await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "retired", "reason": "archived"},
    )
    resp = await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "active", "reason": "restore"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "INVALID_STATE_TRANSITION"


@pytest.mark.asyncio
async def test_api_banned_only_retire(fsm_client):
    client, session_factory = fsm_client
    async with session_factory() as db:
        acc = await _new_account(db, "api_ban")
        await db.commit()
        aid = acc.id

    await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "banned", "reason": "platform ban"},
    )
    bad = await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "active", "reason": "unban"},
    )
    assert bad.status_code == 422
    ok = await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "retired", "reason": "FB confirmed ban"},
    )
    assert ok.status_code == 200
    assert ok.json()["state"] == "retired"


@pytest.mark.asyncio
async def test_audit_state_changes(fsm_client):
    client, session_factory = fsm_client
    async with session_factory() as db:
        acc = await _new_account(db, "audit1")
        await db.commit()
        aid = acc.id

    for target in ("cooldown", "suspended", "active"):
        payload = {"to": target, "reason": f"go {target}"}
        if target == "cooldown":
            payload["ttl_seconds"] = 120
        r = await client.post(f"/api/accounts/{aid}/state", json=payload)
        assert r.status_code == 200, r.text

    async with session_factory() as db:
        events, _, _ = await list_account_events(db, aid, limit=20)
        state_events = [
            e for e in events if e.event_type == AccountEventType.STATE_CHANGED
        ]
        assert len(state_events) >= 3


# ── Round-robin / pick active only ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_round_robin_skips_non_active(tenancy_session_factory, fsm_seed):
    async with tenancy_session_factory() as db:
        states = [
            ("a1", AccountState.ACTIVE),
            ("a2", AccountState.ACTIVE),
            ("a3", AccountState.COOLDOWN),
            ("a4", AccountState.SUSPENDED),
            ("a5", AccountState.BANNED),
        ]
        ids = []
        svc = AccountStateService()
        for uname, st in states:
            acc = await _new_account(db, uname)
            if st != AccountState.ACTIVE:
                await svc.transition(
                    db,
                    acc.id,
                    to=st,
                    reason="setup",
                    ttl_seconds=3600 if st == AccountState.COOLDOWN else None,
                    actor=USER_ID,
                )
            ids.append(acc.id)

        active = await list_active_account_ids(db, ids)
        assert set(active) == {ids[0], ids[1]}

        dev_id = _uuid()
        db.add(
            Device(
                id=dev_id,
                serial=f"dev-{dev_id[:8]}",
                name="d1",
                user_id=USER_ID,
                org_id=ORG_ID,
            )
        )
        await db.flush()
        created = await round_robin_assign(db, ids, [dev_id])
        created_active = await round_robin_assign(db, active, [dev_id])
        assert created_active <= 2
        assert created >= created_active


@pytest.mark.asyncio
async def test_pick_next_batch_only_active(tenancy_session_factory, fsm_seed):
    async with tenancy_session_factory() as db:
        grp = await create_group(
            db,
            name="g1",
            platform="facebook",
            user_id=USER_ID,
            org_id=ORG_ID,
        )
        svc = AccountStateService()
        active_acc = await _new_account(db, "pick_act")
        cool_acc = await _new_account(db, "pick_cd")
        await svc.transition(
            db,
            cool_acc.id,
            to=AccountState.COOLDOWN,
            reason="x",
            ttl_seconds=9999,
            actor=USER_ID,
        )
        await add_members(db, group=grp, account_ids=[active_acc.id, cool_acc.id])
        picks = await pick_next_batch(db, grp.id, 10)
        await db.commit()
        assert len(picks) == 1
        assert picks[0].id == active_acc.id
