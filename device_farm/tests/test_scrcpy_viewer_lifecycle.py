from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import api.routes.device_control.scrcpy as scrcpy_routes
from api.routes.device_control.scrcpy import build_scrcpy_router
from core.config import Config
from runtime.core import device_client as device_client_module
from runtime.core.device_client import DeviceClient


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
        self.last_attach_options: dict[str, int | None] = {}
        self._scrcpy_params: tuple[str, int, bool, int | None, int | None, int | None] | None = None

    def attach_scrcpy_stream(
        self,
        device_ip: str,
        adb_port: int = 5555,
        enable_control: bool = True,
        *,
        max_fps: int | None = None,
        max_width: int | None = None,
        bitrate: int | None = None,
    ) -> str | None:
        self.attach_started.set()
        self.last_attach_options = {
            "max_fps": max_fps,
            "max_width": max_width,
            "bitrate": bitrate,
        }
        self._scrcpy_params = (
            device_ip,
            adb_port,
            enable_control,
            max_fps,
            max_width,
            bitrate,
        )
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


class _MultiFakeManager:
    def __init__(self, devices: dict[str, _FakeScrcpyDevice]) -> None:
        self.devices = devices

    def get_device(self, serial: str) -> _FakeScrcpyDevice | None:
        return self.devices.get(serial)


def _build_app(
    device: _FakeScrcpyDevice,
    serial: str = "serial-1",
    *,
    detach_grace_s: float = 0,
    viewer_lease_ttl_s: float = 0,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_scrcpy_router(
            _FakeManager(device, serial=serial),
            db_enabled=False,
            scrcpy_detach_grace_s=detach_grace_s,
            scrcpy_viewer_lease_ttl_s=viewer_lease_ttl_s,
        ),
        prefix="/api",
    )
    return app


def _build_multi_app(devices: dict[str, _FakeScrcpyDevice]) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_scrcpy_router(
            _MultiFakeManager(devices),
            db_enabled=False,
            scrcpy_detach_grace_s=0,
        ),
        prefix="/api",
    )
    return app


def test_device_client_subscribe_returns_bootstrap_without_queueing_it() -> None:
    device = DeviceClient(serial="serial-bootstrap-contract", index=0, config=Config())
    config = b"config"
    key = b"key"
    device._latest_stream.set_config(config)
    device._latest_stream.set_frame(key, is_key=True)
    frame_q: asyncio.Queue[bytes] = asyncio.Queue()

    bootstrap = device.subscribe_frames(frame_q)

    assert bootstrap == (config, key)
    assert frame_q.empty()


def test_stream_generation_reset_uses_same_lock_as_subscribe() -> None:
    device = DeviceClient(serial="serial-generation-lock", index=0, config=Config())
    device._latest_stream.set_config(b"old-config")
    device._latest_stream.set_frame(b"old-key", is_key=True)
    reset_started = threading.Event()
    reset_finished = threading.Event()

    def _reset() -> None:
        reset_started.set()
        device.reset_stream_bootstrap_generation()
        reset_finished.set()

    device._frame_lock.acquire()
    thread = threading.Thread(target=_reset)
    try:
        thread.start()
        assert reset_started.wait(timeout=1)
        assert reset_finished.wait(timeout=0.02) is False
    finally:
        device._frame_lock.release()
    thread.join(timeout=1)

    frame_q: asyncio.Queue[bytes] = asyncio.Queue()
    assert reset_finished.is_set()
    assert device.subscribe_frames(frame_q) == (None, None)


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
async def test_scrcpy_viewer_without_heartbeat_expires_and_stops_stream() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(
        device,
        serial="serial-lease-expiry",
        viewer_lease_ttl_s=0.1,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        attach = await client.post(
            "/api/devices/serial-lease-expiry/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:lease-expiry",
            },
        )
        await asyncio.sleep(0.15)

    assert attach.status_code == 200
    assert "serial-lease-expiry" not in scrcpy_routes._SCRCPY_VIEWERS
    assert device.detach_calls == 1


