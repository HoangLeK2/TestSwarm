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
from runtime.transports.minitouch import MinitouchSender
from runtime.transports.scrcpy_receiver import ScrcpyReceiver
from runtime.transports.u2_jsonrpc import U2JsonRpcClient

log = logging.getLogger(__name__)

# ── Binary assets directory ───────────────────────────────────────────────────
# Put prebuilt minitouch binary here: assets/minitouch/<abi>/minitouch or bundle/minitouch/<abi>/minitouch
_ASSETS_DIR = Path(__file__).parent.parent / "assets"
_BUNDLE_DIR = Path(__file__).parent.parent / "bundle"

# Remote paths on device
_REMOTE_TMP = "/data/local/tmp"
# u2-server listens on this TCP port (openatx/android-uiautomator-server default)
U2_TCP_PORT = 9008
# minitouch: abstract socket "minitouch" on device → adb forward to this host port
MINITOUCH_HOST_PORT = 27184
_MINITOUCH_REMOTE = f"{_REMOTE_TMP}/minitouch"
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
        on_minitouch_ready: Optional[Callable[[MinitouchSender], None]] = None,
        u2_wait_timeout: float = 20.0,
        u2_implicitly_wait: float = 10.0,
    ) -> None:
        self._transport = transport
        self._on_frame = on_frame
        self._on_battery = on_battery
        self._on_rotation = on_rotation
        self._on_u2_ready = on_u2_ready
        self._on_metadata = on_metadata
        self._on_minitouch_ready = on_minitouch_ready
        self._u2_wait_timeout = u2_wait_timeout
        self._u2_implicitly_wait = u2_implicitly_wait

        self._running = False
        self._lock = threading.Lock()

        # Components started by bootstrap
        self._scrcpy_receiver: Optional[ScrcpyReceiver] = None
        self._u2_client: Optional[U2JsonRpcClient] = None
        self._minitouch_sender: Optional[MinitouchSender] = None
        self._poll_thread: Optional[threading.Thread] = None

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

        # Disconnect minitouch and remove forward
        if self._minitouch_sender:
            try:
                self._minitouch_sender.disconnect()
            except Exception:
                pass
            self._minitouch_sender = None
        try:
            subprocess.run(
                ["adb", "-s", self._transport.serial, "forward", "--remove", f"tcp:{MINITOUCH_HOST_PORT}"],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass
        try:
            self._transport.kill_process("minitouch")
        except Exception:
            pass
        try:
            self._transport.shell_safe(
                f"am force-stop {U2_SERVER_PKG}"
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

            # 2. Start screen stream (scrcpy only)
            if self._running:
                self._start_stream()

            # 3. Start minitouch (push binary, start process, forward, connect)
            # NOTE: On modern Android (SDK>=34), raw minitouch binary often can't access /dev/input/*
            # without additional privileges/relay. Default to U2 for touch on these devices.
            sdk = 0
            try:
                sdk = int(meta.get("sdk", 0) or 0)
            except Exception:
                sdk = 0
            force_minitouch = os.environ.get("FORCE_MINITOUCH", "").strip().lower() in {"1", "true", "yes"}
            if (
                self._running
                and self._on_minitouch_ready is not None
                and (force_minitouch or sdk < 34)
            ):
                if self._ensure_minitouch():
                    self._start_minitouch()
            elif self._running and self._on_minitouch_ready is not None and sdk >= 34 and not force_minitouch:
                log.info(f"[{serial}] SDK={sdk} → skip minitouch (set FORCE_MINITOUCH=1 to try anyway)")

            # 4. Start uiautomator2-server
            if self._running:
                self._start_u2_server()

            # 5. Start battery/rotation polling
            if self._running:
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

        # 2-5. Search well-known relative paths (relative to this file's parent)
        _base = Path(__file__).parent.parent
        candidates = [
            _base / "runtime" / "scrcpy-server",
            _base / "bundle" / "scrcpy-server",
            _base / "assets" / "scrcpy-server",
            Path.cwd() / "scrcpy-server",
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

    def _ensure_minitouch(self) -> bool:
        """Push minitouch binary to device if not present. Returns True if ready to start."""
        t = self._transport
        serial = t.serial
        if t.is_file_present(_MINITOUCH_REMOTE):
            log.info(f"[{serial}] minitouch already on device")
            return True
        abi = self._abi or "arm64-v8a"
        for try_abi in (abi, "arm64-v8a", "armeabi-v7a"):
            for base in (_ASSETS_DIR, _BUNDLE_DIR):
                bin_asset = base / "minitouch" / try_abi / "minitouch"
                if not bin_asset.exists() or bin_asset.stat().st_size == 0:
                    continue
                log.info(f"[{serial}] Pushing minitouch ({try_abi}) from {base.name}/...")
                if t.push_file(str(bin_asset), _MINITOUCH_REMOTE, mode=0o755):
                    t.chmod(_MINITOUCH_REMOTE, "755")
                    log.info(f"[{serial}] minitouch pushed successfully")
                    return True
                # push failed for this binary — try next base dir, then next ABI
                log.warning(f"[{serial}] push failed for {bin_asset}, trying next...")
        log.warning(
            f"[{serial}] minitouch binary not found in assets/minitouch/<abi>/ or bundle/minitouch/<abi>/. "
            "Place prebuilt minitouch in e.g. assets/minitouch/arm64-v8a/minitouch"
        )
        return False

    def _start_minitouch(self) -> None:
        """Start minitouch on device (abstract socket), adb forward, connect MinitouchSender."""
        t = self._transport
        serial = t.serial
        w = self._screen_width or 1080
        h = self._screen_height or 1920
        t.kill_process("minitouch")
        time.sleep(0.5)
        # Capture logs so we can debug permission/device selection issues
        log_path = f"{_REMOTE_TMP}/minitouch.log"
        t.shell_safe(f"rm -f {log_path}")
        # Force socket name to "minitouch" explicitly
        t.shell_safe(f"nohup {_MINITOUCH_REMOTE} -n minitouch > {log_path} 2>&1 &")
        time.sleep(1.0)
        # Verify process is running; if not, print the log and a foreground run output for debugging
        ps = t.shell_safe("pgrep -f minitouch || true").strip()
        if not ps:
            mt_log = t.shell_safe(
                f"ls -l {log_path} || true; "
                f"(toybox tail -n 80 {log_path} 2>/dev/null || tail -n 80 {log_path} 2>/dev/null || cat {log_path} 2>/dev/null || true)",
                timeout=5.0,
            ).strip()
            # Try a short foreground run to capture immediate errors (permission/device missing)
            fg = t.shell_safe(
                f"toybox timeout 2 {_MINITOUCH_REMOTE} -n minitouch 2>&1 || true",
                timeout=5.0,
            ).strip()
            log.warning(
                f"[{serial}] minitouch failed to start.\n"
                f"--- /data/local/tmp/minitouch.log ---\n{mt_log}\n"
                f"--- foreground (2s) ---\n{fg}".rstrip()
            )
        try:
            subprocess.run(
                ["adb", "-s", serial, "forward", f"tcp:{MINITOUCH_HOST_PORT}", "localabstract:minitouch"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            log.warning(f"[{serial}] adb forward minitouch failed: {exc}")
            return
        for attempt in range(3):
            if not self._running:
                return
            try:
                sender = MinitouchSender(serial, "127.0.0.1", MINITOUCH_HOST_PORT, w, h)
                sender.connect()
                self._minitouch_sender = sender
                if self._on_minitouch_ready:
                    self._on_minitouch_ready(sender)
                log.info(f"[{serial}] minitouch ready (ADB)")
                return
            except Exception as exc:
                log.debug(f"[{serial}] minitouch connect attempt {attempt + 1}/3: {exc}")
                time.sleep(0.8)
        log.warning(f"[{serial}] minitouch connect failed after retries")

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

        # Ensure adb transport is connected (minitouch probing may run a command that fails with rc!=0)
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

        # Start u2 instrumentation in background
        u2_cmd = (
            f"am instrument -w "
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
        client = U2JsonRpcClient(host, U2_TCP_PORT, timeout=self._u2_wait_timeout)
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
        """Called when u2-server instrument exits."""
        if not self._running:
            u2_transport.close()
            return
        serial = self._transport.serial
        log.warning(f"[{serial}] u2-server exited — restarting after 5s")
        self._u2_client = None
        time.sleep(5.0)
        u2_transport.close()
        if self._running:
            self._start_u2_server()

    # ── Battery / Rotation Polling (replaces STFService) ─────────────────────

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
