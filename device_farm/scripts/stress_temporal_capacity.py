#!/usr/bin/env python3
"""Stress Temporal worker slots against a live Docker farm.

Starts N concurrent CapacityProbeWorkflow runs (registered on every worker).
Each run occupies one activity slot for --delay-ms, so wall-time scaling shows
whether worker_count × max_concurrent_activities can absorb the fan-out.

Does not need physical phones. Use --production-120 for the current production
target: 120 concurrent probes on 140 activity slots, plus a 120-way activity DB
connection hold probe.

Usage (host, Temporal published on :7233):

  cd device_farm
  PYTHONUNBUFFERED=1 uv run python scripts/stress_temporal_capacity.py --ladder
  PYTHONUNBUFFERED=1 uv run python scripts/stress_temporal_capacity.py \
    --production-120 --json-output tmp/temporal-capacity-120.json

Env:
  TEMPORAL_SERVER_URL   default localhost:7233
  TEMPORAL_NAMESPACE    default default
  TEMPORAL_TASK_QUEUE   default device-scenario
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from temporalio.client import Client, WorkflowFailureError
from temporalio.common import WorkflowIDReusePolicy

# Line-buffer stdout when piped / backgrounded.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = max(0.0, min(1.0, p)) * (len(xs) - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= len(xs) - 1:
        return xs[-1]
    return xs[idx] + (xs[idx + 1] - xs[idx]) * frac


@dataclass
class WaveResult:
    concurrency: int
    payload_delay_ms: int = 0
    ok: int = 0
    fail: int = 0
    wall_s: float = 0.0
    latencies_s: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def p50_s(self) -> float:
        return _percentile(self.latencies_s, 0.50)

    @property
    def p95_s(self) -> float:
        return _percentile(self.latencies_s, 0.95)

    @property
    def p99_s(self) -> float:
        return _percentile(self.latencies_s, 0.99)

    @property
    def mean_s(self) -> float:
        return statistics.fmean(self.latencies_s) if self.latencies_s else 0.0

    @property
    def throughput_per_s(self) -> float:
        return self.ok / self.wall_s if self.wall_s > 0 else 0.0

    @property
    def effective_slots(self) -> float:
        hold_s = max(0.0, self.payload_delay_ms / 1000.0)
        if self.wall_s <= 0 or hold_s <= 0:
            return 0.0
        return self.ok * hold_s / self.wall_s

    @property
    def p95_queue_delay_s(self) -> float:
        hold_s = max(0.0, self.payload_delay_ms / 1000.0)
        return max(0.0, self.p95_s - hold_s)


@dataclass
class CapacityMath:
    target_phones: int
    worker_count: int
    activities_per_worker: int
    workflows_per_worker: int
    db_activity_pool_size: int
    db_activity_max_overflow: int
    db_pool_size: int
    db_max_overflow: int

    @property
    def activity_slots(self) -> int:
        return self.worker_count * self.activities_per_worker

    @property
    def workflow_task_slots(self) -> int:
        return self.worker_count * self.workflows_per_worker

    @property
    def thread_pool_per_worker(self) -> int:
        return max(self.activities_per_worker * 2, 20)

    @property
    def total_activity_threads(self) -> int:
        return self.worker_count * self.thread_pool_per_worker

    @property
    def activity_db_connections_max(self) -> int:
        return self.worker_count * (self.db_activity_pool_size + self.db_activity_max_overflow)

    @property
    def web_db_connections_max(self) -> int:
        return self.db_pool_size + self.db_max_overflow

    @property
    def process_db_connections_max(self) -> int:
        return self.activity_db_connections_max + self.web_db_connections_max

    @property
    def slot_headroom(self) -> int:
        return self.activity_slots - self.target_phones

    @property
    def required_workers_at_current_activity_limit(self) -> int:
        return math.ceil(self.target_phones / max(1, self.activities_per_worker))


async def _run_one(
    client: Client,
    *,
    workflow: str,
    task_queue: str,
    workflow_id: str,
    delay_ms: int,
) -> tuple[bool, float, str | None]:
    started = time.perf_counter()
    try:
        if workflow in ("CapacityProbeWorkflow", "DbHoldProbeWorkflow"):
            handle = await client.start_workflow(
                workflow,
                delay_ms,
                id=workflow_id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        else:
            handle = await client.start_workflow(
                workflow,
                id=workflow_id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        await handle.result()
        return True, time.perf_counter() - started, None
    except WorkflowFailureError as exc:
        return False, time.perf_counter() - started, f"workflow_failed: {exc}"
    except Exception as exc:  # noqa: BLE001 — stress harness must keep going
        return False, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"


async def run_wave(
    client: Client,
    *,
    concurrency: int,
    task_queue: str,
    tag: str,
    workflow: str,
    delay_ms: int,
) -> WaveResult:
    result = WaveResult(concurrency=concurrency, payload_delay_ms=delay_ms)
    wave_id = uuid.uuid4().hex[:10]
    wall_started = time.perf_counter()

    tasks = [
        _run_one(
            client,
            workflow=workflow,
            task_queue=task_queue,
            workflow_id=f"stress-capacity-{tag}-{wave_id}-{i:04d}",
            delay_ms=delay_ms,
        )
        for i in range(concurrency)
    ]
    outcomes = await asyncio.gather(*tasks)
    result.wall_s = time.perf_counter() - wall_started

    for ok, latency_s, err in outcomes:
        result.latencies_s.append(latency_s)
        if ok:
            result.ok += 1
        else:
            result.fail += 1
            if err and len(result.errors) < 8:
                result.errors.append(err)
    return result


def _print_wave(result: WaveResult) -> None:
    print(
        f"concurrency={result.concurrency:>4}  "
        f"ok={result.ok:>4} fail={result.fail:>3}  "
        f"wall={result.wall_s:6.2f}s  "
        f"p50={result.p50_s:5.2f}s p95={result.p95_s:5.2f}s p99={result.p99_s:5.2f}s  "
        f"queue_p95={result.p95_queue_delay_s:5.2f}s  "
        f"mean={result.mean_s:5.2f}s  thr={result.throughput_per_s:5.1f}/s  "
        f"eff_slots={result.effective_slots:6.1f}"
    )
    for err in result.errors:
        print(f"  ! {err}")


def _pass_fail(result: WaveResult, *, max_fail: int, max_p95_s: float) -> bool:
    if result.fail > max_fail:
        return False
    if result.p95_s > max_p95_s:
        return False
    return True


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _capacity_math(args: argparse.Namespace) -> CapacityMath:
    return CapacityMath(
        target_phones=args.target_phones,
        worker_count=args.worker_count,
        activities_per_worker=args.activities_per_worker,
        workflows_per_worker=args.workflows_per_worker,
        db_activity_pool_size=args.db_activity_pool_size,
        db_activity_max_overflow=args.db_activity_max_overflow,
        db_pool_size=args.db_pool_size,
        db_max_overflow=args.db_max_overflow,
    )


def _print_capacity_math(math_: CapacityMath) -> None:
    print("capacity math")
    print(f"  target_phones={math_.target_phones}")
    print(
        f"  activity_slots={math_.activity_slots} "
        f"({math_.worker_count} workers x {math_.activities_per_worker} activities) "
        f"headroom={math_.slot_headroom}"
    )
    print(
        f"  workflow_task_slots={math_.workflow_task_slots} "
        f"({math_.worker_count} workers x {math_.workflows_per_worker} workflows)"
    )
    print(
        f"  thread_pool={math_.total_activity_threads} total "
        f"({math_.thread_pool_per_worker}/worker)"
    )
    print(
        f"  db_activity_connections_max={math_.activity_db_connections_max} "
        f"({math_.worker_count} workers x "
        f"({math_.db_activity_pool_size}+{math_.db_activity_max_overflow}))"
    )
    print(f"  db_web_connections_max={math_.web_db_connections_max}")
    print(f"  db_process_connections_max={math_.process_db_connections_max}")
    print(
        f"  required_workers_for_target={math_.required_workers_at_current_activity_limit} "
        f"at {math_.activities_per_worker} activities/worker"
    )


def _wave_to_dict(result: WaveResult) -> dict:
    data = asdict(result)
    data.update(
        p50_s=result.p50_s,
        p95_s=result.p95_s,
        p99_s=result.p99_s,
        mean_s=result.mean_s,
        throughput_per_s=result.throughput_per_s,
        effective_slots=result.effective_slots,
        p95_queue_delay_s=result.p95_queue_delay_s,
    )
    return data


def _write_json_report(path: str, payload: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"wrote json report: {out}")


async def _run_waves(
    client: Client,
    *,
    levels: list[int],
    task_queue: str,
    tag: str,
    workflow: str,
    delay_ms: int,
    pause_s: float,
) -> list[WaveResult]:
    print(f"workflow={workflow} delay_ms={delay_ms}")
    print(f"wave levels: {levels}")
    print("-" * 88)
    results: list[WaveResult] = []
    for n in levels:
        print(f"starting wave concurrency={n} ...", flush=True)
        wave = await run_wave(
            client,
            concurrency=n,
            task_queue=task_queue,
            tag=tag,
            workflow=workflow,
            delay_ms=delay_ms,
        )
        _print_wave(wave)
        results.append(wave)
        if pause_s > 0 and n != levels[-1]:
            await asyncio.sleep(pause_s)
    print("-" * 88)
    return results


def _meets_schedule_to_start_budget(
    result: WaveResult,
    *,
    max_queue_delay_s: float,
) -> bool:
    if result.p95_queue_delay_s <= max_queue_delay_s:
        return True
    print(
        f"FAIL: schedule-to-start proxy p95 {result.p95_queue_delay_s:.2f}s > "
        f"{max_queue_delay_s:.2f}s"
    )
    return False


async def _run_production_120_suite(
    client: Client,
    *,
    args: argparse.Namespace,
    task_queue: str,
) -> int:
    math_ = _capacity_math(args)
    _print_capacity_math(math_)
    print("")

    ok = True
    if math_.activity_slots < math_.target_phones:
        ok = False
        print(
            f"FAIL: configured activity_slots={math_.activity_slots} "
            f"< target_phones={math_.target_phones}"
        )

    slot_results = await _run_waves(
        client,
        levels=args.levels,
        task_queue=task_queue,
        tag=f"{args.tag}-slot",
        workflow="CapacityProbeWorkflow",
        delay_ms=args.slot_delay_ms,
        pause_s=args.pause_s,
    )
    slot_target = slot_results[-1]
    ok = _pass_fail(
        slot_target,
        max_fail=args.max_fail,
        max_p95_s=args.slot_max_p95_s,
    ) and ok
    ok = _meets_schedule_to_start_budget(
        slot_target,
        max_queue_delay_s=args.slot_max_schedule_to_start_s,
    ) and ok

    db_results = await _run_waves(
        client,
        levels=[args.target_phones],
        task_queue=task_queue,
        tag=f"{args.tag}-db",
        workflow="DbHoldProbeWorkflow",
        delay_ms=args.db_hold_ms,
        pause_s=0.0,
    )
    db_target = db_results[-1]
    ok = _pass_fail(
        db_target,
        max_fail=args.max_fail,
        max_p95_s=args.db_max_p95_s,
    ) and ok

    report = {
        "mode": "production-120",
        "task_queue": task_queue,
        "capacity_math": asdict(math_) | {
            "activity_slots": math_.activity_slots,
            "workflow_task_slots": math_.workflow_task_slots,
            "total_activity_threads": math_.total_activity_threads,
            "activity_db_connections_max": math_.activity_db_connections_max,
            "web_db_connections_max": math_.web_db_connections_max,
            "process_db_connections_max": math_.process_db_connections_max,
            "slot_headroom": math_.slot_headroom,
            "required_workers_at_current_activity_limit": (
                math_.required_workers_at_current_activity_limit
            ),
        },
        "slot_probe": [_wave_to_dict(r) for r in slot_results],
        "db_probe": [_wave_to_dict(r) for r in db_results],
        "passed": ok,
    }
    if args.json_output:
        _write_json_report(args.json_output, report)

    if ok:
        print(
            f"PASS production-120: target={math_.target_phones} "
            f"slot_eff={slot_target.effective_slots:.1f} "
            f"slot_p95={slot_target.p95_s:.2f}s "
            f"queue_p95={slot_target.p95_queue_delay_s:.2f}s "
            f"db_p95={db_target.p95_s:.2f}s"
        )
        return 0
    print(
        f"FAIL production-120: target={math_.target_phones} "
        f"slot_eff={slot_target.effective_slots:.1f} "
        f"slot_p95={slot_target.p95_s:.2f}s "
        f"queue_p95={slot_target.p95_queue_delay_s:.2f}s "
        f"db_p95={db_target.p95_s:.2f}s"
    )
    return 1


async def async_main(args: argparse.Namespace) -> int:
    server = os.environ.get("TEMPORAL_SERVER_URL", args.server)
    namespace = os.environ.get("TEMPORAL_NAMESPACE", args.namespace)
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", args.task_queue)

    print(f"connecting temporal={server} ns={namespace} queue={task_queue}")
    client = await Client.connect(server, namespace=namespace)

    if args.production_120:
        return await _run_production_120_suite(client, args=args, task_queue=task_queue)

    levels = args.levels if args.ladder else [args.concurrency]
    results = await _run_waves(
        client,
        levels=levels,
        task_queue=task_queue,
        tag=args.tag,
        workflow=args.workflow,
        delay_ms=args.delay_ms,
        pause_s=args.pause_s,
    )
    # Heuristic: with enough worker slots, wall time should stay near p95 of a
    # single activity (~few seconds), not scale linearly with concurrency.
    target = max(levels)
    target_wave = next(r for r in results if r.concurrency == target)
    ok = _pass_fail(
        target_wave,
        max_fail=args.max_fail,
        max_p95_s=args.max_p95_s,
    )
    baseline = next((r for r in results if r.concurrency == min(levels)), None)
    if baseline and baseline.wall_s > 0 and target_wave.concurrency > baseline.concurrency:
        slowdown = target_wave.wall_s / baseline.wall_s
        print(
            f"slowdown wall({target}/{baseline.concurrency})={slowdown:.2f}x "
            f"(ideal ~1.0 if slots >= concurrency; ignore when baseline wall < 1s)"
        )
        # Short baselines (sub-second) make ratios noisy — only gate on slowdown
        # when the low-concurrency wave itself took meaningful time.
        if baseline.wall_s >= 1.0 and slowdown > args.max_slowdown:
            ok = False
            print(f"FAIL: slowdown {slowdown:.2f}x > max_slowdown {args.max_slowdown}")

    if ok:
        print(
            f"PASS: concurrency={target} fail={target_wave.fail} "
            f"p95={target_wave.p95_s:.2f}s <= {args.max_p95_s}s"
        )
        return 0

    print(
        f"FAIL: concurrency={target} fail={target_wave.fail} "
        f"p95={target_wave.p95_s:.2f}s (budget fail<={args.max_fail} p95<={args.max_p95_s}s)"
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="localhost:7233")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--task-queue", default="device-scenario")
    parser.add_argument("--concurrency", type=int, default=120)
    parser.add_argument(
        "--production-120",
        action="store_true",
        help="Run the production target suite: 120 slot probe + 120 DB-hold probe",
    )
    parser.add_argument(
        "--target-phones",
        type=int,
        default=_env_int("DEVICE_FARM_TARGET_PHONES", 120),
    )
    parser.add_argument(
        "--worker-count",
        type=int,
        default=_env_int("TEMPORAL_WORKER_COUNT", 7),
    )
    parser.add_argument(
        "--activities-per-worker",
        type=int,
        default=_env_int("TEMPORAL_WORKER_MAX_CONCURRENT_ACTIVITIES", 20),
    )
    parser.add_argument(
        "--workflows-per-worker",
        type=int,
        default=_env_int("TEMPORAL_WORKER_MAX_CONCURRENT_WORKFLOWS", 60),
    )
    parser.add_argument(
        "--db-activity-pool-size",
        type=int,
        default=_env_int("DB_ACTIVITY_POOL_SIZE", 4),
    )
    parser.add_argument(
        "--db-activity-max-overflow",
        type=int,
        default=_env_int("DB_ACTIVITY_MAX_OVERFLOW", 0),
    )
    parser.add_argument("--db-pool-size", type=int, default=_env_int("DB_POOL_SIZE", 12))
    parser.add_argument("--db-max-overflow", type=int, default=_env_int("DB_MAX_OVERFLOW", 3))
    parser.add_argument(
        "--slot-delay-ms",
        type=int,
        default=5000,
        help="Hold time for production slot probe; use >=5000ms to reduce noise",
    )
    parser.add_argument(
        "--db-hold-ms",
        type=int,
        default=1500,
        help="DB connection hold time for production DB probe",
    )
    parser.add_argument("--slot-max-p95-s", type=float, default=15.0)
    parser.add_argument("--db-max-p95-s", type=float, default=30.0)
    parser.add_argument(
        "--slot-max-schedule-to-start-s",
        type=float,
        default=2.0,
        help="Maximum p95 workflow/activity overhead above --slot-delay-ms",
    )
    parser.add_argument("--json-output", default="")
    parser.add_argument(
        "--workflow",
        default="CapacityProbeWorkflow",
        choices=(
            "CapacityProbeWorkflow",
            "DbHoldProbeWorkflow",
            "AccountCooldownTickWorkflow",
        ),
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=100,
        help="Sleep for CapacityProbeWorkflow / hold_ms for DbHoldProbeWorkflow",
    )
    parser.add_argument(
        "--ladder",
        action="store_true",
        help="Run 20 → 60 → 120 (or --levels)",
    )
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=[20, 60, 120],
        help="Used with --ladder",
    )
    parser.add_argument("--pause-s", type=float, default=2.0)
    parser.add_argument("--tag", default="run")
    parser.add_argument("--max-fail", type=int, default=0)
    parser.add_argument(
        "--max-p95-s",
        type=float,
        default=30.0,
        help="Per-workflow latency p95 budget (seconds)",
    )
    parser.add_argument(
        "--max-slowdown",
        type=float,
        default=3.0,
        help="Max wall-time ratio high/low concurrency (ladder mode)",
    )
    args = parser.parse_args()
    if args.production_120:
        args.ladder = True
        if args.levels == [20, 60, 120]:
            args.levels = [30, 60, args.target_phones]
    elif not args.ladder:
        args.levels = [args.concurrency]
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