@pytest.mark.anyio
async def test_expired_control_viewer_downgrades_to_live_preview_profile() -> None:
    serial = "serial-lease-downgrade"
    device = _FakeScrcpyDevice()
    app = _build_app(
        device,
        serial=serial,
        viewer_lease_ttl_s=0.3,
    )
    preview_payload = {
        "device_ip": "10.0.0.10",
        "viewer_id": "snapshot-preview:live",
        "max_fps": 1,
        "max_width": 360,
        "bitrate": 100_000,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json=preview_payload,
        )
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:stale",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800_000,
            },
        )
        await asyncio.sleep(0.15)
        heartbeat = await client.post(
            f"/api/devices/{serial}/scrcpy/heartbeat",
            json={"viewer_id": "snapshot-preview:live"},
        )
        assert heartbeat.status_code == 200
        assert device.attach_calls == 2
        await asyncio.sleep(0.2)

        assert scrcpy_routes._SCRCPY_VIEWERS[serial] == {"snapshot-preview:live"}
        assert device.last_attach_options == {
            "max_fps": 1,
            "max_width": 360,
            "bitrate": 100_000,
        }

        await client.post(
            f"/api/devices/{serial}/scrcpy/detach",
            json={"viewer_id": "snapshot-preview:live"},
        )


@pytest.mark.anyio
async def test_expired_control_viewer_downgrades_after_grace_when_preview_remains() -> None:
    serial = "serial-lease-downgrade-grace"
    device = _FakeScrcpyDevice()
    app = _build_app(
        device,
        serial=serial,
        detach_grace_s=0.05,
        viewer_lease_ttl_s=0.3,
    )
    preview_payload = {
        "device_ip": "10.0.0.10",
        "viewer_id": "snapshot-preview:live",
        "max_fps": 1,
        "max_width": 360,
        "bitrate": 100_000,
    }

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json=preview_payload,
        )
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:stale",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800_000,
            },
        )
        await asyncio.sleep(0.15)
        heartbeat = await client.post(
            f"/api/devices/{serial}/scrcpy/heartbeat",
            json={"viewer_id": "snapshot-preview:live"},
        )
        assert heartbeat.status_code == 200
        assert device.attach_calls == 2
        await asyncio.sleep(0.12)

        assert scrcpy_routes._SCRCPY_VIEWERS[serial] == {"snapshot-preview:live"}
        assert device.attach_calls == 2

        await asyncio.sleep(0.08)

        assert device.attach_calls == 3
        assert device.last_attach_options == {
            "max_fps": 1,
            "max_width": 360,
            "bitrate": 100_000,
        }

        await client.post(
            f"/api/devices/{serial}/scrcpy/detach",
            json={"viewer_id": "snapshot-preview:live"},
        )


