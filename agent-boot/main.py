"""
agent-boot/main.py — Entry point.

Modes:
  uv run main.py                     # start relay immediately; reconcile via control plane
  uv run main.py --startup-mode legacy
                                      # bootstrap all devices, then start relay
  uv run main.py --relay-only        # skip bootstrap, just run relay
  uv run main.py --bootstrap-only    # setup devices, then exit
  uv run main.py --serial <serial>   # target a specific device

Config (via .env or environment):
  RELAY_SERVER    WebSocket server URL  (default: ws://localhost:8080/relay-agent)
  RELAY_API_KEY   API key for server auth
  RELAY_ENROLLMENT_TOKEN  User-scoped token that owns this relay agent

Quick start:
  cp .env.example .env   # fill in RELAY_SERVER + RELAY_API_KEY
  uv run main.py
"""
from __future__ import annotations

import os as _os

# Silence gRPC C++ glog fork warnings BEFORE any grpc import.
# subprocess.Popen() falls back to fork+exec on Linux/glibc<2.34 (no
# posix_spawn close-from support). With gRPC threads alive, fork triggers
# `Other threads are currently calling into gRPC, skipping fork() handlers`
# in parent + `FD from fork parent still in poll list: fd(N)` in child for
# every inherited FD. Pure noise — child immediately exec's, FDs vanish.
# ERROR drops INFO/WARNING glog from gRPC's C++ runtime; Python-level
# gRPC errors still surface via the standard logger.
_os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

import argparse
import asyncio
import os
import sys
import time


# ── Config helpers ────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """Load .env from agent-boot/ if present (no external deps)."""
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_file):
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-boot",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode flags
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--relay-only", action="store_true",
                      help="Skip bootstrap, only run relay daemon")
    mode.add_argument("--bootstrap-only", action="store_true",
                      help="Bootstrap devices then exit (no relay)")
    parser.add_argument(
        "--startup-mode",
        choices=("relay-first", "legacy"),
        default=_env("AGENT_BOOT_STARTUP_MODE", "relay-first"),
        help=(
            "Default startup lifecycle: relay-first makes devices stream-capable "
            "before background bootstrap; legacy bootstraps before relay "
            "(default: $AGENT_BOOT_STARTUP_MODE or relay-first)"
        ),
    )

    # Device selection
    parser.add_argument("--serial", "-s", metavar="SERIAL",
                        help="Target a specific device (default: all connected)")

    # Bootstrap options
    parser.add_argument("--apk", metavar="PATH",
                        help="Path to STFService.apk")
    parser.add_argument("--tcpip-port", type=int, default=5555, metavar="PORT",
                        help="Port for adb tcpip (default: 5555)")
    parser.add_argument("--skip-tcpip", action="store_true")
    parser.add_argument("--use-bundle", action="store_true",
                        help="If u2/atx-agent not ready, deploy device_bundle.tar.gz and run launch.sh on device")
    parser.add_argument("--skip-u2", action="store_true",
                        help="Skip uiautomator2 APKs + atx-agent")
    parser.add_argument("--force-u2-install", action="store_true",
                        help="Reinstall uiautomator2 APKs even when already present")
    parser.add_argument("--skip-atx", action="store_true",
                        help="Skip atx-agent push (APKs still installed)")
    parser.add_argument("--skip-stf", action="store_true",
                        help="Skip STFService install + permissions")

    # Relay options
    parser.add_argument("--relay-server", metavar="URL",
                        default=_env("RELAY_SERVER", "ws://localhost:8081/relay-agent"),
                        help="Server URL: ws://host:port/relay-agent (WS) or host:50051 (gRPC)")
    parser.add_argument("--relay-api-key", metavar="KEY",
                        default=_env("RELAY_API_KEY", ""),
                        help="API key (default: $RELAY_API_KEY)")
    parser.add_argument("--relay-enrollment-token", metavar="TOKEN",
                        default=_env("RELAY_ENROLLMENT_TOKEN", ""),
                        help="User-scoped relay ownership token (default: $RELAY_ENROLLMENT_TOKEN)")
    parser.add_argument("--relay-id", metavar="ID",
                        default="",
                        help="Stable relay ID (default: $RELAY_ID or persisted .relay_id file)")
    parser.add_argument("--relay-mode", metavar="MODE",
                        default=_env("RELAY_MODE", "ws"),
                        choices=["ws", "grpc"],
                        help="Transport mode: 'ws' (WebSocket, default) or 'grpc' (HTTP/2 multiplexed)")
    parser.add_argument("--relay-grpc-tls", action="store_true",
                        default=_env("RELAY_GRPC_TLS", "").strip().lower() in {"1", "true", "yes", "on"},
                        help="Use TLS for gRPC relay (also enabled by grpcs:// or https:// relay server)")
    parser.add_argument("--relay-grpc-root-cert-file", metavar="PATH",
                        default=_env("RELAY_GRPC_ROOT_CERT_FILE", ""),
                        help="Optional CA/root certificate PEM for gRPC relay TLS")
    parser.add_argument("--ws-url", metavar="URL",
                        default=_env("DEVICE_FARM_WS", ""),
                        help="WebSocket URL for STFService auto-connect (default: $DEVICE_FARM_WS)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")

    return parser


