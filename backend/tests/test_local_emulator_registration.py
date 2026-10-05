from __future__ import annotations

from types import SimpleNamespace

from runtime.core.device_client import DeviceClient, DeviceState
from runtime.core.device_manager import DeviceManager


class _FakeClient:
    def __init__(self, serial: str, *, connects: bool = True) -> None:
        self.serial = serial
        self.state = DeviceState.DISCONNECTED
        self._adb_serial = None
        self._tunnel_ports = None
        self._local_emulator_adb = False
        self._connects = connects

    def _reconnect_u2(self) -> bool:
        return self._connects

    def ensure_u2_healthy(self) -> bool:
        return self._connects


def _manager(tmp_path) -> DeviceManager:
    config = SimpleNamespace(
        adb=SimpleNamespace(path="adb"),
        device=SimpleNamespace(index_file=str(tmp_path / "device-index.json")),
    )
    return DeviceManager(config)


def test_register_local_emulator_is_scoped_and_connects_through_atx_forward(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    client = _FakeClient("emulator-5580")
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        stdout = "device\n" if command[-1] == "get-state" else "39127\n"
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr("runtime.core.device_manager.subprocess.run", fake_run)
    monkeypatch.setattr(manager, "ensure_device", lambda _serial: client)

    result = manager.register_local_emulator("emulator-5580")

    assert result is client
    assert client.state == DeviceState.READY
    assert client._adb_serial == "emulator-5580"
    assert client._tunnel_ports == {"u2": 39127}
    assert client._local_emulator_adb is True
    assert manager._local_emulator_forwards == {"emulator-5580": 39127}
    assert calls[0] == ["adb", "-s", "emulator-5580", "get-state"]
    assert calls[1] == [
        "adb",
        "-s",
        "emulator-5580",
        "forward",
        "tcp:0",
        "tcp:7912",
    ]


def test_register_local_emulator_rejects_non_emulator_without_running_adb(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    monkeypatch.setattr(
        "runtime.core.device_manager.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert manager.register_local_emulator("physical-device") is None


def test_register_local_emulator_reuses_healthy_forward_without_leaking_ports(
    tmp_path,
    monkeypatch,
) -> None:
    manager = _manager(tmp_path)
    client = _FakeClient("emulator-5580")
    client.state = DeviceState.READY
    client._local_emulator_adb = True
    client._tunnel_ports = {"u2": 39127}
    manager._registry[client.serial] = client
    manager._local_emulator_forwards[client.serial] = 39127
    monkeypatch.setattr(
        "runtime.core.device_manager.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("healthy registration must not create another ADB forward")
        ),
    )

    assert manager.register_local_emulator(client.serial) is client
    assert manager._local_emulator_forwards == {client.serial: 39127}


def test_local_emulator_shell_sync_uses_scoped_adb_serial(monkeypatch) -> None:
    client = object.__new__(DeviceClient)
    client.serial = "emulator-5580"
    client._adb_serial = "emulator-5580"
    client._local_emulator_adb = True
    client.config = SimpleNamespace(adb=SimpleNamespace(path="adb"))
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout="versionName=15\n")

    monkeypatch.setattr("runtime.core.device_client.subprocess.run", fake_run)

    assert client.shell_sync("dumpsys package com.android.settings") == "versionName=15\n"
    assert calls == [
        [
            "adb",
            "-s",
            "emulator-5580",
            "shell",
            "dumpsys package com.android.settings",
        ]
    ]
