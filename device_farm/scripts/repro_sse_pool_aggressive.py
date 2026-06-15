#!/usr/bin/env python3
"""Aggressive SSE + API stress test against a running Device Farm server."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

import httpx

API_TIMEOUT = 10.0


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
        idx = min(len(xs) - 1, int(len(xs) * 0.95))
        return xs[idx]

    def summary(self) -> str:
        return (
            f"ok={self.ok} fail={self.fail} timeout={self.timeout} "
            f"p95={self.p95_ms:.0f}ms statuses={self.statuses[:20]}"
            + ("..." if len(self.statuses) > 20 else "")
        )


def _api_headers(token: str, org_id: str | None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if org_id:
        h["X-Organization-Id"] = org_id
    return h


def _sse_headers(token: str, org_id: str | None) -> dict[str, str]:
    h = {**_api_headers(token, org_id), "Accept": "text/event-stream"}
    return h


async def _probe_one(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    stats: ProbeStats,
) -> None:
    started = time.perf_counter()
    try:
        resp = await client.get(url, headers=headers, timeout=API_TIMEOUT)
        ms = (time.perf_counter() - started) * 1000.0
        stats.add(resp.status_code, ms)
    except Exception:
        ms = (time.perf_counter() - started) * 1000.0
        stats.add(0, ms)


async def _probe_barrage(
    base: str,
    token: str,
    org_id: str | None,
    *,
    rounds: int,
    concurrency: int,
) -> dict[str, ProbeStats]:
    paths = [
        "/api/devices",
        "/api/executions?limit=10",
        "/api/campaigns?limit=10",
        "/api/content?limit=10",
        "/api/server/status",
    ]
    results = {p: ProbeStats() for p in paths}
    headers = _api_headers(token, org_id)

    async with httpx.AsyncClient() as client:
        for _ in range(rounds):
            tasks = []
            for path in paths:
                for _ in range(concurrency):
                    tasks.append(
                        asyncio.create_task(
                            _probe_one(client, f"{base}{path}", headers, results[path])
                        )
                    )
            await asyncio.gather(*tasks)
    return results


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


async def _f5_wave(
    url: str,
    headers: dict[str, str],
    *,
    waves: int,
    per_wave: int,
    interval_sec: float,
) -> None:
    """Simulate rapid F5: open many short-lived SSE connections."""
    for _ in range(waves):
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(_hold_sse(url, headers, hold_seconds=3.0, stop=stop))
            for _ in range(per_wave)
        ]
        await asyncio.sleep(interval_sec)
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    token = args.token.strip()
    org_id = (args.org_id or "").strip() or None
    execution_id = args.execution_id.strip()
    stream_url = f"{base}/api/executions/{execution_id}/events/stream"
    sse_headers = _sse_headers(token, org_id)

    print("=== AGGRESSIVE SSE POOL STRESS ===")
    print(f"base={base} execution={execution_id}")
    print(f"phase1_streams={args.phase1_streams} phase2_f5={args.f5_waves}x{args.f5_per_wave} phase3_streams={args.phase3_streams}")

    # Baseline
    baseline = await _probe_barrage(base, token, org_id, rounds=1, concurrency=3)
    print("\n--- BASELINE ---")
    for path, st in baseline.items():
        print(f"  {path}: {st.summary()}")

    stop = asyncio.Event()
    stream_tasks: list[asyncio.Task[None]] = []

    # Phase 1: many long-held SSE
    print(f"\n--- PHASE 1: {args.phase1_streams} SSE x {args.phase1_hold}s ---")
    for _ in range(args.phase1_streams):
        stream_tasks.append(
            asyncio.create_task(
                _hold_sse(stream_url, sse_headers, args.phase1_hold, stop)
            )
        )
    await asyncio.sleep(3.0)
    p1 = await _probe_barrage(base, token, org_id, rounds=args.probe_rounds, concurrency=args.probe_concurrency)
    for path, st in p1.items():
        print(f"  {path}: {st.summary()}")
    _, status1, _ = await _get_status(base, token, org_id)
    print(f"  safe_mode={status1.get('safe_mode') if isinstance(status1, dict) else status1}")

    # Phase 2: F5 spam while some SSE still held
    print(f"\n--- PHASE 2: F5 spam {args.f5_waves} waves x {args.f5_per_wave} streams ---")
    await _f5_wave(
        stream_url,
        sse_headers,
        waves=args.f5_waves,
        per_wave=args.f5_per_wave,
        interval_sec=args.f5_interval,
    )
    p2 = await _probe_barrage(base, token, org_id, rounds=args.probe_rounds, concurrency=args.probe_concurrency)
    for path, st in p2.items():
        print(f"  {path}: {st.summary()}")
    _, status2, _ = await _get_status(base, token, org_id)
    print(f"  safe_mode={status2.get('safe_mode') if isinstance(status2, dict) else status2}")

    # Phase 3: even more SSE on top
    print(f"\n--- PHASE 3: +{args.phase3_streams} more SSE x {args.phase3_hold}s ---")
    for _ in range(args.phase3_streams):
        stream_tasks.append(
            asyncio.create_task(
                _hold_sse(stream_url, sse_headers, args.phase3_hold, stop)
            )
        )
    await asyncio.sleep(3.0)
    p3 = await _probe_barrage(base, token, org_id, rounds=args.probe_rounds, concurrency=args.probe_concurrency)
    total_fail = sum(st.fail for st in p3.values())
    total_ok = sum(st.ok for st in p3.values())
    for path, st in p3.items():
        print(f"  {path}: {st.summary()}")
    _, status3, _ = await _get_status(base, token, org_id)
    safe3 = bool(isinstance(status3, dict) and status3.get("safe_mode"))
    print(f"  safe_mode={safe3}")

    reproduced = safe3 or total_fail >= max(5, total_ok // 4)
    print(f"\nverdict_under_stress={'REPRODUCED' if reproduced else 'HELD'}")

    # Teardown
    print("\n--- TEARDOWN: closing all SSE ---")
    stop.set()
    for t in stream_tasks:
        t.cancel()
    await asyncio.gather(*stream_tasks, return_exceptions=True)
    await asyncio.sleep(5.0)

    recovery = await _probe_barrage(base, token, org_id, rounds=2, concurrency=5)
    print("--- RECOVERY ---")
    rec_fail = 0
    for path, st in recovery.items():
        print(f"  {path}: {st.summary()}")
        rec_fail += st.fail
    _, status_after, _ = await _get_status(base, token, org_id)
    safe_after = bool(isinstance(status_after, dict) and status_after.get("safe_mode"))
    recovered = rec_fail == 0 and not safe_after
    print(f"  safe_mode={safe_after}")
    print(f"verdict_recovery={'RECOVERED' if recovered else 'STILL_DEGRADED'}")

    return 0 if recovered else 2


async def _get_status(base: str, token: str, org_id: str | None):
    async with httpx.AsyncClient() as client:
        started = time.perf_counter()
        try:
            resp = await client.get(
                f"{base}/api/server/status",
                headers=_api_headers(token, org_id),
                timeout=API_TIMEOUT,
            )
            ms = (time.perf_counter() - started) * 1000.0
            return resp.status_code, resp.json(), ms
        except Exception as exc:
            ms = (time.perf_counter() - started) * 1000.0
            return 0, str(exc), ms


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.environ.get("DEVICE_FARM_BASE_URL", "http://localhost:8081"))
    p.add_argument("--token", default=os.environ.get("DEVICE_FARM_TOKEN", ""))
    p.add_argument("--org-id", default=os.environ.get("DEVICE_FARM_ORG_ID", ""))
    p.add_argument("--execution-id", default=os.environ.get("DEVICE_FARM_EXECUTION_ID", ""))
    p.add_argument("--phase1-streams", type=int, default=80)
    p.add_argument("--phase1-hold", type=float, default=45.0)
    p.add_argument("--f5-waves", type=int, default=15)
    p.add_argument("--f5-per-wave", type=int, default=10)
    p.add_argument("--f5-interval", type=float, default=0.3)
    p.add_argument("--phase3-streams", type=int, default=50)
    p.add_argument("--phase3-hold", type=float, default=30.0)
    p.add_argument("--probe-rounds", type=int, default=3)
    p.add_argument("--probe-concurrency", type=int, default=8)
    args = p.parse_args()
    if not args.token or not args.execution_id:
        print("need --token and --execution-id", file=sys.stderr)
        sys.exit(2)
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