# ── Wait for device ───────────────────────────────────────────────────────────

def _wait_for_devices(timeout: int = 120) -> bool:
    """
    Poll `adb devices` until at least one device appears or timeout is reached.
    mDNS wireless-debugging discovery is opt-in via AGENT_BOOT_MDNS=1.
    """
    from relay import start_mdns_discovery, _list_serials
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    console = Console()
    zc = start_mdns_discovery()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            "Waiting for device (USB or pre-connected ADB; mDNS if AGENT_BOOT_MDNS=1)…",
            total=None,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            serials = _list_serials()
            if serials:
                progress.update(task, description=f"Found: {serials}")
                if zc:
                    zc.close()  # relay will start its own instance
                return True
            time.sleep(2)

    if zc:
        zc.close()
    console.print(
        f"[red]✗[/red] No device found after {timeout}s.\n"
        "  → Plug USB and enable USB Debugging, or enable Wireless Debugging on phone."
    )
    return False


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _run_bootstrap(args: argparse.Namespace) -> bool:
    from bootstrap import list_serials, find_stf_apk, run_bootstrap

    if not args.serial and not _wait_for_devices():
        return False

    serials = [args.serial] if args.serial else list_serials()
    stf_apk = find_stf_apk(args.apk)

    print(f"[agent-boot] Bootstrapping {len(serials)} device(s): {serials}")
    results = run_bootstrap(
        serials, stf_apk,
        relay_id=getattr(args, "relay_id", ""),
        api_key=getattr(args, "relay_api_key", ""),
        enrollment_token=getattr(args, "relay_enrollment_token", ""),
        skip_tcpip=args.skip_tcpip,
        tcpip_port=args.tcpip_port,
        use_bundle=args.use_bundle,
        skip_u2=args.skip_u2,
        force_u2_install=args.force_u2_install,
        skip_atx=args.skip_atx,
        skip_stf=args.skip_stf,
        ws_url=getattr(args, "ws_url", ""),
    )

    failed = [s for s, ok in results.items() if not ok]
    print()
    print("=" * 60)
    if not failed:
        print("[agent-boot] ✅ All devices bootstrapped successfully")
    else:
        print(f"[agent-boot] ⚠ Failed: {failed}")
    print("=" * 60)

    return not failed


# ── Relay ─────────────────────────────────────────────────────────────────────

