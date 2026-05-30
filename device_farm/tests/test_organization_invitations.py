"""Organization invitation email flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api import deps
from api.routes import organizations as organization_routes
from db.models import Organization, OrganizationInvitation, User


def _user(role: str = "operator", org_role: str = "owner") -> User:
    user = User(
        id="user-1",
        email="owner@example.com",
        name="Owner",
        hashed_password="x",
        role=role,
        api_key="k",
        is_active=True,
    )
    user.org_id = "org-1"  # type: ignore[attr-defined]
    user.org_role = org_role  # type: ignore[attr-defined]
    return user


def _org() -> Organization:
    return Organization(
        id="org-1",
        business_name="Acme",
        business_email=None,
        business_logo=None,
    )


def _invite(email: str = "new@example.com") -> OrganizationInvitation:
    return OrganizationInvitation(
        id="inv-1",
        organization_id="org-1",
        email=email,
        role="member",
        token="tok-test",
        status="pending",
        invited_by_user_id="user-1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )


@pytest.mark.asyncio
async def test_invite_sends_email_for_unknown_user(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)
    user = _user()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db

    invite = _invite()
    with patch.object(
        organization_routes,
        "create_and_email_invitation",
        AsyncMock(return_value=(invite, False, True)),
    ) as send_mock:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/organizations/members",
                json={"email": "new@example.com"},
            )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["status"] == "invited"
    assert body["existingUser"] is False
    assert body["emailSent"] is True
    send_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_invite_already_member_returns_409(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)
    user = _user()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db

    with patch.object(
        organization_routes,
        "create_and_email_invitation",
        AsyncMock(side_effect=ValueError("ALREADY_MEMBER")),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/organizations/members",
                json={"email": "member@example.com"},
            )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ALREADY_MEMBER"


@pytest.mark.asyncio
async def test_preview_invitation_public(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)
    invite = _invite()
    org = _org()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        organization_routes.invite_repo,
        "get_invitation_by_token",
        AsyncMock(return_value=invite),
    )
    monkeypatch.setattr(
        organization_routes.invite_repo,
        "get_organization_by_id",
        AsyncMock(return_value=org),
    )
    monkeypatch.setattr(
        organization_routes.repo,
        "get_user_by_email",
        AsyncMock(return_value=None),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/organizations/invitations/tok-test")

    assert response.status_code == 200
    body = response.json()
    assert body["organizationName"] == "Acme"
    assert body["email"] == "new@example.com"
    assert body["existingUser"] is False
    assert body["expired"] is False


@pytest.mark.asyncio
async def test_accept_invitation_adds_member(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)
    user = User(
        id="user-2",
        email="new@example.com",
        name="New",
        hashed_password="x",
        role="operator",
        api_key="k2",
        is_active=True,
    )

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db

    with patch.object(
        organization_routes,
        "accept_organization_invitation",
        AsyncMock(return_value=("org-1", "Acme")),
    ) as accept_mock:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/organizations/invitations/accept",
                json={"token": "tok-test"},
            )

    assert response.status_code == 200
    assert response.json()["organizationName"] == "Acme"
    accept_mock.assert_awaited_once()
