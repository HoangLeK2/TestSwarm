"""
adb_transport.py — ADB transport via system `adb` binary (subprocess).

Connects to device via `adb connect host:port` and shells out all commands
through `adb -s host:port shell ...`. Requires `adb` on PATH.

Compatible devices:
  - Android 11+ : Settings → Developer Options → Wireless Debugging → Enable
  - Android ≤10 : `adb tcpip 5555` once via USB, then disconnect USB

Usage:
    transport = AdbTransport('192.168.1.100', 5555)
    ok = transport.connect()
    output = transport.shell('whoami')
    transport.push_file('/local/file', '/data/local/tmp/file', mode=0o755)
    transport.start_streaming_shell('am instrument -w ...', on_exit=lambda: ...)
    transport.close()
"""
from __future__ import annotations

import logging
import os
import stat
import subprocess
import threading
import time
from typing import Callable, Iterator, Optional

log = logging.getLogger(__name__)


# ── AdbTransport ──────────────────────────────────────────────────────────────


class AdbTransport:
    """
    One logical ADB handle to one device, implemented via the system `adb` binary.

    We do NOT use the `adb-shell` Python library anymore; every operation shells out
    to `adb -s <serial> ...`.
    """

    def __init__(
        self,
        host: str,
        port: int = 5555,
        connect_timeout: float = 10.0,
        shell_timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self._connect_timeout = connect_timeout
        self._shell_timeout = shell_timeout

        self._lock = threading.Lock()
        self._connected = False
        self._serial = f"{host}:{port}"

    # ── Connection ────────────────────────────────────────────────────────────

    def _adb_base(self) -> list[str]:
        """Base adb command for this device."""
        return ["adb", "-s", self._serial]

    def connect(self, retries: int = 3, retry_delay: float = 2.0) -> bool:
        """
        "Connect" to a TCP device using the system adb client.

        For TCP devices we just run `adb connect host:port` and consider that our
        logical connection. All subsequent operations go through `adb -s host:port`.
        """
        serial = self._serial
        for attempt in range(1, retries + 1):
            try:
                proc = subprocess.run(
                    ["adb", "connect", serial],
                    capture_output=True,
                    text=True,
                    timeout=self._connect_timeout,
                )
                if proc.returncode == 0:
                    with self._lock:
                        self._connected = True
                    msg = (proc.stdout or proc.stderr or "").strip()
                    log.info(
                        f"[{serial}] adb connect OK (attempt {attempt}): {msg or 'connected'}"
                    )
                    return True
                else:
                    msg = (proc.stderr or proc.stdout or "").strip()
                    log.warning(
                        f"[{serial}] adb connect failed (attempt {attempt}): rc={proc.returncode} {msg}"
                    )
            except Exception as exc:
                log.warning(
                    f"[{serial}] adb connect exception (attempt {attempt}): {exc}"
                )
            if attempt < retries:
                time.sleep(retry_delay)

        log.error(f"[{serial}] adb connect failed after {retries} attempts")
        return False

    def close(self) -> None:
        # Nothing persistent to close when using the adb binary.
        with self._lock:
            self._connected = False
        log.info(f"[{self._serial}] ADB handle closed")

    def reconnect(self, retries: int = 3) -> bool:
        """
        Tear down and re-establish ADB connection with exponential backoff.
        Returns True if reconnection succeeds.
        """
        log.info(f"[{self._serial}] Attempting ADB reconnect...")
        self.close()
        for attempt in range(1, retries + 1):
            delay = min(2 ** attempt, 10)  # 2s, 4s, 8s (capped at 10s)
            time.sleep(delay)
            if self.connect(retries=1, retry_delay=0):
                log.info(f"[{self._serial}] ADB reconnect OK (attempt {attempt})")
                return True
            log.warning(f"[{self._serial}] ADB reconnect failed (attempt {attempt}/{retries})")
        log.error(f"[{self._serial}] ADB reconnect failed after {retries} attempts")
        return False

    def is_alive(self, timeout: float = 5.0) -> bool:
        """
        Quick health check: run 'echo ok' on device and verify output.
        Returns False if transport is disconnected or command fails.
        """
        if not self._connected:
            return False
        try:
            result = self.shell("echo ok", timeout=timeout)
            return result.strip() == "ok"
        except Exception:
            return False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def serial(self) -> str:
        return self._serial

    # ── Shell ─────────────────────────────────────────────────────────────────

    def shell(self, cmd: str, timeout: Optional[float] = None) -> str:
        """
        Execute shell command on device via `adb shell`.
        Returns stdout as string. Raises RuntimeError on hard failure.
        """
        t = timeout or self._shell_timeout
        with self._lock:
            if not self._connected:
                raise RuntimeError(f"[{self._serial}] ADB not connected")
        try:
            proc = subprocess.run(
                self._adb_base() + ["shell", cmd],
                capture_output=True,
                text=True,
                timeout=t,
            )
        except Exception as exc:
            # Hard failure talking to adb → mark disconnected
            with self._lock:
                self._connected = False
            raise RuntimeError(f"[{self._serial}] shell transport error: {exc}") from exc

        if proc.returncode != 0:
            # Command failed on device, but adb transport is still healthy.
            raise RuntimeError(
                f"[{self._serial}] adb shell rc={proc.returncode} stderr={proc.stderr.strip()}"
            )
        return proc.stdout or ""

    def shell_safe(self, cmd: str, timeout: Optional[float] = None) -> str:
        """Shell that returns empty string on error instead of raising."""
        try:
            return self.shell(cmd, timeout=timeout)
        except Exception as exc:
            log.debug(f"[{self._serial}] shell_safe error: {exc}")
            return ""

    # ── File Push ─────────────────────────────────────────────────────────────

    def push_file(
        self,
        local_path: str,
        remote_path: str,
        mode: int = 0o644,
    ) -> bool:
        """
        Push a local file to device using `adb push`.
        mode: Unix permission bits (e.g. 0o755 for executable).
        Returns True on success.
        """
        with self._lock:
            if not self._connected:
                log.error(f"[{self._serial}] push_file: not connected")
                return False
        try:
            proc = subprocess.run(
                self._adb_base() + ["push", local_path, remote_path],
                capture_output=True,
                text=True,
                timeout=max(self._shell_timeout, 60.0),
            )
            if proc.returncode != 0:
                log.error(
                    f"[{self._serial}] adb push failed rc={proc.returncode} "
                    f"stderr={proc.stderr.strip()}"
                )
                return False
            log.info(f"[{self._serial}] Pushed {local_path} → {remote_path}")
            # chmod separately to honor requested mode
            self.chmod(remote_path, oct(mode & 0o777)[2:])
            return True
        except Exception as exc:
            log.error(f"[{self._serial}] push_file error: {exc}")
            return False

    def push_bytes(
        self,
        data: bytes,
        remote_path: str,
        mode: int = 0o644,
    ) -> bool:
        """Push raw bytes to device as a file (without creating a local temp file)."""
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            return self.push_file(tmp_path, remote_path, mode=mode)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ── Streaming Shell (long-running processes) ──────────────────────────────

    def start_streaming_shell(
        self,
        cmd: str,
        on_line: Optional[Callable[[str], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> threading.Thread:
        """
        Start a long-running command on device in a background thread.
        Implemented via `adb shell` using subprocess.Popen.

        Calls on_line(line) for each output line.
        Calls on_exit() when process ends (crash or stop).
        Returns the daemon thread (already started).
        """
        def _run():
            proc = None
            try:
                with self._lock:
                    if not self._connected:
                        return
                proc = subprocess.Popen(
                    self._adb_base() + ["shell", cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if on_line:
                        try:
                            on_line(line)
                        except Exception:
                            pass
            except Exception as exc:
                log.warning(
                    f"[{self._serial}] streaming_shell '{cmd[:60]}' ended: {exc}"
                )
            finally:
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                if on_exit:
                    try:
                        on_exit()
                    except Exception:
                        pass

        t = threading.Thread(target=_run, daemon=True, name=f"adb-stream-{self._serial}")
        t.start()
        return t

    # ── Device Info Helpers ───────────────────────────────────────────────────

    def get_serial(self) -> str:
        """Get device serial number."""
        return self.shell_safe("getprop ro.serialno").strip() or self._serial

    def get_prop(self, prop: str) -> str:
        """Get Android system property."""
        return self.shell_safe(f"getprop {prop}").strip()

    def get_battery_level(self) -> int:
        """Return battery level 0-100, or -1 on failure."""
        output = self.shell_safe("dumpsys battery | grep -E '^ *level:'", timeout=5.0)
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("level:"):
                try:
                    return int(line.split(":")[1].strip())
                except ValueError:
                    pass
        return -1

    def get_rotation(self) -> int:
        """Return current display rotation in degrees: 0, 90, 180, 270."""
        # Try display info first
        out = self.shell_safe(
            "dumpsys window displays | grep -E 'mCurrentRotation|mRotation'",
            timeout=5.0,
        )
        for line in out.splitlines():
            for kw in ("mCurrentRotation=", "mRotation="):
                if kw in line:
                    try:
                        # Value is like ROTATION_0=0, ROTATION_90=1 etc.
                        val_str = line.split(kw)[1].split()[0]
                        # Might be numeric 0-3 or "ROTATION_90" etc.
                        if val_str.isdigit():
                            return int(val_str) * 90
                        if "ROTATION_" in val_str:
                            deg = val_str.split("ROTATION_")[1].rstrip(";,")
                            if deg.isdigit():
                                return int(deg)
                    except Exception:
                        pass
        return 0

    def get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of device screen."""
        out = self.shell_safe("wm size", timeout=5.0)
        for line in out.splitlines():
            if "Physical size" in line or "Override size" in line:
                try:
                    size_part = line.split(":")[1].strip()
                    w, h = size_part.split("x")
                    return int(w), int(h)
                except Exception:
                    pass
        return 1080, 1920

    def kill_process(self, name: str) -> None:
        """Kill process by name on device."""
        self.shell_safe(f"pkill -f {name}")

    def is_file_present(self, remote_path: str) -> bool:
        """Check if file exists on device."""
        out = self.shell_safe(f"test -f {remote_path} && echo 1 || echo 0").strip()
        return out == "1"

    def chmod(self, remote_path: str, mode: str = "755") -> None:
        """chmod a file on device."""
        self.shell_safe(f"chmod {mode} {remote_path}")

    def __repr__(self) -> str:
        return f"AdbTransport({self._serial}, connected={self._connected})"


# ── mDNS Discovery (Android 11+ Wireless Debugging) ──────────────────────────


class AdbMdnsDiscovery:
    """
    Listens for Android 11+ Wireless Debugging advertisements via mDNS.
    Android broadcasts service type: _adb-tls-connect._tcp

    When a device is found, calls on_device(host, port, name).
    """

    SERVICE_TYPE = "_adb-tls-connect._tcp.local."

    def __init__(self, on_device: Callable[[str, int, str], None]) -> None:
        self._on_device = on_device
        self._zeroconf = None
        self._browser = None

    def start(self) -> bool:
        """Start mDNS listener. Returns True if zeroconf is available."""
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except ImportError:
            log.warning(
                "zeroconf not installed; mDNS discovery unavailable.\n"
                "Install: pip install zeroconf"
            )
            return False

        self._zeroconf = Zeroconf()
        self._browser = ServiceBrowser(
            self._zeroconf, self.SERVICE_TYPE, listener=self
        )
        log.info("mDNS discovery started for Android Wireless Debugging")
        return True

    def stop(self) -> None:
        if self._zeroconf:
            try:
                self._zeroconf.close()
            except Exception:
                pass
            self._zeroconf = None

    # zeroconf listener callbacks
    def add_service(self, zc, service_type: str, name: str) -> None:
        import socket
        info = zc.get_service_info(service_type, name)
        if not info:
            return
        host = socket.inet_ntoa(info.addresses[0]) if info.addresses else None
        port = info.port
        if host and port:
            log.info(f"mDNS: found Android ADB device {name} at {host}:{port}")
            self._on_device(host, port, name)

    def remove_service(self, zc, service_type: str, name: str) -> None:
        log.debug(f"mDNS: device removed {name}")

    def update_service(self, zc, service_type: str, name: str) -> None:
        self.add_service(zc, service_type, name)
