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
import shlex

import uvicorn

from core.config import load_config, setup_logging
from core.env import (
    farm_config_path,
    farm_frontend_dist_override,
    farm_reload_enabled,
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

    log.info("Devices: app scans ws:// QR → connects via /device-agent WebSocket")

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

    # Attach lifecycle components — started/stopped by FastAPI lifespan
    app.state.watchdog = WatchdogThread(manager, config)
    app.state.dispatcher = Dispatcher(manager, task_queue, config)

    # ── 3. Run uvicorn in main thread (owns the event loop) ──────────────
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


if __name__ == "__main__":
    # Change working directory to where main.py lives so relative paths work
    os.chdir(Path(__file__).parent)
    main()
