from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.device_control.connect import build_connect_router
from api.routes.device_control.scenarios import build_scenarios_router


class _Config:
    class database:
        enabled = False


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
