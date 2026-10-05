from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import InterfaceError, InternalError
from sqlalchemy.orm import Session

import api.deps as deps
from api.auth.context import AuthContext


class FakeDb:
    def __init__(self, *, in_transaction: bool = True) -> None:
        self._in_transaction = in_transaction
        self.commit = AsyncMock(side_effect=self._commit)

    def in_transaction(self) -> bool:
        return self._in_transaction

    async def _commit(self) -> None:
        self._in_transaction = False


class FakeEnforcer:
    def enforce(self, *_args) -> bool:
        return True


def test_request_session_write_tracking_catches_core_sql_writes() -> None:
    engine = create_engine("sqlite://")
    sync_session = Session(engine)
    db = SimpleNamespace(sync_session=sync_session)
    deps._install_request_write_tracking(db)
    closed_error = InterfaceError(
        "COMMIT",
        {},
        RuntimeError("the underlying connection is closed"),
    )
    concurrent_error = InternalError(
        "COMMIT",
        {},
        RuntimeError("cannot switch to state 15; another operation is in progress"),
    )
    try:
        sync_session.execute(select(1))
        assert deps._can_ignore_read_only_commit_error(db, closed_error) is True
        assert deps._can_ignore_read_only_commit_error(db, concurrent_error) is False

        sync_session.execute(text("create table tracked_write (id integer)"))
        assert deps._can_ignore_read_only_commit_error(db, closed_error) is False
    finally:
        deps._remove_request_write_tracking(db)
        sync_session.close()
        engine.dispose()


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        url=SimpleNamespace(path="/api/devices/live"),
        state=SimpleNamespace(
            auth=AuthContext(user_id="user-1", token_type="access", raw_token="t")
        ),
    )


@pytest.mark.asyncio
async def test_require_request_permission_releases_read_transaction(monkeypatch):
    db = FakeDb()
    user = SimpleNamespace(
        id="user-1",
        role="operator",
        org_id="org-1",
        default_org_id="org-1",
        is_active=True,
    )

    monkeypatch.setattr(deps.repo, "get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(
        deps.repo,
        "get_organization_role_for_user",
        AsyncMock(return_value="owner"),
    )
    monkeypatch.setattr(
        deps,
        "build_enforcer_for_user_from_db",
        AsyncMock(return_value=FakeEnforcer()),
    )

    request = _request()
    dependency = deps.require_request_permission(True, "devices", "read")
    await dependency(request, db)

    db.commit.assert_awaited_once()
    assert db.in_transaction() is False
    assert request.state.user_id == "user-1"
    assert request.state.org_id == "org-1"


@pytest.mark.asyncio
async def test_current_user_releases_read_transaction(monkeypatch):
    db = FakeDb()
    user = SimpleNamespace(
        id="user-1",
        role="operator",
        org_id="org-1",
        default_org_id="org-1",
        is_active=True,
    )

    monkeypatch.setattr(deps.repo, "get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(
        deps.repo,
        "get_organization_role_for_user",
        AsyncMock(return_value="member"),
    )

    result = await deps._get_current_user(
        _request(),
        db,
        AuthContext(user_id="user-1", token_type="access", raw_token="t"),
    )

    assert result is user
    db.commit.assert_awaited_once()
    assert db.in_transaction() is False
