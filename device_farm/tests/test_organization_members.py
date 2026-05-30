"""Organization member invite/list routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api import deps
from api.routes import organizations as organization_routes
from db.models import OrganizationMember, User


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


def _org(org_id: str, name: str):
    return SimpleNamespace(
        id=org_id,
        business_name=name,
        business_email=None,
        business_logo=None,
        slug=None,
        status="active",
        plan="standard",
        created_at="2026-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_list_organization_members(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user()
    member = OrganizationMember(
        id="m-1",
        organization_id="org-1",
        user_id="user-1",
        role="owner",
        created_at="2026-01-01T00:00:00Z",
    )
    target_user = SimpleNamespace(
        id="user-1",
        email="owner@example.com",
        name="Owner",
    )

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        organization_routes.repo,
        "list_organization_members",
        AsyncMock(return_value=[(member, target_user)]),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/organizations/members")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["email"] == "owner@example.com"
    assert body[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_superadmin_lists_all_organizations(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user(role="superadmin", org_role="")
    user.org_id = None  # type: ignore[attr-defined]

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    list_all = AsyncMock(return_value=([_org("org-1", "One"), _org("org-2", "Two")], 2))
    list_member = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(organization_routes.repo, "query_organizations", list_all)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/organizations")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["org-1", "org-2"]
    assert body["total"] == 2
    list_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_invite_organization_member_denied_for_non_owner(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user(org_role="member")

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/organizations/members",
            json={"email": "new@example.com"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_organization_member_assigns_supervisor(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user()
    member = OrganizationMember(
        id="m-2",
        organization_id="org-1",
        user_id="user-2",
        role="member",
        created_at="2026-01-01T00:00:00Z",
    )
    target_user = SimpleNamespace(
        id="user-2",
        email="staff@example.com",
        name="Staff",
    )

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        organization_routes.repo,
        "get_organization_member",
        AsyncMock(return_value=member),
    )
    updated_member = OrganizationMember(
        id="m-2",
        organization_id="org-1",
        user_id="user-2",
        role="supervisor",
        created_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(
        organization_routes.repo,
        "update_organization_member_role",
        AsyncMock(return_value=updated_member),
    )
    monkeypatch.setattr(
        organization_routes.repo,
        "get_user",
        AsyncMock(return_value=target_user),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/organizations/members/user-2",
            json={"role": "supervisor"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "staff@example.com"
    assert body["role"] == "supervisor"


@pytest.mark.asyncio
async def test_update_organization_member_rejects_owner_assignment(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user()
    member = OrganizationMember(
        id="m-2",
        organization_id="org-1",
        user_id="user-2",
        role="member",
        created_at="2026-01-01T00:00:00Z",
    )

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        organization_routes.repo,
        "get_organization_member",
        AsyncMock(return_value=member),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/organizations/members/user-2",
            json={"role": "owner"},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_ROLE"


@pytest.mark.asyncio
async def test_update_organization_member_rejects_owner_target(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user()
    member = OrganizationMember(
        id="m-1",
        organization_id="org-1",
        user_id="user-2",
        role="owner",
        created_at="2026-01-01T00:00:00Z",
    )

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        organization_routes.repo,
        "get_organization_member",
        AsyncMock(return_value=member),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/organizations/members/user-2",
            json={"role": "member"},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CANNOT_CHANGE_OWNER"


@pytest.mark.asyncio
async def test_update_organization_member_rejects_self(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user()

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/organizations/members/user-1",
            json={"role": "member"},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CANNOT_CHANGE_OWN_ROLE"
