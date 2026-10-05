from __future__ import annotations

import asyncio

import pytest

from core.config import Config
from runtime.core.device_client import DeviceClient
from runtime.transports.adb_relay_server import AdbRelayManager, RelayConnection


class _NoVideoRelay:
    def __init__(self) -> None:
        self.pending: dict[str, object] = {}

    def resolve_serial(self, serial: str) -> str:
        return serial

    def relay_for_serial(self, serial: str) -> None:
        return None

    def registered_relays(self) -> dict[str, list[str]]:
        return {}

    def register_pending_scrcpy(self, key: str, callback: object) -> None:
        self.pending[key] = callback


class _StickyNoVideoRelay:
    """Keeps stale callbacks to model concurrent pending registrations."""

    def __init__(self) -> None:
        self.pending: dict[str, list[object]] = {}

    def resolve_serial(self, serial: str) -> str:
        return serial

    def relay_for_serial(self, serial: str) -> None:
        return None

    def registered_relays(self) -> dict[str, list[str]]:
        return {}

    def register_pending_scrcpy(self, key: str, callback: object) -> None:
        self.pending.setdefault(key, []).append(callback)


class _RejectingRelay:
    def __init__(self) -> None:
        self.receivers: dict[str, object] = {}

    def resolve_serial(self, serial: str) -> str:
        return "192.168.1.43:33865"

    def relay_for_serial(self, serial: str) -> object:
        return object()

    def get_capabilities(self, serial: str) -> dict:
        return {}

    def register_scrcpy_receiver(self, serial: str, receiver: object) -> None:
        self.receivers[serial] = receiver

    def unregister_scrcpy_receiver(self, serial: str) -> None:
        self.receivers.pop(serial, None)

    def is_scrcpy_running(self, serial: str) -> bool:
        return False

    async def start_scrcpy(self, **_kwargs) -> bool:
        return False


class _FakeRelayScrcpyReceiver:
    def __init__(self, serial: str, **_kwargs) -> None:
        self.serial = serial
        self.control = None
        self.started = False
        self.stopped = False

    def start_receiver(self) -> None:
        self.started = True

    def stop_receiver(self) -> None:
        self.stopped = True


def test_attach_scrcpy_waits_when_video_relay_channel_not_registered(monkeypatch):
    relay = _NoVideoRelay()
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: relay,
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    device = DeviceClient(serial="logical-serial", index=0, config=Config())

    device.attach_scrcpy_stream("192.168.1.43:33865", 5555, True)

    assert device._scrcpy_pending_registered_ip == "192.168.1.43:33865"
    assert "logical-serial" in relay.pending
    assert "192.168.1.43:33865" in relay.pending
    assert "192.168.1.43" in relay.pending


def test_stale_pending_scrcpy_callbacks_only_submit_one_reattach(monkeypatch):
    relay = _StickyNoVideoRelay()
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: relay,
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    submissions: list[tuple[str, int, bool]] = []

    class _FakeThreadPoolExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def submit(self, fn, *args):
            submissions.append(args)

    monkeypatch.setattr(
        "concurrent.futures.ThreadPoolExecutor",
        _FakeThreadPoolExecutor,
    )

    device = DeviceClient(serial="logical-serial", index=0, config=Config())

    assert device.attach_scrcpy_stream("192.168.1.43:33865", 5555, True) == "pending"
    assert device.attach_scrcpy_stream("192.168.1.43:33865", 5555, True) == "pending"

    callbacks = [
        callback
        for callbacks_for_key in relay.pending.values()
        for callback in callbacks_for_key
    ]
    assert len(callbacks) > 1

    for callback in callbacks:
        callback("192.168.1.43:33865")

    assert submissions == [("192.168.1.43:33865", 5555, True)]


def test_attach_scrcpy_does_not_raise_when_relay_manager_unavailable(monkeypatch):
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: None,
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    device = DeviceClient(serial="logical-serial", index=0, config=Config())

    device.attach_scrcpy_stream("192.168.1.43:33865", 5555, True)

    assert device._scrcpy_receiver is None
    assert device._scrcpy_active is False


@pytest.mark.asyncio
async def test_relay_pending_scrcpy_keeps_multiple_callbacks_for_same_serial():
    manager = AdbRelayManager()
    fired: list[tuple[str, str]] = []

    def cb_one(serial: str) -> None:
        fired.append(("one", serial))

    def cb_two(serial: str) -> None:
        fired.append(("two", serial))

    manager.register_pending_scrcpy("192.168.1.43:33865", cb_one)
    manager.register_pending_scrcpy("192.168.1.43", cb_two)

    conn = RelayConnection("relay-1", write_queue=None)  # type: ignore[arg-type]
    conn.serials = {"192.168.1.43:33865"}

    await manager.register(conn)

    assert fired == [
        ("one", "192.168.1.43:33865"),
        ("two", "192.168.1.43:33865"),
    ]
    assert manager._pending_scrcpy == {}


def test_relay_pending_scrcpy_cancel_removes_only_matching_callback():
    manager = AdbRelayManager()
    fired: list[str] = []

    def cb_one(serial: str) -> None:
        fired.append(f"one:{serial}")

    def cb_two(serial: str) -> None:
        fired.append(f"two:{serial}")

    manager.register_pending_scrcpy("192.168.1.43", cb_one)
    manager.register_pending_scrcpy("192.168.1.43", cb_two)

    manager.cancel_pending_scrcpy("192.168.1.43", cb_one)

    callbacks = manager._pending_scrcpy["192.168.1.43"]
    assert callbacks == [cb_two]


def test_relay_frame_race_fires_pending_callback_once_until_reattached():
    manager = AdbRelayManager()
    calls: list[str] = []

    def cb(serial: str) -> None:
        calls.append(serial)

    manager.register_pending_scrcpy("192.168.1.43", cb)

    manager.dispatch_scrcpy_frame(
        "192.168.1.43:33865",
        b"frame-1",
        0,
        1080,
        1920,
        is_config=True,
    )
    manager.dispatch_scrcpy_frame(
        "192.168.1.43:33865",
        b"frame-2",
        0,
        1080,
        1920,
        is_config=True,
    )

    assert calls == ["192.168.1.43:33865"]
    assert manager._pending_scrcpy == {}


@pytest.mark.asyncio
async def test_attach_scrcpy_does_not_mark_active_when_start_rejected(monkeypatch):
    relay = _RejectingRelay()
    monkeypatch.setattr(
        "runtime.transports.adb_relay_server.get_relay_manager",
        lambda: relay,
    )
    monkeypatch.setattr(
        "runtime.transports.scrcpy_receiver.RelayScrcpyReceiver",
        _FakeRelayScrcpyReceiver,
    )

    device = DeviceClient(serial="logical-serial", index=0, config=Config())
    device._loop = asyncio.get_running_loop()

    status = await asyncio.to_thread(
        device.attach_scrcpy_stream,
        "192.168.1.43:33865",
        5555,
        False,
    )

    assert status == "unavailable"
    assert device._scrcpy_active is False
    assert device._scrcpy_receiver is None
    assert relay.receivers == {}
