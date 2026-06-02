from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from api import deps
from api.auth.rbac import (
    build_enforcer_for_user,
    build_enforcer_for_user_from_db,
    clear_rbac_cache,
)
from api.deps import require_permission
from api.routes import campaigns as campaign_routes
from api.routes import devices as device_routes
from api.routes import executions as execution_routes
from api.routes import organizations as organization_routes
from api.routes import scenario_templates as scenario_template_routes


def _user(role: str, org_id: str | None = "org-1"):
    return SimpleNamespace(id=f"{role}-user", role=role, org_id=org_id, is_active=True)


class _PolicyResult:
    def __init__(self, rows, one=None):
        self._rows = rows
        self._one = one

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._one


class _PolicyDb:
    def __init__(self, rows, revision: int = 1):
        self.rows = rows
        self.revision = revision
        self.queries = 0

    async def execute(self, statement):
        self.queries += 1
        sql = str(statement)
        if "casbin_policy_revision" in sql:
            return _PolicyResult([], (self.revision,))
        return _PolicyResult(self.rows)


@pytest.mark.asyncio
async def test_casbin_rbac_loads_policy_from_database_not_csv():
    clear_rbac_cache()
    user = _user("operator")
    user.org_role = "owner"
    db = _PolicyDb(
        [
            ("p", "owner", "*", "devices", "read", None, None),
            ("p", "member", "*", "devices", "read", None, None),
        ]
    )

    enforcer = await build_enforcer_for_user_from_db(user, db, domain="org-1")
    cached_enforcer = await build_enforcer_for_user_from_db(user, db, domain="org-1")

    assert db.queries == 2
    assert enforcer.enforce("operator-user", "org-1", "devices", "read")
    assert not enforcer.enforce("operator-user", "org-1", "devices", "manage")
    assert cached_enforcer is enforcer
    clear_rbac_cache()


@pytest.mark.asyncio
async def test_casbin_rbac_cache_refreshes_when_revision_changes(monkeypatch):
    clear_rbac_cache()
    monkeypatch.setenv("DEVICE_FARM_RBAC_POLICY_CACHE_TTL_SECONDS", "0")
    user = _user("operator")
    user.org_role = "owner"
    db = _PolicyDb(
        [("p", "owner", "*", "devices", "read", None, None)],
        revision=1,
    )

    first = await build_enforcer_for_user_from_db(user, db, domain="org-1")
    db.rows = [("p", "owner", "*", "devices", "(read|manage)", None, None)]
    db.revision = 2
    second = await build_enforcer_for_user_from_db(user, db, domain="org-1")

    assert first.enforce("operator-user", "org-1", "devices", "read")
    assert not first.enforce("operator-user", "org-1", "devices", "manage")
    assert second.enforce("operator-user", "org-1", "devices", "manage")
    assert second is not first
    clear_rbac_cache()


def test_casbin_rbac_domain_allows_admin_user_permissions():
    enforcer = build_enforcer_for_user(_user("admin"), domain="org-1")

    assert enforcer.enforce("admin-user", "org-1", "users", "read")
    assert enforcer.enforce("admin-user", "org-1", "users", "create")


def test_casbin_rbac_domain_allows_superadmin_all_permissions():
    enforcer = build_enforcer_for_user(_user("superadmin"), domain="org-any")

    assert enforcer.enforce("superadmin-user", "org-any", "users", "read")
    assert enforcer.enforce("superadmin-user", "org-any", "devices", "manage")
    assert enforcer.enforce("superadmin-user", "org-any", "executions", "execute")


def test_casbin_rbac_domain_denies_operator_user_permissions():
    enforcer = build_enforcer_for_user(_user("operator"), domain="org-1")

    assert not enforcer.enforce("operator-user", "org-1", "users", "read")


def test_casbin_rbac_domain_allows_owner_org_management():
    user = _user("operator")
    user.org_role = "owner"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "organizations", "read")
    assert enforcer.enforce("operator-user", "org-1", "organizations", "update")


def test_casbin_rbac_domain_denies_member_org_management():
    user = _user("operator")
    user.org_role = "member"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "organizations", "read")
    assert not enforcer.enforce("operator-user", "org-1", "organizations", "update")


def test_casbin_rbac_domain_allows_member_device_read_only():
    user = _user("operator")
    user.org_role = "member"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "devices", "read")
    assert not enforcer.enforce("operator-user", "org-1", "devices", "create")
    assert not enforcer.enforce("operator-user", "org-1", "devices", "execute")


