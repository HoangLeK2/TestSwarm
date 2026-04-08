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

# Suppress gRPC C-core fork() handler warnings that appear when subprocess.Popen
# is called (e.g. for adb shell / scrcpy restart) while gRPC threads are active.
# These are harmless — gRPC safely skips its fork handlers in this scenario.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

import logging
import shlex
import shutil

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


# def _run_agent_boot(argv: list[str]) -> None:
#     """
#     Bridge to ../agent-boot/main.py via subprocess.

#     Usage:
#       uv run main.py agent-boot --serial <device>
#       uv run main.py --agent-boot --serial <device>
#     """
#     import subprocess

#     agent_boot_dir = (_root.parent / "agent-boot").resolve()
#     if not (agent_boot_dir / "main.py").is_file():
#         raise SystemExit(f"agent-boot not found: {agent_boot_dir}/main.py")

#     # Prefer uv run (respects agent-boot's own venv/pyproject), fall back to plain python.
#     uv = shutil.which("uv")
#     if uv:
#         cmd = [uv, "run", "main.py", *argv]
#     else:
#         cmd = [sys.executable, "main.py", *argv]

#     result = subprocess.run(cmd, cwd=str(agent_boot_dir))
#     if result.returncode not in (0, 1):  # 1 = bootstrap skipped/no-devices is normal
#         raise SystemExit(f"agent-boot exited with code {result.returncode}")


def _start_agent_boot_relay_bg(relay_server: str, api_key: str) -> None:
    """Start agent-boot relay daemon as a background subprocess (non-blocking)."""
    import subprocess

    agent_boot_dir = (_root.parent / "agent-boot").resolve()
    if not (agent_boot_dir / "main.py").is_file():
        return

    uv = shutil.which("uv")
    cmd = [uv or sys.executable, "run", "main.py", "--relay-only"]
    if not uv:
        cmd = [sys.executable, "main.py", "--relay-only"]

    env = os.environ.copy()
    # Remove device_farm venv vars so uv/pip inside agent-boot uses its own env
    for _k in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT"):
        env.pop(_k, None)
    if relay_server:
        env["RELAY_SERVER"] = relay_server
    if api_key:
        env["RELAY_API_KEY"] = api_key

    log = logging.getLogger("main")
    log.info("agent-boot relay: starting background daemon → %s  cmd=%s", relay_server, cmd)
    proc = subprocess.Popen(
        cmd,
        cwd=str(agent_boot_dir),
        env=env,
        # Inherit stderr so relay errors appear in device_farm console
        stdout=subprocess.DEVNULL,
    )
    log.info("agent-boot relay: subprocess started (pid=%d)", proc.pid)


def main() -> None:
    # Convenience: allow launching agent-boot from the same entrypoint.
    # (Keeps server startup unchanged unless explicitly requested.)
    # if len(sys.argv) > 1 and sys.argv[1] in {"agent-boot", "agent_boot"}:
    #     _run_agent_boot(sys.argv[2:])
    #     return
    # if "--agent-boot" in sys.argv:
    #     i = sys.argv.index("--agent-boot")
    #     _run_agent_boot(sys.argv[i + 1 :])
    #     return

    config_path = farm_config_path()
    config = load_config(config_path)
    setup_logging(config.logging)
    reload_enabled = farm_reload_enabled()

    # Auto-run agent-boot when starting the server.
    # Phase 1: bootstrap (blocking, fast) — installs u2/atx-agent on connected devices.
    # Phase 2: relay daemon (background subprocess) — keeps gRPC stream open for scrcpy/adb.
    # Disable entirely with FARM_AGENT_BOOT=0.
    auto = os.getenv("FARM_AGENT_BOOT", "1").strip().lower()
    if auto not in {"0", "false", "no", "off"}:
        log = logging.getLogger("main")
        # ── Phase 1: bootstrap ────────────────────────────────────────────────
        try:
            args_raw = os.getenv("FARM_AGENT_BOOT_ARGS", "").strip()
            if args_raw:
                bootstrap_args = shlex.split(args_raw)
            else:
                bootstrap_args = ["--bootstrap-only", "--skip-stf", "--skip-tcpip"]
                serial = os.getenv("FARM_AGENT_BOOT_SERIAL", "").strip()
                if serial:
                    bootstrap_args = ["--serial", serial, *bootstrap_args]

            log.info("agent-boot bootstrap: %s", " ".join(bootstrap_args))
            # _run_agent_boot(bootstrap_args)
            log.info("agent-boot bootstrap: done")
        except SystemExit as e:
            log.warning("agent-boot bootstrap: skipped (%s)", e)
        except Exception as e:
            log.warning("agent-boot bootstrap: failed (%s)", e)

        # ── Phase 2: relay daemon (background) ───────────────────────────────
        try:
            # Relay is WebSocket on the main HTTP port (/relay-agent), not gRPC :relay.port.
            _default_ws_relay = f"localhost:{config.web.port}"
            relay_server = os.getenv("RELAY_SERVER", _default_ws_relay).strip()
            relay_api_key = os.getenv("RELAY_API_KEY", getattr(config.relay, "api_key", "") or "").strip()
            _start_agent_boot_relay_bg(relay_server, relay_api_key)
        except Exception as e:
            log.warning("agent-boot relay daemon: failed to start (%s)", e)

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
    # uvloop: 2-4x faster event loop vs asyncio default (C extension, zero-overhead I/O).
    # Falls back to asyncio if uvloop is not installed.
    _loop = "uvloop" if not reload_enabled else "auto"
    uvicorn.run(
        app,
        host=config.web.host,
        port=config.web.port,
        log_level=config.logging.level.lower(),
        access_log=False,
        ws_ping_interval=config.web.ws_ping_interval,
        ws_ping_timeout=config.web.ws_ping_timeout,
        loop=_loop,
        reload=reload_enabled,
        reload_dirs=[str(root_dir)],
    )


if __name__ == "__main__":
    # Change working directory to where main.py lives so relative paths work
    os.chdir(Path(__file__).parent)
    main()
