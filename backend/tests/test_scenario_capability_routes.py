from __future__ import annotations

import asyncio
import queue
import threading
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from api.auth.context import AuthContext
from api.routes.device_control.connect import build_connect_router
from api.routes.device_control.scenarios import build_scenarios_router
from db.models.account import Account, DeviceAccount
from db.models.device import Device
from db.models.execution import Execution, ExecutionResult
from db.models.execution_step import ExecutionStep
from db.models.organization import Organization


class _Config:
    class database:
        enabled = False


class _DbConfig:
    class database:
        enabled = True


class _FakeDevice:
    serial = "dev-1"
    u2 = object()
    stf = None

    def __init__(self, *, ocr: bool = True) -> None:
        self._ocr = ocr

    def ocr_supported(self) -> bool:
        return self._ocr

    def image_match_supported(self) -> bool:
        return True

    def set_clipboard(self, text: str) -> None:
        return None

    def push_file(self, local_path: str, remote_path: str) -> None:
        return None

    def pull_file(self, remote_path: str, local_path: str) -> None:
        return None

    def install(self, apk_source: str, timeout: float = 90.0) -> None:
        return None

    def take_screenshot(self):
        return None

    def shell(self, cmd: str) -> None:
        return None


class _FakeManager:
    def __init__(self, device: _FakeDevice | None = None) -> None:
        self.device = device

    def get_device(self, serial: str):
        if self.device is not None and serial == self.device.serial:
            return self.device
        return None


def _app(device: _FakeDevice | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(build_connect_router(_FakeManager(device), _Config()), prefix="/api")
    return app


def _scenario_app(device: _FakeDevice | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_scenarios_router(_FakeManager(device), _Config(), object()),
        prefix="/api",
    )
    return app


@pytest.mark.anyio
async def test_device_capabilities_route_returns_live_runtime_facts():
    async with AsyncClient(transport=ASGITransport(app=_app(_FakeDevice())), base_url="http://test") as client:
        response = await client.get("/api/scenario/device-capabilities/dev-1")

    assert response.status_code == 200
    data = response.json()
    assert data["serial"] == "dev-1"
    assert data["capabilities"]["has_u2"] is True
    assert data["capabilities"]["has_ocr"] is True
    assert data["capabilities"]["supports_file_ops"] is True


@pytest.mark.anyio
async def test_scenario_preflight_route_returns_issues_from_live_capabilities():
    async with AsyncClient(
        transport=ASGITransport(app=_app(_FakeDevice(ocr=False))),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/scenario/preflight/dev-1",
            json={"scenario": {"steps": [{"type": "extract_text_ocr"}]}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["preflight"]["ok"] is False
    assert data["preflight"]["issues"][0]["missing"] == ["has_ocr", "has_tesseract"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/api/devices/dev-1/scenario/preview",
        "/api/devices/dev-1/scenario/preview-stream",
    ],
)
async def test_preview_routes_reject_unsupported_nodes_before_running(path: str):
    with patch(
        "api.routes.device_control.scenarios._apply_preview_variables",
        new=AsyncMock(),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=_scenario_app(_FakeDevice(ocr=False))),
            base_url="http://test",
        ) as client:
            response = await client.post(
                path,
                json={"steps": [{"type": "extract_text_ocr", "save_as": "text"}]},
            )

    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "node_capability_preflight_failed"
    assert data["preflight"]["ok"] is False
    assert data["preflight"]["issues"][0]["missing"] == ["has_ocr", "has_tesseract"]


@pytest.mark.anyio
async def test_preview_stream_passes_org_scenario_registry_for_run_scenario(monkeypatch):
    from api.routes.device_control import scenarios as scenario_routes

    registry = {
        "by_id": {
            "child-1": {
                "steps": [{"id": "child-wait", "type": "wait", "seconds": 0}],
                "variables": {},
                "name": "child",
            }
        },
        "by_campaign_name": {},
        "by_template_name": {},
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        scenario_routes,
        "caller_auth_from_request",
        lambda _request: AuthContext(
            user_id="user-1",
            token_type="access",
            raw_token="test",
            org_id="org-1",
        ),
    )
    monkeypatch.setattr(
        scenario_routes,
        "_apply_preview_variables",
        AsyncMock(),
    )
    monkeypatch.setattr(
        scenario_routes,
        "_build_preview_scenario_registry",
        AsyncMock(return_value=registry),
    )

    def fake_run_scenario_on_device(*_args, **kwargs):
        captured["scenario_registry"] = kwargs.get("scenario_registry")
        on_step_done = kwargs.get("on_step_done")
        result = {
            "index": 0,
            "type": "run_scenario",
            "ok": True,
            "message": "run_scenario: child-1 completed",
        }
        if on_step_done:
            on_step_done(result)
        return {
            "serial": "dev-1",
            "success": True,
            "steps_executed": 1,
            "step_results": [result],
            "failed_message": "",
            "context": {},
        }

    monkeypatch.setattr(
        scenario_routes,
        "run_scenario_on_device",
        fake_run_scenario_on_device,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_scenario_app(_FakeDevice())),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/devices/dev-1/scenario/preview-stream",
            json={"steps": [{"type": "run_scenario", "scenario_id": "child-1"}]},
        )

    assert response.status_code == 200
    assert captured["scenario_registry"] is registry
    assert '"event": "done"' in response.text