@pytest.mark.anyio
async def test_scrcpy_preview_attach_respects_global_preview_budget(monkeypatch) -> None:
    scrcpy_routes._SCRCPY_VIEWERS.clear()
    monkeypatch.setattr(scrcpy_routes, "_SCRCPY_PREVIEW_VIEWER_LIMIT", 2)
    devices = {
        "serial-a": _FakeScrcpyDevice(),
        "serial-b": _FakeScrcpyDevice(),
        "serial-c": _FakeScrcpyDevice(),
    }
    app = _build_multi_app(devices)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/devices/serial-a/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "snapshot-preview:a"},
        )
        second = await client.post(
            "/api/devices/serial-b/scrcpy/attach",
            json={"device_ip": "10.0.0.11", "viewer_id": "snapshot-preview:b"},
        )
        over_budget = await client.post(
            "/api/devices/serial-c/scrcpy/attach",
            json={"device_ip": "10.0.0.12", "viewer_id": "snapshot-preview:c"},
        )
        assert "serial-c" not in scrcpy_routes._SCRCPY_VIEWERS
        control = await client.post(
            "/api/devices/serial-c/scrcpy/attach",
            json={"device_ip": "10.0.0.12", "viewer_id": "device-screen:c"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert over_budget.status_code == 429
    assert over_budget.json()["status"] == "preview_budget_exhausted"
    assert over_budget.json()["active_preview_viewers"] == 2
    assert control.status_code == 200
    assert devices["serial-c"].attach_calls == 1


@pytest.mark.anyio
async def test_live_monitor_viewers_are_not_limited_by_snapshot_budget(monkeypatch) -> None:
    scrcpy_routes._SCRCPY_VIEWERS.clear()
    monkeypatch.setattr(scrcpy_routes, "_SCRCPY_PREVIEW_VIEWER_LIMIT", 1)
    devices = {
        "serial-a": _FakeScrcpyDevice(),
        "serial-b": _FakeScrcpyDevice(),
        "serial-c": _FakeScrcpyDevice(),
    }
    app = _build_multi_app(devices)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        snapshot = await client.post(
            "/api/devices/serial-a/scrcpy/attach",
            json={"device_ip": "10.0.0.10", "viewer_id": "snapshot-preview:a"},
        )
        campaign = await client.post(
            "/api/devices/serial-b/scrcpy/attach",
            json={"device_ip": "10.0.0.11", "viewer_id": "campaign-monitor:b"},
        )
        follower = await client.post(
            "/api/devices/serial-c/scrcpy/attach",
            json={"device_ip": "10.0.0.12", "viewer_id": "follower-preview:c"},
        )

    assert snapshot.status_code == 200
    assert campaign.status_code == 200
    assert follower.status_code == 200


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
async def test_control_replaces_lower_priority_pending_preview_profile() -> None:
    device = _FakeScrcpyDevice()
    device.attach_status = "pending"
    app = _build_app(device, serial="serial-pending-upgrade")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        preview = await client.post(
            "/api/devices/serial-pending-upgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:low",
                "enable_control": False,
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )
        control = await client.post(
            "/api/devices/serial-pending-upgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:high",
                "max_fps": 10,
                "max_width": 720,
                "bitrate": 800000,
            },
        )

    assert preview.status_code == 200
    assert control.status_code == 200
    assert device.attach_calls == 2
    assert device.last_attach_options == {
        "max_fps": 10,
        "max_width": 720,
        "bitrate": 800000,
    }


@pytest.mark.anyio
async def test_scrcpy_attach_preserves_distinct_viewers_from_same_surface() -> None:
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
    assert second.json()["active_viewers"] == 2
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
async def test_device_client_auto_stop_grace_does_not_hold_frame_lock(monkeypatch) -> None:
    monkeypatch.setattr(device_client_module, "SCRCPY_AUTO_STOP_IDLE_S", 0.0)
    monkeypatch.setattr(device_client_module, "SCRCPY_STOP_GRACE_S", 10.0)

    device = DeviceClient(serial="serial-lock", index=0, config=Config())
    device._loop = asyncio.get_running_loop()
    device._scrcpy_receiver = object()  # type: ignore[assignment]
    device._scrcpy_attached_at = time.monotonic()
    frame_q: asyncio.Queue[bytes] = asyncio.Queue()
    device._frame_queues.append(frame_q)

    device.unsubscribe_frames(frame_q)
    await asyncio.sleep(0.05)

    acquired = device._frame_lock.acquire(blocking=False)
    if acquired:
        device._frame_lock.release()
    stop_task = device._scrcpy_stop_task
    if stop_task is not None:
        stop_task.cancel()
        await asyncio.sleep(0)

    assert acquired is True


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
async def test_scrcpy_attach_forwards_preview_profile_options() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-preview")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/devices/serial-preview/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 5,
                "max_width": 360,
                "bitrate": 350000,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert device.last_attach_options == {
        "max_fps": 5,
        "max_width": 360,
        "bitrate": 350000,
    }


@pytest.mark.anyio
async def test_control_attach_reapplies_profile_after_low_fps_preview() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-upgrade")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        preview = await client.post(
            "/api/devices/serial-upgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 1,
                "max_width": 480,
                "bitrate": 180000,
            },
        )
        control = await client.post(
            "/api/devices/serial-upgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:test",
            },
        )

    assert preview.status_code == 200
    assert control.status_code == 200
    assert control.json()["status"] == "active"
    assert device.attach_calls == 2
    assert device.last_attach_options == {
        "max_fps": None,
        "max_width": None,
        "bitrate": None,
    }


