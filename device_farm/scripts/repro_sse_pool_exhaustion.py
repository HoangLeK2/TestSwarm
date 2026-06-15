#!/usr/bin/env python3
"""Reproduce SSE-driven DB pool exhaustion against a running Device Farm server.

Usage:
    cd device_farm
    uv run python scripts/repro_sse_pool_exhaustion.py \\
        --base-url http://localhost:8081 \\
        --token "$ACCESS_TOKEN" \\
        --org-id "$ORG_ID" \\
        --execution-id "$EXECUTION_ID" \\
        --streams 35

Verdict:
    REPRODUCED  — business APIs fail while SSE streams are held open
    RECOVERED   — APIs work again after streams close (expected after pool-leak fix)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_STREAMS = 35
DEFAULT_HOLD_SECONDS = 60
DEFAULT_PROBE_COUNT = 10
API_TIMEOUT = 8.0


@dataclass
class ProbeResult:
    ok_count: int
    fail_count: int
    statuses: list[int]
    latencies_ms: list[float]


def _headers(token: str, org_id: str | None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    if org_id:
        h["X-Organization-Id"] = org_id
    return h


def _api_headers(token: str, org_id: str | None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {token}"}
    if org_id:
        h["X-Organization-Id"] = org_id
    return h


async def _get_json(
    client: httpx.AsyncClient, path: str, headers: dict[str, str]
) -> tuple[int, Any, float]:
    started = time.perf_counter()
    try:
        resp = await client.get(path, headers=headers, timeout=API_TIMEOUT)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body, elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return 0, str(exc), elapsed_ms


async def _probe_devices(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    org_id: str | None,
    count: int,
) -> ProbeResult:
    headers = _api_headers(token, org_id)
    ok = 0
    fail = 0
    statuses: list[int] = []
    latencies: list[float] = []
    for _ in range(count):
        status, _body, ms = await _get_json(client, f"{base_url}/api/devices", headers)
        statuses.append(status)
        latencies.append(ms)
        if status == 200:
            ok += 1
        else:
            fail += 1
    return ProbeResult(ok_count=ok, fail_count=fail, statuses=statuses, latencies_ms=latencies)


async def _hold_sse_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    hold_seconds: float,
    stop: asyncio.Event,
) -> None:
    try:
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


async def _pg_connection_count() -> int | None:
    url = (os.environ.get("DATABASE_URL") or os.environ.get("DEVICE_FARM_DATABASE_URL") or "").strip()
    if not url:
        return None
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    try:
        import asyncpg  # type: ignore
    except ImportError:
        return None
    try:
        conn = await asyncpg.connect(url, timeout=5)
        try:
            row = await conn.fetchrow(
                """
                SELECT count(*)::int AS cnt
                  FROM pg_stat_activity
                 WHERE datname = current_database()
                   AND pid <> pg_backend_pid()
                """
            )
            return int(row["cnt"]) if row else None
        finally:
            await conn.close()
    except Exception:
        return None


async def run(args: argparse.Namespace) -> int:
    base = args.base_url.rstrip("/")
    token = args.token.strip()
    org_id = (args.org_id or "").strip() or None
    execution_id = args.execution_id.strip()
    stream_url = f"{base}/api/executions/{execution_id}/events/stream"

    print(f"base_url={base}")
    print(f"execution_id={execution_id}")
    print(f"streams={args.streams} hold_seconds={args.hold_seconds}")

    stop = asyncio.Event()
    stream_tasks: list[asyncio.Task[None]] = []

    async with httpx.AsyncClient() as client:
        ready_status, ready_body, ready_ms = await _get_json(
            client, f"{base}/health/ready", {}
        )
        status_status, status_body, status_ms = await _get_json(
            client, f"{base}/api/server/status", _api_headers(token, org_id)
        )
        print(f"baseline /health/ready -> {ready_status} ({ready_ms:.0f}ms)")
        print(f"baseline /api/server/status -> {status_status} ({status_ms:.0f}ms) {status_body}")

        baseline = await _probe_devices(client, base, token, org_id, 3)
        print(
            f"baseline /api/devices -> ok={baseline.ok_count} fail={baseline.fail_count} "
            f"statuses={baseline.statuses}"
        )

        pg_before = await _pg_connection_count()
        if pg_before is not None:
            print(f"pg_connections_before={pg_before}")

        print(f"opening {args.streams} SSE streams ...")
        headers = _headers(token, org_id)
        for _ in range(args.streams):
            stream_tasks.append(
                asyncio.create_task(
                    _hold_sse_stream(client, stream_url, headers, args.hold_seconds, stop)
                )
            )
        await asyncio.sleep(2.0)

        under_load = await _probe_devices(
            client, base, token, org_id, args.probe_count
        )
        print(
            f"under_load /api/devices -> ok={under_load.ok_count} fail={under_load.fail_count} "
            f"statuses={under_load.statuses}"
        )

        _, status_under, _ = await _get_json(
            client, f"{base}/api/server/status", _api_headers(token, org_id)
        )
        safe_mode = bool(isinstance(status_under, dict) and status_under.get("safe_mode"))
        print(f"under_load safe_mode={safe_mode} status={status_under}")

        pg_under = await _pg_connection_count()
        if pg_under is not None:
            print(f"pg_connections_under_load={pg_under}")

        reproduced = under_load.fail_count >= max(1, args.probe_count // 2) or safe_mode
        print(f"verdict_stress={'REPRODUCED' if reproduced else 'NOT_REPRODUCED'}")

        print("closing SSE streams ...")
        stop.set()
        for task in stream_tasks:
            task.cancel()
        await asyncio.gather(*stream_tasks, return_exceptions=True)
        await asyncio.sleep(5.0)

        recovered_probe = await _probe_devices(client, base, token, org_id, 5)
        _, status_after, _ = await _get_json(
            client, f"{base}/api/server/status", _api_headers(token, org_id)
        )
        safe_after = bool(isinstance(status_after, dict) and status_after.get("safe_mode"))
        recovered = recovered_probe.ok_count >= 4 and not safe_after
        print(
            f"after_close /api/devices -> ok={recovered_probe.ok_count} "
            f"fail={recovered_probe.fail_count} statuses={recovered_probe.statuses}"
        )
        print(f"after_close safe_mode={safe_after}")
        print(f"verdict_recovery={'RECOVERED' if recovered else 'STILL_DEGRADED'}")

    if reproduced and recovered:
        return 0
    if not reproduced:
        print("NOTE: stress did not reproduce failure — pool may already be fixed or streams too low.")
        return 0 if recovered else 2
    return 1 if not recovered else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("DEVICE_FARM_BASE_URL", "http://localhost:8081"))
    parser.add_argument("--token", default=os.environ.get("DEVICE_FARM_TOKEN", ""))
    parser.add_argument("--org-id", default=os.environ.get("DEVICE_FARM_ORG_ID", ""))
    parser.add_argument("--execution-id", default=os.environ.get("DEVICE_FARM_EXECUTION_ID", ""))
    parser.add_argument("--streams", type=int, default=int(os.environ.get("REPRO_STREAMS", DEFAULT_STREAMS)))
    parser.add_argument("--hold-seconds", type=float, default=DEFAULT_HOLD_SECONDS)
    parser.add_argument("--probe-count", type=int, default=DEFAULT_PROBE_COUNT)
    args = parser.parse_args()

    if not args.token:
        print("error: --token or DEVICE_FARM_TOKEN required", file=sys.stderr)
        sys.exit(2)
    if not args.execution_id:
        print("error: --execution-id or DEVICE_FARM_EXECUTION_ID required", file=sys.stderr)
        sys.exit(2)

    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
