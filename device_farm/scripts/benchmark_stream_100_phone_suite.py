from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scripts.benchmark_stream_backend_fanout import _run as run_backend_fanout
from scripts.benchmark_stream_e2e import _run as run_e2e
from scripts.benchmark_stream_ws_isolation import _run as run_ws_isolation


@dataclass(frozen=True)
class Budget:
    metric: str
    limit: float
    op: str = "<="


def _get_path(data: dict[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _check_budgets(result: dict[str, Any], budgets: list[Budget]) -> list[str]:
    failures: list[str] = []
    for budget in budgets:
        raw = _get_path(result, budget.metric)
        if not isinstance(raw, int | float):
            failures.append(f"{budget.metric}=missing")
            continue
        value = float(raw)
        if budget.op == "<=" and value > budget.limit:
            failures.append(f"{budget.metric}={value:g}>{budget.limit:g}")
        elif budget.op == ">=" and value < budget.limit:
            failures.append(f"{budget.metric}={value:g}<{budget.limit:g}")
    return failures


async def _timed(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result = await fn()
    result["suite_elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    result["name"] = name
    return result


async def _run_suite(args: argparse.Namespace) -> dict[str, Any]:
    expected_fast_seen = (args.phones - args.slow_phones) * args.frames
    ws_producer_drop_budget = (
        args.ws_producer_drops
        if args.ws_producer_drops >= 0
        else args.slow_phones * args.frames
    )
    cases: list[dict[str, Any]] = []

    backend = await _timed(
        "backend_fanout_100",
        lambda: run_backend_fanout(
            args.phones,
            args.frames,
            args.subscribers_per_phone,
        ),
    )
    backend["failures"] = _check_budgets(
        backend,
        [
            Budget("p95_ms", args.backend_p95_ms),
            Budget("total_ms", args.backend_total_ms),
            Budget("peak_mb", args.backend_peak_mb),
            Budget("telemetry.fanout_no_subscriber", 0),
            Budget("telemetry.fanout_max_subscribers", args.subscribers_per_phone),
        ],
    )
    cases.append(backend)

    ws_isolated = await _timed(
        "ws_isolated_100",
        lambda: run_ws_isolation(
            phones=args.phones,
            frames=args.frames,
            slow_phones=args.slow_phones,
            slow_send_ms=args.slow_send_ms,
            shared_lock=False,
            lock_wait_ms=args.lock_wait_ms,
            frame_interval_ms=args.frame_interval_ms,
        ),
    )
    ws_isolated["failures"] = _check_budgets(
        ws_isolated,
        [
            Budget("fast_seen", expected_fast_seen, ">="),
            Budget("fast_p95_ms", args.ws_fast_p95_ms),
            Budget("producer_drops", ws_producer_drop_budget),
        ],
    )
    cases.append(ws_isolated)

    e2e_isolated = await _timed(
        "e2e_isolated_100",
        lambda: run_e2e(
            phones=args.phones,
            frames=args.frames,
            slow_phones=args.slow_phones,
            slow_send_ms=args.slow_send_ms,
            shared_lock=False,
            frame_interval_ms=args.frame_interval_ms,
        ),
    )
    e2e_isolated["failures"] = _check_budgets(
        e2e_isolated,
        [
            Budget("fast_seen", expected_fast_seen, ">="),
            Budget("fast_p95_ms", args.e2e_fast_p95_ms),
            Budget("telemetry.dispatch_no_receiver", 0),
            Budget("telemetry.fanout_no_subscriber", 0),
            Budget("telemetry.ws_dropped", args.e2e_ws_drops),
            Budget("stream_status.media_ws_active", args.phones),
            Budget("stream_status.media_streams_active", args.phones),
            Budget("stream_status.max_media_streams_per_connection", 1),
            Budget("stream_status.shared_media_ws_connections", 0),
        ],
    )
    e2e_isolated["failures"].extend(
        [] if e2e_isolated["stream_status"]["dedicated_media_ws_ok"] is True else ["dedicated_media_ws_ok=false"]
    )
    cases.append(e2e_isolated)

    if args.include_shared_control:
        e2e_shared = await _timed(
            "e2e_shared_control_100",
            lambda: run_e2e(
                phones=args.phones,
                frames=args.frames,
                slow_phones=args.slow_phones,
                slow_send_ms=args.slow_send_ms,
                shared_lock=True,
                frame_interval_ms=args.frame_interval_ms,
            ),
        )
        e2e_shared["expected_failure"] = True
        e2e_shared["failures"] = _check_budgets(
            e2e_shared,
            [
                Budget("fast_seen", expected_fast_seen, ">="),
                Budget("fast_p95_ms", args.e2e_fast_p95_ms),
                Budget("stream_status.max_media_streams_per_connection", 1),
                Budget("stream_status.shared_media_ws_connections", 0),
            ],
        )
        cases.append(e2e_shared)

    optimized_failures = [
        {"name": case["name"], "failures": case["failures"]}
        for case in cases
        if case.get("failures") and not case.get("expected_failure")
    ]
    return {
        "kind": "stream_100_phone_mock_suite",
        "phones": args.phones,
        "frames": args.frames,
        "slow_phones": args.slow_phones,
        "slow_send_ms": args.slow_send_ms,
        "frame_interval_ms": args.frame_interval_ms,
        "ok": not optimized_failures,
        "budgets": {
            "expected_fast_seen": expected_fast_seen,
            "ws_producer_drops": ws_producer_drop_budget,
            "backend_p95_ms": args.backend_p95_ms,
            "ws_fast_p95_ms": args.ws_fast_p95_ms,
            "e2e_fast_p95_ms": args.e2e_fast_p95_ms,
            "e2e_ws_drops": args.e2e_ws_drops,
        },
        "optimized_failures": optimized_failures,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run 100-phone mock stream benchmarks in one pass."
    )
    parser.add_argument("--phones", type=int, default=100)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--slow-phones", type=int, default=4)
    parser.add_argument("--slow-send-ms", type=float, default=25.0)
    parser.add_argument("--frame-interval-ms", type=float, default=5.0)
    parser.add_argument("--lock-wait-ms", type=float, default=8.0)
    parser.add_argument("--subscribers-per-phone", type=int, default=1)
    parser.add_argument("--backend-p95-ms", type=float, default=1.0)
    parser.add_argument("--backend-total-ms", type=float, default=500.0)
    parser.add_argument("--backend-peak-mb", type=float, default=4.0)
    parser.add_argument("--ws-fast-p95-ms", type=float, default=5.0)
    parser.add_argument(
        "--ws-producer-drops",
        type=float,
        default=-1.0,
        help=(
            "Standalone WS producer drop budget. Default -1 scales to "
            "slow_phones * frames because drops on simulated slow clients are expected."
        ),
    )
    parser.add_argument("--e2e-fast-p95-ms", type=float, default=5.0)
    parser.add_argument("--e2e-ws-drops", type=float, default=5.0)
    parser.add_argument(
        "--include-shared-control",
        action="store_true",
        help="Also run the old shared-lock shape as an expected-failure control.",
    )
    args = parser.parse_args()

    result = asyncio.run(_run_suite(args))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