@pytest.mark.anyio
async def test_control_attach_reapplies_requested_profile_after_default_stream() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-control-upgrade")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        default = await client.post(
            "/api/devices/serial-control-upgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:old",
            },
        )
        upgraded = await client.post(
            "/api/devices/serial-control-upgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:new",
                "max_fps": 8,
                "max_width": 540,
                "bitrate": 900000,
            },
        )

    assert default.status_code == 200
    assert upgraded.status_code == 200
    assert upgraded.json()["status"] == "active"
    assert device.attach_calls == 2
    assert device.last_attach_options == {
        "max_fps": 8,
        "max_width": 540,
        "bitrate": 900000,
    }


@pytest.mark.anyio
async def test_low_fps_preview_reapplies_profile_during_control_detach_grace() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-downgrade", detach_grace_s=60)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        control = await client.post(
            "/api/devices/serial-downgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:test",
            },
        )
        detach_control = await client.post(
            "/api/devices/serial-downgrade/scrcpy/detach",
            json={"viewer_id": "device-screen:test"},
        )
        preview = await client.post(
            "/api/devices/serial-downgrade/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 1,
                "max_width": 480,
                "bitrate": 180000,
            },
        )

    assert control.status_code == 200
    assert detach_control.status_code == 200
    assert detach_control.json()["stop_scheduled"] is True
    assert preview.status_code == 200
    assert preview.json()["status"] == "active"
    assert preview.json()["active_viewers"] == 1
    assert device.attach_calls == 2
    assert device.detach_calls == 0
    assert device.last_attach_options == {
        "max_fps": 1,
        "max_width": 480,
        "bitrate": 180000,
    }


@pytest.mark.anyio
async def test_low_fps_preview_starts_light_profile_after_control_fully_stops() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-preview-after-stop", detach_grace_s=0)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        control = await client.post(
            "/api/devices/serial-preview-after-stop/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:test",
            },
        )
        detach_control = await client.post(
            "/api/devices/serial-preview-after-stop/scrcpy/detach",
            json={"viewer_id": "device-screen:test"},
        )
        preview = await client.post(
            "/api/devices/serial-preview-after-stop/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 1,
                "max_width": 480,
                "bitrate": 180000,
            },
        )

    assert control.status_code == 200
    assert detach_control.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["status"] == "active"
    assert preview.json()["active_viewers"] == 1
    assert device.attach_calls == 2
    assert device.detach_calls == 1
    assert device.last_attach_options == {
        "max_fps": 1,
        "max_width": 480,
        "bitrate": 180000,
    }


@pytest.mark.anyio
async def test_last_preview_viewer_detaches_without_encoder_grace() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-preview-stop", detach_grace_s=60)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        attach = await client.post(
            "/api/devices/serial-preview-stop/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )
        detach = await client.post(
            "/api/devices/serial-preview-stop/scrcpy/detach",
            json={"viewer_id": "snapshot-preview:test"},
        )

    assert attach.status_code == 200
    assert detach.status_code == 200
    assert detach.json()["active_viewers"] == 0
    assert detach.json().get("stop_scheduled") is not True
    assert device.detach_calls == 1


