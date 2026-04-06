"""
agent-boot/main.py — Entry point.

Modes:
  uv run main.py                     # bootstrap all devices + start relay daemon
  uv run main.py --relay-only        # skip bootstrap, just run relay
  uv run main.py --bootstrap-only    # setup devices, then exit
  uv run main.py --serial <serial>   # target a specific device

Config (via .env or environment):
  RELAY_SERVER    WebSocket server URL  (default: ws://localhost:8080/relay-agent)
  RELAY_API_KEY   API key for server auth

Quick start:
  cp .env.example .env   # fill in RELAY_SERVER + RELAY_API_KEY
  uv run main.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys
import time
import uuid


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

    # Device selection
    parser.add_argument("--serial", "-s", metavar="SERIAL",
                        help="Target a specific device (default: all connected)")

    # Bootstrap options
    parser.add_argument("--apk", metavar="PATH",
                        help="Path to STFService.apk")
    parser.add_argument("--tcpip-port", type=int, default=5555, metavar="PORT",
                        help="Port for adb tcpip (default: 5555)")
    parser.add_argument("--skip-tcpip", action="store_true")
    parser.add_argument("--skip-u2", action="store_true",
                        help="Skip uiautomator2 APKs + atx-agent")
    parser.add_argument("--skip-atx", action="store_true",
                        help="Skip atx-agent push (APKs still installed)")
    parser.add_argument("--skip-stf", action="store_true",
                        help="Skip STFService install + permissions")

    # Relay options
    parser.add_argument("--relay-server", metavar="URL",
                        default=_env("RELAY_SERVER", "ws://localhost:8081/relay-agent"),
                        help="WebSocket server URL (default: $RELAY_SERVER or ws://localhost:8080/relay-agent)")
    parser.add_argument("--relay-api-key", metavar="KEY",
                        default=_env("RELAY_API_KEY", ""),
                        help="API key (default: $RELAY_API_KEY)")
    parser.add_argument("--relay-id", metavar="ID",
                        default=f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}",
                        help="Stable relay ID (default: hostname+uuid)")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")

    return parser


# ── Wait for device ───────────────────────────────────────────────────────────

def _wait_for_devices(timeout: int = 120) -> bool:
    """
    Start mDNS discovery then poll `adb devices` until at least one device
    appears or timeout is reached. Returns True if device found.
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
            "Waiting for device (USB or Wireless Debugging mDNS)…", total=None
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
        skip_tcpip=args.skip_tcpip,
        tcpip_port=args.tcpip_port,
        skip_u2=args.skip_u2,
        skip_atx=args.skip_atx,
        skip_stf=args.skip_stf,
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

    print(f"\n[agent-boot] Starting relay daemon", file=sys.stderr)
    print(f"  Server : {args.relay_server}", file=sys.stderr)
    print(f"  Relay ID: {args.relay_id}", file=sys.stderr)
    print("  Ctrl+C to stop.\n", file=sys.stderr)

    agent = RelayAgent(
        server_url=args.relay_server,
        api_key=args.relay_api_key or None,
        relay_id=args.relay_id,
    )
    asyncio.run(agent.run())


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    _load_dotenv()
    args = _build_parser().parse_args()

    if args.relay_only:
        _run_relay(args)
        return

    if args.bootstrap_only:
        ok = _run_bootstrap(args)
        sys.exit(0 if ok else 1)

    # Default: bootstrap → relay
    _run_bootstrap(args)
    _run_relay(args)


if __name__ == "__main__":
    main()
