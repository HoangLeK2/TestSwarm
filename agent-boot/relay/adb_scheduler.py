"""ADB command scheduler and transport implementations.

The scheduler is the process boundary for ADB work. Callers submit one logical
ADB command; this module admits it through the shared concurrency controller and
then chooses a transport backend:

* binary: spawn the system ``adb`` binary.
* adbutils: talk to the ADB server over its TCP protocol.
* hybrid: use adbutils for supported high-frequency commands and fall back to
  the binary for the rest.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from relay.adb_admission import AdbLane, adb_admission


@dataclass(frozen=True)
class AdbRunResult:
    output: str
    returncode: int
    timed_out: bool = False
    transport: str = "unknown"
    supported: bool = True


@dataclass(frozen=True)
class AdbRunBytesResult:
    output: bytes
    returncode: int
    timed_out: bool = False
    transport: str = "unknown"
    supported: bool = True
    # stdout is binary here, so adb's diagnostics have to be carried separately.
    # Without this the caller cannot tell "wrong ADB server" from "empty frame".
    error: str = ""


class AdbTransport(Protocol):
    name: str

    def run(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunResult:
        ...

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunBytesResult:
        ...


class BinaryAdbTransport:
    name = "binary"

    def __init__(
        self,
        *,
        command_builder: Callable[..., list[str]],
        adb_bin: str,
    ) -> None:
        self._command_builder = command_builder
        self._adb_bin = adb_bin

    def run(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunResult:
        cmd = self._command_builder(*args, serial=serial)
        env = os.environ.copy()
        env.pop("MallocStackLogging", None)
        env.pop("MallocStackLoggingDirectory", None)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AdbRunResult(
                f"adb timeout after {timeout:g}s",
                -1,
                timed_out=True,
                transport=self.name,
            )
        except FileNotFoundError:
            return AdbRunResult(
                f"adb binary not found at {self._adb_bin!r}",
                -1,
                transport=self.name,
            )
        except Exception as exc:
            return AdbRunResult(str(exc), -1, transport=self.name)
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        return AdbRunResult(output, result.returncode, transport=self.name)

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunBytesResult:
        cmd = self._command_builder(*args, serial=serial)
        env = os.environ.copy()
        env.pop("MallocStackLogging", None)
        env.pop("MallocStackLoggingDirectory", None)
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return AdbRunBytesResult(
                b"",
                -1,
                timed_out=True,
                transport=self.name,
                error=f"adb timeout after {timeout:g}s",
            )
        except Exception as exc:
            return AdbRunBytesResult(b"", -1, transport=self.name, error=str(exc))
        return AdbRunBytesResult(
            result.stdout,
            result.returncode,
            transport=self.name,
            error=result.stderr.decode("utf-8", errors="replace"),
        )


class AdbutilsTransport:
    name = "adbutils"

    def __init__(
        self,
        *,
        server_specs_provider: Callable[[], list[tuple[str, str]]],
        client_factory: Callable[..., object] | None = None,
        endpoint_provider: Callable[[str | None], tuple[str, int] | None] | None = None,
    ) -> None:
        self._server_specs_provider = server_specs_provider
        self._client_factory = client_factory
        # Resolves serial → (host, port). Without it every command would land on
        # the first configured server, which is wrong as soon as a second ADB
        # server is configured.
        self._endpoint_provider = endpoint_provider
        self._clients: dict[tuple[str, int], object] = {}

    def run(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunResult:
        args_tuple = tuple(str(arg) for arg in args)
        if not args_tuple:
            return self._unsupported(args_tuple)
        command = args_tuple[0]
        try:
            if command == "devices":
                return self._devices(args_tuple, timeout=timeout)
            if command == "shell" and serial:
                return self._shell(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "forward" and serial:
                return self._forward(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "reverse" and serial:
                return self._reverse(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "push" and serial:
                return self._push(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "pull" and serial:
                return self._pull(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "install" and serial:
                return self._install(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "uninstall" and serial:
                return self._uninstall(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "exec-out" and serial:
                result = self.run_bytes(args_tuple, serial=serial, timeout=timeout)
                output = result.output.decode("utf-8", errors="replace")
                return AdbRunResult(
                    output,
                    result.returncode,
                    timed_out=result.timed_out,
                    transport=result.transport,
                    supported=result.supported,
                )
            if command == "connect" and len(args_tuple) >= 2:
                return self._connect(args_tuple[1], timeout=timeout)
            if command == "disconnect" and len(args_tuple) >= 2:
                return self._disconnect(args_tuple[1], timeout=timeout)
            return self._unsupported(args_tuple)
        except Exception as exc:
            return AdbRunResult(str(exc), -1, transport=self.name)

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
    ) -> AdbRunBytesResult:
        args_tuple = tuple(str(arg) for arg in args)
        if not serial or not args_tuple:
            return self._unsupported_bytes(args_tuple)
        command = args_tuple[0]
        try:
            if command == "exec-out":
                return self._exec_out(args_tuple[1:], serial=serial, timeout=timeout)
            if command == "shell":
                return self._shell_bytes(args_tuple[1:], serial=serial, timeout=timeout)
            return self._unsupported_bytes(args_tuple)
        except Exception as exc:
            return AdbRunBytesResult(b"", -1, transport=self.name, error=str(exc))

    def _unsupported(self, args: Sequence[str]) -> AdbRunResult:
        command = " ".join(args) if args else "<empty>"
        return AdbRunResult(
            f"adbutils transport does not support adb {command}",
            -2,
            transport=self.name,
            supported=False,
        )

    def _unsupported_bytes(self, args: Sequence[str]) -> AdbRunBytesResult:
        return AdbRunBytesResult(
            b"",
            -2,
            transport=self.name,
            supported=False,
        )

    def _client(self, *, timeout: float, serial: str | None = None) -> object:
        host, port = self._server_for(serial)
        key = (host, int(port))
        client = self._clients.get(key)
        if client is None:
            factory = self._client_factory or self._load_adb_client()
            client = factory(host=host, port=int(port), socket_timeout=timeout)
            self._clients[key] = client
        return client

    def _load_adb_client(self) -> Callable[..., object]:
        from adbutils import AdbClient

        return AdbClient

    def _server_for(self, serial: str | None) -> tuple[str, int]:
        if serial and self._endpoint_provider is not None:
            endpoint = self._endpoint_provider(serial)
            if endpoint is not None:
                return endpoint[0], int(endpoint[1])
        return self._primary_server()

    def _primary_server(self) -> tuple[str, int]:
        specs = self._server_specs_provider()
        if specs:
            host, port = specs[0]
            return host, int(port)
        return "127.0.0.1", 5037

    def _device(self, serial: str, *, timeout: float) -> object:
        client = self._client(timeout=timeout, serial=serial)
        return client.device(serial=serial)

    def _devices(self, args: Sequence[str], *, timeout: float) -> AdbRunResult:
        extended = "-l" in args
        client = self._client(timeout=timeout)
        devices = client.list(extended=extended)
        lines = ["List of devices attached"]
        for device in devices:
            serial = str(getattr(device, "serial", "") or "").strip()
            state = str(getattr(device, "state", "") or "device").strip()
            detail = ""
            if extended:
                detail = self._device_detail(device)
            if serial:
                lines.append(
                    f"{serial}\t{state}{(' ' + detail) if detail else ''}"
                )
        return AdbRunResult("\n".join(lines) + "\n", 0, transport=self.name)

    def _device_detail(self, device: object) -> str:
        parts: list[str] = []
        for attr in ("product", "model", "device", "transport_id"):
            value = getattr(device, attr, None)
            if value is not None and str(value).strip():
                parts.append(f"{attr}:{value}")
        return " ".join(parts)

    def _shell(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        if not argv:
            return self._unsupported(("shell",))
        cmdargs: str | list[str]
        if len(argv) == 1:
            cmdargs = argv[0]
        else:
            cmdargs = list(argv)
        output = self._device(serial, timeout=timeout).shell(
            cmdargs,
            timeout=timeout,
            encoding="utf-8",
        )
        if isinstance(output, bytes):
            text = output.decode("utf-8", errors="replace")
        else:
            text = str(output)
        return AdbRunResult(text, 0, transport=self.name)

    def _shell_bytes(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunBytesResult:
        if not argv:
            return self._unsupported_bytes(("shell",))
        cmdargs: str | list[str]
        if len(argv) == 1:
            cmdargs = argv[0]
        else:
            cmdargs = list(argv)
        output = self._device(serial, timeout=timeout).shell(
            cmdargs,
            timeout=timeout,
            encoding=None,
        )
        if isinstance(output, bytes):
            payload = output
        else:
            payload = str(output).encode("utf-8", errors="replace")
        return AdbRunBytesResult(payload, 0, transport=self.name)

    def _exec_out(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunBytesResult:
        if not argv:
            return self._unsupported_bytes(("exec-out",))
        command = self._command_string(argv)
        connection = self._device(serial, timeout=timeout).open_transport(
            timeout=timeout,
        )
        try:
            connection.send_command(f"exec:{command}")
            connection.check_okay()
            if timeout:
                connection.conn.settimeout(timeout)
            output = connection.read_until_close(encoding=None)
        finally:
            connection.close()
        if isinstance(output, bytes):
            payload = output
        else:
            payload = str(output).encode("utf-8", errors="replace")
        return AdbRunBytesResult(payload, 0, transport=self.name)

    def _command_string(self, argv: Sequence[str]) -> str:
        if len(argv) == 1:
            return argv[0]
        from adbutils._utils import list2cmdline

        return list2cmdline(list(argv))

    def _forward(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        device = self._device(serial, timeout=timeout)
        if tuple(argv) == ("--list",):
            client = self._client(timeout=timeout, serial=serial)
            items = client.forward_list(serial=serial)
            lines: list[str] = []
            for item in items:
                item_serial = getattr(item, "serial", serial) or serial
                local = getattr(item, "local", "")
                remote = getattr(item, "remote", "")
                lines.append(f"{item_serial} {local} {remote}".strip())
            output = "\n".join(lines) + ("\n" if lines else "")
            return AdbRunResult(output, 0, transport=self.name)
        if len(argv) == 2 and argv[0] == "--remove":
            device.forward_remove(argv[1], raise_non_found=False)
            return AdbRunResult("", 0, transport=self.name)
        if len(argv) == 2:
            local, remote = argv
            if local == "tcp:0":
                port = device.forward_port(remote)
                return AdbRunResult(f"{port}\n", 0, transport=self.name)
            device.forward(local, remote)
            return AdbRunResult("", 0, transport=self.name)
        return self._unsupported(("forward", *argv))

    def _reverse(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        device = self._device(serial, timeout=timeout)
        if tuple(argv) == ("--list",):
            items = device.reverse_list()
            lines: list[str] = []
            for item in items:
                remote = getattr(item, "remote", "")
                local = getattr(item, "local", "")
                lines.append(f"{remote} {local}".strip())
            output = "\n".join(lines) + ("\n" if lines else "")
            return AdbRunResult(output, 0, transport=self.name)
        if len(argv) == 2 and argv[0] == "--remove":
            device.reverse_remove(argv[1])
            return AdbRunResult("", 0, transport=self.name)
        if len(argv) == 2:
            remote, local = argv
            device.reverse(remote, local)
            return AdbRunResult("", 0, transport=self.name)
        return self._unsupported(("reverse", *argv))

    def _push(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        if len(argv) != 2:
            return self._unsupported(("push", *argv))
        src, dst = argv
        bytes_written = self._device(serial, timeout=timeout).sync.push(src, dst)
        return AdbRunResult(f"{bytes_written} bytes pushed\n", 0, transport=self.name)

    def _pull(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        if len(argv) != 2:
            return self._unsupported(("pull", *argv))
        src, dst = argv
        bytes_written = self._device(serial, timeout=timeout).sync.pull(src, dst)
        return AdbRunResult(f"{bytes_written} bytes pulled\n", 0, transport=self.name)

    def _install(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        if not argv:
            return self._unsupported(("install",))
        path = argv[-1]
        flags = list(argv[:-1]) or ["-r", "-t"]
        self._device(serial, timeout=timeout).install(path, flags=flags)
        return AdbRunResult("Success\n", 0, transport=self.name)

    def _uninstall(
        self,
        argv: Sequence[str],
        *,
        serial: str,
        timeout: float,
    ) -> AdbRunResult:
        if len(argv) != 1:
            return self._unsupported(("uninstall", *argv))
        self._device(serial, timeout=timeout).uninstall(argv[0])
        return AdbRunResult("Success\n", 0, transport=self.name)

    def _connect(self, addr: str, *, timeout: float) -> AdbRunResult:
        output = self._client(timeout=timeout).connect(addr, timeout=timeout)
        return AdbRunResult(str(output), 0, transport=self.name)

    def _disconnect(self, addr: str, *, timeout: float) -> AdbRunResult:
        output = self._client(timeout=timeout).disconnect(addr, raise_error=False)
        return AdbRunResult(str(output), 0, transport=self.name)


class AdbScheduler:
    def __init__(
        self,
        *,
        binary: AdbTransport,
        adbutils: AdbTransport,
        mode_provider: Callable[[], str] | None = None,
    ) -> None:
        self._binary = binary
        self._adbutils = adbutils
        self._mode_provider = mode_provider or adb_transport_mode

    def run(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
        lane: AdbLane,
    ) -> AdbRunResult:
        args_tuple = tuple(str(arg) for arg in args)
        mode = self._normalize_mode(self._mode_provider())
        with adb_admission(serial=serial, lane=lane):
            if mode == "binary":
                return self._binary.run(args_tuple, serial=serial, timeout=timeout)
            if mode == "adbutils":
                return self._adbutils.run(args_tuple, serial=serial, timeout=timeout)
            result = self._adbutils.run(args_tuple, serial=serial, timeout=timeout)
            if result.supported:
                return result
            return self._binary.run(args_tuple, serial=serial, timeout=timeout)

    def run_bytes(
        self,
        args: Sequence[str],
        *,
        serial: str | None,
        timeout: float,
        lane: AdbLane,
    ) -> AdbRunBytesResult:
        args_tuple = tuple(str(arg) for arg in args)
        mode = self._normalize_mode(self._mode_provider())
        with adb_admission(serial=serial, lane=lane):
            if mode == "binary":
                return self._binary.run_bytes(args_tuple, serial=serial, timeout=timeout)
            if mode == "adbutils":
                return self._adbutils.run_bytes(args_tuple, serial=serial, timeout=timeout)
            result = self._adbutils.run_bytes(args_tuple, serial=serial, timeout=timeout)
            if result.supported:
                return result
            return self._binary.run_bytes(args_tuple, serial=serial, timeout=timeout)

    def _normalize_mode(self, raw: str) -> str:
        value = str(raw or "").strip().lower()
        if value in {"adbutils", "hybrid"}:
            return value
        return "binary"


def adb_transport_mode() -> str:
    return os.environ.get("AGENT_BOOT_ADB_TRANSPORT", "binary")