def test_casbin_rbac_domain_allows_owner_device_management():
    user = _user("operator")
    user.org_role = "owner"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "devices", "create")
    assert enforcer.enforce("operator-user", "org-1", "devices", "update")
    assert enforcer.enforce("operator-user", "org-1", "devices", "delete")
    assert enforcer.enforce("operator-user", "org-1", "devices", "execute")


def test_casbin_rbac_domain_allows_member_campaign_read_only():
    user = _user("operator")
    user.org_role = "member"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "campaigns", "read")
    assert not enforcer.enforce("operator-user", "org-1", "campaigns", "create")
    assert not enforcer.enforce("operator-user", "org-1", "campaigns", "execute")


def test_casbin_rbac_domain_allows_owner_campaign_management():
    user = _user("operator")
    user.org_role = "owner"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "campaigns", "create")
    assert enforcer.enforce("operator-user", "org-1", "campaigns", "update")
    assert enforcer.enforce("operator-user", "org-1", "campaigns", "delete")
    assert enforcer.enforce("operator-user", "org-1", "campaigns", "execute")


def test_casbin_rbac_domain_allows_member_execution_read_only():
    user = _user("operator")
    user.org_role = "member"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "executions", "read")
    assert not enforcer.enforce("operator-user", "org-1", "executions", "create")
    assert not enforcer.enforce("operator-user", "org-1", "executions", "execute")


def test_casbin_rbac_domain_allows_owner_execution_management():
    user = _user("operator")
    user.org_role = "owner"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "executions", "create")
    assert enforcer.enforce("operator-user", "org-1", "executions", "update")
    assert enforcer.enforce("operator-user", "org-1", "executions", "delete")
    assert enforcer.enforce("operator-user", "org-1", "executions", "execute")


def test_casbin_rbac_domain_allows_member_scenario_template_read_only():
    user = _user("operator")
    user.org_role = "member"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "scenario-templates", "read")
    assert not enforcer.enforce("operator-user", "org-1", "scenario-templates", "create")
    assert not enforcer.enforce("operator-user", "org-1", "scenario-templates", "update")
    assert not enforcer.enforce("operator-user", "org-1", "scenario-templates", "delete")


def test_casbin_rbac_domain_allows_owner_scenario_template_management():
    user = _user("operator")
    user.org_role = "owner"

    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "scenario-templates", "create")
    assert enforcer.enforce("operator-user", "org-1", "scenario-templates", "update")
    assert enforcer.enforce("operator-user", "org-1", "scenario-templates", "delete")


def test_casbin_rbac_domain_covers_remaining_route_resources():
    user = _user("operator")
    user.org_role = "owner"
    enforcer = build_enforcer_for_user(user, domain="org-1")

    resource_actions = {
        "accounts": {"read", "create", "update", "delete", "execute"},
        "account-groups": {"read", "create", "update", "delete", "execute"},
        "device-groups": {"read", "create", "update", "delete"},
        "schedules": {"read", "create", "update", "delete", "execute"},
        "relay-agents": {"read", "create", "update", "delete", "execute"},
        "notifications": {"read", "create", "update", "delete", "execute"},
        "content": {"read", "create", "update", "delete"},
        "analytics": {"read"},
        "me": {"read"},
    }

    for resource, actions in resource_actions.items():
        for action in actions:
            assert enforcer.enforce("operator-user", "org-1", resource, action)


def test_casbin_rbac_domain_keeps_members_read_only_for_remaining_resources():
    user = _user("operator")
    user.org_role = "member"
    enforcer = build_enforcer_for_user(user, domain="org-1")

    for resource in {
        "accounts",
        "account-groups",
        "device-groups",
        "schedules",
        "relay-agents",
        "notifications",
        "content",
        "analytics",
    }:
        assert enforcer.enforce("operator-user", "org-1", resource, "read")
        assert not enforcer.enforce("operator-user", "org-1", resource, "create")


