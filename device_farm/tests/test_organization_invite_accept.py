"""Organization invite accept business logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from db.models import Organization, OrganizationInvitation, User
from services.organization_invite import accept_organization_invitation


def _user(email: str = "guest@example.com", org_id: str | None = "personal-org") -> User:
    user = User(
        id="user-guest",
        email=email,
        name="Guest",
        hashed_password="x",
        role="operator",
        api_key="k",
        is_active=True,
    )
    user.org_id = org_id  # type: ignore[attr-defined]
    return user


def _invite(email: str = "guest@example.com") -> OrganizationInvitation:
    return OrganizationInvitation(
        id="inv-1",
        organization_id="team-org",
        email=email,
        role="member",
        token="tok",
        status="pending",
        invited_by_user_id="owner-1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )


@pytest.mark.asyncio
async def test_accept_sets_active_org_to_invited_org():
    db = object()
    user = _user()
    invite = _invite()
    org = Organization(id="team-org", business_name="Team")

    with (
        patch(
            "services.organization_invite.invite_repo.get_invitation_by_token",
            AsyncMock(return_value=invite),
        ),
        patch(
            "services.organization_invite.invite_repo.get_organization_by_id",
            AsyncMock(return_value=org),
        ),
        patch(
            "services.organization_invite.invite_repo.user_has_membership",
            AsyncMock(return_value=False),
        ),
        patch(
            "services.organization_invite.repo.add_organization_member",
            AsyncMock(),
        ) as add_member,
        patch(
            "services.organization_invite.invite_repo.mark_invitation_accepted",
            AsyncMock(return_value=invite),
        ),
    ):
        org_id, name = await accept_organization_invitation(db, token="tok", user=user)

    assert org_id == "team-org"
    assert name == "Team"
    assert user.org_id == "team-org"  # type: ignore[attr-defined]
    add_member.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_rejects_email_mismatch():
    db = object()
    user = _user(email="other@example.com")
    invite = _invite(email="guest@example.com")

    with patch(
        "services.organization_invite.invite_repo.get_invitation_by_token",
        AsyncMock(return_value=invite),
    ):
        with pytest.raises(ValueError, match="INVITE_EMAIL_MISMATCH"):
            await accept_organization_invitation(db, token="tok", user=user)
