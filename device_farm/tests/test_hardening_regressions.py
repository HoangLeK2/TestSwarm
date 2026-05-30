from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_create_execution_rejects_cross_tenant_device():
    from api.routes import executions as route
    from api.schemas.execution import ExecutionCreate

    body = ExecutionCreate(run_type="campaign_run", device_ids=["dev-1"])
    db = AsyncMock()
    user = SimpleNamespace(id="user-1", org_id="org-1")
    foreign_device = SimpleNamespace(id="dev-1", user_id="other-user", org_id="org-2")

    with patch.object(route, "get_device", AsyncMock(return_value=foreign_device)):
        with pytest.raises(HTTPException) as exc:
            await route.create_execution_endpoint(body, db, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_execution_rejects_cross_tenant_campaign():
    from api.routes import executions as route
    from api.schemas.execution import ExecutionCreate

    body = ExecutionCreate(run_type="campaign_run", campaign_id="camp-1")
    db = AsyncMock()
    user = SimpleNamespace(id="user-1", org_id="org-1")
    foreign_campaign = SimpleNamespace(id="camp-1", user_id="other-user", org_id="org-2")

    with patch.object(route, "get_campaign", AsyncMock(return_value=foreign_campaign)):
        with pytest.raises(HTTPException) as exc:
            await route.create_execution_endpoint(body, db, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_execution_rejects_cross_tenant_scenario():
    from api.routes import executions as route
    from api.schemas.execution import ExecutionCreate

    body = ExecutionCreate(run_type="campaign_run", scenario_id="sc-1")
    db = AsyncMock()
    user = SimpleNamespace(id="user-1", org_id="org-1")
    scenario = SimpleNamespace(id="sc-1", campaign_id="camp-2")
    foreign_campaign = SimpleNamespace(id="camp-2", user_id="other-user", org_id="org-2")

    with (
        patch.object(route, "get_scenario", AsyncMock(return_value=scenario)),
        patch.object(route, "get_campaign", AsyncMock(return_value=foreign_campaign)),
    ):
        with pytest.raises(HTTPException) as exc:
            await route.create_execution_endpoint(body, db, user)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_device_rejects_cross_tenant_device():
    from api.routes import executions as route
    from api.schemas.execution import AddDeviceBody

    db = AsyncMock()
    user = SimpleNamespace(id="user-1", org_id="org-1")
    execution = SimpleNamespace(id="exec-1", user_id="user-1")
    foreign_device = SimpleNamespace(id="dev-1", user_id="other-user", org_id="org-2")

    with (
        patch.object(route, "_get_or_404", AsyncMock(return_value=execution)),
        patch.object(route, "get_device", AsyncMock(return_value=foreign_device)),
    ):
        with pytest.raises(HTTPException) as exc:
            await route.add_device_endpoint("exec-1", AddDeviceBody(device_id="dev-1"), db, user)

    assert exc.value.status_code == 404


def test_dlq_route_declared_before_execution_id_route():
    from api.routes.executions import router

    path_order = [r.path for r in router.routes]
    assert "/executions/dlq" in path_order
    assert "/executions/{execution_id}" in path_order
    assert path_order.index("/executions/dlq") < path_order.index("/executions/{execution_id}")


@pytest.mark.asyncio
async def test_run_content_stats_enforces_run_campaign_ownership():
    from api.routes import campaigns as route

    db = AsyncMock()
    user = SimpleNamespace(id="user-1")
    campaign = SimpleNamespace(id="camp-1", user_id="user-1")
    wrong_run = SimpleNamespace(id="run-1", campaign_id="camp-2", user_id="user-1")

    with (
        patch.object(route, "_get_campaign_or_404", AsyncMock(return_value=campaign)),
        patch("db.crud.execution.get_execution", AsyncMock(return_value=wrong_run)),
    ):
        with pytest.raises(HTTPException) as exc:
            await route.run_content_stats("camp-1", "run-1", db, user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_compile_scenario_rejects_cross_tenant_device_serial():
    from api.routes import campaigns as route
    from api.routes.campaigns import CompileScenarioBody

    db = AsyncMock()
    user = SimpleNamespace(id="user-1")
    campaign = SimpleNamespace(id="camp-1", user_id="user-1", name="C")
    foreign_device = SimpleNamespace(serial="SERIAL-1", user_id="other-user")

    with (
        patch.object(route, "_get_campaign_or_404", AsyncMock(return_value=campaign)),
        patch("api.routes.campaigns.get_device_by_serial", AsyncMock(return_value=foreign_device)),
    ):
        with pytest.raises(HTTPException) as exc:
            await route.compile_scenario(
                request=MagicMock(),
                campaign_id="camp-1",
                body=CompileScenarioBody(instructions="test", device_serial="SERIAL-1", device_context={}),
                db=db,
                user=user,
            )
    assert exc.value.status_code == 404


def test_webhook_ssrf_private_hosts_are_blocked():
    from services import webhook_dispatcher as wd

    cases = [
        ("http://127.0.0.1/hook", [("127.0.0.1",)]),
        ("https://localhost/hook", [("127.0.0.1",)]),
        ("http://10.1.2.3/hook", [("10.1.2.3",)]),
        ("http://169.254.10.10/hook", [("169.254.10.10",)]),
        ("http://[::1]/hook", [("::1",)]),
    ]

    for url, ips in cases:
        fake_info = [(None, None, None, None, (ip[0], 443)) for ip in ips]
        with patch("services.webhook_dispatcher.socket.getaddrinfo", return_value=fake_info):
            assert wd._is_safe_webhook_url(url) is False


def test_webhook_ssrf_public_host_allowed():
    from services import webhook_dispatcher as wd

    fake_info = [(None, None, None, None, ("8.8.8.8", 443))]
    with patch("services.webhook_dispatcher.socket.getaddrinfo", return_value=fake_info):
        assert wd._is_safe_webhook_url("https://example.com/hook") is True


def test_cors_uses_allowlist_without_regex():
    from runtime.core import DeviceManager, TaskQueue
    from web.server import create_app
    from core.config import Config, WebConfig

    manager = MagicMock(spec=DeviceManager)
    manager.all_devices.return_value = []
    queue = MagicMock(spec=TaskQueue)
    config = Config(
        web=WebConfig(cors_allowed_origins=["https://app.example.com"]),
    )
    app = create_app(manager, queue, config, templates_dir="templates", static_dir=".", front_end_dist=None)
    cors_middleware = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors_middleware.kwargs["allow_origins"] == ["https://app.example.com"]
    assert "allow_origin_regex" not in cors_middleware.kwargs


def test_campaign_fleet_workflow_endpoints_enforce_ownership_guard():
    from pathlib import Path

    target = Path(__file__).resolve().parents[1] / "api" / "routes" / "device_control" / "campaign_fleet.py"
    content = target.read_text(encoding="utf-8")
    assert "await _assert_workflow_owned(db, workflow_id, user.id)" in content
    assert "await _assert_campaign_owned(db, campaign_id, user.id)" in content


def test_migration_019_contains_unmapped_guardrail():
    from pathlib import Path

    migration = Path(__file__).resolve().parents[1] / "db" / "migrations" / "019_merge_campaign_runs_into_executions.py"
    content = migration.read_text(encoding="utf-8")
    assert "rows with run_id remain unmapped" in content
    assert "RAISE EXCEPTION" in content
    assert "refusing to drop campaign_runs/content_items.run_id" in content
    assert "Time-nearest fallback" not in content


def test_migration_runner_records_applied_files_and_checksums():
    from pathlib import Path

    runner = Path(__file__).resolve().parents[1] / "db" / "migrations" / "__init__.py"
    content = runner.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in content
    assert "checksum" in content
    assert "checksum mismatch" in content
    assert "_record_applied_migration" in content


def test_production_disables_sqlalchemy_create_all_by_default(monkeypatch):
    from db.database import _auto_create_schema_enabled

    monkeypatch.setenv("DEVICE_FARM_ENV", "production")
    monkeypatch.delenv("FARM_DB_AUTO_CREATE_SCHEMA", raising=False)
    assert _auto_create_schema_enabled() is False

    monkeypatch.setenv("FARM_DB_AUTO_CREATE_SCHEMA", "1")
    assert _auto_create_schema_enabled() is True

    monkeypatch.setenv("FARM_DB_AUTO_CREATE_SCHEMA", "0")
    assert _auto_create_schema_enabled() is False


@pytest.mark.asyncio
async def test_create_dlq_entry_is_idempotent_for_open_items():
    from db.crud.execution_dlq import create_dlq_entry

    db = AsyncMock()
    existing = SimpleNamespace(status="pending", error=None)
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = existing
    db.execute.return_value = result_proxy

    out = await create_dlq_entry(
        db,
        execution_id="exec-1",
        device_serial="SERIAL-1",
        error="failed",
    )
    assert out is existing
    assert out.error == "failed"
    db.add.assert_not_called()


def test_non_db_mode_requires_device_control_key_in_prod():
    from api.deps import make_device_auth_dependency

    with patch.dict("os.environ", {"DEVICE_FARM_ENV": "production", "DEVICE_CONTROL_API_KEY": ""}, clear=False):
        with pytest.raises(RuntimeError):
            make_device_auth_dependency(False)


@pytest.mark.asyncio
async def test_non_db_mode_validates_device_control_key_header():
    from api.deps import make_device_auth_dependency

    with patch.dict("os.environ", {"DEVICE_CONTROL_API_KEY": "k1", "DEVICE_FARM_ENV": "dev"}, clear=False):
        dep = make_device_auth_dependency(False)
        req = MagicMock()
        req.headers.get.side_effect = lambda k, default=None: "k1" if k == "x-device-control-key" else default
        req.query_params.get.return_value = None
        await dep(req)


def test_agent_session_has_strict_auth_guard():
    from pathlib import Path

    target = Path(__file__).resolve().parents[1] / "web" / "ws.py"
    content = target.read_text(encoding="utf-8")
    assert "_strict_agent_auth" in content
    assert "_has_valid_pair = bool(pair_id and pair_id in _pairing_mod.store)" in content
    assert "Agent auth required (set AGENT_SECRET or use pairing key)." in content


def test_grpc_relay_supports_tls_and_prod_insecure_block():
    from pathlib import Path

    target = Path(__file__).resolve().parents[1] / "runtime" / "transports" / "grpc_relay_server.py"
    content = target.read_text(encoding="utf-8")
    assert "add_secure_port" in content
    assert "Refusing insecure gRPC relay in production/staging" in content


def test_relay_capabilities_retroactive_callback_signature_fixed():
    from pathlib import Path

    target = Path(__file__).resolve().parents[1] / "runtime" / "transports" / "adb_relay_server.py"
    content = target.read_text(encoding="utf-8")
    assert "callback(serial, self._capabilities.get(serial, {}))" in content