@pytest.mark.anyio
async def test_preview_stream_accepts_manual_input_and_continues(monkeypatch):
    from api.routes.device_control import scenarios as scenario_routes

    captured: dict[str, str] = {}
    monkeypatch.setattr(
        scenario_routes,
        "uuid4",
        lambda: type("FixedUuid", (), {"hex": "manualinput123456"})(),
    )
    monkeypatch.setattr(
        scenario_routes,
        "caller_auth_from_request",
        lambda _request: AuthContext(
            user_id="user-1",
            token_type="access",
            raw_token="test",
            org_id="org-1",
        ),
    )
    monkeypatch.setattr(scenario_routes, "_apply_preview_variables", AsyncMock())

    def fake_run_scenario_on_device(*_args, **kwargs):
        handler = kwargs["manual_input_handler"]
        captured["text"] = handler(
            {
                "kind": "captcha",
                "challenge_id": "visual_code",
                "prompt": "Hãy nhập các ký tự mà bạn nhìn thấy",
                "platform": "instagram",
                "package": "com.instagram.android",
            }
        )
        return {
            "serial": "dev-1",
            "success": True,
            "steps_executed": 1,
            "step_results": [],
            "failed_message": "",
            "context": {},
        }

    monkeypatch.setattr(
        scenario_routes,
        "run_scenario_on_device",
        fake_run_scenario_on_device,
    )

    async with AsyncClient(
        transport=ASGITransport(app=_scenario_app(_FakeDevice())),
        base_url="http://test",
    ) as client:
        stream_task = asyncio.create_task(
            client.post(
                "/api/devices/dev-1/scenario/preview-stream",
                json={"steps": [{"type": "wait", "seconds": 0}]},
            )
        )
        submit_response = None
        for _ in range(50):
            submit_response = await client.post(
                "/api/devices/dev-1/scenario/preview-stream/scn-manualinpu/input",
                json={"text": "314015"},
            )
            if submit_response.status_code != 404:
                break
            await asyncio.sleep(0.01)
        response = await asyncio.wait_for(stream_task, timeout=2)

    assert submit_response is not None
    assert submit_response.status_code == 200
    assert submit_response.json()["accepted"] is True
    assert captured["text"] == "314015"
    assert '"event": "input_required"' in response.text
    assert '"challenge_id": "visual_code"' in response.text
    assert '"platform": "instagram"' in response.text
    assert '"event": "done"' in response.text


def test_preview_manual_input_rejects_duplicate_and_cancelled_submissions():
    from api.routes.device_control.scenarios import _PreviewManualInput

    cancel_event = threading.Event()
    broker = _PreviewManualInput(queue.Queue(), cancel_event)
    with broker._condition:
        broker._pending = True

    broker.submit("first-code")
    with pytest.raises(RuntimeError, match="already submitted"):
        broker.submit("replacement-code")

    cancel_event.set()
    with pytest.raises(RuntimeError, match="cancelled"):
        broker.submit("late-code")