def test_casbin_rbac_domain_allows_supervisor_device_and_campaign_ops():
    user = _user("operator")
    user.org_role = "supervisor"
    enforcer = build_enforcer_for_user(user, domain="org-1")

    assert enforcer.enforce("operator-user", "org-1", "devices", "read")
    assert enforcer.enforce("operator-user", "org-1", "devices", "create")
    assert enforcer.enforce("operator-user", "org-1", "devices", "execute")
    assert not enforcer.enforce("operator-user", "org-1", "devices", "delete")

    assert enforcer.enforce("operator-user", "org-1", "campaigns", "read")
    assert enforcer.enforce("operator-user", "org-1", "campaigns", "create")
    assert enforcer.enforce("operator-user", "org-1", "campaigns", "update")
    assert enforcer.enforce("operator-user", "org-1", "campaigns", "execute")
    assert not enforcer.enforce("operator-user", "org-1", "campaigns", "delete")
    assert not enforcer.enforce("operator-user", "org-1", "organizations", "manage")


def test_current_user_routes_require_casbin_permission_dependency():
    routes_dir = Path(__file__).resolve().parents[1] / "api" / "routes"
    missing: list[str] = []

    for path in sorted(routes_dir.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_decorators = [
                dec
                for dec in node.decorator_list
                if isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in {"get", "post", "patch", "put", "delete"}
            ]
            if not route_decorators:
                continue

            uses_current_user = any(
                ast.unparse(arg.annotation) in {"CurrentUser", "AdminUser"}
                for arg in node.args.args
                if arg.annotation is not None
            )
            if not uses_current_user:
                continue

            if not any("require_permission" in ast.unparse(dec) for dec in route_decorators):
                missing.append(f"{path.relative_to(routes_dir.parent.parent)}:{node.name}")

    assert missing == []


def test_stf_apk_download_requires_device_read_permission():
    routes_dir = Path(__file__).resolve().parents[1] / "api" / "routes"
    tree = ast.parse((routes_dir / "devices.py").read_text())

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "download_stf_apk":
            decorators = [ast.unparse(dec) for dec in node.decorator_list]
            assert any(
                "require_permission('devices', 'read')" in decorator
                or 'require_permission("devices", "read")' in decorator
                for decorator in decorators
            )
            return

    pytest.fail("download_stf_apk route not found")


@pytest.mark.asyncio
async def test_require_permission_denies_forbidden_role():
    app = FastAPI()

    @app.get("/users", dependencies=[Depends(require_permission("users", "read"))])
    async def protected_users():
        return {"ok": True}

    app.dependency_overrides[deps._get_current_user] = lambda: _user("operator")

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_db] = fake_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/users")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN_ROLE"


