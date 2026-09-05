from __future__ import annotations

import asyncio

import pytest

from relay import device_watcher
from relay.device_watcher import AdbDeviceWatcher


class _FakeConnection:
    def __init__(self, snapshots: list[str]) -> None:
        self.snapshots = list(snapshots)
        self.commands: list[str] = []
        self.closed = False

    def send_command(self, cmd: str) -> None:
        self.commands.append(cmd)

    def check_okay(self) -> None:
        return None

    def read_string_block(self) -> str:
        if not self.snapshots:
            raise RuntimeError("fake track closed")
        return self.snapshots.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakeAdbutilsClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        socket_timeout: float | None,
        connection: _FakeConnection,
    ) -> None:
        self.host = host
        self.port = port
        self.socket_timeout = socket_timeout
        self.connection = connection

    def make_connection(self, timeout: float | None = None) -> _FakeConnection:
        assert timeout is None
        return self.connection


def test_parse_track_devices_snapshot_handles_supported_states() -> None:
    snapshot = device_watcher._parse_track_devices_snapshot(
        "PHONE1\tdevice\n"
        "PHONE2\toffline\n"
        "PHONE3\tunauthorized\n"
        "ignored malformed line\n"
    )

    assert snapshot == {
        "PHONE1": "device",
        "PHONE2": "offline",
        "PHONE3": "unauthorized",
    }


@pytest.mark.asyncio
async def test_adbutils_track_loop_applies_snapshot_and_remembers_server(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_BOOT_ADB_STREAM_TRANSPORT", "adbutils")
    remembered: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        device_watcher,
        "_remember_serial_adb_server",
        lambda serial, host, port: remembered.append((serial, host, port)),
    )
    connection = _FakeConnection(["PHONE1\tdevice\nPHONE2\toffline\n"])
    clients: list[_FakeAdbutilsClient] = []

    def client_factory(**kwargs: object) -> _FakeAdbutilsClient:
        client = _FakeAdbutilsClient(
            **kwargs,  # type: ignore[arg-type]
            connection=connection,
        )
        clients.append(client)
        return client

    events: list[tuple[str, str]] = []

    async def on_event(serial: str, state: str) -> None:
        events.append((serial, state))

    watcher = AdbDeviceWatcher(
        on_event,
        adbutils_client_factory=client_factory,
    )

    with pytest.raises(RuntimeError, match="fake track closed"):
        await asyncio.wait_for(
            watcher._track_loop(server=("adb-host", "5038"), key="adb-host:5038"),
            timeout=1.0,
        )

    assert events == [("PHONE1", "device"), ("PHONE2", "offline")]
    assert remembered == [("PHONE1", "adb-host", "5038")]
    assert connection.commands == ["host:track-devices"]
    assert connection.closed
    assert clients[0].host == "adb-host"
    assert clients[0].port == 5038
    assert clients[0].socket_timeout is None
