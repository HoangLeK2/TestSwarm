from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api import deps
from api.auth.rbac import clear_rbac_cache
from api.routes import devices as devices_routes
from api.routes import organizations as organization_routes
from api.routes import workspace_admin as workspace_admin_routes
from api.routes.workspace_admin import router as workspace_admin_router
from db.database import Base
from db.crud import relay_agent as relay_agent_repo
from db.models import (
    Account,
    ActivityLog,
    Campaign,
    CampaignDevice,
    Device,
    DeviceAccount,
    DeviceGroup,
    DeviceGroupMember,
    DeviceTargetGroup,
    ExternalEntity,
    Organization,
    OrganizationMember,
    RelayAgent,
    Scenario,
    ScenarioDeviceVariable,
    User,
)
from tenancy.context import set_current_org_id, tenant_context

NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE casbin_policy_revision (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL)"))
        await conn.execute(text("INSERT INTO casbin_policy_revision (id, revision) VALUES (1, 1)"))
        await conn.execute(
            text(
                """
                CREATE TABLE casbin_rule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ptype VARCHAR(32) NOT NULL,
                    v0 VARCHAR(255),
                    v1 VARCHAR(255),
                    v2 VARCHAR(255),
                    v3 VARCHAR(255),
                    v4 VARCHAR(255),
                    v5 VARCHAR(255)
                )
                """
            )
        )
        for role, obj, act in (
            ("superadmin", "*", "(read|create|update|delete|execute|manage)"),
            ("admin", "organizations", "(read|create|update|delete|manage)"),
            ("admin", "relay-agents", "(read|create|update|delete|manage)"),
            ("admin", "devices", "(read|create|update|delete|execute|manage)"),
            ("admin", "campaigns", "(read|create|update|delete|execute|manage)"),
            ("admin", "executions", "(read|create|update|delete|execute|manage)"),
            ("admin", "scenario-templates", "(read|create|update|delete|manage)"),
            ("admin", "scenarios", "(read|create|update|delete|manage)"),
            ("admin", "accounts", "(read|create|update|delete|execute|manage)"),
            ("admin", "account-groups", "(read|create|update|delete|execute|manage)"),
            ("admin", "device-groups", "(read|create|update|delete|manage)"),
            ("admin", "schedules", "(read|create|update|delete|execute|manage)"),
            ("admin", "notifications", "(read|create|update|delete|execute|manage)"),
            ("admin", "content", "(read|create|update|delete|manage)"),
            ("admin", "mcp", "(read|manage)"),
            ("admin", "analytics", "read"),
            ("owner", "organizations", "(read|create|update|delete|manage)"),
            ("owner", "devices", "(read|create|update|delete|execute|manage)"),
        ):
            await conn.execute(
                text(
                    """
                    INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
                    VALUES ('p', :role, '*', :obj, :act)
                    """
                ),
                {"role": role, "obj": obj, "act": act},
            )
        clear_rbac_cache()
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _user(
    *,
    user_id: str = "admin-1",
    org_role: str = "owner",
    role: str = "operator",
    org_id: str = "org-1",
):
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
        hashed_password="x",
        role=role,
        api_key=f"k-{user_id}",
        is_active=True,
    )
    user.org_id = org_id  # type: ignore[attr-defined]
    user.org_role = org_role  # type: ignore[attr-defined]
    return user


def _app(session_factory, user):
    app = FastAPI()
    app.include_router(devices_routes.router, prefix="/api")
    app.include_router(workspace_admin_router, prefix="/api")
    app.include_router(organization_routes.router, prefix="/api")

    async def fake_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    return app


async def _seed_workspace(session_factory):
    set_current_org_id(None)
    async with session_factory() as db:
        org = Organization(
            id="org-1",
            business_name="Acme Workspace",
            business_email="ops@example.com",
            status="active",
            plan="standard",
            # org-1 runs relay-1 and hands its phones to tenants.
            kind="pool",
            created_at=NOW,
            updated_at=NOW,
        )
        owner = User(
            id="owner-1",
            email="owner@example.com",
            name="Owner",
            hashed_password="x",
            role="system",
            api_key="k-owner",
            is_active=True,
            default_org_id="org-1",
            created_at=NOW,
        )
        db.add_all(
            [
                org,
                owner,
                OrganizationMember(
                    organization_id="org-1",
                    user_id="owner-1",
                    role="owner",
                    created_at=NOW,
                ),
                RelayAgent(
                    id="ra-1",
                    org_id="org-1",
                    relay_id="relay-1",
                    hostname="host-a",
                    ip="10.0.0.2",
                    version="0.3.0",
                    serials=["SN001"],
                    status="online",
                    user_id="owner-1",
                    connected_at=NOW,
                    last_heartbeat_at=NOW,
                    created_at=NOW,
                ),
                Device(
                    id="dev-1",
                    org_id="org-1",
                    serial="SN001",
                    device_serial="SN001",
                    name="Pixel",
                    user_id="owner-1",
                    status="paired",
                    created_at=NOW,
                ),
            ]
        )
        await db.commit()


