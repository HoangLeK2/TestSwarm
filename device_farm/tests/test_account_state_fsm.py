"""DF-T-07-005 — Account state FSM unit and API tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.crud.router import api_router
from api.deps import _get_current_user, _get_db
from db.crud.account import (
    assign_account_to_device,
    create_account,
    get_account,
    list_active_account_ids,
    round_robin_assign,
    unassign_account_from_device,
)
from db.crud.account_event import list_account_events
from db.crud.account_group import add_members, create_group, pick_next_batch
from db.models import Organization, User
from db.models.device import Device
from tenancy.context import clear_current_org_id, set_current_org_id
from db.models.enums import AccountEventType, AccountState
from db.models.utils import _uuid
from fastapi import FastAPI
from services.account_state.exceptions import InvalidStateTransitionError
from services.account_state.fsm import (
    all_transition_pairs,
    can_transition,
    normalize_state,
    transition_error_message,
)
from services.account_state.service import AccountStateService
from services.account_event_recorder import AccountEventRecorder, reset_account_event_recorder
from types import SimpleNamespace


USER_ID = "user-fsm-test"
ORG_ID = "org-fsm-test"


async def _new_account(db: AsyncSession, username: str, *, active: bool = True):
    """Create an account. New accounts start `unassigned`; `active=True` walks
    it up the ladder the way a device link plus a login would."""
    acc = await create_account(
        db,
        platform="facebook",
        username=username,
        user_id=USER_ID,
        org_id=ORG_ID,
    )
    if active:
        svc = AccountStateService()
        for target in (AccountState.ASSIGNED, AccountState.ACTIVE):
            await svc.transition(
                db, acc.id, to=target, reason="test setup", actor=USER_ID
            )
        await db.refresh(acc)
    return acc


def _new_device(db: AsyncSession) -> str:
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
    return dev_id


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

    def test_unassigned_assigns_but_cannot_skip_to_active(self):
        # `active` means "a session exists", which an unlinked account cannot
        # have — it has to be linked (`assigned`) and log in first.
        assert can_transition(AccountState.UNASSIGNED, AccountState.ASSIGNED)
        assert not can_transition(AccountState.UNASSIGNED, AccountState.ACTIVE)
        assert not can_transition(AccountState.UNASSIGNED, AccountState.SUSPENDED)

    def test_assigned_is_the_only_door_into_active(self):
        assert can_transition(AccountState.ASSIGNED, AccountState.ACTIVE)
        assert can_transition(AccountState.ACTIVE, AccountState.ASSIGNED)
        assert can_transition(AccountState.ASSIGNED, AccountState.UNASSIGNED)

    def test_cooldown_is_no_longer_a_state(self):
        assert "cooldown" not in {s.value for s in AccountState}
        # Legacy rows and old API clients still normalize rather than blow up.
        assert normalize_state("cooldown") is AccountState.ACTIVE

    def test_full_matrix_snapshot(self):
        allowed = {(a.value, b.value) for a, b, ok in all_transition_pairs() if ok}
        assert ("unassigned", "assigned") in allowed
        assert ("assigned", "active") in allowed
        assert ("active", "unassigned") in allowed
        assert ("unassigned", "active") not in allowed
        assert ("banned", "retired") in allowed
        assert ("retired", "active") not in allowed


# ── Service ───────────────────────────────────────────────────────────────────


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
async def test_api_transition_to_verifying(fsm_client):
    client, session_factory = fsm_client
    async with session_factory() as db:
        acc = await _new_account(db, "api1")
        await db.commit()
        aid = acc.id

    resp = await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "suspended", "reason": "selfie checkpoint"},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "suspended"


@pytest.mark.asyncio
async def test_api_rejects_retired_cooldown_state(fsm_client):
    client, session_factory = fsm_client
    async with session_factory() as db:
        acc = await _new_account(db, "api_cd")
        await db.commit()
        aid = acc.id

    resp = await client.post(
        f"/api/accounts/{aid}/state",
        json={"to": "cooldown", "reason": "FB rate limit"},
    )
    assert resp.status_code == 422


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

    for target in ("suspended", "active", "unassigned"):
        r = await client.post(
            f"/api/accounts/{aid}/state",
            json={"to": target, "reason": f"go {target}"},
        )
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
            ("a3", AccountState.UNASSIGNED),
            ("a4", AccountState.SUSPENDED),
            ("a5", AccountState.BANNED),
        ]
        ids = []
        svc = AccountStateService()
        for uname, st in states:
            acc = await _new_account(db, uname, active=st != AccountState.UNASSIGNED)
            if st not in (AccountState.ACTIVE, AccountState.UNASSIGNED):
                await svc.transition(
                    db, acc.id, to=st, reason="setup", actor=USER_ID
                )
            ids.append(acc.id)

        active = await list_active_account_ids(db, ids)
        assert set(active) == {ids[0], ids[1]}

        dev_id = _new_device(db)
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
        active_acc = await _new_account(db, "pick_act")
        # Resting is an eligibility gate, not a state: still `active`, still skipped.
        resting_acc = await _new_account(db, "pick_cd")
        resting_acc.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=3)
        await db.flush()
        await add_members(db, group=grp, account_ids=[active_acc.id, resting_acc.id])
        picks = await pick_next_batch(db, grp.id, 10)
        await db.commit()
        assert len(picks) == 1
        assert picks[0].id == active_acc.id


# ── unassigned ↔ device links ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_account_starts_unassigned(tenancy_session_factory, fsm_seed):
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "fresh", active=False)
        await db.commit()
        assert acc.state == AccountState.UNASSIGNED.value
        assert acc.status == AccountState.UNASSIGNED.value


@pytest.mark.asyncio
async def test_link_assigns_without_activating_and_unlink_reverts(
    tenancy_session_factory, fsm_seed
):
    """A phone is not a login: linking stops at `assigned`, never `active`."""
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "linkme", active=False)
        dev_id = _new_device(db)
        await db.flush()

        await assign_account_to_device(db, dev_id, acc.id)
        assert (await get_account(db, acc.id)).state == AccountState.ASSIGNED.value

        await unassign_account_from_device(db, dev_id, acc.id)
        assert (await get_account(db, acc.id)).state == AccountState.UNASSIGNED.value
        await db.commit()


@pytest.mark.asyncio
async def test_unlink_does_not_revive_banned_account(
    tenancy_session_factory, fsm_seed
):
    """A banned account that loses its device stays banned, not 'unassigned'."""
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "banned_link")
        dev_id = _new_device(db)
        await db.flush()
        await assign_account_to_device(db, dev_id, acc.id)
        await AccountStateService().transition(
            db, acc.id, to=AccountState.BANNED, reason="platform ban", actor=USER_ID
        )

        await unassign_account_from_device(db, dev_id, acc.id)
        assert (await get_account(db, acc.id)).state == AccountState.BANNED.value
        await db.commit()


@pytest.mark.asyncio
async def test_second_link_does_not_retrigger_transition(
    tenancy_session_factory, fsm_seed
):
    """Only the last unlink reverts — an account on two devices stays assigned."""
    async with tenancy_session_factory() as db:
        acc = await _new_account(db, "twodev", active=False)
        dev_a, dev_b = _new_device(db), _new_device(db)
        await db.flush()
        await assign_account_to_device(db, dev_a, acc.id)
        await assign_account_to_device(db, dev_b, acc.id)

        await unassign_account_from_device(db, dev_a, acc.id)
        assert (await get_account(db, acc.id)).state == AccountState.ASSIGNED.value

        await unassign_account_from_device(db, dev_b, acc.id)
        assert (await get_account(db, acc.id)).state == AccountState.UNASSIGNED.value
        await db.commit()
