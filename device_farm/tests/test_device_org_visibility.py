"""Org-scoped device visibility for media streams and WS allowlists."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.auth.context import AuthContext
from api.auth import policy


@pytest.mark.asyncio
async def test_assert_owns_device_allows_org_member(monkeypatch):
    owner_id = "owner-1"
    member_id = "member-1"
    serial = "device-serial-1"
    org_id = "org-1"

    ref = MagicMock(user_id=owner_id, org_id=org_id)
    member = MagicMock(id=member_id, is_active=True, org_id=org_id)

    async def fake_lookup(db, s):
        assert s == serial
        return ref

    async def fake_get_user(db, user_id):
        return member if user_id == member_id else None

    async def fake_org_role(db, user_id, oid):
        return "member"

    async def fake_visible(db, user, *, owner_user_id=None, org_id=None):
        assert user.id == member_id
        assert owner_user_id == owner_id
        assert org_id == "org-1"
        return True

    monkeypatch.setattr(policy, "lookup_device_by_serial", fake_lookup)
    monkeypatch.setattr(policy.repo, "get_user", fake_get_user)
    monkeypatch.setattr(
        policy.repo, "get_organization_role_for_user", fake_org_role
    )
    monkeypatch.setattr(policy, "resource_visible_to_user", fake_visible)
    monkeypatch.setattr(
        policy,
        "AsyncSessionLocal",
        MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=object()),
                __aexit__=AsyncMock(return_value=False),
            )
        ),
    )

    ctx = AuthContext(user_id=member_id, token_type="access", raw_token="t")
    await policy.assert_owns_device(ctx, serial)


@pytest.mark.asyncio
async def test_assert_owns_device_denies_outside_org(monkeypatch):
    ref = MagicMock(user_id="owner-1", org_id="org-a")
    user = MagicMock(id="member-1", is_active=True, org_id="org-b")

    monkeypatch.setattr(policy, "lookup_device_by_serial", AsyncMock(return_value=ref))
    monkeypatch.setattr(policy.repo, "get_user", AsyncMock(return_value=user))
    monkeypatch.setattr(
        policy.repo, "get_organization_role_for_user", AsyncMock(return_value="member")
    )
    monkeypatch.setattr(
        policy, "resource_visible_to_user", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        policy,
        "AsyncSessionLocal",
        MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=object()),
                __aexit__=AsyncMock(return_value=False),
            )
        ),
    )

    ctx = AuthContext(user_id="member-1", token_type="access", raw_token="t")
    with pytest.raises(HTTPException) as exc:
        await policy.assert_owns_device(ctx, "serial-x")
    assert exc.value.status_code == 403
