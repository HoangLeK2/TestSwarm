from __future__ import annotations

import subprocess
from collections.abc import Sequence

from relay.adb_admission import AdbLane
from relay.adb_scheduler import (
    AdbRunBytesResult,
    AdbRunResult,
    AdbScheduler,
    AdbutilsTransport,
    BinaryAdbTransport,
)


class _FakeDeviceInfo:
    def __init__(self, serial: str, state: str = "device") -> None:
        self.serial = serial
        self.state = state
        self.product = "product1"
        self.model = "model1"
        self.device = "device1"
        self.transport_id = 7


class _FakeForwardItem:
    def __init__(self, serial: str, local: str, remote: str) -> None:
        self.serial = serial
        self.local = local
        self.remote = remote


class _FakeReverseItem:
    def __init__(self, remote: str, local: str) -> None:
        self.remote = remote
        self.local = local


class _FakeSync:
    def __init__(self) -> None:
        self.push_calls: list[tuple[str, str]] = []
        self.pull_calls: list[tuple[str, str]] = []

    def push(self, src: str, dst: str) -> int:
        self.push_calls.append((src, dst))
        return 123

    def pull(self, src: str, dst: str) -> int:
        self.pull_calls.append((src, dst))
        return 456


class _FakeSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class _FakeConnection:
    def __init__(self) -> None:
        self.conn = _FakeSocket()
        self.commands: list[str] = []
        self.closed = False

    def send_command(self, command: str) -> None:
        self.commands.append(command)

    def check_okay(self) -> None:
        return None

    def read_until_close(self, *, encoding: str | None = "utf-8") -> bytes:
        assert encoding is None
        return b"\x89PNG\r\n\x1a\nfake"

    def close(self) -> None:
        self.closed = True


class _FakeAdbDevice:
    def __init__(self) -> None:
        self.shell_calls: list[tuple[object, float | None]] = []
        self.forward_calls: list[tuple[str, str]] = []
        self.forward_remove_calls: list[str] = []
        self.reverse_calls: list[tuple[str, str]] = []
        self.reverse_remove_calls: list[str] = []
        self.install_calls: list[tuple[str, list[str]]] = []
        self.uninstall_calls: list[str] = []
        self.sync = _FakeSync()
        self.connection = _FakeConnection()

    def shell(
        self,
        cmdargs: object,
        *,
        timeout: float | None = None,
        encoding: str | None = "utf-8",
    ) -> str:
        self.shell_calls.append((cmdargs, timeout))
        return f"shell:{cmdargs}:{encoding}"

    def forward_port(self, remote: str) -> int:
        self.forward_calls.append(("tcp:0", remote))
        return 49123

    def forward(self, local: str, remote: str) -> None:
        self.forward_calls.append((local, remote))

    def forward_remove(
        self,
        local: str,
        *,
        raise_non_found: bool = True,
    ) -> None:
        self.forward_remove_calls.append(local)

    def reverse(self, remote: str, local: str) -> None:
        self.reverse_calls.append((remote, local))

    def reverse_list(self) -> list[_FakeReverseItem]:
        return [_FakeReverseItem("tcp:7912", "tcp:49123")]

    def reverse_remove(self, remote: str) -> None:
        self.reverse_remove_calls.append(remote)

    def install(self, path: str, *, flags: list[str]) -> None:
        self.install_calls.append((path, flags))

    def uninstall(self, package: str) -> None:
        self.uninstall_calls.append(package)

    def open_transport(self, *, timeout: float | None = None) -> _FakeConnection:
        return self.connection


