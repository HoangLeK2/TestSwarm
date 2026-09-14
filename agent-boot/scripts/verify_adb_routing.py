#!/usr/bin/env python3
"""Check serial → ADB server routing against the ADB servers that are really running.

Read-only. It runs `adb devices -l`, `adb shell true` and `adb forward --list`,
resolves routes through the production code path, and reports where each command
actually landed. It does not install, push, tap, reboot, start scrcpy, or start
or kill an ADB server.

    ADB_SERVER_SOCKETS="tcp:127.0.0.1:5037,tcp:127.0.0.1:5038" \
        uv run scripts/verify_adb_routing.py

Add --u2 to also open a real uiautomator2 session per phone. That starts the
uiautomator server on the device, so it is opt-in.

Exit code is 0 only when every check passes.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from relay import adb as adb_mod  # noqa: E402
from relay.adb_routes import AdbEndpoint  # noqa: E402

OK = "PASS"
BAD = "FAIL"
SKIP = "SKIP"

_failures: list[str] = []
_skips: list[str] = []


def report(status: str, check: str, detail: str = "") -> None:
    print(f"  [{status}] {check}" + (f" — {detail}" if detail else ""))
    if status == BAD:
        _failures.append(f"{check}: {detail}")
    elif status == SKIP:
        _skips.append(f"{check}: {detail}")


def section(title: str) -> None:
    print(f"\n{title}\n" + "─" * len(title))


def parse_devices_l(out: str) -> dict[str, dict[str, str]]:
    """serial → {state, usb, transport_id, model, ...} from `adb devices -l`."""
    devices: dict[str, dict[str, str]] = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        info = {"state": state}
        for token in parts[2:]:
            if ":" in token:
                key, _, value = token.partition(":")
                info[key] = value
        devices[serial] = info
    return devices


# ── 1. what is actually listening ────────────────────────────────────────────


def survey(endpoints: list[AdbEndpoint]) -> dict[AdbEndpoint, dict[str, dict[str, str]]]:
    section("1. ADB servers")
    per_endpoint: dict[AdbEndpoint, dict[str, dict[str, str]]] = {}
    for endpoint in endpoints:
        out, rc = adb_mod._run_raw([*endpoint.flags, "devices", "-l"], timeout=10)
        if rc != 0:
            lines = [ln for ln in (out or "").strip().splitlines() if ln.strip()]
            report(BAD, f"{endpoint} reachable", lines[-1][:160] if lines else "no output")
            per_endpoint[endpoint] = {}
            continue
        devices = parse_devices_l(out)
        usable = {s: i for s, i in devices.items() if i["state"] == "device"}
        unusable = {s: i["state"] for s, i in devices.items() if i["state"] != "device"}
        report(OK, f"{endpoint} reachable", f"{len(usable)} device, {len(unusable)} other")
        for serial, info in sorted(usable.items()):
            usb = info.get("usb", "-")
            tid = info.get("transport_id", "-")
            print(f"         {serial:<24} usb={usb:<10} transport_id={tid}")
        for serial, state in sorted(unusable.items()):
            print(f"         {serial:<24} state={state}")
        per_endpoint[endpoint] = usable
    return per_endpoint


# ── 2. ownership ─────────────────────────────────────────────────────────────


def check_ownership(
    per_endpoint: dict[AdbEndpoint, dict[str, dict[str, str]]],
) -> dict[str, AdbEndpoint]:
    section("2. Device ownership")
    owners: dict[str, list[AdbEndpoint]] = defaultdict(list)
    for endpoint, devices in per_endpoint.items():
        for serial in devices:
            owners[serial].append(endpoint)

    if not owners:
        report(SKIP, "devices present", "no phone is usable on any endpoint")
        return {}

    unique: dict[str, AdbEndpoint] = {}
    for serial, endpoints in sorted(owners.items()):
        if len(endpoints) == 1:
            unique[serial] = endpoints[0]
        else:
            report(
                BAD,
                f"{serial} owned by exactly one server",
                "claimed by " + ", ".join(str(e) for e in endpoints),
            )
    if unique:
        report(OK, "no duplicate ownership", f"{len(unique)} phone(s) each on one server")

    used = {str(e) for e in owners_flat(owners)}
    for endpoint in per_endpoint:
        if str(endpoint) not in used:
            report(
                SKIP,
                f"{endpoint} carries devices",
                "configured but owns no phone — routing to it is never exercised",
            )
    return unique


def owners_flat(owners: dict[str, list[AdbEndpoint]]) -> list[AdbEndpoint]:
    return [e for endpoints in owners.values() for e in endpoints]


# ── 3. routing ───────────────────────────────────────────────────────────────


def check_routing(expected: dict[str, AdbEndpoint]) -> None:
    section("3. serial → endpoint routing")
    adb_mod.route_table.clear()
    adb_mod._list_serials()  # startup scan, same call the agent makes

    for serial, endpoint in sorted(expected.items()):
        route = adb_mod.route_table.get(serial)
        if route is None:
            report(BAD, f"{serial} has a route", "route table empty for this serial")
        elif route.endpoint != endpoint:
            report(BAD, f"{serial} routed to its owner", f"routed {route.endpoint}, owned by {endpoint}")
        else:
            report(OK, f"{serial} routed to its owner", str(endpoint))


def check_dispatch(expected: dict[str, AdbEndpoint]) -> None:
    section("4. commands land on the routed server")
    for serial, endpoint in sorted(expected.items()):
        argv = adb_mod._adb_command("shell", "true", serial=serial)
        landed = endpoint.host in argv and str(endpoint.port) in argv
        if not landed:
            report(BAD, f"{serial} command targets {endpoint}", " ".join(argv))
            continue
        started = time.perf_counter()
        out, rc = adb_mod._adb_shell(serial, "true", timeout=15)
        ms = (time.perf_counter() - started) * 1000
        if rc != 0:
            report(BAD, f"{serial} adb shell true", f"rc={rc} {out.strip()[:80]}")
        else:
            report(OK, f"{serial} adb shell true via {endpoint}", f"{ms:.0f}ms")


def check_no_rescan(expected: dict[str, AdbEndpoint]) -> None:
    section("5. steady state does not scan")
    adb_mod.route_table.stats(reset=True)
    lookups = 0
    for serial in expected:
        for _ in range(5):
            # _ensure_route is the hot path; route_table.get is what u2 and the
            # forward host use. In single-endpoint mode the former is a
            # deliberate no-op, so count the latter too or this check is vacuous.
            adb_mod._ensure_route(serial)
            adb_mod.route_table.get(serial)
            lookups += 1
    stats = adb_mod.route_table.stats()
    scans = stats.get("discovery_scans", 0)
    hits = stats.get("hit", 0)
    if scans:
        report(BAD, "cached lookups scan no endpoint", f"{scans} discovery scan(s)")
    elif hits < lookups:
        report(BAD, "every lookup hit the cache", f"{hits} hits for {lookups} lookups")
    else:
        report(OK, "cached lookups scan no endpoint", f"{hits} cache hits, 0 scans")


def check_unknown_serial() -> None:
    section("6. unknown serial")
    adb_mod.route_table.stats(reset=True)
    route = adb_mod._ensure_route("NO-SUCH-DEVICE-0000")
    stats = adb_mod.route_table.stats()
    if route is not None:
        report(BAD, "unknown serial gets no route", f"routed to {route.endpoint}")
        return
    scans = stats.get("discovery_scans", 0)
    endpoints = len(adb_mod.configured_adb_endpoints())
    if scans > 1:
        report(BAD, "unknown serial scans once", f"{scans} scans for one serial")
    elif endpoints > 1:
        report(OK, "unknown serial gets no route", f"1 bounded scan over {endpoints} endpoints")
    else:
        report(SKIP, "unknown serial scan is bounded", "single endpoint: no discovery path")


# ── 7. uiautomator2 ──────────────────────────────────────────────────────────


def check_u2(expected: dict[str, AdbEndpoint], *, connect: bool) -> None:
    section("7. uiautomator2 endpoint")
    singleton_host = os.environ.get("ANDROID_ADB_SERVER_HOST", "127.0.0.1")
    singleton_port = os.environ.get("ANDROID_ADB_SERVER_PORT", "5037")
    print(f"  adbutils singleton (u2 fallback): {singleton_host}:{singleton_port}")

    for serial, endpoint in sorted(expected.items()):
        device = adb_mod.adb_device_for_u2(serial)
        if device is None:
            report(BAD, f"{serial} u2 device is routed", "no route — u2 would use the singleton")
            continue
        client = device._client
        host = client._BaseClient__host
        port = int(client._BaseClient__port)
        if (host, port) != (endpoint.host, endpoint.port):
            report(BAD, f"{serial} u2 device on {endpoint}", f"bound to {host}:{port}")
            continue
        detail = f"{host}:{port}"
        if (host, str(port)) != (singleton_host, singleton_port):
            detail += "  (differs from the singleton — this is the bug being guarded)"
        report(OK, f"{serial} u2 device on its own server", detail)

        if not connect:
            continue
        try:
            import uiautomator2 as u2

            started = time.perf_counter()
            session = u2.connect(device)
            info = session.device_info
            ms = (time.perf_counter() - started) * 1000
            report(OK, f"{serial} u2.connect via route", f"{info.get('model')} in {ms:.0f}ms")
        except Exception as exc:
            report(BAD, f"{serial} u2.connect via route", f"{type(exc).__name__}: {exc}")


# ── 8. forwards ──────────────────────────────────────────────────────────────


def check_forwards(expected: dict[str, AdbEndpoint]) -> None:
    section("8. atx forwards across endpoints")
    discovered = adb_mod._list_atx_forwards_all_endpoints()
    if discovered is None:
        report(BAD, "forward --list answered", "no endpoint answered")
        return
    report(OK, "forward --list answered", f"{len(discovered)} tcp:7912 forward(s)")
    by_endpoint: dict[str, int] = defaultdict(int)
    for serial in discovered:
        endpoint = expected.get(serial)
        by_endpoint[str(endpoint) if endpoint else "unowned"] += 1
    for endpoint, count in sorted(by_endpoint.items()):
        print(f"         {endpoint:<24} {count} forward(s)")
    missing = [s for s in expected if s not in discovered]
    if missing:
        report(SKIP, "every phone has a forward", f"{len(missing)} without one (created on demand)")


# ── 9. scrcpy (media-adapter, Go) ────────────────────────────────────────────


def check_scrcpy(expected: dict[str, AdbEndpoint]) -> None:
    section("9. scrcpy route (media-adapter)")
    report(
        SKIP,
        "scrcpy endpoint",
        "runs in the media-adapter container; verify with: "
        "docker logs media-adapter | grep -E 'adb .*-P [0-9]+ -s'",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--u2",
        action="store_true",
        help="also open a real uiautomator2 session (starts the u2 server on the device)",
    )
    args = parser.parse_args()

    endpoints = adb_mod.configured_adb_endpoints()
    print("ADB_SERVER_SOCKETS =", os.environ.get("ADB_SERVER_SOCKETS", "(unset)"))
    print("configured endpoints =", ", ".join(str(e) for e in endpoints) or "(none)")
    if not endpoints:
        print("\nNothing to verify: no ADB server configured. Set ADB_SERVER_SOCKETS.")
        return 2

    per_endpoint = survey(endpoints)
    expected = check_ownership(per_endpoint)
    if expected:
        check_routing(expected)
        check_dispatch(expected)
        check_no_rescan(expected)
    check_unknown_serial()
    if expected:
        check_u2(expected, connect=args.u2)
        check_forwards(expected)
    check_scrcpy(expected)

    section("Summary")
    stats = adb_mod.route_table.stats()
    print(f"  route stats: {stats}")
    if stats.get("conflicts"):
        print(f"  !! {stats['conflicts']} route conflict(s) — two servers claimed one phone")
    for skip in _skips:
        print(f"  [SKIP] {skip}")
    if _failures:
        print(f"\n  {len(_failures)} FAILURE(S):")
        for failure in _failures:
            print(f"    - {failure}")
        return 1
    print("\n  all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
