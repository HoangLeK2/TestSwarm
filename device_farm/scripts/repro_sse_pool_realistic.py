#!/usr/bin/env python3
"""Realistic pool stress: MJPEG screen streams + campaign monitor SSE + dashboard polling.

Simulates production load when phones are on the farm dashboard and user spams F5
on Campaign Monitor — without requiring live relay/USB devices (uses registered
serials; MJPEG loop runs even when device is offline/dead).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

import httpx

API_TIMEOUT = 12.0


@dataclass
class ProbeStats:
    ok: int = 0
    fail: int = 0
    timeout: int = 0
    statuses: list[int] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)

    def add(self, status: int, ms: float) -> None:
        self.statuses.append(status)
        self.latencies_ms.append(ms)
        if status == 200:
            self.ok += 1
        elif status == 0:
            self.timeout += 1
            self.fail += 1
        else:
            self.fail += 1

    @property
    def p95_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        xs = sorted(self.latencies_ms)
        return xs[min(len(xs) - 1, int(len(xs) * 0.95))]

    def summary(self) -> str:
        return (
            f"ok={self.ok} fail={self.fail} timeout={self.timeout} "
            f"p95={self.p95_ms:.0f}ms"
        )


def _headers(token: str, org_id: str | None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if org_id:
        h["X-Organization-Id"] = org_id
    return h


def _sse_headers(token: str, org_id: str | None) -> dict[str, str]:
    return {**_headers(token, org_id), "Accept": "text/event-stream"}


async def login(base: str, email: str, password: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base}/api/auth/login",
            json={"email": email, "password": password},
            timeout=API_TIMEOUT,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError(f"login failed: {resp.text}")
        return token


async def discover_context(
    base: str, token: str, org_id: str | None
) -> tuple[list[str], str | None]:
    headers = _headers(token, org_id)
    serials: list[str] = []
    execution_id: str | None = None
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{base}/api/devices", headers=headers, params={"limit": 100}, timeout=API_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            items = data if isinstance(data, list) else data.get("items", [])
            for item in items:
                s = item.get("device_serial") or item.get("adb_serial")
                if s:
                    serials.append(str(s))

        r2 = await client.get(
            f"{base}/api/executions",
            headers=headers,
            params={"limit": 5},
            timeout=API_TIMEOUT,
        )
        if r2.status_code == 200:
            data2 = r2.json()
            items2 = data2 if isinstance(data2, list) else data2.get("items", [])
            if items2:
                execution_id = str(items2[0]["id"])

        if not execution_id:
            r3 = await client.post(
                f"{base}/api/executions",
                headers=headers,
                json={"run_type": "manual", "device_ids": []},
                timeout=API_TIMEOUT,
            )
            if r3.status_code in (200, 201):
                execution_id = str(r3.json().get("id") or "")

    return serials, execution_id or None


async def _hold_mjpeg(
    base: str,
    serial: str,
    token: str,
    *,
    fps: float,
    hold_seconds: float,
    stop: asyncio.Event,
) -> None:
    url = f"{base}/stream/{serial}?fps={fps}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=headers, timeout=None) as resp:
                if resp.status_code != 200:
                    return
                started = time.monotonic()
                async for _chunk in resp.aiter_bytes():
                    if stop.is_set():
                        break
                    if time.monotonic() - started >= hold_seconds:
                        break
    except Exception:
        return


async def _hold_sse(
    url: str,
    headers: dict[str, str],
    hold_seconds: float,
    stop: asyncio.Event,
) -> None:
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url, headers=headers, timeout=None) as resp:
                if resp.status_code != 200:
                    return
                started = time.monotonic()
                async for _chunk in resp.aiter_bytes():
                    if stop.is_set():
                        break
                    if time.monotonic() - started >= hold_seconds:
                        break
    except Exception:
        return


async def _poll_dashboard(
    base: str,
    token: str,
    org_id: str | None,
    serials: list[str],
    *,
    duration_sec: float,
    interval_sec: float,
    stop: asyncio.Event,
) -> ProbeStats:
    stats = ProbeStats()
    headers = _headers(token, org_id)
    started = time.monotonic()
    async with httpx.AsyncClient() as client:
        while not stop.is_set() and (time.monotonic() - started) < duration_sec:
            paths = [
                "/api/devices/live",
                "/api/devices?limit=50",
                "/api/campaigns?limit=20",
            ]
            for serial in serials[:5]:
                paths.append(f"/screenshot-b64/{serial}")
            tasks = []
            for path in paths:
                tasks.append(_probe_one(client, f"{base}{path}", headers, stats))
            await asyncio.gather(*tasks)
            await asyncio.sleep(interval_sec)
    return stats


async def _probe_one(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    stats: ProbeStats,
) -> None:
    t0 = time.perf_counter()
    try:
        resp = await client.get(url, headers=headers, timeout=API_TIMEOUT)
        stats.add(resp.status_code, (time.perf_counter() - t0) * 1000)
    except Exception:
        stats.add(0, (time.perf_counter() - t0) * 1000)


async def _probe_barrage(
    base: str,
    token: str,
    org_id: str | None,
    *,
    concurrency: int,
) -> ProbeStats:
    stats = ProbeStats()
    headers = _headers(token, org_id)
    paths = [
        "/api/devices",
        "/api/devices/live",
        "/api/executions?limit=10",
        "/api/campaigns?limit=10",
        "/api/content?limit=10",
        "/api/server/status",
    ]
    async with httpx.AsyncClient() as client:
        tasks = []
        for path in paths:
            for _ in range(concurrency):
                tasks.append(_probe_one(client, f"{base}{path}", headers, stats))
        await asyncio.gather(*tasks)
    return stats


async def _zombie_sse(url: str, headers: dict[str, str]) -> None:
    """Hold SSE open until cancelled — simulates F5 tabs that never disconnect."""
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    return
                async for _chunk in resp.aiter_bytes():
                    pass
    except Exception:
        return


async def _f5_zombie_accumulate(
    url: str,
    headers: dict[str, str],
    *,
    waves: int,
    per_wave: int,
    interval: float,
) -> list[asyncio.Task[None]]:
    """F5 spam: each wave opens NEW streams without closing previous ones."""
    zombies: list[asyncio.Task[None]] = []
    for _ in range(waves):
        for _ in range(per_wave):
            zombies.append(asyncio.create_task(_zombie_sse(url, headers)))
        await asyncio.sleep(interval)
    return zombies


async def _probe_devices_loop(
    base: str,
    token: str,
    org_id: str | None,
    *,
    duration_sec: float,
    interval_sec: float,
) -> ProbeStats:
    stats = ProbeStats()
    headers = _headers(token, org_id)
    started = time.monotonic()
    async with httpx.AsyncClient() as client:
        while (time.monotonic() - started) < duration_sec:
            await _probe_one(client, f"{base}/api/devices", headers, stats)
            await asyncio.sleep(interval_sec)
    return stats


def _status_histogram(stats: ProbeStats) -> str:
    hist: dict[int, int] = {}
    for s in stats.statuses:
        hist[s] = hist.get(s, 0) + 1
    return str(dict(sorted(hist.items())))


async def _f5_sse(
    url: str,
    headers: dict[str, str],
    *,
    waves: int,
    per_wave: int,
    interval: float,
) -> None:
    for _ in range(waves):
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(_hold_sse(url, headers, hold_seconds=2.0, stop=stop))
            for _ in range(per_wave)
        ]
        await asyncio.sleep(interval)
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _get_safe_mode(base: str, token: str, org_id: str | None) -> bool:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(
                f"{base}/api/server/status",
                headers=_headers(token, org_id),
                timeout=API_TIMEOUT,
            )
            if r.status_code == 200:
                return bool(r.json().get("safe_mode"))
        except Exception:
            pass
    return False


async def run(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    token = await login(base, args.email, args.password)
    org_id = (args.org_id or "").strip() or None

    serials, execution_id = await discover_context(base, token, org_id)
    if not serials:
        print("WARN: no device serials in DB — screen simulation skipped")
    if not execution_id:
        print("ERROR: no execution_id", file=sys.stderr)
        return 2

    print("=== REALISTIC STRESS (screen + campaign monitor) ===")
    print(f"user={args.email} org={org_id}")
    print(f"devices={len(serials)} serials={serials}")
    print(f"execution_id={execution_id}")
    print(
        f"screen_streams={args.viewers_per_device}x{len(serials)} devices "
        f"sse={args.sse_streams} f5={args.f5_waves}x{args.f5_per_wave}"
    )

    stop = asyncio.Event()
    tasks: list[asyncio.Task] = []

    # Baseline
    base_stats = await _probe_barrage(base, token, org_id, concurrency=3)
    print(f"\nBASELINE: {base_stats.summary()} safe_mode={await _get_safe_mode(base, token, org_id)}")

    # Phase 1: MJPEG screen streams (like device farm tiles / control view)
    print(f"\nPHASE 1: MJPEG screen streams ({args.hold_seconds}s) ...")
    for serial in serials:
        for _ in range(args.viewers_per_device):
            tasks.append(
                asyncio.create_task(
                    _hold_mjpeg(
                        base,
                        serial,
                        token,
                        fps=args.mjpeg_fps,
                        hold_seconds=args.hold_seconds,
                        stop=stop,
                    )
                )
            )
    await asyncio.sleep(2.0)

    # Phase 2: dashboard polling while screens stream
    print("PHASE 2: dashboard polling ...")
    poll_task = asyncio.create_task(
        _poll_dashboard(
            base,
            token,
            org_id,
            serials,
            duration_sec=args.hold_seconds,
            interval_sec=args.poll_interval,
            stop=stop,
        )
    )
    await asyncio.sleep(3.0)
    mid_stats = await _probe_barrage(base, token, org_id, concurrency=args.probe_concurrency)
    safe_mid = await _get_safe_mode(base, token, org_id)
    print(f"  under_screen+poll: {mid_stats.summary()} safe_mode={safe_mid}")

    # Phase 3: campaign monitor SSE + F5
    sse_url = f"{base}/api/executions/{execution_id}/events/stream"
    sse_headers = _sse_headers(token, org_id)
    print(f"PHASE 3: {args.sse_streams} execution SSE + F5 spam ...")
    for _ in range(args.sse_streams):
        tasks.append(
            asyncio.create_task(
                _hold_sse(sse_url, sse_headers, args.hold_seconds, stop)
            )
        )
    await asyncio.sleep(1.0)
    await _f5_sse(
        sse_url,
        sse_headers,
        waves=args.f5_waves,
        per_wave=args.f5_per_wave,
        interval=args.f5_interval,
    )
    await asyncio.sleep(2.0)

    hot_stats = await _probe_barrage(base, token, org_id, concurrency=args.probe_concurrency)
    safe_hot = await _get_safe_mode(base, token, org_id)
    reproduced = safe_hot or hot_stats.fail >= max(3, hot_stats.ok // 3)
    print(f"  under_full_load: {hot_stats.summary()} safe_mode={safe_hot}")
    print(f"  verdict_stress={'REPRODUCED' if reproduced else 'HELD'}")

    # Phase 4: F5 zombie SSE — streams accumulate, NOT closed (production bug pattern)
    print(
        f"\nPHASE 4: F5 ZOMBIE SSE ({args.zombie_waves}x{args.zombie_per_wave} "
        f"accumulate, probe {args.zombie_probe_seconds}s) ..."
    )
    zombie_tasks = await _f5_zombie_accumulate(
        sse_url,
        sse_headers,
        waves=args.zombie_waves,
        per_wave=args.zombie_per_wave,
        interval=args.zombie_interval,
    )
    zombie_probe = await _probe_devices_loop(
        base,
        token,
        org_id,
        duration_sec=args.zombie_probe_seconds,
        interval_sec=1.0,
    )
    safe_zombie = await _get_safe_mode(base, token, org_id)
    zombie_reproduced = (
        safe_zombie
        or zombie_probe.fail >= max(5, zombie_probe.ok)
        or zombie_probe.timeout >= 3
    )
    print(f"  zombie_probe: {zombie_probe.summary()} hist={_status_histogram(zombie_probe)}")
    print(f"  safe_mode={safe_zombie} active_zombies={len(zombie_tasks)}")
    print(f"  verdict_zombie={'REPRODUCED' if zombie_reproduced else 'NOT_REPRODUCED'}")

    if args.skip_teardown:
        print("\nSKIP_TEARDOWN: zombies left open — manual restart required to recover")
        return 2 if zombie_reproduced else 0

    # Teardown
    print("\nTEARDOWN (close zombies + streams) ...")
    for t in zombie_tasks:
        t.cancel()
    await asyncio.gather(*zombie_tasks, return_exceptions=True)
    stop.set()
    poll_task.cancel()
    for t in tasks:
        t.cancel()
    await asyncio.gather(poll_task, *tasks, return_exceptions=True)
    await asyncio.sleep(5.0)

    rec_stats = await _probe_barrage(base, token, org_id, concurrency=5)
    safe_after = await _get_safe_mode(base, token, org_id)
    recovered = rec_stats.fail == 0 and not safe_after
    print(f"RECOVERY: {rec_stats.summary()} safe_mode={safe_after}")
    print(f"verdict_recovery={'RECOVERED' if recovered else 'STILL_DEGRADED'}")
    return 0 if recovered else 2


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=os.environ.get("DEVICE_FARM_BASE_URL", "http://localhost:8081"))
    p.add_argument("--email", default=os.environ.get("REPRO_EMAIL", "dev@gmail.com"))
    p.add_argument("--password", default=os.environ.get("REPRO_PASSWORD", "11111111"))
    p.add_argument("--org-id", default=os.environ.get("DEVICE_FARM_ORG_ID", ""))
    p.add_argument("--viewers-per-device", type=int, default=8, help="MJPEG streams per phone serial")
    p.add_argument("--mjpeg-fps", type=float, default=10.0)
    p.add_argument("--hold-seconds", type=float, default=45.0)
    p.add_argument("--poll-interval", type=float, default=3.0)
    p.add_argument("--sse-streams", type=int, default=40)
    p.add_argument("--f5-waves", type=int, default=15)
    p.add_argument("--f5-per-wave", type=int, default=12)
    p.add_argument("--f5-interval", type=float, default=0.25)
    p.add_argument("--probe-concurrency", type=int, default=10)
    p.add_argument("--zombie-waves", type=int, default=25, help="F5 waves that accumulate SSE zombies")
    p.add_argument("--zombie-per-wave", type=int, default=8)
    p.add_argument("--zombie-interval", type=float, default=0.2)
    p.add_argument("--zombie-probe-seconds", type=float, default=30.0)
    p.add_argument(
        "--skip-teardown",
        action="store_true",
        help="Leave zombie SSE open (manual recovery test)",
    )
    raise SystemExit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