@pytest.mark.asyncio
async def test_organization_route_allows_org_member_read(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    user = _user("operator")
    user.org_role = "member"

    async def fake_db():
        yield object()

    fake_org = SimpleNamespace(
        id="org-1",
        business_name="Acme",
        business_email=None,
        business_logo=None,
        slug="acme",
        status="active",
        plan="standard",
        created_at="2026-01-01T00:00:00Z",
    )

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        organization_routes.repo,
        "query_organizations",
        AsyncMock(return_value=([fake_org], 1)),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/organizations")

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "org-1"


@pytest.mark.asyncio
async def test_organization_route_denies_role_without_policy(monkeypatch):
    app = FastAPI()
    app.include_router(organization_routes.router)

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: _user("viewer")
    app.dependency_overrides[deps._get_db] = fake_db
    list_orgs = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(
        organization_routes.repo,
        "query_organizations",
        list_orgs,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/organizations")

    assert response.status_code == 403
    list_orgs.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_route_allows_org_member_read(monkeypatch):
    app = FastAPI()
    app.include_router(device_routes.router)

    user = _user("operator")
    user.org_role = "member"

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(device_routes.repo, "list_devices", AsyncMock(return_value=[]))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/devices")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_device_create_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(device_routes.router)

    user = _user("operator")
    user.org_role = "member"
    get_by_serial = AsyncMock(return_value=None)
    create_device = AsyncMock(return_value=SimpleNamespace(
        id="dev-1",
        serial="s1",
        name="S1",
        device_key="key",
        user_id=user.id,
        brand="",
        model="",
        android_version="",
        sdk_version=0,
        screen_width=0,
        screen_height=0,
        last_seen=None,
        created_at="2026-01-01T00:00:00Z",
    ))

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(device_routes.repo, "get_device_by_serial", get_by_serial)
    monkeypatch.setattr(device_routes.repo, "create_device", create_device)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/devices", json={"serial": "s1", "name": "S1"})

    assert response.status_code == 403
    get_by_serial.assert_not_awaited()
    create_device.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_control_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(device_routes.router)

    user = _user("operator")
    user.org_role = "member"
    dispatch = AsyncMock(return_value={
        "ok": True,
        "output": "",
        "exit_code": 0,
        "error": "",
    })

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(device_routes, "_dispatch_relay_command", dispatch)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/devices/dev-1/bootstrap")

    assert response.status_code == 403
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_campaign_route_allows_org_member_read(monkeypatch):
    app = FastAPI()
    app.include_router(campaign_routes.router)

    user = _user("operator")
    user.org_role = "member"

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(campaign_routes.repo, "list_campaigns", AsyncMock(return_value=[]))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/campaigns")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_campaign_create_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(campaign_routes.router)

    user = _user("operator")
    user.org_role = "member"
    get_by_name = AsyncMock(return_value=None)
    create_campaign = AsyncMock(return_value=SimpleNamespace(
        id="camp-1",
        name="C1",
        description="",
        status="idle",
        variables={},
        user_id=user.id,
        target_group_id=None,
        created_at="2026-01-01T00:00:00Z",
    ))
    list_scenarios = AsyncMock(return_value=[])

    async def fake_db():
        yield SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(campaign_routes.repo, "get_campaign_by_name", get_by_name)
    monkeypatch.setattr(campaign_routes.repo, "create_campaign", create_campaign)
    monkeypatch.setattr(campaign_routes.repo, "list_scenarios", list_scenarios)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/campaigns", json={"name": "C1"})

    assert response.status_code == 403
    get_by_name.assert_not_awaited()
    create_campaign.assert_not_awaited()


@pytest.mark.asyncio
async def test_campaign_compile_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(campaign_routes.router)

    user = _user("operator")
    user.org_role = "member"
    get_campaign_or_404 = AsyncMock(return_value=SimpleNamespace(
        id="camp-1",
        name="C1",
        description="",
        status="idle",
        variables={},
        user_id=user.id,
        target_group_id=None,
        created_at="2026-01-01T00:00:00Z",
    ))

    async def fake_db():
        yield SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(campaign_routes, "_get_campaign_or_404", get_campaign_or_404)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/campaigns/camp-1/compile-scenario",
            json={"instructions": "open app"},
        )

    assert response.status_code == 403
    get_campaign_or_404.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_route_allows_org_member_read(monkeypatch):
    app = FastAPI()
    app.include_router(execution_routes.router)

    user = _user("operator")
    user.org_role = "member"

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(execution_routes, "list_executions", AsyncMock(return_value=([], 0)))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/executions")

    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_execution_create_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(execution_routes.router)

    user = _user("operator")
    user.org_role = "member"
    create_execution = AsyncMock()

    async def fake_db():
        yield SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(execution_routes, "create_execution", create_execution)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/executions", json={"run_type": "campaign_run"})

    assert response.status_code == 403
    create_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_dlq_retry_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(execution_routes.router)

    user = _user("operator")
    user.org_role = "member"
    get_execution = AsyncMock()

    async def fake_db():
        yield SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(execution_routes, "get_execution", get_execution)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/executions/dlq/dlq-1/retry")

    assert response.status_code == 403
    get_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_scenario_template_route_allows_org_member_read(monkeypatch):
    app = FastAPI()
    app.include_router(scenario_template_routes.router)

    user = _user("operator")
    user.org_role = "member"

    async def fake_db():
        yield object()

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(
        scenario_template_routes,
        "org_member_user_ids",
        AsyncMock(return_value=[user.id]),
    )
    monkeypatch.setattr(
        scenario_template_routes,
        "list_templates",
        AsyncMock(return_value=[]),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/scenario-templates")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_scenario_template_create_route_denies_org_member(monkeypatch):
    app = FastAPI()
    app.include_router(scenario_template_routes.router)

    user = _user("operator")
    user.org_role = "member"
    create_template = AsyncMock()

    async def fake_db():
        yield SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())

    app.dependency_overrides[deps._get_current_user] = lambda: user
    app.dependency_overrides[deps._get_db] = fake_db
    monkeypatch.setattr(scenario_template_routes, "create_template", create_template)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/scenario-templates",
            json={"name": "tmpl", "steps": []},
        )

    assert response.status_code == 403
    create_template.assert_not_awaited()
