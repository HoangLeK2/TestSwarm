"""
main.py — Entry point for the Android Device Farm.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root))
os.chdir(_root)
load_dotenv(dotenv_path=_root / ".env", override=False)

import logging
import signal
import shlex
import threading
import time

import uvicorn

from core.config import load_config, setup_logging
from core.env import (
    farm_config_path,
    farm_frontend_dist_override,
    farm_reload_enabled,
    ngrok_authtoken,
    ngrok_enabled,
    resolve_farm_frontend_dist,
)
from runtime.core import DeviceManager, TaskQueue, Dispatcher, WatchdogThread
from web.server import create_app


def _run_agent_boot(argv: list[str]) -> None:
    """
    Bridge to ../agent-boot/main.py (folder name contains '-', can't be imported normally).

    Usage:
      uv run main.py agent-boot --serial <device>
      uv run main.py --agent-boot --serial <device>
    """
    import importlib.util

    agent_boot_path = (_root.parent / "agent-boot" / "main.py").resolve()
    if not agent_boot_path.is_file():
        raise SystemExit(f"agent-boot not found: {agent_boot_path}")

    spec = importlib.util.spec_from_file_location("device_farm_agent_boot", agent_boot_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load agent-boot module: {agent_boot_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]

    if not hasattr(mod, "main") or not callable(mod.main):
        raise SystemExit(f"agent-boot main() missing in: {agent_boot_path}")

    old_argv = sys.argv[:]
    try:
        sys.argv = [str(agent_boot_path), *argv]
        mod.main()
    finally:
        sys.argv = old_argv


def main() -> None:
    # Convenience: allow launching agent-boot from the same entrypoint.
    # (Keeps server startup unchanged unless explicitly requested.)
    if len(sys.argv) > 1 and sys.argv[1] in {"agent-boot", "agent_boot"}:
        _run_agent_boot(sys.argv[2:])
        return
    if "--agent-boot" in sys.argv:
        i = sys.argv.index("--agent-boot")
        _run_agent_boot(sys.argv[i + 1 :])
        return

    config_path = farm_config_path()
    config = load_config(config_path)
    setup_logging(config.logging)
    reload_enabled = farm_reload_enabled()

    # Auto-run agent-boot when starting the server.
    # Default: enabled (so `uv run main.py` "just works"), but never blocks startup if it fails.
    auto = os.getenv("FARM_AGENT_BOOT", "1").strip().lower()
    if auto not in {"0", "false", "no", "off"}:
        log = logging.getLogger("main")
        try:
            # Default behavior: don't touch STF app; just make u2 available.
            # Override with FARM_AGENT_BOOT_ARGS, e.g. "--serial 192.168.1.10:5555 --skip-stf --skip-tcpip"
            args_raw = os.getenv("FARM_AGENT_BOOT_ARGS", "").strip()
            if args_raw:
                args = shlex.split(args_raw)
            else:
                args = ["--skip-stf", "--skip-tcpip"]
                serial = os.getenv("FARM_AGENT_BOOT_SERIAL", "").strip()
                if serial:
                    args = ["--serial", serial, *args]

            log.info("agent-boot: auto running (%s)", " ".join(args) if args else "(no args)")
            _run_agent_boot(args)
            log.info("agent-boot: done")
        except SystemExit as e:
            # agent-boot uses SystemExit for normal failures (no devices, missing apks, etc.)
            log.warning("agent-boot: skipped/failed (%s) — continuing server startup", e)
        except Exception as e:
            log.warning("agent-boot: failed (%s) — continuing server startup", e)

    log = logging.getLogger("main")
    log.info("=" * 60)
    log.info("Android Device Farm starting up")
    log.info(f"Config: {config_path}")
    log.info(f"Web server: http://{config.web.host}:{config.web.port}")
    log.info("=" * 60)

    # ── 2. Core components ────────────────────────────────────────────────────
    task_queue = TaskQueue()
    manager = DeviceManager(config)

    # Cloud-first architecture:
    #   App scans ws:// QR from dashboard → connects to /device-agent WebSocket
    #   Watchdog auto-starts u2-server via ADB wireless (phone_ip:5555) when needed
    #   Requires phone: Developer Options → Wireless debugging enabled (once at setup)
    log.info("Devices: app scans ws:// QR → connects via /device-agent WebSocket")

    watchdog = WatchdogThread(manager, config)
    watchdog.start_watchdog()
    log.info("Watchdog started")

    dispatcher = Dispatcher(manager, task_queue, config)
    dispatcher.start_dispatcher()
    log.info("Dispatcher started")


    shutdown_event = threading.Event()

    def _shutdown(signum, frame):
        log.info("Shutdown signal received")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    root_dir = Path(__file__).resolve().parent
    templates_dir = str(root_dir / "web" / "templates")
    static_dir = str(root_dir / "web" / "static")
    front_end_dist = resolve_farm_frontend_dist(root_dir)
    override = farm_frontend_dist_override()
    if override and not front_end_dist:
        log.warning("FARM_FRONTEND_DIST is set but not a directory: %s", override)
    elif front_end_dist:
        log.info("SPA static: %s", front_end_dist)

    app = create_app(manager, task_queue, config, templates_dir, static_dir, front_end_dist)

    def _run_server():
        uvicorn.run(
            app,
            host=config.web.host,
            port=config.web.port,
            log_level=config.logging.level.lower(),
            access_log=False,
            ws_ping_interval=config.web.ws_ping_interval,
            ws_ping_timeout=config.web.ws_ping_timeout,
            reload=reload_enabled,
            reload_dirs=[str(root_dir)],
        )

    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()
    # Let server run startup so event loop is set before ADB bootstrap sends frames
    time.sleep(1.5)

    # ADB devices are registered only after "Connect by QR" flow (app scan → POST /api/connect/register).
    # No auto-register from FARM_ADB_HOST at startup.

    ngrok_tunnel = None
    if ngrok_enabled():
        try:
            import pyngrok
            auth = ngrok_authtoken()
            if auth:
                pyngrok.set_auth_token(auth)
            ngrok_tunnel = pyngrok.ngrok.connect(addr=str(config.web.port), bind_tls=True)
            log.info("=" * 60)
            log.info("ngrok tunnel: %s", ngrok_tunnel.public_url)
            log.info("=" * 60)
        except Exception as e:
            err = str(e).lower()
            log.warning("ngrok failed: %s", e)
            if "bandwidth" in err:
                log.warning(
                    "ngrok free tier bandwidth limit. Options: 1) Lower config: scrcpy_bitrate. "
                    "2) Upgrade at dashboard.ngrok.com. 3) Use Cloudflare Tunnel: cloudflared tunnel --url http://localhost:%s",
                    config.web.port,
                )

    log.info(f"Dashboard: http://localhost:{config.web.port}")
    log.info("Press Ctrl+C to stop")

    # Block until shutdown signal
    try:
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=1.0)
    except KeyboardInterrupt:
        pass

    log.info("Shutting down…")

    if ngrok_tunnel is not None:
        try:
            import pyngrok
            pyngrok.ngrok.disconnect(ngrok_tunnel.public_url)
            pyngrok.ngrok.kill()
        except Exception:
            pass

    watchdog.stop_watchdog()
    dispatcher.stop_dispatcher()
    manager.teardown_all()

    log.info("Shutdown complete. Goodbye.")


if __name__ == "__main__":
    # Change working directory to where main.py lives so relative paths work
    os.chdir(Path(__file__).parent)
    main()
