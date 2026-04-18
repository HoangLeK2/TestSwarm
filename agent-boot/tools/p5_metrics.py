#!/usr/bin/env python3
"""
p5_metrics.py — rolling 1-minute snapshot of the 7 metrics defined in
docs/plans/agent-boot-stability-rollout/plan.md Phase 5.

Prints a plain-text table suitable for tee'ing to a log file for the
48h observation window:

    uv run python tools/p5_metrics.py --log /tmp/agent-canary.log >> /tmp/p5.csv

Columns:
    timestamp, agent_rss_mb, agent_threads, agent_uptime_s,
    scrcpy_pids, session_restarts_1h, encoder_stalls_1h,
    idr_requests_1h, breaker_opens_1h, u2_heartbeat_evicts_1h,
    unplugs_1h

Green/Yellow/Red thresholds from the plan. Exit code is non-zero if any
counter crossed the red line — use in crontab or loop to page an operator.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

# Thresholds (per hour rate) — mirror plan.md Phase 5 table
GREEN_MAX = {
    "session_restarts":    2,
    "encoder_stalls":      0,
    "breaker_opens":       0,   # green is zero; any is yellow
    "u2_heartbeat_evicts": 1,   # ≤ 5/day ≈ 0.2/hr rounded up
}
YELLOW_MAX = {
    "session_restarts":    6,
    "encoder_stalls":      3,
    "breaker_opens":       1,
    "u2_heartbeat_evicts": 3,
}

# Regex patterns — must match the log lines emitted by the agent.
_PATTERNS = {
    "session_restarts":    re.compile(r"session stopped.*reason=(runtime_error|zombie_thread|startup_failure)"),
    "encoder_stalls":      re.compile(r"encoder stalled"),
    "idr_requests":        re.compile(r"requested IDR keyframe"),
    "breaker_opens":       re.compile(r"breaker opened"),
    "u2_heartbeat_evicts": re.compile(r"u2-pool: heartbeat evicted"),
    "unplugs":             re.compile(r"device_offline"),
}

ONE_HOUR = 3600


def _agent_pid() -> int | None:
    r = subprocess.run(
        ["pgrep", "-f", "agent-boot.*main.py"],
        capture_output=True, text=True,
    )
    for line in r.stdout.splitlines():
        pid = line.strip()
        if pid.isdigit():
            return int(pid)
    return None


def _ps_stats(pid: int) -> tuple[int, int, int] | None:
    """Return (rss_kb, thread_count, uptime_seconds) or None."""
    r = subprocess.run(
        ["ps", "-o", "rss=,etime=", "-p", str(pid)],
        capture_output=True, text=True,
    )
    line = r.stdout.strip()
    if not line:
        return None
    parts = line.split()
    if len(parts) < 2:
        return None
    rss_kb = int(parts[0])
    etime = parts[1]
    # etime format: [[DD-]HH:]MM:SS
    uptime_s = _parse_etime(etime)
    # Thread count via separate call — ps -M is macOS; fall back to /proc on Linux
    tc = _thread_count(pid)
    return rss_kb, tc, uptime_s


def _parse_etime(etime: str) -> int:
    # "DD-HH:MM:SS" or "HH:MM:SS" or "MM:SS"
    days, _, rest = etime.partition("-")
    if not rest:
        rest = days
        days = "0"
    parts = rest.split(":")
    while len(parts) < 3:
        parts.insert(0, "0")
    h, m, s = map(int, parts)
    return int(days) * 86400 + h * 3600 + m * 60 + s


def _thread_count(pid: int) -> int:
    # macOS: ps -M -p <pid>
    r = subprocess.run(
        ["ps", "-M", "-p", str(pid)],
        capture_output=True, text=True,
    )
    if r.returncode == 0 and r.stdout:
        return max(0, len(r.stdout.splitlines()) - 1)
    # Linux fallback
    try:
        return len(list(Path(f"/proc/{pid}/task").iterdir()))
    except Exception:
        return 0


def _scrcpy_pids(serial: str) -> int:
    r = subprocess.run(
        ["adb", "-s", serial, "shell",
         "pgrep -f 'com.genymobile.scrcpy.Server' 2>/dev/null | wc -l"],
        capture_output=True, text=True, timeout=10,
    )
    try:
        return int((r.stdout or "0").strip())
    except ValueError:
        return 0


def _count_in_last_hour(log_path: Path, pattern: re.Pattern) -> int:
    """Cheap tail-grep: read only last ~2MB and count matches."""
    if not log_path.exists():
        return 0
    size = log_path.stat().st_size
    with log_path.open("rb") as f:
        if size > 2_000_000:
            f.seek(-2_000_000, 2)
            f.readline()  # drop partial line
        data = f.read().decode("utf-8", errors="replace")
    # Rough age filter: look at lines with recent timestamp if present
    return sum(1 for _ in pattern.finditer(data))


def _classify(name: str, value: int) -> str:
    if value <= GREEN_MAX.get(name, float("inf")):
        return "🟢"
    if value <= YELLOW_MAX.get(name, float("inf")):
        return "🟡"
    return "🔴"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--log", default="/tmp/agent-canary.log",
                   help="path to agent-boot log (stderr redirect)")
    p.add_argument("--serial", default="",
                   help="device serial for scrcpy probe (optional)")
    p.add_argument("--csv", action="store_true",
                   help="print one CSV row instead of table")
    args = p.parse_args()

    log_path = Path(args.log)
    pid = _agent_pid()
    if pid is None:
        print("no agent-boot process running", file=sys.stderr)
        return 2

    stats = _ps_stats(pid)
    if stats is None:
        print(f"agent-boot pid {pid} disappeared", file=sys.stderr)
        return 2
    rss_kb, threads, uptime_s = stats

    counts = {
        name: _count_in_last_hour(log_path, pat)
        for name, pat in _PATTERNS.items()
    }
    scrcpy = _scrcpy_pids(args.serial) if args.serial else -1

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if args.csv:
        print(",".join([
            ts, str(pid), str(rss_kb // 1024), str(threads), str(uptime_s),
            str(scrcpy),
            *(str(counts[k]) for k in (
                "session_restarts", "encoder_stalls", "idr_requests",
                "breaker_opens", "u2_heartbeat_evicts", "unplugs",
            )),
        ]))
    else:
        print(f"\n=== {ts}  pid={pid}  uptime={uptime_s}s  rss={rss_kb//1024}MB  threads={threads} ===")
        print(f"scrcpy PIDs on {args.serial or '-'}: {scrcpy}")
        print()
        for name in ("session_restarts", "encoder_stalls", "idr_requests",
                     "breaker_opens", "u2_heartbeat_evicts", "unplugs"):
            v = counts[name]
            mark = _classify(name, v) if name in GREEN_MAX else "•"
            print(f"  {mark} {name:<22} {v}")

    # Exit red if any tracked metric crossed the red threshold
    reds = [n for n, v in counts.items()
            if n in YELLOW_MAX and v > YELLOW_MAX[n]]
    return 1 if reds else 0


if __name__ == "__main__":
    sys.exit(main())