class _FakeAdbClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        socket_timeout: float,
    ) -> None:
        self.host = host
        self.port = port
        self.socket_timeout = socket_timeout
        self.fake_device = _FakeAdbDevice()

    def device(self, *, serial: str) -> _FakeAdbDevice:
        assert serial == "SERIAL1"
        return self.fake_device

    def list(self, *, extended: bool = False) -> list[_FakeDeviceInfo]:
        assert extended
        return [_FakeDeviceInfo("SERIAL1"), _FakeDeviceInfo("OFFLINE1", "offline")]

    def forward_list(self, *, serial: str | None = None) -> list[_FakeForwardItem]:
        assert serial == "SERIAL1"
        return [_FakeForwardItem("SERIAL1", "tcp:49123", "tcp:7912")]

    def connect(self, addr: str, *, timeout: float | None = None) -> str:
        return f"connected to {addr}"

    def disconnect(self, addr: str, *, raise_error: bool = False) -> str:
        return f"disconnected {addr}"


def _fake_client_factory(**kwargs: object) -> _FakeAdbClient:
    return _FakeAdbClient(**kwargs)  # type: ignore[arg-type]


def test_adbutils_transport_runs_shell_without_spawning_binary() -> None:
    transport = AdbutilsTransport(
        server_specs_provider=lambda: [("adb-host", "5038")],
        client_factory=_fake_client_factory,
    )

    result = transport.run(
        ("shell", "getprop", "ro.product.model"),
        serial="SERIAL1",
        timeout=2.5,
    )

    assert result == AdbRunResult(
        "shell:['getprop', 'ro.product.model']:utf-8",
        0,
        transport="adbutils",
    )
    client = transport._client(timeout=1.0)
    assert isinstance(client, _FakeAdbClient)
    assert client.host == "adb-host"
    assert client.port == 5038
    assert client.fake_device.shell_calls == [
        (["getprop", "ro.product.model"], 2.5)
    ]


def test_adbutils_transport_formats_devices_like_adb_devices_l() -> None:
    transport = AdbutilsTransport(
        server_specs_provider=lambda: [],
        client_factory=_fake_client_factory,
    )

    result = transport.run(("devices", "-l"), serial=None, timeout=1.0)

    assert result.returncode == 0
    assert result.transport == "adbutils"
    assert "SERIAL1\tdevice product:product1 model:model1" in result.output
    assert "OFFLINE1\toffline" in result.output


def test_adbutils_transport_handles_forward_lifecycle() -> None:
    transport = AdbutilsTransport(
        server_specs_provider=lambda: [],
        client_factory=_fake_client_factory,
    )

    create = transport.run(
        ("forward", "tcp:0", "tcp:7912"),
        serial="SERIAL1",
        timeout=1.0,
    )
    listed = transport.run(("forward", "--list"), serial="SERIAL1", timeout=1.0)
    remove = transport.run(
        ("forward", "--remove", "tcp:49123"),
        serial="SERIAL1",
        timeout=1.0,
    )

    assert create.output == "49123\n"
    assert listed.output == "SERIAL1 tcp:49123 tcp:7912\n"
    assert remove.returncode == 0


def test_adbutils_transport_handles_reverse_lifecycle() -> None:
    transport = AdbutilsTransport(
        server_specs_provider=lambda: [],
        client_factory=_fake_client_factory,
    )

    create = transport.run(
        ("reverse", "tcp:7912", "tcp:49123"),
        serial="SERIAL1",
        timeout=1.0,
    )
    listed = transport.run(("reverse", "--list"), serial="SERIAL1", timeout=1.0)
    remove = transport.run(
        ("reverse", "--remove", "tcp:7912"),
        serial="SERIAL1",
        timeout=1.0,
    )

    client = transport._client(timeout=1.0)
    assert isinstance(client, _FakeAdbClient)
    assert create.returncode == 0
    assert listed.output == "tcp:7912 tcp:49123\n"
    assert remove.returncode == 0
    assert client.fake_device.reverse_calls == [("tcp:7912", "tcp:49123")]
    assert client.fake_device.reverse_remove_calls == ["tcp:7912"]


