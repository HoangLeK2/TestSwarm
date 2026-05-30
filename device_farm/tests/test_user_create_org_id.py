"""User creation must satisfy users.org_id NOT NULL."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from db.crud.user import create_user_with_default_org


@pytest.mark.asyncio
async def test_create_user_with_default_org_sets_org_id_before_flush():
    db = MagicMock()
    flush_order: list[str] = []

    async def track_flush():
        flush_order.append("flush")

    db.flush = AsyncMock(side_effect=track_flush)
    db.add = MagicMock()

    org = MagicMock()
    org.id = "org-new"
    user = MagicMock()
    user.id = "user-new"
    user.org_id = "org-new"

    org_cls = MagicMock(return_value=org)
    user_cls = MagicMock(return_value=user)
    member_cls = MagicMock()

    import db.crud.user as user_mod

    original_org = user_mod.Organization
    original_user = user_mod.User
    original_member = user_mod.OrganizationMember
    user_mod.Organization = org_cls
    user_mod.User = user_cls
    user_mod.OrganizationMember = member_cls

    try:
        result = await create_user_with_default_org(
            db,
            "guest@example.com",
            "Guest",
            "hashed",
            "operator",
        )
    finally:
        user_mod.Organization = original_org
        user_mod.User = original_user
        user_mod.OrganizationMember = original_member

    assert result is user
    user_cls.assert_called_once()
    assert user_cls.call_args.kwargs["org_id"] == "org-new"
    assert db.add.call_count == 3
    assert flush_order == ["flush", "flush", "flush"]