@pytest.mark.anyio
async def test_account_login_preview_stream_creates_account_execution_history(
    tenancy_session_factory,
    monkeypatch,
):
    from api.routes.device_control import scenarios as scenario_routes

    org_id = "org-login-stream"
    user_id = "user-login-stream"
    account_id = "acc-login-stream"
    org_scenario_id = "org-login-scenario-preview"
    device_id = "dev-login-stream"
    serial = "dev-1"
    step_result = {
        "index": 0,
        "type": "wait",
        "ok": True,
        "message": "waited",
        "trace": {
            "account_id": account_id,
            "step_path": "login_wait",
            "step_id": "login_wait",
            "step_type": "wait",
            "depth": 0,
        },
    }
    captured: dict[str, str | None] = {}

    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=org_id,
                business_name="Login Stream Org",
                business_email="login-stream@example.com",
            )
        )
        db.add(
            Device(
                id=device_id,
                serial=serial,
                device_serial=serial,
                org_id=org_id,
            )
        )
        db.add(
            Account(
                id=account_id,
                org_id=org_id,
                platform="instagram",
                username="61582490922369",
            )
        )
        db.add(
            DeviceAccount(
                device_id=device_id,
                account_id=account_id,
                is_primary=True,
            )
        )
        await db.commit()

    monkeypatch.setattr(scenario_routes, "AsyncSessionLocal", tenancy_session_factory)
    monkeypatch.setattr(
        scenario_routes,
        "caller_auth_from_request",
        lambda _request: AuthContext(
            user_id=user_id,
            token_type="access",
            raw_token="test",
            org_id=org_id,
        ),
    )

    def fake_run_scenario_on_device(*_args, **kwargs):
        captured["execution_id"] = kwargs.get("execution_id")
        on_step_done = kwargs.get("on_step_done")
        if on_step_done:
            on_step_done(step_result)
        return {
            "serial": serial,
            "success": True,
            "steps_executed": 1,
            "step_results": [step_result],
            "failed_message": "",
            "context": {},
        }

    monkeypatch.setattr(
        scenario_routes,
        "run_scenario_on_device",
        fake_run_scenario_on_device,
    )

    app = FastAPI()
    app.include_router(
        build_scenarios_router(_FakeManager(_FakeDevice()), _DbConfig(), object()),
        prefix="/api",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/devices/{serial}/scenario/preview-stream",
            json={
                "steps": [{"id": "login_wait", "type": "wait", "seconds": 0}],
                "variables": {"__ACCOUNT_ID__": account_id},
                "persist_account_login_execution": True,
                "scenario_id": org_scenario_id,
            },
        )

    assert response.status_code == 200
    assert '"event": "start"' in response.text
    assert '"execution_id":' in response.text
    assert captured["execution_id"]

    async with tenancy_session_factory() as db:
        execution = (
            await db.execute(
                select(Execution).where(Execution.account_id == account_id)
            )
        ).scalar_one()
        step = (
            await db.execute(
                select(ExecutionStep).where(
                    ExecutionStep.execution_id == execution.id
                )
            )
        ).scalar_one()
        result = (
            await db.execute(
                select(ExecutionResult).where(
                    ExecutionResult.execution_id == execution.id
                )
            )
        ).scalar_one()

    assert execution.kind == "session"
    assert execution.run_type == "account_login"
    assert execution.status == "completed"
    assert execution.org_id == org_id
    assert execution.scenario_id is None
    assert execution.meta["org_scenario_id"] == org_scenario_id
    assert step.step_type == "wait"
    assert step.effective_config_json["trace"]["account_id"] == account_id
    assert result.status == "passed"


async def test_generic_account_preview_stream_does_not_create_account_login_history(
    tenancy_session_factory,
    monkeypatch,
):
    from api.routes.device_control import scenarios as scenario_routes

    org_id = "org-generic-preview"
    user_id = "user-generic-preview"
    account_id = "acc-generic-preview"
    device_id = "dev-generic-preview"
    serial = "dev-1"

    async with tenancy_session_factory() as db:
        db.add(
            Organization(
                id=org_id,
                business_name="Generic Preview Org",
                business_email="generic-preview@example.com",
            )
        )
        db.add(
            Device(
                id=device_id,
                serial=serial,
                device_serial=serial,
                org_id=org_id,
            )
        )
        db.add(
            Account(
                id=account_id,
                org_id=org_id,
                platform="instagram",
                username="61582490922369",
            )
        )
        db.add(
            DeviceAccount(
                device_id=device_id,
                account_id=account_id,
                is_primary=True,
            )
        )
        await db.commit()

    monkeypatch.setattr(scenario_routes, "AsyncSessionLocal", tenancy_session_factory)
    monkeypatch.setattr(
        scenario_routes,
        "caller_auth_from_request",
        lambda _request: AuthContext(
            user_id=user_id,
            token_type="access",
            raw_token="test",
            org_id=org_id,
        ),
    )

    def fake_run_scenario_on_device(*_args, **kwargs):
        assert kwargs.get("execution_id") is None
        return {
            "serial": serial,
            "success": True,
            "steps_executed": 1,
            "step_results": [
                {
                    "index": 0,
                    "type": "wait",
                    "ok": True,
                    "message": "waited",
                }
            ],
            "failed_message": "",
            "context": {},
        }

    monkeypatch.setattr(
        scenario_routes,
        "run_scenario_on_device",
        fake_run_scenario_on_device,
    )

    app = FastAPI()
    app.include_router(
        build_scenarios_router(_FakeManager(_FakeDevice()), _DbConfig(), object()),
        prefix="/api",
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/api/devices/{serial}/scenario/preview-stream",
            json={
                "steps": [{"id": "generic_wait", "type": "wait", "seconds": 0}],
                "variables": {"__ACCOUNT_ID__": account_id},
            },
        )

    assert response.status_code == 200
    assert '"event": "start"' in response.text

    async with tenancy_session_factory() as db:
        executions = (
            await db.execute(
                select(Execution).where(Execution.account_id == account_id)
            )
        ).scalars().all()

    assert executions == []