@pytest.mark.anyio
async def test_low_fps_preview_does_not_downgrade_active_control_viewer() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-control-keeps-profile")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        control = await client.post(
            "/api/devices/serial-control-keeps-profile/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:test",
            },
        )
        preview = await client.post(
            "/api/devices/serial-control-keeps-profile/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 1,
                "max_width": 480,
                "bitrate": 180000,
            },
        )

    assert control.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["active_viewers"] == 2
    assert device.attach_calls == 1
    assert device.last_attach_options == {
        "max_fps": None,
        "max_width": None,
        "bitrate": None,
    }


@pytest.mark.anyio
async def test_follower_preview_does_not_downgrade_active_control_viewer() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-control-with-follower")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        control = await client.post(
            "/api/devices/serial-control-with-follower/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:primary",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800000,
            },
        )
        follower = await client.post(
            "/api/devices/serial-control-with-follower/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "follower-preview:secondary",
                "enable_control": False,
                "max_fps": 4,
                "max_width": 360,
                "bitrate": 120000,
            },
        )

    assert control.status_code == 200
    assert follower.status_code == 200
    assert follower.json()["active_viewers"] == 2
    assert device.attach_calls == 1
    assert device.last_attach_options == {
        "max_fps": 10,
        "max_width": 480,
        "bitrate": 800000,
    }


@pytest.mark.anyio
async def test_snapshot_preview_does_not_downgrade_active_follower_profile() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-follower-with-snapshot")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        follower = await client.post(
            "/api/devices/serial-follower-with-snapshot/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "follower-preview:primary",
                "enable_control": False,
                "max_fps": 4,
                "max_width": 360,
                "bitrate": 120000,
            },
        )
        snapshot = await client.post(
            "/api/devices/serial-follower-with-snapshot/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:secondary",
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )

    assert follower.status_code == 200
    assert snapshot.status_code == 200
    assert snapshot.json()["active_viewers"] == 2
    assert device.attach_calls == 1
    assert device.last_attach_options == {
        "max_fps": 4,
        "max_width": 360,
        "bitrate": 120000,
    }


@pytest.mark.anyio
async def test_control_detach_reapplies_remaining_preview_profile() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-control-to-preview")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        control = await client.post(
            "/api/devices/serial-control-to-preview/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "device-screen:test",
                "max_fps": 8,
                "max_width": 540,
                "bitrate": 900000,
            },
        )
        preview = await client.post(
            "/api/devices/serial-control-to-preview/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:test",
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )
        detach_control = await client.post(
            "/api/devices/serial-control-to-preview/scrcpy/detach",
            json={"viewer_id": "device-screen:test"},
        )

    assert control.status_code == 200
    assert preview.status_code == 200
    assert detach_control.status_code == 200
    assert detach_control.json()["active_viewers"] == 1
    assert device.attach_calls == 2
    assert device.last_attach_options == {
        "max_fps": 1,
        "max_width": 360,
        "bitrate": 100000,
    }


@pytest.mark.anyio
async def test_control_to_preview_downgrade_is_cancelled_by_fast_control_reattach() -> None:
    serial = "serial-control-preview-bounce"
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial=serial, detach_grace_s=0.05)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:first",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800000,
            },
        )
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:live",
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )
        detach = await client.post(
            f"/api/devices/{serial}/scrcpy/detach",
            json={"viewer_id": "control-screen:first"},
        )

        assert detach.json()["profile_reapply_scheduled"] is True
        assert device.attach_calls == 1

        reattach = await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:second",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800000,
            },
        )
        await asyncio.sleep(0.08)

    assert reattach.status_code == 200
    assert device.attach_calls == 1
    assert device.detach_calls == 0


