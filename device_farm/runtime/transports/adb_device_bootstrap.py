from __future__ import annotations

import logging
import os
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from runtime.transports.adb_transport import AdbTransport
from runtime.transports.scrcpy_receiver import ScrcpyReceiver
from runtime.transports.stf_client import STFServiceClient
from runtime.transports.u2_jsonrpc import U2JsonRpcClient

log = logging.getLogger(__name__)

# ── Binary assets directory ───────────────────────────────────────────────────
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_BUNDLE_DIR = Path(__file__).parent.parent / "bundle"

# Remote paths on device
_REMOTE_TMP = "/data/local/tmp"
# u2-server listens on this TCP port (openatx/android-uiautomator-server default)
U2_TCP_PORT = 9008
# uiautomator2 APK packages (openatx)
U2_SERVER_PKG = "com.github.uiautomator"
U2_SERVER_TEST_PKG = "com.github.uiautomator.test"
U2_RUNNER = "androidx.test.runner.AndroidJUnitRunner"
_U2_APK_DIR = Path(__file__).parent.parent / "third_party"
U2_SERVER_APK = _U2_APK_DIR / "app-uiautomator.apk"
U2_SERVER_TEST_APK = _U2_APK_DIR / "app-uiautomator-test.apk"
_U2_BUNDLE_APK_DIR = Path(__file__).parent.parent / "bundle" / "apks"
U2_SERVER_APK_BUNDLE = _U2_BUNDLE_APK_DIR / "app-uiautomator.apk"
U2_SERVER_TEST_APK_BUNDLE = _U2_BUNDLE_APK_DIR / "app-uiautomator-test.apk"

# Polling interval for battery/rotation
_POLL_INTERVAL = 15.0  # seconds