def _run_relay(args: argparse.Namespace) -> None:
    try:
        from relay import RelayAgent
    except ImportError:
        print(
            "[agent-boot] ✗ relay module not found.\n"
            "  Install deps: uv sync",
            file=sys.stderr,
        )
        sys.exit(1)

    import logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
        force=True,
    )

    relay_mode = getattr(args, "relay_mode", "ws")
    print(f"\n[agent-boot] Starting relay daemon ({relay_mode.upper()} mode)", file=sys.stderr)
    print(f"  Server : {args.relay_server}", file=sys.stderr)
    print(f"  Relay ID: {args.relay_id}", file=sys.stderr)
    print("  Ctrl+C to stop.\n", file=sys.stderr)

    async def _run() -> None:
        ingest = None
        extra_enabled = os.environ.get("AGENT_BOOT_EXTRA_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        content_enabled = os.environ.get("AGENT_BOOT_CONTENT_DB_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        if extra_enabled or content_enabled:
            from relay.extra_data.ingest import ExtraDataIngestServer

            ingest = ExtraDataIngestServer()
            await ingest.start()

        agent = RelayAgent(
            server_url=args.relay_server,
            api_key=args.relay_api_key or None,
            enrollment_token=args.relay_enrollment_token or None,
            relay_id=args.relay_id,
            relay_mode=relay_mode,
            grpc_tls=bool(args.relay_grpc_tls),
            grpc_root_cert_file=args.relay_grpc_root_cert_file or "",
            extra_ingest=ingest,
        )
        try:
            await agent.run()
        finally:
            if ingest is not None:
                await ingest.stop()

    # uvloop is ~2x faster than the stdlib selector loop for I/O-bound work
    # (ADB sockets, scrcpy stream, gRPC, atx-agent HTTP). Install it before
    # `asyncio.run()` so the relay loop picks it up. Not available on Windows
    # — fall back to the stdlib loop silently.
    try:
        import uvloop  # type: ignore[import-not-found]
        uvloop.install()
        print("[agent-boot] uvloop installed (libuv-backed asyncio loop)", file=sys.stderr)
    except ImportError:
        pass

    asyncio.run(_run())


# ── Main ─────────────────────────────────────────────────────────────────────

def _resolve_relay_id(args: argparse.Namespace) -> None:
    """Pick relay id once per process: explicit flag/env, else persisted file."""
    explicit = (getattr(args, "relay_id", "") or "").strip() or _env("RELAY_ID", "").strip()
    if explicit:
        args.relay_id = explicit
        return
    from relay.agent import load_or_create_relay_id

    args.relay_id = load_or_create_relay_id()


def _bootstrap_options_requested(args: argparse.Namespace) -> bool:
    """Preserve the pre-relay bootstrap semantics of explicit bootstrap flags."""
    return any(
        (
            bool(args.serial),
            bool(args.apk),
            args.tcpip_port != 5555,
            bool(args.skip_tcpip),
            bool(args.use_bundle),
            bool(args.skip_u2),
            bool(args.force_u2_install),
            bool(args.skip_atx),
            bool(args.skip_stf),
        )
    )


def main() -> None:
    _load_dotenv()
    args = _build_parser().parse_args()
    _resolve_relay_id(args)

    if args.relay_only:
        _run_relay(args)
        return

    if args.bootstrap_only:
        ok = _run_bootstrap(args)
        sys.exit(0 if ok else 1)

    # Default: make relay/video available first. The farm control plane performs
    # idempotent device bootstrap after registration, on its maintenance lane,
    # so slow U2/STF repair never blocks scrcpy startup.
    bootstrap_first = args.startup_mode == "legacy"
    if args.startup_mode == "relay-first" and _bootstrap_options_requested(args):
        bootstrap_first = True
        print(
            "[agent-boot] explicit bootstrap option detected; "
            "preserving bootstrap-before-relay behavior",
            file=sys.stderr,
        )
    if bootstrap_first:
        _run_bootstrap(args)
    _run_relay(args)


if __name__ == "__main__":
    main()