@pytest.mark.anyio
async def test_legacy_viewer_cancels_pending_preview_downgrade_and_reapplies_profile() -> None:
    serial = "serial-control-preview-legacy"
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial=serial, detach_grace_s=0.05)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:first",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800000,
            },
        )
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:live",
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )
        detach = await client.post(
            f"/api/devices/{serial}/scrcpy/detach",
            json={"viewer_id": "control-screen:first"},
        )
        legacy = await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={"device_ip": "10.0.0.10"},
        )
        await asyncio.sleep(0.08)

    assert detach.json()["profile_reapply_scheduled"] is True
    assert legacy.status_code == 200
    assert legacy.json()["status"] == "active"
    assert device.attach_calls == 2
    assert device.last_attach_options == {
        "max_fps": None,
        "max_width": None,
        "bitrate": None,
    }
    assert device.detach_calls == 0


@pytest.mark.anyio
async def test_control_to_preview_downgrade_applies_after_grace() -> None:
    serial = "serial-control-preview-stable"
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial=serial, detach_grace_s=0.03)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "control-screen:test",
                "max_fps": 10,
                "max_width": 480,
                "bitrate": 800000,
            },
        )
        await client.post(
            f"/api/devices/{serial}/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:live",
                "max_fps": 1,
                "max_width": 360,
                "bitrate": 100000,
            },
        )
        detach = await client.post(
            f"/api/devices/{serial}/scrcpy/detach",
            json={"viewer_id": "control-screen:test"},
        )

        assert detach.json()["profile_reapply_scheduled"] is True
        assert device.attach_calls == 1
        await asyncio.sleep(0.06)

    assert device.attach_calls == 2
    assert device.last_attach_options == {
        "max_fps": 1,
        "max_width": 360,
        "bitrate": 100000,
    }


def test_device_client_reconfigures_when_preview_downgrades_existing_stream(monkeypatch) -> None:
    import runtime.transports.adb_relay_server as relay_server
    from runtime.transports.scrcpy_receiver import RelayScrcpyReceiver

    class _RelayManager:
        def __init__(self, old_receiver: RelayScrcpyReceiver) -> None:
            self.calls: list[str] = []
            self.receivers: dict[str, RelayScrcpyReceiver] = {
                "10.0.0.10": old_receiver,
            }
            self.running: set[str] = {"10.0.0.10"}

        def resolve_serial(self, serial: str) -> str:
            if serial == "serial-profile":
                return "10.0.0.10"
            return serial

        def relay_for_serial(self, serial: str) -> object | None:
            return object() if self.resolve_serial(serial) == "10.0.0.10" else None

        def get_capabilities(self, serial: str) -> dict[str, object]:
            return {}

        def get_scrcpy_receiver(self, serial: str) -> RelayScrcpyReceiver | None:
            return self.receivers.get(serial)

        def register_scrcpy_receiver(self, serial: str, receiver: RelayScrcpyReceiver) -> None:
            self.calls.append("register")
            self.receivers[serial] = receiver

        def unregister_scrcpy_receiver(self, serial: str) -> None:
            self.receivers.pop(serial, None)

        def is_scrcpy_running(self, serial: str) -> bool:
            return serial in self.running

        async def stop_scrcpy(self, serial: str, reason: str = "unspecified") -> None:
            self.calls.append("stop")
            self.running.discard(serial)
            self.unregister_scrcpy_receiver(serial)

        async def start_scrcpy(
            self,
            *,
            serial: str,
            max_fps: int,
            max_width: int,
            enable_control: bool,
            port: int,
            bitrate: int = 2_000_000,
            low_latency: bool = False,
        ) -> bool:
            self.calls.append("start")
            self.running.add(serial)
            return True

    device = DeviceClient(serial="serial-profile", index=0, config=Config())
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    device._scrcpy_active = True
    device._loop = loop
    old_receiver = RelayScrcpyReceiver(serial="10.0.0.10")
    relay = _RelayManager(old_receiver)
    device._scrcpy_receiver = old_receiver
    device._scrcpy_params = ("10.0.0.10", 5555, True, None, None, None)

    monkeypatch.setattr(relay_server, "get_relay_manager", lambda: relay)

    try:
        status = device.attach_scrcpy_stream(
            "10.0.0.10",
            5555,
            True,
            max_fps=1,
            max_width=480,
            bitrate=180000,
        )
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()

    assert status == "active"
    assert relay.calls == ["stop", "register", "start"]
    assert device._scrcpy_active is True
    assert relay.is_scrcpy_running("10.0.0.10") is True