async def _seed_second_workspace(session_factory):
    set_current_org_id(None)
    async with session_factory() as db:
        db.add_all(
            [
                Organization(
                    id="org-2",
                    business_name="Beta Workspace",
                    business_email="beta@example.com",
                    status="active",
                    plan="standard",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                User(
                    id="owner-2",
                    email="owner2@example.com",
                    name="Owner 2",
                    hashed_password="x",
                    role="system",
                    api_key="k-owner-2",
                    is_active=True,
                    default_org_id="org-2",
                    created_at=NOW,
                ),
                OrganizationMember(
                    organization_id="org-2",
                    user_id="owner-2",
                    role="owner",
                    created_at=NOW,
                ),
            ]
        )
        await db.commit()


async def _assign_workspace_admin(session_factory, *, user_id: str, org_id: str):
    set_current_org_id(None)
    async with session_factory() as db:
        db.add(
            OrganizationMember(
                organization_id=org_id,
                user_id=user_id,
                role="admin",
                created_at=NOW,
            )
        )
        await db.commit()


async def _seed_workspace_member(
    session_factory,
    *,
    user_id: str,
    org_id: str,
    role: str = "member",
):
    set_current_org_id(None)
    async with session_factory() as db:
        db.add_all(
            [
                User(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    hashed_password="x",
                    role="operator",
                    api_key=f"k-{user_id}",
                    is_active=True,
                    default_org_id=org_id,
                    created_at=NOW,
                ),
                OrganizationMember(
                    organization_id=org_id,
                    user_id=user_id,
                    role=role,
                    created_at=NOW,
                ),
            ]
        )
        await db.commit()


async def _seed_workspace_admin_user(
    session_factory,
    *,
    user_id: str = "admin-1",
    email: str | None = None,
    org_id: str = "org-1",
):
    set_current_org_id(None)
    async with session_factory() as db:
        db.add(
            User(
                id=user_id,
                email=email or f"{user_id}@example.com",
                name=user_id,
                hashed_password="x",
                role="support",
                api_key=f"k-{user_id}",
                is_active=True,
                default_org_id=org_id,
                created_at=NOW,
            )
        )
        await db.commit()
    await _assign_workspace_admin(session_factory, user_id=user_id, org_id=org_id)


async def _seed_customer_workspace(session_factory, *, org_id: str, owner_id: str, name: str):
    set_current_org_id(None)
    async with session_factory() as db:
        db.add_all(
            [
                Organization(
                    id=org_id,
                    business_name=name,
                    business_email=f"{org_id}@example.com",
                    status="active",
                    plan="standard",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                User(
                    id=owner_id,
                    email=f"{owner_id}@example.com",
                    name=owner_id,
                    hashed_password="x",
                    role="system",
                    api_key=f"k-{owner_id}",
                    is_active=True,
                    default_org_id=org_id,
                    created_at=NOW,
                ),
                OrganizationMember(
                    organization_id=org_id,
                    user_id=owner_id,
                    role="owner",
                    created_at=NOW,
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
async def test_workspace_admin_summary_uses_real_workspace_data(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/dashboard/summary")

    assert resp.status_code == 200
    body = resp.json()
    assert body["totalWorkspaces"] == 1
    assert body["totalAgents"] == 1
    assert body["totalDevices"] == 1
    assert body["devicesByWorkspace"][0]["workspaceName"] == "Acme Workspace"


@pytest.mark.asyncio
async def test_workspace_admin_summary_excludes_archived_agents(session_factory):
    """Archived duplicates are hidden from the agent list — don't count them here."""
    await _seed_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        db.add(
            RelayAgent(
                id="ra-archived",
                org_id="org-1",
                relay_id="relay-archived",
                hostname="host-a",
                ip="10.0.0.2",
                version="0.3.0",
                serials=[],
                status="archived",
                created_at=NOW,
            )
        )
        await db.commit()
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        summary = await client.get("/api/admin/dashboard/summary")
        agents = await client.get("/api/admin/agents")

    assert summary.json()["totalAgents"] == agents.json()["total"] == 1
    assert summary.json()["agentsByWorkspace"][0]["count"] == 1


@pytest.mark.asyncio
async def test_workspace_admin_routes_reject_regular_member(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="member"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/workspaces")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_workspace_admin_routes_reject_workspace_owner(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="owner"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/dashboard/summary")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_lists_all_workspaces(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/workspaces")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {item["id"] for item in body["items"]} == {"org-1", "org-2"}


@pytest.mark.asyncio
async def test_workspace_admin_lists_all_assigned_workspace_scope(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-1")
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-2")
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/workspaces")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {item["id"] for item in body["items"]} == {"org-1", "org-2"}


@pytest.mark.asyncio
async def test_superadmin_can_filter_admin_workspace_scope(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/admin/workspaces", params={"workspaceId": "org-2"})
        summary = await client.get(
            "/api/admin/dashboard/summary",
            params={"workspaceId": "org-2"},
        )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == "org-2"
    assert summary.status_code == 200
    assert summary.json()["totalWorkspaces"] == 1
    assert summary.json()["devicesByWorkspace"][0]["workspaceId"] == "org-2"


@pytest.mark.asyncio
async def test_workspace_admin_can_filter_assigned_workspace_scope(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-1")
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-2")
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/admin/workspaces", params={"workspaceId": "org-2"})
        summary = await client.get(
            "/api/admin/dashboard/summary",
            params={"workspaceId": "org-2"},
        )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == "org-2"
    assert summary.status_code == 200
    assert summary.json()["totalWorkspaces"] == 1
    assert summary.json()["devicesByWorkspace"][0]["workspaceId"] == "org-2"


@pytest.mark.asyncio
async def test_workspace_admin_can_manage_assigned_workspace_without_switching(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-2")
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        detail = await client.get("/api/admin/workspaces/org-2")
        updated = await client.patch(
            "/api/admin/workspaces/org-2",
            json={"description": "managed from global admin"},
        )
        admins = await client.get("/api/admin/workspaces/org-2/admins")

    assert detail.status_code == 200
    assert detail.json()["id"] == "org-2"
    assert updated.status_code == 200
    assert updated.json()["description"] == "managed from global admin"
    assert admins.status_code == 200
    assert admins.json()[0]["user_id"] == "admin-1"


@pytest.mark.asyncio
async def test_workspace_admin_can_manage_members_in_assigned_workspace_without_switching(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_workspace_member(session_factory, user_id="member-2", org_id="org-2")
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-2")
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/admin/workspaces/org-2/members")
        changed = await client.patch(
            "/api/admin/workspaces/org-2/members/member-2",
            json={"role": "supervisor"},
        )
        removed = await client.delete("/api/admin/workspaces/org-2/members/member-2")
        relisted = await client.get("/api/admin/workspaces/org-2/members")

    assert listed.status_code == 200
    assert {member["userId"] for member in listed.json()} == {"owner-2", "member-2", "admin-1"}
    assert changed.status_code == 200
    assert changed.json()["role"] == "supervisor"
    assert removed.status_code == 204
    assert {member["userId"] for member in relisted.json()} == {"owner-2", "admin-1"}


@pytest.mark.asyncio
async def test_workspace_access_defaults_to_every_visible_workspace(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_workspace_member(session_factory, user_id="member-1", org_id="org-1")
    await _seed_workspace_member(session_factory, user_id="member-2", org_id="org-2")
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        every = await client.get("/api/admin/workspace-access")
        scoped = await client.get("/api/admin/workspace-access", params={"workspaceId": "org-2"})

    assert every.status_code == 200
    body = every.json()
    # Owners are not editable here, so they stay out of both lists.
    assert {(m["userId"], m["workspaceName"]) for m in body["members"]} == {
        ("member-1", "Acme Workspace"),
        ("member-2", "Beta Workspace"),
    }
    assert {(a["user_id"], a["workspaceId"]) for a in body["admins"]} == {("admin-1", "org-1")}
    assert scoped.status_code == 200
    assert {m["userId"] for m in scoped.json()["members"]} == {"member-2"}
    assert scoped.json()["admins"] == []


@pytest.mark.asyncio
async def test_workspace_access_is_limited_to_assigned_workspaces(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_workspace_member(session_factory, user_id="member-1", org_id="org-1")
    await _seed_workspace_member(session_factory, user_id="member-2", org_id="org-2")
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        every = await client.get("/api/admin/workspace-access")
        outside = await client.get("/api/admin/workspace-access", params={"workspaceId": "org-2"})

    assert every.status_code == 200
    assert {m["userId"] for m in every.json()["members"]} == {"member-1"}
    assert outside.status_code == 403


@pytest.mark.asyncio
async def test_workspace_admin_audit_log_spans_assigned_workspaces(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-1")
    await _assign_workspace_admin(session_factory, user_id="admin-1", org_id="org-2")
    set_current_org_id(None)
    async with session_factory() as db:
        db.add_all(
            [
                ActivityLog(
                    id="audit-1",
                    action="workspace.updated",
                    entity_type="organization",
                    entity_id="org-1",
                    org_id="org-1",
                    user_id="admin-1",
                    outcome="success",
                    created_at=NOW,
                ),
                ActivityLog(
                    id="audit-2",
                    action="agent.updated",
                    entity_type="relay_agent",
                    entity_id="ra-2",
                    org_id="org-2",
                    user_id="admin-1",
                    outcome="success",
                    created_at=NOW,
                ),
            ]
        )
        await db.commit()
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        all_events = await client.get("/api/admin/audit-log")
        filtered = await client.get("/api/admin/audit-log", params={"workspaceId": "org-2"})

    assert all_events.status_code == 200
    assert {item["id"] for item in all_events.json()["activities"]} == {
        "audit-1",
        "audit-2",
    }
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["activities"]] == ["audit-2"]


@pytest.mark.asyncio
async def test_legacy_platform_admin_without_workspace_membership_is_rejected(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(role="admin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/workspaces")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_create_workspace_with_new_owner_sets_owner_default_workspace(
    session_factory,
):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/workspaces",
            json={
                "businessName": "Customer Workspace",
                "description": "Customer operations",
                "ownerEmail": "customer-owner@example.com",
                "ownerName": "Customer Owner",
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["businessName"] == "Customer Workspace"
    assert body["description"] == "Customer operations"
    assert body["owner"]["email"] == "customer-owner@example.com"
    assert body["temporaryPassword"]

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT u.default_org_id, u.must_change_password, m.role "
                    "FROM users u "
                    "JOIN organization_members m "
                    "ON m.user_id = u.id AND m.organization_id = u.default_org_id "
                    "WHERE u.email = 'customer-owner@example.com'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] == body["id"]
    assert bool(row[1]) is True
    assert row[2] == "owner"


@pytest.mark.asyncio
async def test_admin_create_workspace_appends_workspace_suffix(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/admin/workspaces",
            json={"businessName": "hoang"},
        )

    assert response.status_code == 201, response.text
    assert response.json()["businessName"] == "hoang Workspace"


@pytest.mark.asyncio
async def test_admin_create_workspace_keeps_existing_workspace_suffix(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/admin/workspaces",
            json={"businessName": "Customer Workspace"},
        )

    assert response.status_code == 201, response.text
    assert response.json()["businessName"] == "Customer Workspace"


@pytest.mark.asyncio
async def test_superadmin_can_delete_empty_workspace_without_deleting_owner_user(
    session_factory,
):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspaces",
            json={
                "businessName": "Delete Me Workspace",
                "ownerEmail": "delete-owner@example.com",
                "ownerName": "Delete Owner",
            },
        )
        assert created.status_code == 201, created.text
        workspace_id = created.json()["id"]

        deleted = await client.delete(f"/api/admin/workspaces/{workspace_id}")
        listed = await client.get("/api/admin/workspaces")

    assert deleted.status_code == 204, deleted.text
    assert workspace_id not in {item["id"] for item in listed.json()["items"]}

    set_current_org_id(None)
    async with session_factory() as db:
        org = await db.get(Organization, workspace_id)
        owner = (
            await db.execute(
                text(
                    "SELECT id, default_org_id FROM users "
                    "WHERE email = 'delete-owner@example.com'"
                )
            )
        ).first()
        member_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM organization_members WHERE organization_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalar_one()

    assert org is None
    assert owner is not None
    assert owner[1] is not None
    assert owner[1] != workspace_id
    async with session_factory() as db:
        fallback_org = await db.get(Organization, owner[1])
        fallback_member = (
            await db.execute(
                text(
                    "SELECT role FROM organization_members "
                    "WHERE organization_id = :organization_id AND user_id = :user_id"
                ),
                {"organization_id": owner[1], "user_id": owner[0]},
            )
        ).first()
    assert fallback_org is not None
    assert fallback_member is not None
    assert fallback_member[0] == "owner"
    assert member_count == 0


@pytest.mark.asyncio
async def test_superadmin_cannot_delete_workspace_with_operational_records(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/admin/workspaces/org-1")

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "WORKSPACE_NOT_EMPTY"
    assert body["detail"]["blockers"]["devices"] == 1
    assert body["detail"]["blockers"]["relayAgents"] == 1


@pytest.mark.asyncio
async def test_workspace_admin_can_delete_empty_workspace_in_their_scope(
    session_factory,
):
    await _seed_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspaces",
            json={
                "businessName": "Temporary Customer Workspace",
                "ownerEmail": "temporary-owner@example.com",
                "ownerName": "Temporary Owner",
            },
        )
        assert created.status_code == 201, created.text
        workspace_id = created.json()["id"]

        deleted = await client.delete(f"/api/admin/workspaces/{workspace_id}")
        listed = await client.get("/api/admin/workspaces")

    assert deleted.status_code == 204, deleted.text
    assert workspace_id not in {item["id"] for item in listed.json()["items"]}


@pytest.mark.asyncio
async def test_workspace_admin_can_create_workspace_for_owner_and_manage_it(
    session_factory,
):
    await _seed_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspaces",
            json={
                "businessName": "Customer Workspace",
                "description": "Customer operations",
                "ownerEmail": "customer-admin-owner@example.com",
                "ownerName": "Customer Owner",
            },
        )
        listed = await client.get("/api/admin/workspaces")

    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["owner"]["email"] == "customer-admin-owner@example.com"
    assert created_body["temporaryPassword"]
    assert {admin["user_id"] for admin in created_body["workspaceAdmins"]} == {
        "admin-1"
    }
    assert created_body["adminCount"] == 1
    assert listed.status_code == 200
    assert created_body["id"] in {item["id"] for item in listed.json()["items"]}


@pytest.mark.asyncio
async def test_workspace_admin_can_create_pool_workspace_for_owner(session_factory):
    await _seed_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspaces",
            json={
                "businessName": "Pool Rack",
                "kind": "pool",
                "ownerEmail": "pool-owner@example.com",
                "ownerName": "Pool Owner",
            },
        )

    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["kind"] == "pool"
    assert created_body["owner"]["email"] == "pool-owner@example.com"
    assert {admin["user_id"] for admin in created_body["workspaceAdmins"]} == {
        "admin-1"
    }


@pytest.mark.asyncio
async def test_workspace_admin_create_workspace_requires_owner(session_factory):
    await _seed_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/admin/workspaces",
            json={"businessName": "Missing Owner Workspace"},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "OWNER_REQUIRED"


@pytest.mark.asyncio
async def test_workspace_admin_can_update_description_and_reset_owner_password(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        updated = await client.patch(
            "/api/admin/workspaces/org-1",
            json={"description": "Operations workspace"},
        )
        reset = await client.post(
            "/api/admin/workspaces/org-1/owner/reset-password",
            json={},
        )

    assert updated.status_code == 200
    assert updated.json()["description"] == "Operations workspace"
    assert reset.status_code == 200
    assert reset.json()["owner"]["email"] == "owner@example.com"
    assert reset.json()["temporaryPassword"]
    async with session_factory() as db:
        must_change = (
            await db.execute(
                text("SELECT must_change_password FROM users WHERE id = 'owner-1'")
            )
        ).scalar_one()
    assert bool(must_change) is True


@pytest.mark.asyncio
async def test_workspace_admin_can_disable_owner_and_force_password_change(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/api/admin/workspaces/org-1/owner",
            json={"is_active": False, "mustChangePassword": True},
        )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["mustChangePassword"] is True

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT is_active, must_change_password "
                    "FROM users WHERE id = 'owner-1'"
                )
            )
        ).first()
    assert row is not None
    assert bool(row[0]) is False
    assert bool(row[1]) is True


@pytest.mark.asyncio
async def test_workspace_admin_update_appends_workspace_suffix(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/api/admin/workspaces/org-1",
            json={"businessName": "dev123123213"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["businessName"] == "dev123123213 Workspace"


@pytest.mark.asyncio
async def test_workspace_admin_update_keeps_existing_workspace_suffix(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/api/admin/workspaces/org-1",
            json={"businessName": "Customer Workspace"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["businessName"] == "Customer Workspace"


@pytest.mark.asyncio
async def test_workspace_admin_cannot_update_owner_outside_scope(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/api/admin/workspaces/org-2/owner",
            json={"is_active": False},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_SCOPE_REQUIRED"


@pytest.mark.asyncio
async def test_workspace_admin_can_create_and_revoke_agent_activation_token(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/agent-activation-tokens",
            json={"workspaceId": "org-1", "name": "rack-a"},
        )
        listed = await client.get("/api/admin/agent-activation-tokens?workspaceId=org-1")
        revoked = await client.delete(
            f"/api/admin/agent-activation-tokens/{created.json()['id']}"
        )

    assert created.status_code == 201
    assert created.json()["workspaceId"] == "org-1"
    assert created.json()["token"].startswith("dfra_")
    assert listed.status_code == 200
    assert listed.json()[0]["prefix"] == created.json()["prefix"]
    assert revoked.status_code == 204


@pytest.mark.asyncio
async def test_tenant_workspace_gets_a_code_but_its_phones_stay_its_own(
    session_factory,
):
    """A tenant may run its own relay; what it may not do is manage its peers.

    So minting the code is allowed, and allocating phones from the resulting
    agent to another workspace is the thing that gets refused.
    """
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/agent-activation-tokens",
            json={"workspaceId": "org-2", "name": "rack-b"},
        )

    assert created.status_code == 201
    assert created.json()["workspaceId"] == "org-2"
    # The refusal lives on allocation, see
    # test_phone_allocation_refused_when_agent_is_in_tenant_workspace.


@pytest.mark.asyncio
async def test_phone_allocation_refused_when_agent_is_in_tenant_workspace(
    session_factory,
):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        # relay-1 enrolled with org-1's code, then org-1 was demoted to tenant.
        await db.execute(text("UPDATE organizations SET kind = 'tenant' WHERE id = 'org-1'"))
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )

    assert assign.status_code == 409
    assert assign.json()["detail"]["code"] == "AGENT_NOT_IN_POOL_WORKSPACE"


@pytest.mark.asyncio
async def test_workspace_admin_can_promote_own_workspace_to_pool(session_factory):
    await _seed_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        await db.execute(text("UPDATE organizations SET kind = 'tenant' WHERE id = 'org-1'"))
        await db.commit()

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        promote = await client.patch("/api/admin/workspaces/org-1", json={"kind": "pool"})
        rename = await client.patch(
            "/api/admin/workspaces/org-1",
            json={"businessName": "Acme Renamed", "kind": "tenant"},
        )

    assert promote.status_code == 200, promote.text
    assert promote.json()["kind"] == "pool"
    assert rename.status_code == 200, rename.text
    # The route normalises workspace names with a " Workspace" suffix.
    assert rename.json()["businessName"] == "Acme Renamed Workspace"
    assert rename.json()["kind"] == "tenant"


@pytest.mark.asyncio
async def test_workspace_admin_can_replace_agent_activation_token(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/agent-activation-tokens",
            json={"workspaceId": "org-1", "name": "rack-a"},
        )
        assert created.status_code == 201, created.text
        replaced = await client.post(
            f"/api/admin/agent-activation-tokens/{created.json()['id']}/replace"
        )
        listed = await client.get("/api/admin/agent-activation-tokens?workspaceId=org-1")

    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["token"].startswith("dfra_")
    assert replaced.json()["token"] != created.json()["token"]
    assert replaced.json()["workspaceId"] == "org-1"
    assert replaced.json()["name"] == "rack-a"
    tokens = {item["id"]: item for item in listed.json()}
    assert tokens[created.json()["id"]]["status"] == "revoked"
    assert tokens[replaced.json()["id"]]["status"] == "active"


@pytest.mark.asyncio
async def test_workspace_admin_cannot_replace_agent_token_outside_scope(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    set_current_org_id("org-2")
    async with session_factory() as db:
        _raw_token, token = await relay_agent_repo.create_relay_agent_token(
            db,
            user_id="owner-2",
            name="other-rack",
            org_id="org-2",
        )
        await db.commit()
        token_id = token.id
    set_current_org_id(None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/admin/agent-activation-tokens/{token_id}/replace"
        )

    assert response.status_code in {400, 403, 404}


@pytest.mark.asyncio
async def test_owner_cannot_promote_member_to_workspace_admin(monkeypatch, session_factory):
    app = _app(session_factory, _user())
    member = OrganizationMember(
        id="member-row",
        organization_id="org-1",
        user_id="member-1",
        role="member",
        created_at=NOW,
    )
    target_user = SimpleNamespace(id="member-1", email="member@example.com", name="Member")
    monkeypatch.setattr(organization_routes.repo, "get_organization_member", AsyncMock(return_value=member))
    monkeypatch.setattr(
        organization_routes.repo,
        "update_organization_member_role",
        AsyncMock(return_value=OrganizationMember(
            id="member-row",
            organization_id="org-1",
            user_id="member-1",
            role="admin",
            created_at=NOW,
        )),
    )
    monkeypatch.setattr(organization_routes.repo, "get_user", AsyncMock(return_value=target_user))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/api/organizations/members/member-1", json={"role": "admin"})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "WORKSPACE_ADMIN_SUPERADMIN_ONLY"


@pytest.mark.asyncio
async def test_superadmin_can_create_and_assign_multiple_workspace_admins(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/admin/workspace-admins",
            json={"email": "admin-a@example.com", "name": "Admin A"},
        )
        second = await client.post(
            "/api/admin/workspace-admins",
            json={"email": "admin-b@example.com", "name": "Admin B"},
        )
        assign_first = await client.post(
            "/api/admin/workspaces/org-1/admins",
            json={"userId": first.json()["user_id"]},
        )
        assign_second = await client.post(
            "/api/admin/workspaces/org-1/admins",
            json={"userId": second.json()["user_id"]},
        )
        listed = await client.get("/api/admin/workspaces/org-1/admins")
        workspace = await client.get("/api/admin/workspaces/org-1")

    assert first.status_code == 201
    assert first.json()["platformRole"] == "support"
    assert first.json()["temporaryPassword"]
    assert first.json()["adminWorkspaceCount"] == 0
    assert second.status_code == 201
    assert assign_first.status_code == 201
    assert assign_second.status_code == 201
    assert {item["email"] for item in listed.json()} == {
        "admin-a@example.com",
        "admin-b@example.com",
    }
    assert workspace.json()["adminCount"] == 2

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT default_org_id, must_change_password "
                    "FROM users WHERE id = :user_id"
                ),
                {"user_id": first.json()["user_id"]},
            )
        ).first()
    assert row is not None
    assert row[0] == "org-1"
    assert bool(row[1]) is True


@pytest.mark.asyncio
async def test_superadmin_workspace_admin_assignment_rejects_duplicates(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspace-admins",
            json={"email": "admin-a@example.com", "name": "Admin A"},
        )
        user_id = created.json()["user_id"]
        first = await client.post(
            "/api/admin/workspaces/org-1/admins",
            json={"userId": user_id},
        )
        duplicate = await client.post(
            "/api/admin/workspaces/org-1/admins",
            json={"userId": user_id},
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "WORKSPACE_ADMIN_EXISTS"


@pytest.mark.asyncio
async def test_superadmin_can_reset_workspace_admin_temporary_password(session_factory):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspace-admins",
            json={"email": "reset-admin@example.com", "name": "Reset Admin"},
        )
        reset = await client.post(
            f"/api/admin/workspace-admins/{created.json()['user_id']}/reset-password",
            json={},
        )

    assert created.status_code == 201
    assert reset.status_code == 200
    assert reset.json()["temporaryPassword"]
    assert reset.json()["temporaryPassword"] != created.json()["temporaryPassword"]
    assert reset.json()["admin"]["email"] == "reset-admin@example.com"

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT must_change_password "
                    "FROM users WHERE id = :user_id"
                ),
                {"user_id": created.json()["user_id"]},
            )
        ).first()
    assert row is not None
    assert bool(row[0]) is True


@pytest.mark.asyncio
async def test_workspace_admin_cannot_manage_workspace_admin_accounts(session_factory):
    await _seed_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create = await client.post(
            "/api/admin/workspace-admins",
            json={
                "email": "scoped-admin@example.com",
                "name": "Scoped Admin",
                "workspaceIds": ["org-1"],
            },
        )
        update = await client.patch(
            "/api/admin/workspace-admins/admin-1",
            json={"is_active": False},
        )
        reset = await client.post(
            "/api/admin/workspace-admins/admin-1/reset-password",
            json={},
        )
        bulk_assign = await client.post(
            "/api/admin/workspace-admins/admin-1/workspaces",
            json={"workspaceIds": ["org-1"]},
        )
        direct_assign = await client.post(
            "/api/admin/workspaces/org-1/admins",
            json={"userId": "admin-1"},
        )
        direct_remove = await client.delete("/api/admin/workspaces/org-1/admins/admin-1")

    for response in [create, update, reset, bulk_assign, direct_assign, direct_remove]:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "SUPERADMIN_ONLY"


@pytest.mark.asyncio
async def test_workspace_admin_can_still_list_scoped_workspace_admins(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_workspace_admin_user(session_factory, user_id="admin-1", org_id="org-1")
    await _seed_workspace_admin_user(session_factory, user_id="admin-2", org_id="org-2")
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/admin/workspace-admins")

    assert listed.status_code == 200
    assert {item["email"] for item in listed.json()["items"]} == {
        "admin-1@example.com",
    }


@pytest.mark.asyncio
async def test_superadmin_can_bulk_assign_and_remove_workspace_admin_workspaces(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/admin/workspace-admins",
            json={"email": "matrix-admin@example.com", "name": "Matrix Admin"},
        )
        user_id = created.json()["user_id"]
        assigned = await client.post(
            f"/api/admin/workspace-admins/{user_id}/workspaces",
            json={"workspaceIds": ["org-1", "org-2", "missing-org", "org-1"]},
        )
        listed = await client.get("/api/admin/workspace-admins")
        removed = await client.post(
            f"/api/admin/workspace-admins/{user_id}/workspaces/remove",
            json={"workspaceIds": ["org-1", "missing-org"]},
        )

    assert created.status_code == 201
    assert assigned.status_code == 200
    assert [item["workspaceId"] for item in assigned.json()["assigned"]] == ["org-1", "org-2"]
    assert [item["reason"] for item in assigned.json()["skipped"]] == ["WORKSPACE_NOT_FOUND"]
    admin_row = next(item for item in listed.json()["items"] if item["user_id"] == user_id)
    assert admin_row["adminWorkspaceCount"] == 2
    assert {item["id"] for item in admin_row["adminWorkspaces"]} == {"org-1", "org-2"}
    assert removed.status_code == 200
    assert [item["workspaceId"] for item in removed.json()["removed"]] == ["org-1"]
    assert [item["reason"] for item in removed.json()["skipped"]] == ["WORKSPACE_NOT_FOUND"]
    assert removed.json()["admin"]["adminWorkspaceCount"] == 1
    assert [item["id"] for item in removed.json()["admin"]["adminWorkspaces"]] == ["org-2"]


@pytest.mark.asyncio
async def test_assignable_workspaces_are_scoped_for_workspace_admin(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(role="operator", org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/admin/workspaces/assignable")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["org-1"]


@pytest.mark.asyncio
async def test_workspace_admin_assigns_agent_phone_pool_to_customer_workspaces(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_customer_workspace(
        session_factory,
        org_id="org-3",
        owner_id="owner-3",
        name="Gamma Workspace",
    )
    serials = [f"SN{i:03d}" for i in range(1, 21)]
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = serials
        await db.commit()

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    first_ten = serials[:10]
    second_ten = serials[10:]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assign_b = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": first_ten},
        )
        assign_c = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-3", "serials": second_ten},
        )
        phones = await client.get("/api/admin/agents/relay-1/phone-allocations")
        devices = await client.get("/api/admin/devices?limit=100")

    app_b = _app(session_factory, _user(user_id="admin-b", org_role="admin", org_id="org-2"))
    async with AsyncClient(transport=ASGITransport(app=app_b), base_url="http://test") as client:
        customer_devices = await client.get("/api/admin/devices?limit=100")
        hidden_agent = await client.get("/api/admin/agents/relay-1/phone-allocations")

    assert assign_b.status_code == 200
    assert assign_c.status_code == 200
    assert phones.status_code == 200
    assert phones.json()["total"] == 20
    assert devices.status_code == 200
    assert devices.json()["total"] == 20
    assert customer_devices.status_code == 200
    assert customer_devices.json()["total"] == 10
    assert {item["workspaceId"] for item in customer_devices.json()["items"]} == {"org-2"}
    assert hidden_agent.status_code == 404

    by_serial = {item["serial"]: item for item in phones.json()["items"]}
    assert {by_serial[serial]["assignedWorkspaceId"] for serial in first_ten} == {"org-2"}
    assert {by_serial[serial]["assignedWorkspaceId"] for serial in second_ten} == {"org-3"}
    assert {item["managedByWorkspaceId"] for item in phones.json()["items"]} == {"org-1"}

    set_current_org_id(None)
    async with session_factory() as db:
        rows = (await db.execute(text("SELECT serial, org_id, managed_by_org_id, user_id, status FROM devices"))).all()
    assert {row[2] for row in rows} == {"org-1"}
    assert len([row for row in rows if row[1] == "org-2"]) == 10
    assert len([row for row in rows if row[1] == "org-3"]) == 10
    assert {row[3] for row in rows} == {None}
    assert {row[4] for row in rows} == {"unpaired"}


@pytest.mark.asyncio
async def test_agent_phone_list_supports_pagination_and_server_filters(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    await _seed_customer_workspace(
        session_factory,
        org_id="org-3",
        owner_id="owner-3",
        name="Gamma Workspace",
    )
    serials = [f"SN{i:03d}" for i in range(1, 21)]
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = serials
        await db.commit()

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assign_b = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": serials[:10]},
        )
        assign_c = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-3", "serials": serials[10:]},
        )
        page = await client.get("/api/admin/agents/relay-1/phone-allocations?offset=5&limit=5")
        filtered = await client.get(
            "/api/admin/agents/relay-1/phone-allocations?assignedWorkspaceId=org-3&limit=5"
        )
        searched = await client.get(
            "/api/admin/agents/relay-1/phone-allocations?search=SN011&limit=5"
        )

    assert assign_b.status_code == 200
    assert assign_c.status_code == 200
    assert page.status_code == 200
    assert page.json()["total"] == 20
    assert page.json()["offset"] == 5
    assert page.json()["limit"] == 5
    assert [item["serial"] for item in page.json()["items"]] == serials[5:10]
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 10
    assert {item["assignedWorkspaceId"] for item in filtered.json()["items"]} == {"org-3"}
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["serial"] == "SN011"


@pytest.mark.asyncio
async def test_agent_phone_assignment_rejects_oversized_batches(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    serials = [f"SN{i:03d}" for i in range(1, 202)]
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = serials
        await db.commit()

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": serials},
        )

    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "PHONE_BATCH_TOO_LARGE"
    assert resp.json()["detail"]["limit"] == 200


@pytest.mark.asyncio
async def test_workspace_admin_releases_agent_phone_allocation_with_delete(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
        release = await client.request(
            "DELETE",
            "/api/admin/agents/relay-1/phone-allocations",
            json={"serials": ["SN001"]},
        )
        phones = await client.get("/api/admin/agents/relay-1/phone-allocations")

    assert assign.status_code == 200
    assert release.status_code == 200
    assert release.json()["items"][0]["assignedWorkspaceId"] == "org-1"
    assert phones.status_code == 200
    assert phones.json()["items"][0]["assignedWorkspaceId"] == "org-1"
    assert phones.json()["items"][0]["managedByWorkspaceId"] == "org-1"


@pytest.mark.asyncio
async def test_superadmin_agent_list_does_not_materialize_workspace_scope(
    session_factory,
    monkeypatch,
):
    await _seed_workspace(session_factory)
    app = _app(session_factory, _user(role="superadmin", org_role=""))

    async def fail_visible_workspace_ids(*_args, **_kwargs):
        raise AssertionError("superadmin list should not load all workspace ids")

    monkeypatch.setattr(
        workspace_admin_routes,
        "_visible_workspace_ids",
        fail_visible_workspace_ids,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/agents?limit=10")

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_workspace_owner_lists_allocated_unclaimed_phones(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001", "SN002"]
        await db.commit()

    app_admin_a = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
    assert assign.status_code == 200

    app_owner_b = _app(
        session_factory,
        _user(user_id="owner-2", org_role="owner", role="system", org_id="org-2"),
    )
    async with AsyncClient(transport=ASGITransport(app=app_owner_b), base_url="http://test") as client:
        allocated = await client.get("/api/devices/allocated")
        filtered = await client.get("/api/devices/allocated?q=SN001")
        claim = await client.post("/api/devices/dev-1/claim-allocated")
        after_claim = await client.get("/api/devices/allocated")

    assert allocated.status_code == 200
    assert [item["serial"] for item in allocated.json()] == ["SN001"]
    assert allocated.json()[0]["user_id"] is None
    assert allocated.json()[0]["managed_by_org_id"] == "org-1"
    assert allocated.json()[0]["managed_by_relay_id"] == "relay-1"
    assert filtered.status_code == 200
    assert [item["serial"] for item in filtered.json()] == ["SN001"]
    assert claim.status_code == 200
    assert after_claim.status_code == 200
    assert after_claim.json() == []


@pytest.mark.asyncio
async def test_reassigning_claimed_phone_does_not_require_registration_again(
    session_factory,
):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app_admin_a = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        first_assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
    assert first_assign.status_code == 200, first_assign.text
    assert first_assign.json()["items"][0]["status"] == "unpaired"

    app_owner_b = _app(
        session_factory,
        _user(user_id="owner-2", org_role="owner", role="system", org_id="org-2"),
    )
    async with AsyncClient(transport=ASGITransport(app=app_owner_b), base_url="http://test") as client:
        before_claim = await client.get("/api/devices/allocated")
        claim = await client.post("/api/devices/dev-1/claim-allocated")
        after_claim = await client.get("/api/devices/allocated")

    assert before_claim.status_code == 200
    assert [item["serial"] for item in before_claim.json()] == ["SN001"]
    assert claim.status_code == 200
    assert claim.json()["status"] == "paired"
    assert after_claim.status_code == 200
    assert after_claim.json() == []

    app_admin_a = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        release = await client.request(
            "DELETE",
            "/api/admin/agents/relay-1/phone-allocations",
            json={"serials": ["SN001"]},
        )
        second_assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )

    assert release.status_code == 200
    assert release.json()["items"][0]["assignedWorkspaceId"] == "org-1"
    assert release.json()["items"][0]["status"] == "paired"
    assert second_assign.status_code == 200
    assert second_assign.json()["items"][0]["assignedWorkspaceId"] == "org-2"
    assert second_assign.json()["items"][0]["status"] == "paired"

    app_owner_b = _app(
        session_factory,
        _user(user_id="owner-2", org_role="owner", role="system", org_id="org-2"),
    )
    async with AsyncClient(transport=ASGITransport(app=app_owner_b), base_url="http://test") as client:
        allocated_after_reassign = await client.get("/api/devices/allocated")
        devices_after_reassign = await client.get("/api/devices?page=1&page_size=10")

    assert allocated_after_reassign.status_code == 200
    assert allocated_after_reassign.json() == []
    assert devices_after_reassign.status_code == 200
    row = next(
        item for item in devices_after_reassign.json()["items"] if item["serial"] == "SN001"
    )
    assert row["status"] == "paired"
    assert row["user_id"] is None
    assert row["managed_by_relay_id"] == "relay-1"


@pytest.mark.asyncio
async def test_workspace_owner_claims_allocated_phone_and_delete_releases_to_admin_pool(
    session_factory,
):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    serials = ["SN001", "SN002"]
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = serials
        await db.commit()

    app_admin_a = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
    assert assign.status_code == 200

    app_owner_b = _app(
        session_factory,
        _user(user_id="owner-2", org_role="owner", role="system", org_id="org-2"),
    )
    async with AsyncClient(transport=ASGITransport(app=app_owner_b), base_url="http://test") as client:
        claim = await client.post("/api/devices/dev-1/claim-allocated")
        delete = await client.delete("/api/devices/dev-1")

    assert claim.status_code == 200
    assert claim.json()["user_id"] == "owner-2"
    assert claim.json()["status"] == "paired"
    assert claim.json()["managed_by_org_id"] == "org-1"
    assert claim.json()["managed_by_relay_id"] == "relay-1"
    assert delete.status_code == 204

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT org_id, managed_by_org_id, managed_by_relay_id, user_id, status "
                    "FROM devices WHERE id = 'dev-1'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] == "org-1"
    assert row[1] == "org-1"
    assert row[2] == "relay-1"
    assert row[3] is None
    assert row[4] == "unpaired"


@pytest.mark.asyncio
async def test_workspace_admin_revoke_cleans_workspace_phone_bindings(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app_admin_a = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
    assert assign.status_code == 200

    app_owner_b = _app(
        session_factory,
        _user(user_id="owner-2", org_role="owner", role="system", org_id="org-2"),
    )
    async with AsyncClient(transport=ASGITransport(app=app_owner_b), base_url="http://test") as client:
        claim = await client.post("/api/devices/dev-1/claim-allocated")
    assert claim.status_code == 200

    async with session_factory() as db:
        with tenant_context("org-2"):
            db.add_all(
                [
                    Account(
                        id="acct-1",
                        org_id="org-2",
                        platform="facebook",
                        username="fb-user",
                        user_id="owner-2",
                    ),
                    Campaign(
                        id="camp-1",
                        org_id="org-2",
                        name="Campaign B",
                        name_lower="campaign b",
                        user_id="owner-2",
                        per_device_overrides={"dev-1": {"PAGE": "A"}},
                        per_device_accounts={"dev-1": "acct-1"},
                    ),
                    DeviceGroup(
                        id="group-1",
                        org_id="org-2",
                        name="Group B",
                        user_id="owner-2",
                    ),
                    ExternalEntity(
                        id="entity-1",
                        org_id="org-2",
                        platform="facebook",
                        entity_type="page",
                        identity_key="page:1",
                        display_name="Page B",
                    ),
                ]
            )
            db.add_all(
                [
                    CampaignDevice(campaign_id="camp-1", device_id="dev-1"),
                    DeviceAccount(device_id="dev-1", account_id="acct-1", is_primary=True),
                    DeviceGroupMember(
                        id="dgm-1",
                        org_id="org-2",
                        group_id="group-1",
                        device_id="dev-1",
                    ),
                    DeviceTargetGroup(
                        id="dtg-1",
                        org_id="org-2",
                        device_id="dev-1",
                        external_entity_id="entity-1",
                        position=1,
                        assigned_by="owner-2",
                    ),
                    Scenario(
                        id="scn-1",
                        campaign_id="camp-1",
                        name="Scenario",
                        instructions="",
                    ),
                    ScenarioDeviceVariable(
                        scenario_id="scn-1",
                        device_id="dev-1",
                        vars={"PAGE": "A"},
                    ),
                ]
            )
        await db.commit()

    set_current_org_id("org-1")
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        revoke = await client.request(
            "DELETE",
            "/api/admin/agents/relay-1/phone-allocations",
            json={"serials": ["SN001"]},
        )

    assert revoke.status_code == 200, revoke.text

    async with session_factory() as db:
        with tenant_context("org-1"):
            device = await db.get(Device, "dev-1")
        with tenant_context("org-2"):
            campaign = await db.get(Campaign, "camp-1")
        assert device is not None
        assert campaign is not None
        counts = {
            "campaign_devices": (
                await db.execute(text("SELECT COUNT(*) FROM campaign_devices WHERE device_id = 'dev-1'"))
            ).scalar_one(),
            "device_accounts": (
                await db.execute(text("SELECT COUNT(*) FROM device_accounts WHERE device_id = 'dev-1'"))
            ).scalar_one(),
            "device_group_members": (
                await db.execute(text("SELECT COUNT(*) FROM device_group_members WHERE device_id = 'dev-1'"))
            ).scalar_one(),
            "device_target_groups": (
                await db.execute(text("SELECT COUNT(*) FROM device_target_groups WHERE device_id = 'dev-1'"))
            ).scalar_one(),
            "scenario_device_variables": (
                await db.execute(text("SELECT COUNT(*) FROM scenario_device_variables WHERE device_id = 'dev-1'"))
            ).scalar_one(),
            "accounts": (
                await db.execute(text("SELECT COUNT(*) FROM accounts WHERE id = 'acct-1'"))
            ).scalar_one(),
            "campaigns": (
                await db.execute(text("SELECT COUNT(*) FROM campaigns WHERE id = 'camp-1'"))
            ).scalar_one(),
            "device_groups": (
                await db.execute(text("SELECT COUNT(*) FROM device_groups WHERE id = 'group-1'"))
            ).scalar_one(),
            "device_keys": (
                await db.execute(text("SELECT COUNT(*) FROM device_keys WHERE device_id = 'dev-1'"))
            ).scalar_one(),
            "active_device_keys": (
                await db.execute(
                    text("SELECT COUNT(*) FROM device_keys WHERE device_id = 'dev-1' AND status = 'active'")
                )
            ).scalar_one(),
            "max_device_key_version": (
                await db.execute(text("SELECT MAX(version) FROM device_keys WHERE device_id = 'dev-1'"))
            ).scalar_one(),
        }

    assert device.org_id == "org-1"
    assert device.managed_by_org_id == "org-1"
    assert device.user_id is None
    assert device.status == "unpaired"
    assert campaign.per_device_overrides == {}
    assert campaign.per_device_accounts == {}
    assert counts == {
        "campaign_devices": 0,
        "device_accounts": 0,
        "device_group_members": 0,
        "device_target_groups": 0,
        "scenario_device_variables": 0,
        "accounts": 1,
        "campaigns": 1,
        "device_groups": 1,
        "device_keys": 3,
        "active_device_keys": 1,
        "max_device_key_version": 3,
    }


@pytest.mark.asyncio
async def test_workspace_owner_connects_claimed_allocated_phone_via_managed_agent(
    session_factory,
    monkeypatch,
):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app_admin_a = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app_admin_a), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
    assert assign.status_code == 200

    class FakeControl:
        def __init__(self):
            self.calls = []

        async def shell(self, serial, cmd, timeout=15.0):
            self.calls.append((serial, cmd, timeout))
            return {"ok": True, "output": "started", "exit_code": 0, "error": ""}

    ctrl = FakeControl()
    monkeypatch.setattr(devices_routes, "_get_ctrl_servicer_optional", lambda: ctrl)

    app_owner_b = _app(
        session_factory,
        _user(user_id="owner-2", org_role="owner", role="system", org_id="org-2"),
    )
    async with AsyncClient(transport=ASGITransport(app=app_owner_b), base_url="http://test") as client:
        claim = await client.post("/api/devices/dev-1/claim-allocated")
        connect = await client.post(
            "/api/devices/dev-1/connect-via-managed-agent",
            json={"wsBaseUrl": "ws://farm.example.test"},
        )

    assert claim.status_code == 200
    assert connect.status_code == 200, connect.text
    assert connect.json()["ok"] is True
    assert ctrl.calls
    assert ctrl.calls[0][0] == "SN001"
    assert "farm.example.test/device-agent?key=" in ctrl.calls[0][1]


@pytest.mark.asyncio
async def test_workspace_admin_cannot_assign_phone_from_another_admin_pool(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)

    app = _app(session_factory, _user(user_id="admin-b", org_role="admin", org_id="org-2"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "AGENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_agent_phone_assignment_rejects_serial_not_reported_by_agent(session_factory):
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["NOT-REPORTED"]},
        )

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SERIAL_NOT_REPORTED_BY_AGENT"


@pytest.mark.asyncio
async def test_disabling_an_agent_parks_every_transport(
    session_factory, monkeypatch
):
    """Disable must reach the transports, not just the row a tenant never reads."""
    await _seed_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001", "SN002"]
        await db.commit()

    applied: list[tuple[str, list[str], bool]] = []
    monkeypatch.setattr(
        workspace_admin_routes,
        "_apply_agent_suspension",
        lambda relay_id, serials, *, suspend: applied.append(
            (relay_id, list(serials), suspend)
        ),
    )

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/admin/agents/relay-1/disable")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    # One call parks control, video and media together — with the phone list,
    # because the media plane only knows serials.
    assert applied == [("relay-1", ["SN001", "SN002"], True)]

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text("SELECT status, serials FROM relay_agents WHERE relay_id = 'relay-1'")
            )
        ).first()
    assert row is not None
    assert row[0] == "disabled"
    # serials stay: they are the only serial → agent map once the agent is gone.
    assert "SN001" in str(row[1])


@pytest.mark.asyncio
async def test_admin_device_console_lists_tenant_phones_as_not_transferable(session_factory):
    """A phone a tenant registered on its own relay is listed, but not movable."""
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        await db.execute(
            text("UPDATE devices SET managed_by_org_id = 'org-2' WHERE id = 'dev-1'")
        )
        await db.commit()

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tenant_managed = await client.get("/api/admin/devices")
        transfer = await client.put(
            "/api/admin/devices/dev-1/assignment",
            json={"workspaceId": "org-1"},
        )

    assert tenant_managed.status_code == 200
    assert [item["serial"] for item in tenant_managed.json()["items"]] == ["SN001"]
    assert tenant_managed.json()["items"][0]["transferable"] is False
    assert transfer.status_code == 409
    assert transfer.json()["detail"]["code"] == "DEVICE_NOT_IN_POOL_WORKSPACE"

    set_current_org_id(None)
    async with session_factory() as db:
        await db.execute(
            text("UPDATE devices SET managed_by_org_id = 'org-1' WHERE id = 'dev-1'")
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/admin/devices")

    assert listed.status_code == 200
    assert [item["serial"] for item in listed.json()["items"]] == ["SN001"]
    assert listed.json()["items"][0]["transferable"] is True


def test_agent_health_does_not_age_a_departed_agent_into_stale():
    """`status` is the transport's verdict; only an 'online' row can be stale."""
    just_left = NOW - timedelta(minutes=7)
    # The agent dropped 7 minutes ago and `mark_relay_offline` already said so.
    assert (
        workspace_admin_routes._agent_health_values("offline", just_left, NOW)
        == "offline"
    )
    # A row still claiming online with an aged heartbeat is the real stale case.
    assert (
        workspace_admin_routes._agent_health_values("online", just_left, NOW)
        == "stale"
    )
    assert (
        workspace_admin_routes._agent_health_values(
            "online", NOW - timedelta(seconds=30), NOW
        )
        == "online"
    )
    assert (
        workspace_admin_routes._agent_health_values("disabled", NOW, NOW) == "disabled"
    )


@pytest.mark.asyncio
async def test_admin_deletes_pool_phone_so_its_serial_can_register_again(
    session_factory,
):
    """A retired pool phone's row holds its serial hostage until admin drops it."""
    await _seed_workspace(session_factory)

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        deleted = await client.delete("/api/admin/devices/dev-1")
        listed = await client.get("/api/admin/devices")

    assert deleted.status_code == 204
    assert listed.json()["items"] == []

    set_current_org_id(None)
    async with session_factory() as db:
        remaining = (
            await db.execute(text("SELECT COUNT(*) FROM devices WHERE serial = 'SN001'"))
        ).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_admin_cannot_delete_a_phone_a_tenant_is_currently_using(
    session_factory,
):
    """Deleting an allocated phone would yank it from the tenant mid-use."""
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        await db.execute(
            text(
                "UPDATE devices SET org_id = 'org-2', managed_by_org_id = 'org-1' "
                "WHERE id = 'dev-1'"
            )
        )
        await db.commit()

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.delete("/api/admin/devices/dev-1")

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "DEVICE_ASSIGNED_TO_WORKSPACE"

    set_current_org_id(None)
    async with session_factory() as db:
        remaining = (
            await db.execute(text("SELECT COUNT(*) FROM devices WHERE serial = 'SN001'"))
        ).scalar_one()
    assert remaining == 1


@pytest.mark.asyncio
async def test_admin_cannot_delete_a_phone_owned_by_a_tenant_relay(session_factory):
    """Only pool-managed phones are the admin's to drop — same rule as transfer."""
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        await db.execute(
            text("UPDATE devices SET managed_by_org_id = 'org-2' WHERE id = 'dev-1'")
        )
        await db.commit()

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.delete("/api/admin/devices/dev-1")

    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "DEVICE_NOT_IN_POOL_WORKSPACE"


@pytest.mark.asyncio
async def test_agent_payload_reports_transport_fact_not_just_intent(
    session_factory, monkeypatch
):
    """Enabling sets intent; the console must not claim it took effect."""
    await _seed_workspace(session_factory)

    live: set[str] = set()
    monkeypatch.setattr(
        workspace_admin_routes, "_live_relay_ids", lambda: set(live)
    )
    monkeypatch.setattr(
        workspace_admin_routes,
        "_apply_agent_suspension",
        lambda relay_id, serials, *, suspend: None,
    )

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        enabled = await client.post("/api/admin/agents/relay-1/enable")
        listed_before = await client.get("/api/admin/agents")
        live.add("relay-1")
        listed_after = await client.get("/api/admin/agents")

    assert enabled.status_code == 200
    # Row says offline-and-allowed, transport says the agent is not back yet.
    assert enabled.json()["connected"] is False
    assert listed_before.json()["items"][0]["connected"] is False
    assert listed_after.json()["items"][0]["connected"] is True


@pytest.mark.asyncio
async def test_agent_actions_work_across_workspaces_not_just_the_current_one(
    session_factory, monkeypatch
):
    """The list reads every workspace; the actions on those rows must too."""
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    monkeypatch.setattr(
        workspace_admin_routes,
        "_apply_agent_suspension",
        lambda relay_id, serials, *, suspend: None,
    )
    # Session sits in org-2 while the agent belongs to org-1.
    set_current_org_id("org-2")

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/admin/agents")
        disabled = await client.post("/api/admin/agents/relay-1/disable")

    assert [item["relay_id"] for item in listed.json()["items"]] == ["relay-1"]
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"


@pytest.mark.asyncio
async def test_enabling_a_still_connected_agent_reports_online_not_stale(
    session_factory, monkeypatch
):
    """Resume keeps the connection, so nothing else would clear 'offline'."""
    await _seed_workspace(session_factory)
    set_current_org_id(None)
    async with session_factory() as db:
        await db.execute(
            text("UPDATE relay_agents SET status = 'disabled' WHERE relay_id = 'relay-1'")
        )
        await db.commit()

    monkeypatch.setattr(
        workspace_admin_routes,
        "_apply_agent_suspension",
        lambda relay_id, serials, *, suspend: None,
    )
    # The agent never went away — it was parked, and it is still on the wire.
    monkeypatch.setattr(workspace_admin_routes, "_live_relay_ids", lambda: {"relay-1"})

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        enabled = await client.post("/api/admin/agents/relay-1/enable")

    assert enabled.status_code == 200
    body = enabled.json()
    assert body["status"] == "online"
    assert body["health"] == "online"
    assert body["connected"] is True


@pytest.mark.asyncio
async def test_enabling_a_departed_agent_stays_offline_until_it_returns(
    session_factory, monkeypatch
):
    await _seed_workspace(session_factory)
    monkeypatch.setattr(
        workspace_admin_routes,
        "_apply_agent_suspension",
        lambda relay_id, serials, *, suspend: None,
    )
    monkeypatch.setattr(workspace_admin_routes, "_live_relay_ids", set)

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        enabled = await client.post("/api/admin/agents/relay-1/enable")

    assert enabled.json()["status"] == "offline"
    assert enabled.json()["connected"] is False


@pytest.mark.asyncio
async def test_releasing_a_phone_the_agent_stopped_reporting_still_returns_it(
    session_factory,
):
    """A dead phone is the one that most needs releasing.

    `agent.serials` is rewritten by every heartbeat, so a phone that was
    unplugged or died drops off it. Requiring it on release stranded the device
    in the workspace it was lent to, with no way back. Assignment keeps the
    guard — the same serial must still be refused there.
    """
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )

    # The phone is unplugged; the next heartbeat overwrites the snapshot.
    set_current_org_id(None)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = []
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        release = await client.request(
            "DELETE",
            "/api/admin/agents/relay-1/phone-allocations",
            json={"serials": ["SN001"]},
        )
        reassign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )

    assert assign.status_code == 200, assign.text
    assert release.status_code == 200, release.text
    assert release.json()["items"][0]["assignedWorkspaceId"] == "org-1"
    # Assignment still picks only from what the agent can see.
    assert reassign.status_code == 409
    assert reassign.json()["detail"]["code"] == "SERIAL_NOT_REPORTED_BY_AGENT"

    set_current_org_id(None)
    async with session_factory() as db:
        row = (
            await db.execute(
                text("SELECT org_id, managed_by_org_id FROM devices WHERE serial = 'SN001'")
            )
        ).one()
    assert row[0] == "org-1"
    assert row[1] == "org-1"


@pytest.mark.asyncio
async def test_releasing_an_unknown_serial_is_refused_and_creates_no_device(
    session_factory,
):
    """Dropping the snapshot guard on release must not let a typo mint a row."""
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)

    set_current_org_id(None)
    async with session_factory() as db:
        before = (await db.execute(text("SELECT COUNT(*) FROM devices"))).scalar_one()

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        release = await client.request(
            "DELETE",
            "/api/admin/agents/relay-1/phone-allocations",
            json={"serials": ["TYPO-SERIAL"]},
        )

    assert release.status_code == 404, release.text
    assert release.json()["detail"]["code"] == "DEVICE_NOT_FOUND"
    assert release.json()["detail"]["serial"] == "TYPO-SERIAL"

    set_current_org_id(None)
    async with session_factory() as db:
        after = (await db.execute(text("SELECT COUNT(*) FROM devices"))).scalar_one()
        ghost = (
            await db.execute(
                text("SELECT COUNT(*) FROM devices WHERE serial = 'TYPO-SERIAL'")
            )
        ).scalar_one()
    assert after == before
    assert ghost == 0


@pytest.mark.asyncio
async def test_pooled_separates_a_phone_in_stock_from_one_handed_out(session_factory):
    """`org_id` alone cannot tell the two apart — it equals the pool in both."""
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)
    async with session_factory() as db:
        with tenant_context("org-1"):
            agent = await db.get(RelayAgent, "ra-1")
            assert agent is not None
            agent.serials = ["SN001"]
        await db.commit()

    app = _app(session_factory, _user(org_role="admin", org_id="org-1"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assign = await client.post(
            "/api/admin/agents/relay-1/phone-allocations",
            json={"targetWorkspaceId": "org-2", "serials": ["SN001"]},
        )
        assigned_devices = await client.get("/api/admin/devices?limit=100")
        release = await client.request(
            "DELETE",
            "/api/admin/agents/relay-1/phone-allocations",
            json={"serials": ["SN001"]},
        )
        released_devices = await client.get("/api/admin/devices?limit=100")

    assert assign.status_code == 200, assign.text
    assert assign.json()["items"][0]["pooled"] is False
    assert assigned_devices.status_code == 200
    assert assigned_devices.json()["items"][0]["pooled"] is False
    assert assigned_devices.json()["items"][0]["workspaceId"] == "org-2"

    assert release.status_code == 200, release.text
    assert release.json()["items"][0]["pooled"] is True
    assert released_devices.status_code == 200
    assert released_devices.json()["items"][0]["pooled"] is True
    assert released_devices.json()["items"][0]["workspaceId"] == "org-1"


@pytest.mark.asyncio
async def test_agent_workspace_cannot_be_moved_by_patch(session_factory):
    """The activation code owns the agent's workspace.

    `upsert_relay_agent` writes org_id back from the enrollment token on every
    reconnect, so a move made here would silently revert. Refuse it instead of
    promising a change that does not survive the next heartbeat.
    """
    await _seed_workspace(session_factory)
    await _seed_second_workspace(session_factory)

    app = _app(session_factory, _user(role="superadmin", org_role=""))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        moved = await client.patch(
            "/api/admin/agents/relay-1", json={"workspaceId": "org-2"}
        )
        # Echoing the unchanged value back must stay allowed — edit forms do it.
        renamed = await client.patch(
            "/api/admin/agents/relay-1",
            json={"workspaceId": "org-1", "name": "rack-a"},
        )

    assert moved.status_code == 409, moved.text
    assert moved.json()["detail"]["code"] == "AGENT_WORKSPACE_IS_IMMUTABLE"
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "rack-a"
    assert renamed.json()["workspaceId"] == "org-1"
    # org-1 is the pool workspace, so the console may offer allocation.
    assert renamed.json()["workspaceKind"] == "pool"

    set_current_org_id(None)
    async with session_factory() as db:
        org_id = (
            await db.execute(text("SELECT org_id FROM relay_agents WHERE relay_id = 'relay-1'"))
        ).scalar_one()
    assert org_id == "org-1"
