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

import atexit
import logging
import shutil
import signal
import threading

import uvicorn

# ── Child subprocess lifecycle tracking ─────────────────────────────────────
# agent-boot (and similar long-lived children we spawn with Popen) must die
# when the server dies. Without tracking + signal wiring, parent crash/reload
# leaves orphan relay daemons that hold ports and race a fresh spawn on restart.
#
# Note: the async `runtime.lifecycle.LifecycleManager` owns everything scoped
# to the uvicorn event loop (tasks, grpc, redis, scheduler). Subprocesses must
# be torn down synchronously from atexit / signal handlers because the Python
# interpreter may exit before the async loop can run its shutdown hooks.
_CHILD_PROCS: "list[tuple[str, object]]" = []
_CHILD_LOCK = threading.Lock()
_SHUTDOWN_HOOKED = False


def _register_child(name: str, proc) -> None:
    with _CHILD_LOCK:
        _CHILD_PROCS.append((name, proc))
    _install_shutdown_hooks()


def _reap_child(proc, name: str, timeout: float = 5.0) -> None:
    try:
        if proc.poll() is not None:
            return
        log = logging.getLogger("main")
        log.info("child %s (pid=%s): sending SIGTERM", name, proc.pid)
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except Exception:
            log.warning("child %s (pid=%s): SIGTERM timeout, SIGKILL", name, proc.pid)
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
    except Exception:
        pass


def _reap_all_children() -> None:
    with _CHILD_LOCK:
        procs = list(_CHILD_PROCS)
        _CHILD_PROCS.clear()
    for name, proc in procs:
        _reap_child(proc, name)


def _install_shutdown_hooks() -> None:
    global _SHUTDOWN_HOOKED
    if _SHUTDOWN_HOOKED:
        return
    _SHUTDOWN_HOOKED = True
    atexit.register(_reap_all_children)

    def _handler(signum, _frame):
        logging.getLogger("main").info("signal %s received, reaping children", signum)
        _reap_all_children()
        # Re-raise default so uvicorn / normal shutdown still runs
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _handler)
        except (ValueError, OSError):
            # Not main thread or platform limit — atexit still covers normal exit
            pass

from core.config import load_config, setup_logging
from core.env import (
    farm_config_path,
    farm_frontend_dist_override,
    farm_reload_enabled,
    resolve_farm_frontend_dist,
)
from runtime.core import DeviceManager, TaskQueue, Dispatcher, WatchdogThread, EventRecorder
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
    # Refuse duplicate spawn if a previous relay is still alive (e.g. under
    # uvicorn --reload which re-enters this code path).
    with _CHILD_LOCK:
        for _n, _p in _CHILD_PROCS:
            if _n == "agent-boot-relay" and _p.poll() is None:
                log.info("agent-boot relay: already running (pid=%s) — skip spawn", _p.pid)
                return

    log.info("agent-boot relay: starting background daemon → %s  cmd=%s", relay_server, cmd)
    popen_kwargs = dict(
        cwd=str(agent_boot_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        # Own session so signals to the parent don't propagate ambiguously,
        # and so we can kill the whole tree on shutdown.
        start_new_session=True,
    )
    proc = subprocess.Popen(cmd, **popen_kwargs)
    _register_child("agent-boot-relay", proc)
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
    # Phase 1 (bootstrap install of u2/atx-agent on connected devices) is
    # intentionally disabled — `_run_agent_boot` is no longer invoked here.
    # Phase 2: relay daemon (background subprocess) — keeps gRPC stream open for scrcpy/adb.
    # Disable entirely with FARM_AGENT_BOOT=0.
    auto = os.getenv("FARM_AGENT_BOOT", "1").strip().lower()
    if auto not in {"0", "false", "no", "off"}:
        log = logging.getLogger("main")
        log.warning(
            "agent-boot bootstrap: SKIPPED (phase-1 install disabled in code). "
            "Set FARM_AGENT_BOOT=0 to silence this warning."
        )

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
    db_enabled = bool(
        getattr(config, "database", None)
        and getattr(config.database, "enabled", False)
    )
    event_recorder = EventRecorder(db_enabled=db_enabled)
    task_queue = TaskQueue()
    manager = DeviceManager(config, event_recorder=event_recorder)

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

    app = create_app(manager, task_queue, config, templates_dir, static_dir, front_end_dist, event_recorder=event_recorder)

    # Attach lifecycle components — started/stopped by FastAPI lifespan
    app.state.watchdog = WatchdogThread(manager, config)
    app.state.dispatcher = Dispatcher(manager, task_queue, config)

    # ── 3. Run uvicorn in main thread (owns the event loop) ──────────────
    # Default to asyncio loop for runtime stability with asyncpg on macOS.
    # Allow explicit override via FARM_EVENT_LOOP=uvloop when needed.
    _loop = os.getenv("FARM_EVENT_LOOP", "asyncio").strip().lower() if not reload_enabled else "auto"
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
