from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.device_control.scrcpy import build_scrcpy_router


class _FakeScrcpyDevice:
    def __init__(self) -> None:
        self.attach_calls = 0
        self.detach_calls = 0
        self.block_attach = False
        self.attach_status: str | None = None
        self._scrcpy_active = False
        self._scrcpy_pending_registered_ip: str | None = None
        self._frame_queues: list[object] = []
        self._frame_lock = threading.Lock()
        self.attach_started = threading.Event()
        self.allow_attach = threading.Event()

    def attach_scrcpy_stream(
        self, device_ip: str, adb_port: int = 5555, enable_control: bool = True
    ) -> str | None:
        self.attach_started.set()
        if self.block_attach:
            self.allow_attach.wait(timeout=2)
        self.attach_calls += 1
        if self.attach_status in (None, "active"):
            self._scrcpy_active = True
            self._scrcpy_pending_registered_ip = None
        elif self.attach_status == "pending":
            self._scrcpy_active = False
            self._scrcpy_pending_registered_ip = "10.0.0.10"
        return self.attach_status

    def detach_scrcpy_stream(self, reason: str = "unspecified") -> None:
        self.detach_calls += 1
        self._scrcpy_active = False
        self._scrcpy_pending_registered_ip = None


class _FakeManager:
    def __init__(self, device: _FakeScrcpyDevice, serial: str = "serial-1") -> None:
        self.device = device
        self.serial = serial

    def get_device(self, serial: str) -> _FakeScrcpyDevice | None:
        return self.device if serial == self.serial else None


def _build_app(
    device: _FakeScrcpyDevice,
    serial: str = "serial-1",
    *,
    detach_grace_s: float = 0,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_scrcpy_router(
            _FakeManager(device, serial=serial),
            db_enabled=False,
            scrcpy_detach_grace_s=detach_grace_s,
        ),
        prefix="/api",
    )
    return app


@pytest.mark.anyio
async def test_scrcpy_detach_keeps_stream_until_last_viewer_detaches() -> None:
    device = _FakeScrcpyDevice()
    device._frame_queues.append(object())
    app = _build_app(device)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        attach_a = await client.post(
            "/api/devices/serial-1/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "control"},
        )
        attach_b = await client.post(
            "/api/devices/serial-1/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "grid-tile"},
        )
        detach_a = await client.post(
            "/api/devices/serial-1/scrcpy/detach",
            json={"viewer_id": "grid-tile"},
        )
        detach_b = await client.post(
            "/api/devices/serial-1/scrcpy/detach",
            json={"viewer_id": "control"},
        )

    assert attach_a.status_code == 200
    assert attach_b.status_code == 200
    assert detach_a.status_code == 200
    assert detach_a.json()["active_viewers"] == 1
    assert detach_b.status_code == 200
    assert detach_b.json()["active_viewers"] == 0
    assert device.attach_calls == 1
    assert device.detach_calls == 1


@pytest.mark.anyio
async def test_scrcpy_detach_keeps_remaining_viewer_even_before_frame_subscribe() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-stale-viewers")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            "/api/devices/serial-stale-viewers/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "stale-viewer"},
        )
        await client.post(
            "/api/devices/serial-stale-viewers/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "active-viewer"},
        )
        detach = await client.post(
            "/api/devices/serial-stale-viewers/scrcpy/detach",
            json={"viewer_id": "active-viewer"},
        )

    assert detach.status_code == 200
    assert detach.json()["active_viewers"] == 1
    assert device.attach_calls == 1
    assert device.detach_calls == 0


@pytest.mark.anyio
async def test_scrcpy_attach_reports_pending_without_detaching_viewer() -> None:
    device = _FakeScrcpyDevice()
    device.attach_status = "pending"
    app = _build_app(device, serial="serial-pending")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/devices/serial-pending/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "control"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["active_viewers"] == 1
    assert device.attach_calls == 1