def test_device_client_reconfigures_stale_preview_even_when_frames_are_fresh(monkeypatch) -> None:
    import runtime.transports.adb_relay_server as relay_server
    from runtime.transports.scrcpy_receiver import RelayScrcpyReceiver

    class _RelayManager:
        def __init__(self, old_receiver: RelayScrcpyReceiver) -> None:
            self.calls: list[str] = []
            self.receivers: dict[str, RelayScrcpyReceiver] = {
                "10.0.0.10": old_receiver,
            }

        def resolve_serial(self, serial: str) -> str:
            if serial == "serial-profile-fresh":
                return "10.0.0.10"
            return serial

        def relay_for_serial(self, serial: str) -> object | None:
            return object() if self.resolve_serial(serial) == "10.0.0.10" else None

        def get_capabilities(self, serial: str) -> dict[str, object]:
            return {}

        def get_scrcpy_receiver(self, serial: str) -> RelayScrcpyReceiver | None:
            return self.receivers.get(serial)

        def register_scrcpy_receiver(self, serial: str, receiver: RelayScrcpyReceiver) -> None:
            self.calls.append("register")
            self.receivers[serial] = receiver

        def unregister_scrcpy_receiver(self, serial: str) -> None:
            self.receivers.pop(serial, None)

        def is_scrcpy_running(self, serial: str) -> bool:
            return False

        async def stop_scrcpy(self, serial: str, reason: str = "unspecified") -> None:
            self.calls.append("stop")
            self.unregister_scrcpy_receiver(serial)

        async def start_scrcpy(
            self,
            *,
            serial: str,
            max_fps: int,
            max_width: int,
            enable_control: bool,
            port: int,
            bitrate: int = 2_000_000,
            low_latency: bool = False,
        ) -> bool:
            self.calls.append(f"start:{max_fps}:{max_width}:{bitrate}")
            return True

    device = DeviceClient(serial="serial-profile-fresh", index=0, config=Config())
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    device._scrcpy_active = True
    device._loop = loop
    device._last_frame_time = time.monotonic()
    old_receiver = RelayScrcpyReceiver(serial="10.0.0.10")
    relay = _RelayManager(old_receiver)
    device._scrcpy_receiver = old_receiver
    device._scrcpy_params = ("10.0.0.10", 5555, True, 1, 360, 100000)

    monkeypatch.setattr(relay_server, "get_relay_manager", lambda: relay)

    try:
        status = device.attach_scrcpy_stream("10.0.0.10", 5555, True)
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()

    assert status == "active"
    assert "register" in relay.calls
    assert "start:30:800:2000000" in relay.calls
    assert device._scrcpy_active is True


@pytest.mark.anyio
async def test_second_low_fps_preview_does_not_reapply_scrcpy_profile() -> None:
    device = _FakeScrcpyDevice()
    app = _build_app(device, serial="serial-preview-repeat")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/devices/serial-preview-repeat/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:first",
                "max_fps": 1,
                "max_width": 480,
                "bitrate": 180000,
            },
        )
        second = await client.post(
            "/api/devices/serial-preview-repeat/scrcpy/attach",
            json={
                "device_ip": "10.0.0.10",
                "viewer_id": "snapshot-preview:second",
                "max_fps": 1,
                "max_width": 480,
                "bitrate": 180000,
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["active_viewers"] == 2
    assert device.attach_calls == 1


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