def test_adbutils_transport_handles_file_and_package_commands() -> None:
    transport = AdbutilsTransport(
        server_specs_provider=lambda: [],
        client_factory=_fake_client_factory,
    )

    push = transport.run(("push", "local.txt", "/sdcard/local.txt"), serial="SERIAL1", timeout=1.0)
    pull = transport.run(("pull", "/sdcard/remote.txt", "remote.txt"), serial="SERIAL1", timeout=1.0)
    install = transport.run(("install", "-r", "-t", "app.apk"), serial="SERIAL1", timeout=30.0)
    uninstall = transport.run(("uninstall", "com.example"), serial="SERIAL1", timeout=10.0)

    client = transport._client(timeout=1.0)
    assert isinstance(client, _FakeAdbClient)
    assert push.output == "123 bytes pushed\n"
    assert pull.output == "456 bytes pulled\n"
    assert install.output == "Success\n"
    assert uninstall.output == "Success\n"
    assert client.fake_device.sync.push_calls == [("local.txt", "/sdcard/local.txt")]
    assert client.fake_device.sync.pull_calls == [("/sdcard/remote.txt", "remote.txt")]
    assert client.fake_device.install_calls == [("app.apk", ["-r", "-t"])]
    assert client.fake_device.uninstall_calls == ["com.example"]


def test_adbutils_transport_handles_exec_out_as_raw_bytes() -> None:
    transport = AdbutilsTransport(
        server_specs_provider=lambda: [],
        client_factory=_fake_client_factory,
    )

    result = transport.run_bytes(
        ("exec-out", "screencap", "-p"),
        serial="SERIAL1",
        timeout=2.0,
    )

    client = transport._client(timeout=1.0)
    assert isinstance(client, _FakeAdbClient)
    assert result == AdbRunBytesResult(
        b"\x89PNG\r\n\x1a\nfake",
        0,
        transport="adbutils",
    )
    assert client.fake_device.connection.commands == ["exec:screencap -p"]
    assert client.fake_device.connection.conn.timeouts == [2.0]
    assert client.fake_device.connection.closed


class _FakeTransport:
    def __init__(self, name: str, result: AdbRunResult) -> None:
        self.name = name
        self.result = result
        self.calls: list[tuple[tuple[str, ...], str | None, float]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunResult:
        self.calls.append((tuple(args), serial, timeout))
        return self.result

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunBytesResult:
        self.calls.append((tuple(args), serial, timeout))
        return AdbRunBytesResult(
            b"ok",
            self.result.returncode,
            transport=self.result.transport,
            supported=self.result.supported,
        )


def test_hybrid_scheduler_falls_back_to_binary_only_for_unsupported_commands() -> None:
    adbutils = _FakeTransport(
        "adbutils",
        AdbRunResult(
            "unsupported",
            -2,
            transport="adbutils",
            supported=False,
        ),
    )
    binary = _FakeTransport("binary", AdbRunResult("ok", 0, transport="binary"))
    scheduler = AdbScheduler(
        binary=binary,
        adbutils=adbutils,
        mode_provider=lambda: "hybrid",
    )

    result = scheduler.run(
        ("install", "-r", "app.apk"),
        serial="SERIAL1",
        timeout=30,
        lane=AdbLane.MAINTENANCE,
    )

    assert result.output == "ok"
    assert adbutils.calls == [(("install", "-r", "app.apk"), "SERIAL1", 30)]
    assert binary.calls == [(("install", "-r", "app.apk"), "SERIAL1", 30)]


def test_binary_transport_preserves_adb_command_shape(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout=b"ok\n",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    transport = BinaryAdbTransport(
        command_builder=lambda *args, serial=None: [
            "adb",
            "-s",
            serial,
            *args,
        ],
        adb_bin="adb",
    )

    result = transport.run(("shell", "true"), serial="SERIAL1", timeout=1)

    assert result == AdbRunResult("ok\n", 0, transport="binary")
    assert calls == [["adb", "-s", "SERIAL1", "shell", "true"]]