@pytest.mark.anyio
async def test_scrcpy_attach_replaces_stale_viewer_from_same_surface() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-surface")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/devices/serial-surface/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "device-screen:old"},
        )
        second = await client.post(
            "/api/devices/serial-surface/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "device-screen:new"},
        )
        stale_detach = await client.post(
            "/api/devices/serial-surface/scrcpy/detach",
            json={"viewer_id": "device-screen:old"},
        )
        active_detach = await client.post(
            "/api/devices/serial-surface/scrcpy/detach",
            json={"viewer_id": "device-screen:new"},
        )

    assert first.status_code == 200
    assert first.json()["active_viewers"] == 1
    assert second.status_code == 200
    assert second.json()["active_viewers"] == 1
    assert stale_detach.status_code == 200
    assert stale_detach.json()["active_viewers"] == 1
    assert active_detach.status_code == 200
    assert active_detach.json()["active_viewers"] == 0
    assert device.attach_calls == 1
    assert device.detach_calls == 1


@pytest.mark.anyio
async def test_scrcpy_detach_grace_is_cancelled_by_fast_reattach() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-grace", detach_grace_s=0.05)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            "/api/devices/serial-grace/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "device-screen:old"},
        )
        detach = await client.post(
            "/api/devices/serial-grace/scrcpy/detach",
            json={"viewer_id": "device-screen:old"},
        )
        await client.post(
            "/api/devices/serial-grace/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "device-screen:new"},
        )
        await asyncio.sleep(0.08)

    assert detach.status_code == 200
    assert detach.json()["active_viewers"] == 0
    assert detach.json()["stop_scheduled"] is True
    assert device.attach_calls == 1
    assert device.detach_calls == 0


@pytest.mark.anyio
async def test_scrcpy_attach_unavailable_rolls_back_viewer() -> None:
    device = _FakeScrcpyDevice()
    device.attach_status = "unavailable"
    app = _build_app(device, serial="serial-unavailable")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/devices/serial-unavailable/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "control"},
        )

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["active_viewers"] == 0
    assert device.attach_calls == 1


@pytest.mark.anyio
async def test_scrcpy_attach_restarts_when_existing_viewer_is_stale_and_inactive() -> None:
    device = _FakeScrcpyDevice()
    device.attach_status = "pending"
    app = _build_app(device, serial="serial-stale")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/devices/serial-stale/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "stale-viewer"},
        )
        device._scrcpy_pending_registered_ip = None
        device.attach_status = "active"
        second = await client.post(
            "/api/devices/serial-stale/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "new-viewer"},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "pending"
    assert second.status_code == 200
    assert second.json()["status"] == "active"
    assert second.json()["active_viewers"] == 2
    assert device.attach_calls == 2


@pytest.mark.anyio
async def test_scrcpy_concurrent_attach_accounts_second_viewer() -> None:
    device = _FakeScrcpyDevice()
    device.block_attach = True
    device._frame_queues.append(object())
    app = _build_app(device, serial="serial-2")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = asyncio.create_task(
            client.post(
                "/api/devices/serial-2/scrcpy/attach",
                json={"device_ip": "10.0.0.10", "viewer_id": "control"},
            )
        )
        assert await asyncio.to_thread(device.attach_started.wait, 2)

        second = asyncio.create_task(
            client.post(
                "/api/devices/serial-2/scrcpy/attach",
                json={"device_ip": "10.0.0.10", "viewer_id": "grid-tile"},
            )
        )
        await asyncio.sleep(0)
        device.allow_attach.set()

        first_response, second_response = await asyncio.gather(first, second)
        detach_grid = await client.post(
            "/api/devices/serial-2/scrcpy/detach",
            json={"viewer_id": "grid-tile"},
        )
        detach_control = await client.post(
            "/api/devices/serial-2/scrcpy/detach",
            json={"viewer_id": "control"},
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["active_viewers"] == 2
    assert detach_grid.json()["active_viewers"] == 1
    assert detach_control.json()["active_viewers"] == 0
    assert device.attach_calls == 1
    assert device.detach_calls == 1


@pytest.mark.anyio
async def test_scrcpy_legacy_attach_detach_without_viewer_id_still_works() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-3")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        attach = await client.post(
            "/api/devices/serial-3/scrcpy/attach",
            json={"device_ip": "10.0.0.10"},
        )
        detach = await client.post("/api/devices/serial-3/scrcpy/detach")

    assert attach.status_code == 200
    assert attach.json()["active_viewers"] == 1
    assert detach.status_code == 200
    assert detach.json()["active_viewers"] == 0
    assert device.attach_calls == 1
    assert device.detach_calls == 1