class AdbDeviceBootstrap:
    """
    Bootstraps one Android device connected via ADB over TCP/WiFi.

    Lifecycle:
      bootstrap.start()   — push binaries, start services, begin polling
      bootstrap.stop()    — kill remote processes, stop threads
    """

    def __init__(
        self,
        transport: AdbTransport,
        on_frame: Callable[[bytes], None],
        on_battery: Callable[[int], None],
        on_rotation: Callable[[int], None],
        on_u2_ready: Callable[[U2JsonRpcClient], None],
        on_metadata: Callable[[dict], None],
        on_stf_ready: Optional[Callable[[STFServiceClient], None]] = None,
        u2_wait_timeout: float = 20.0,
        u2_implicitly_wait: float = 10.0,
        skip_scrcpy: bool = False,
    ) -> None:
        self._transport = transport
        self._skip_scrcpy = skip_scrcpy
        self._on_frame = on_frame
        self._on_battery = on_battery
        self._on_rotation = on_rotation
        self._on_u2_ready = on_u2_ready
        self._on_metadata = on_metadata
        self._on_stf_ready = on_stf_ready
        self._u2_wait_timeout = u2_wait_timeout
        self._u2_implicitly_wait = u2_implicitly_wait

        self._running = False
        self._lock = threading.Lock()

        # Components started by bootstrap
        self._scrcpy_receiver: Optional[ScrcpyReceiver] = None
        self._u2_client: Optional[U2JsonRpcClient] = None
        self._stf_service: Optional[STFServiceClient] = None
        self._poll_thread: Optional[threading.Thread] = None

        # Self-healing watchdog
        self._u2_restart_lock = threading.Lock()
        self._u2_last_restart: float = 0.0
        self._u2_watchdog_interval: float = 30.0   # ping every N seconds
        self._u2_watchdog_max_fails: int = 2        # restart after N consecutive failures
        # Exit backoff: exponential delay for rapid consecutive exits
        self._u2_exit_count: int = 0               # consecutive exit count
        self._u2_exit_last: float = 0.0            # monotonic time of last exit

        # Collected device metadata
        self._screen_width: int = 0
        self._screen_height: int = 0
        self._abi: str = ""

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        Start bootstrap in a background thread.
        Returns True immediately (non-blocking). Check on_u2_ready callback
        for when the device is fully ready.
        """
        self._running = True
        t = threading.Thread(
            target=self._bootstrap_sequence,
            daemon=True,
            name=f"adb-bootstrap-{self._transport.serial}",
        )
        t.start()
        return True

    def stop(self) -> None:
        """Stop all background processes and threads."""
        self._running = False

        # Stop scrcpy receiver
        if self._scrcpy_receiver:
            try:
                self._scrcpy_receiver.stop_receiver()
            except Exception:
                pass
            self._scrcpy_receiver = None

        try:
            self._transport.shell_safe(
                f"am force-stop {U2_SERVER_PKG}"
            )
        except Exception:
            pass

        # Stop STFService client and remove forward
        if self._stf_service:
            try:
                self._stf_service.stop_client()
            except Exception:
                pass
            self._stf_service = None
        try:
            subprocess.run(
                ["adb", "-s", self._transport.serial, "forward", "--remove", f"tcp:{self._STF_FORWARD_PORT}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

        self._u2_client = None
        log.info(f"[{self._transport.serial}] ADB bootstrap stopped")

    @property
    def u2(self) -> Optional[U2JsonRpcClient]:
        return self._u2_client

    # ── Bootstrap Sequence ────────────────────────────────────────────────────

    def _bootstrap_sequence(self) -> None:
        serial = self._transport.serial
        log.info(f"[{serial}] Starting ADB bootstrap sequence")

        try:
            # 1. Collect metadata
            meta = self._collect_metadata()
            self._on_metadata(meta)

            # 2. Start screen stream (scrcpy only) — skipped in periodic screenshot mode
            if self._running and not self._skip_scrcpy:
                self._start_stream()
            elif self._skip_scrcpy:
                log.info(f"[{serial}] Skipping scrcpy (periodic screenshot mode)")

            # 3. Start uiautomator2-server
            if self._running:
                self._start_u2_server()

            # 3b. Start u2 watchdog (monitors u2 health, auto-restarts if dead)
            if self._running and self._u2_client is not None:
                self._start_u2_watchdog()

            # 4. Try STFService for push-based events; fall back to shell polling
            if self._running:
                if self._try_stf_service():
                    log.info(f"[{serial}] Using STFService for events (push-based, no polling)")
                else:
                    log.info(f"[{serial}] STFService unavailable, falling back to shell polling")
                    self._start_polling()

            log.info(f"[{serial}] ADB bootstrap complete")

        except Exception as exc:
            log.error(f"[{serial}] Bootstrap failed: {exc}", exc_info=True)

    def _collect_metadata(self) -> dict:
        """Gather device info via getprop + wm size."""
        t = self._transport
        serial = t.serial

        brand = t.get_prop("ro.product.brand")
        model = t.get_prop("ro.product.model")
        android = t.get_prop("ro.build.version.release")
        sdk = t.get_prop("ro.build.version.sdk")
        self._abi = t.get_prop("ro.product.cpu.abi")
        device_serial = t.get_prop("ro.serialno").strip() or serial

        w, h = t.get_screen_size()
        self._screen_width = w
        self._screen_height = h

        meta = {
            "serial": device_serial,
            "brand": brand,
            "model": model,
            "android": android,
            "sdk": int(sdk) if sdk.isdigit() else 0,
            "screen_width": w,
            "screen_height": h,
            "abi": self._abi,
        }
        log.info(
            f"[{serial}] Device: {brand} {model} Android {android} "
            f"SDK={sdk} {w}x{h} ABI={self._abi}"
        )
        return meta

    # ── scrcpy JAR auto-discovery ────────────────────────────────────────────
    _SCRCPY_JAR_SEARCH_PATHS: tuple[str, ...] = (
        # In order of priority: most explicit first.
        # 1. Explicit env var (highest priority)
        # 2. runtime/ (device control package)
        # 3. bundle/scrcpy-server
        # 4. assets/scrcpy-server
        # 5. Current working directory
    )

    @classmethod
    def _resolve_scrcpy_jar(cls) -> str:
        """
        Resolve path to scrcpy-server JAR.

        Priority:
          1. SCRCPY_JAR environment variable
          2. runtime/scrcpy-server  (next to the device_farm package)
          3. bundle/scrcpy-server
          4. assets/scrcpy-server
          5. ./scrcpy-server  (cwd)

        Returns the resolved path string, or raises RuntimeError with
        instructions if not found.
        """
        # 1. Env var
        from_env = os.environ.get("SCRCPY_JAR", "").strip()
        if from_env and Path(from_env).is_file():
            return from_env

        # 2. config.yaml device.scrcpy_jar
        try:
            from core.config import load_config
            cfg_jar = load_config().device.scrcpy_jar
            if cfg_jar and Path(cfg_jar).is_file():
                return cfg_jar
        except Exception:
            pass

        # 3-7. Search well-known paths (relative to this file + system)
        _base = Path(__file__).parent.parent
        candidates = [
            _base / "runtime" / "scrcpy-server",
            _base / "bundle" / "scrcpy-server",
            _base / "assets" / "scrcpy-server",
            Path.cwd() / "scrcpy-server",
            # Homebrew (macOS)
            Path("/opt/homebrew/share/scrcpy/scrcpy-server"),
            Path("/usr/local/share/scrcpy/scrcpy-server"),
            # Linux
            Path("/usr/share/scrcpy/scrcpy-server"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                log.info(f"scrcpy-server JAR auto-discovered: {candidate}")
                return str(candidate)

        # Not found — give actionable instructions
        from runtime.transports.scrcpy_receiver import SCRCPY_SERVER_VERSION
        ver = SCRCPY_SERVER_VERSION
        raise RuntimeError(
            "scrcpy-server JAR not found. Options:\n"
            f"  A) Run:  python download_bundle.py --scrcpy-only\n"
            f"  B) Download manually from https://github.com/Genymobile/scrcpy/releases/tag/v{ver}\n"
            f"     Save as: {_base / 'runtime' / 'scrcpy-server'}\n"
            f"  C) Set env var: export SCRCPY_JAR=/path/to/scrcpy-server-v{ver}"
        )

    def _start_stream(self) -> None:
        """
        Start screen stream using **scrcpy only**.

        The scrcpy-server JAR is resolved automatically (see _resolve_scrcpy_jar).
        Optional `SCRCPY_ADB_BIN` env var overrides the adb binary path.
        """
        serial = self._transport.serial
        adb_bin = os.environ.get("SCRCPY_ADB_BIN", "adb").strip() or "adb"
        try:
            scrcpy_jar = self._resolve_scrcpy_jar()
        except RuntimeError as exc:
            log.error(f"[{serial}] {exc}")
            raise

        try:
            self._start_scrcpy(adb_bin=adb_bin, scrcpy_jar=scrcpy_jar)
        except Exception as exc:
            log.error(f"[{serial}] scrcpy backend failed: {exc!r}")
            raise

    def _start_scrcpy(self, adb_bin: str, scrcpy_jar: str) -> None:
        """
        Start scrcpy-server on device and ScrcpyReceiver on host.

        Design:
          - Use the system adb binary for scrcpy (separate from AdbTransport).
          - Assume device is reachable as "host:port" over adb TCP.
          - adb connect host:port, then forward tcp:PORT → localabstract:scrcpy.
          - ScrcpyReceiver handles pushing server JAR + decoding H264 → JPEG.
        """
        serial = f"{self._transport.host}:{self._transport.port}"

        # Ensure adb is connected to this TCP device
        try:
            subprocess.run(
                [adb_bin, "connect", serial],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            raise RuntimeError(f"adb connect {serial} failed: {exc}") from exc

        port = 27183  # standard scrcpy TCP port

        # Forward host TCP → device localabstract:scrcpy
        result = subprocess.run(
            [adb_bin, "-s", serial, "forward", f"tcp:{port}", "localabstract:scrcpy"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"adb forward failed: {result.stderr.strip()}")

        # Start receiver (pushes server JAR + runs scrcpy-server).
        # Hook up on_frame callback so DeviceClient.publish_frame() gets called.
        self._scrcpy_receiver = ScrcpyReceiver(
            serial=serial,
            adb_path=adb_bin,
            port=port,
            server_jar=scrcpy_jar,
            max_fps=30,
            max_width=800,
            reconnect_delay=2.0,
        )
        # ScrcpyReceiver exposes _on_frame callback for decoded JPEG frames.
        self._scrcpy_receiver._on_frame = self._on_frame  # type: ignore[attr-defined]
        self._scrcpy_receiver.start_receiver()
        log.info(f"[{serial}] ScrcpyReceiver → 127.0.0.1:{port}")

    def _start_u2_server(self) -> None:
        """
        Start uiautomator2-server on device via am instrument.
        u2-server listens on TCP :9008. Server connects directly — no forwarding.
        """
        t = self._transport
        serial = t.serial
        host = t.host

        # Allow disabling u2 entirely via env (scrcpy-only mode)
        if os.environ.get("DISABLE_U2", "").strip():
            log.info(f"[{serial}] DISABLE_U2=1 → skipping uiautomator2-server startup")
            return

        if not t.connected:
            t.connect(retries=2, retry_delay=1.0)

        # Check if u2 APKs are installed; if not, try auto-install from third_party/
        installed = t.shell_safe(f"pm path {U2_SERVER_PKG}").strip()
        # Prefer third_party/, fallback to bundle/apks/
        main_apk = U2_SERVER_APK if U2_SERVER_APK.exists() else U2_SERVER_APK_BUNDLE
        test_apk = U2_SERVER_TEST_APK if U2_SERVER_TEST_APK.exists() else U2_SERVER_TEST_APK_BUNDLE
        apk_src = "third_party" if main_apk == U2_SERVER_APK else "bundle/apks"
        if not installed and main_apk.exists() and test_apk.exists():
            log.info(f"[{serial}] u2 not installed → auto-installing from {apk_src}/")
            remote_main = f"{_REMOTE_TMP}/u2-server.apk"
            remote_test = f"{_REMOTE_TMP}/u2-server-test.apk"
            if t.push_file(str(main_apk), remote_main, mode=0o644) and t.push_file(
                str(test_apk), remote_test, mode=0o644
            ):
                out_main = t.shell_safe(f"pm install -r -t {remote_main}", timeout=60.0)
                out_test = t.shell_safe(f"pm install -r -t {remote_test}", timeout=60.0)
                t.shell_safe(f"rm -f {remote_main} {remote_test}")
                if "Success" in out_main and "Success" in out_test:
                    installed = t.shell_safe(f"pm path {U2_SERVER_PKG}").strip()
                    log.info(f"[{serial}] u2 auto-install OK")
                else:
                    log.warning(f"[{serial}] u2 install output: main={out_main!r} test={out_test!r}")
            else:
                log.warning(f"[{serial}] u2 push failed")
        if not installed:
            log.warning(
                f"[{serial}] uiautomator2-server not installed. "
                f"Place APKs in {_U2_APK_DIR} or {_U2_BUNDLE_APK_DIR} or install manually."
            )
            return

        # Kill any existing u2 session
        t.shell_safe(f"am force-stop {U2_SERVER_PKG}")
        time.sleep(0.5)

        # Exclude u2 APKs from battery optimization so Android won't kill am instrument.
        # Works on Doze-capable devices (Android 6+). Requires ADB shell privilege (shell user).
        for pkg in (U2_SERVER_PKG, U2_SERVER_TEST_PKG):
            t.shell_safe(f"dumpsys deviceidle whitelist +{pkg}", timeout=5.0)

        # Start u2 instrumentation in background.
        # -e timeout 0 disables the default 10-minute instrumentation time-out that
        # causes am instrument to self-terminate and forces a restart loop.
        u2_cmd = (
            f"am instrument -w -e timeout 0 "
            f"{U2_SERVER_TEST_PKG}/{U2_RUNNER}"
        )
        log.info(f"[{serial}] Starting uiautomator2-server: {u2_cmd}")

        u2_transport = AdbTransport(host, self._transport.port)
        if not u2_transport.connect(retries=2, retry_delay=1.0):
            log.error(f"[{serial}] Cannot open second ADB connection for u2")
            return

        u2_transport.start_streaming_shell(
            u2_cmd,
            on_line=lambda line: log.debug(f"[{serial}] u2: {line}"),
            on_exit=lambda: self._on_u2_exit(u2_transport),
        )

        # Wait for u2 HTTP server to become available
        client = U2JsonRpcClient(host, U2_TCP_PORT, timeout=self._u2_wait_timeout,
                                 adb_shell=self._transport.shell_safe)
        client.implicitly_wait(self._u2_implicitly_wait)
        client.settings["wait_timeout"] = self._u2_wait_timeout

        for attempt in range(1, 10):
            if not self._running:
                return
            try:
                client.verify()
                self._u2_client = client
                log.info(
                    f"[{serial}] uiautomator2 HTTP ready at {host}:{U2_TCP_PORT} "
                    f"(attempt {attempt})"
                )
                self._on_u2_ready(client)
                return
            except Exception as exc:
                log.debug(f"[{serial}] u2 not ready yet (attempt {attempt}): {exc}")
                time.sleep(2.0)

        log.error(f"[{serial}] uiautomator2-server failed to start after retries")

    def _on_u2_exit(self, u2_transport: AdbTransport) -> None:
        """Called when u2-server instrument exits (streaming shell closed).

        Uses exponential backoff to avoid rapid restart loops when am-instrument
        exits immediately (e.g. due to memory pressure or a device-side crash):
          exit 1 → wait 5s
          exit 2 → wait 10s
          exit 3 → wait 20s
          exit 4+ → wait 40s (capped)
        The counter resets if the process ran for ≥ 60s (healthy run).
        """
        u2_transport.close()
        if not self._running:
            return
        serial = self._transport.serial

        now = time.monotonic()
        # Reset counter if last exit was long ago (process was running healthily)
        if now - self._u2_exit_last >= 60.0:
            self._u2_exit_count = 0
        self._u2_exit_count += 1
        self._u2_exit_last = now

        delay = min(5.0 * (2 ** (self._u2_exit_count - 1)), 40.0)  # 5, 10, 20, 40, 40, ...
        log.warning(f"[{serial}] u2-server exited (#{self._u2_exit_count}) — restarting in {delay:.0f}s")

        self._u2_client = None
        time.sleep(delay)
        if self._running:
            # Reuse restart machinery so debounce + lock are respected
            self.restart_u2_server(debounce=0.0)

    def restart_u2_server(self, debounce: float = 30.0) -> bool:
        """
        Self-healing: kill the existing u2-server and start a fresh one.

        Called by DeviceClient.ensure_u2_healthy() when a ping to the HTTP
        server fails — covers both the "process exited" and the "process
        frozen / NanoHTTPD hung" cases.

        Debounce: if a restart happened less than `debounce` seconds ago,
        this call is a no-op (returns False) so callers can immediately fall
        back to ratio/image instead of blocking on another restart attempt.

        Returns True once the new u2 HTTP server is verified ready.
        Thread-safe: only one restart proceeds at a time; others return False.
        """
        if not self._running:
            return False

        # Fast debounce check (no lock needed for monotonic read)
        now = time.monotonic()
        if now - self._u2_last_restart < debounce:
            serial = self._transport.serial
            log.debug(
                "[%s] u2 restart skipped (debounce %.0fs remaining)",
                serial, debounce - (now - self._u2_last_restart),
            )
            return False

        # Only one restart at a time
        acquired = self._u2_restart_lock.acquire(blocking=False)
        if not acquired:
            return False

        serial = self._transport.serial
        try:
            self._u2_last_restart = time.monotonic()
            log.warning("[%s] u2 self-healing: killing and restarting atx-agent", serial)

            # 1. Kill existing u2-server (force-stop is idempotent)
            self._u2_client = None
            try:
                self._transport.shell_safe(f"am force-stop {U2_SERVER_PKG}", timeout=5.0)
            except Exception as exc:
                log.debug("[%s] force-stop u2 error (ignored): %s", serial, exc)
            time.sleep(1.0)

            # 2. Re-run am instrument (reuses _start_u2_server fast path)
            #    _start_u2_server() also calls _on_u2_ready which wires _u2 back
            #    into DeviceClient via the callback.
            self._start_u2_server()

            ok = self._u2_client is not None
            if ok:
                log.info("[%s] u2 self-healing: atx-agent restarted successfully", serial)
            else:
                log.error("[%s] u2 self-healing: atx-agent restart failed", serial)
            return ok
        finally:
            self._u2_restart_lock.release()


    # ── U2 Watchdog (tương tự d.healthcheck() của uiautomator2 gốc) ──────────

    def _start_u2_watchdog(self) -> None:
        """
        Start a daemon thread that periodically pings u2 and restarts
        atx-agent if it becomes unresponsive.

        Mirrors the behaviour of ``d.healthcheck()`` / ``d.watchers.watched``
        in the official uiautomator2 Python library, but works with our
        custom U2JsonRpcClient (no dependency on the upstream library).
        """
        t = threading.Thread(
            target=self._u2_watchdog_loop,
            daemon=True,
            name=f"u2-watchdog-{self._transport.serial}",
        )
        t.start()
        log.info(
            "[%s] u2 watchdog started (interval=%.0fs, max_fails=%d)",
            self._transport.serial,
            self._u2_watchdog_interval,
            self._u2_watchdog_max_fails,
        )

    def _u2_watchdog_loop(self) -> None:
        """
        Watchdog loop: runs every _u2_watchdog_interval seconds.

        Algorithm (same as upstream uiautomator2 healthcheck):
          - GET /ping with short timeout
          - Success  → reset consecutive-fail counter
          - Failure  → increment counter
          - Counter >= max_fails → restart atx-agent via restart_u2_server()
        """
        serial = self._transport.serial
        fail_count = 0

        while self._running:
            # Sleep in 1-second ticks so stop() wakes quickly
            for _ in range(int(self._u2_watchdog_interval)):
                if not self._running:
                    return
                time.sleep(1.0)

            client = self._u2_client
            if client is None:
                # u2 not ready yet (still starting or mid-restart) — skip this tick
                fail_count = 0
                continue

            alive = client.ping(timeout=5.0)

            if alive:
                if fail_count > 0:
                    log.debug("[%s] u2 watchdog: ping OK (was failing %d times)", serial, fail_count)
                fail_count = 0
                continue

            fail_count += 1
            log.warning(
                "[%s] u2 watchdog: ping failed (%d/%d)",
                serial, fail_count, self._u2_watchdog_max_fails,
            )

            if fail_count >= self._u2_watchdog_max_fails:
                fail_count = 0
                log.warning("[%s] u2 watchdog: threshold reached — restarting atx-agent", serial)
                # bypass debounce: watchdog already controls its own timing
                self.restart_u2_server(debounce=0.0)

    _STF_PKG = "jp.co.cyberagent.stf"
    _STF_SERVICE_CLS = "jp.co.cyberagent.stf/.Service"
    _STF_FORWARD_PORT = 1100  # local port for adb forward → stfservice socket

    def _try_stf_service(self) -> bool:
        """
        If STFService APK is installed, start it and connect via adb forward.
        Returns True if successfully connected (replaces polling).
        """
        t = self._transport
        serial = t.serial

        # Check if STFService APK is installed
        installed = t.shell_safe(f"pm path {self._STF_PKG}").strip()
        if not installed:
            return False

        # Start the service
        t.shell_safe(
            f"am startservice -n {self._STF_SERVICE_CLS}",
            timeout=5.0,
        )
        time.sleep(1.0)  # Give service time to open socket

        # Forward local port to the STFService abstract socket
        try:
            subprocess.run(
                ["adb", "-s", serial, "forward",
                 f"tcp:{self._STF_FORWARD_PORT}", "localabstract:stfservice"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as exc:
            log.warning(f"[{serial}] adb forward stfservice failed: {exc}")
            return False

        # Connect STFServiceClient
        try:
            svc = STFServiceClient(
                serial=serial,
                host="127.0.0.1",
                port=self._STF_FORWARD_PORT,
                on_battery=self._on_battery,
                on_rotation=self._on_rotation,
            )
            svc.start_client()
            # Wait briefly for initial peek events
            time.sleep(0.5)
            if not svc.connected:
                svc.stop_client()
                return False
            self._stf_service = svc
            if self._on_stf_ready:
                self._on_stf_ready(svc)
            log.info(f"[{serial}] STFService connected via adb forward :{self._STF_FORWARD_PORT}")
            return True
        except Exception as exc:
            log.warning(f"[{serial}] STFService connect failed: {exc}")
            return False

    # ── Battery / Rotation Polling (fallback when STFService unavailable) ───

    def _start_polling(self) -> None:
        """Start background thread that polls battery and rotation via shell."""
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name=f"adb-poll-{self._transport.serial}",
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        serial = self._transport.serial
        while self._running:
            try:
                # Battery
                level = self._transport.get_battery_level()
                if level >= 0:
                    self._on_battery(level)

                # Rotation
                degrees = self._transport.get_rotation()
                self._on_rotation(degrees)

            except Exception as exc:
                log.debug(f"[{serial}] poll error: {exc}")

            # Wait between polls
            for _ in range(int(_POLL_INTERVAL)):
                if not self._running:
                    return
                time.sleep(1.0)
