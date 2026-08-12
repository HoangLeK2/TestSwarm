#!/usr/bin/env python3
"""Benchmark campaign fault isolation with simulated phones.

This does not require real devices.  It stress-tests the retry decision layer:
known transient U2 errors may retry; device-lost, selector/business misses, and
crawl budget timeouts are isolated instead of creating retry storms.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.campaign.failure_classification import classify_campaign_failure

PolicyMode = Literal["naive_retry_all", "classified_isolation"]


@dataclass(frozen=True)
class Fault:
    step_index: int
    message: str
    reason_code: str | None = None
    step_type: str = "tap_selector"


@dataclass
class PhoneResult:
    serial: str
    ok: bool
    duration_ms: float
    attempts: int
    retries: int
    failed_class: str | None
    failed_step: int | None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, p)) * (len(ordered) - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= len(ordered) - 1:
        return ordered[-1]
    return ordered[idx] + (ordered[idx + 1] - ordered[idx]) * frac


def _scenario_step_type(step_index: int) -> str:
    if step_index in {8, 13, 18, 23}:
        return "fb_comment"
    if step_index % 5 == 0:
        return "extract"
    return "tap_selector"


def _build_faults(phones: int, steps: int, seed: int) -> dict[str, Fault]:
    rng = random.Random(seed)
    faults: dict[str, Fault] = {}
    for i in range(phones):
        serial = f"MOCK-{i:04d}"
        roll = rng.random()
        if roll < 0.08:
            faults[serial] = Fault(
                step_index=rng.randrange(1, steps),
                message="edge extra_data failed: JSON-RPC HTTP 502",
                step_type="fb_comment",
            )
        elif roll < 0.13:
            faults[serial] = Fault(
                step_index=rng.randrange(1, steps),
                message="CampaignDeviceClaimLostError: claim lost",
                reason_code="claim_lost",
            )
        elif roll < 0.20:
            faults[serial] = Fault(
                step_index=rng.randrange(1, steps),
                message="post_open_target_not_found",
                reason_code="post_open_target_not_found",
            )
        elif roll < 0.24:
            faults[serial] = Fault(
                step_index=rng.randrange(1, steps),
                message="comment wall-clock cap reached",
                step_type="fb_comment",
            )
    return faults


async def _run_phone(
    serial: str,
    *,
    steps: int,
    u2_sem: asyncio.Semaphore,
    policy: PolicyMode,
    faults: dict[str, Fault],
    scale: float,
    max_attempts: int,
) -> PhoneResult:
    start = time.perf_counter()
    attempts = 0
    retries = 0
    fault = faults.get(serial)
    failed_class: str | None = None
    failed_step: int | None = None

    for step_index in range(steps):
        step_type = _scenario_step_type(step_index)
        attempt = 0
        while True:
            attempt += 1
            attempts += 1
            async with u2_sem:
                base_ms = 18.0 if step_type != "fb_comment" else 55.0
                await asyncio.sleep(base_ms * scale / 1000.0)

            if fault is None or fault.step_index != step_index:
                break
            if "json-rpc http" in fault.message.lower() and attempt > 1:
                break

            classified = classify_campaign_failure(
                {
                    "ok": False,
                    "type": fault.step_type or step_type,
                    "reason_code": fault.reason_code,
                    "message": fault.message,
                },
                step_type=fault.step_type or step_type,
            )
            failed_class = classified.failure_class
            failed_step = step_index

            if policy == "naive_retry_all":
                should_retry = attempt < max_attempts
            else:
                should_retry = classified.retryable and attempt < max_attempts

            if not should_retry:
                duration_ms = (time.perf_counter() - start) * 1000.0
                return PhoneResult(
                    serial=serial,
                    ok=False,
                    duration_ms=duration_ms,
                    attempts=attempts,
                    retries=retries,
                    failed_class=failed_class,
                    failed_step=failed_step,
                )

            retries += 1
            await asyncio.sleep(2.5 * scale / 1000.0)
        continue

    duration_ms = (time.perf_counter() - start) * 1000.0
    return PhoneResult(
        serial=serial,
        ok=True,
        duration_ms=duration_ms,
        attempts=attempts,
        retries=retries,
        failed_class=failed_class,
        failed_step=failed_step,
    )


async def _run_policy(
    *,
    phones: int,
    steps: int,
    u2_slots: int,
    policy: PolicyMode,
    faults: dict[str, Fault],
    scale: float,
    max_attempts: int,
) -> list[PhoneResult]:
    u2_sem = asyncio.Semaphore(u2_slots)
    tasks = [
        _run_phone(
            f"MOCK-{i:04d}",
            steps=steps,
            u2_sem=u2_sem,
            policy=policy,
            faults=faults,
            scale=scale,
            max_attempts=max_attempts,
        )
        for i in range(phones)
    ]
    return await asyncio.gather(*tasks)


def _summarize(policy: PolicyMode, results: list[PhoneResult]) -> dict[str, Any]:
    durations = [r.duration_ms for r in results]
    passed = [r for r in results if r.ok]
    failed = [r for r in results if not r.ok]
    return {
        "policy": policy,
        "phones": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "duration_p50_ms": _percentile(durations, 0.50),
        "duration_p95_ms": _percentile(durations, 0.95),
        "duration_max_ms": max(durations) if durations else 0.0,
        "attempts": sum(r.attempts for r in results),
        "retries": sum(r.retries for r in results),
        "failure_classes": Counter(r.failed_class for r in failed if r.failed_class),
        "passed_p95_ms": _percentile([r.duration_ms for r in passed], 0.95),
        "attempts_per_phone_p95": _percentile([float(r.attempts) for r in results], 0.95),
    }


def _print_summary(rows: list[dict[str, Any]]) -> None:
    print("campaign fault-isolation benchmark")
    print(
        "policy                 phones  pass  fail  p95_ms   retries  attempts  "
        "attempt_p95  failures"
    )
    for row in rows:
        failures = ",".join(f"{k}:{v}" for k, v in sorted(row["failure_classes"].items()))
        print(
            f"{row['policy']:<22} "
            f"{row['phones']:>6} "
            f"{row['passed']:>5} "
            f"{row['failed']:>5} "
            f"{row['duration_p95_ms']:>7.2f} "
            f"{row['retries']:>8} "
            f"{row['attempts']:>9} "
            f"{row['attempts_per_phone_p95']:>11.1f} "
            f"{failures or '-'}"
        )
    if len(rows) == 2:
        before, after = rows
        retry_delta = before["retries"] - after["retries"]
        p95_delta = before["duration_p95_ms"] - after["duration_p95_ms"]
        print(
            "improvement "
            f"p95_saved_ms={p95_delta:.2f} "
            f"retry_saved={retry_delta} "
            f"retry_reduction_pct={(retry_delta / max(1, before['retries'])) * 100:.1f}"
        )


async def _amain(args: argparse.Namespace) -> None:
    faults = _build_faults(args.phones, args.steps, args.seed)
    rows: list[dict[str, Any]] = []
    for policy in ("naive_retry_all", "classified_isolation"):
        results = await _run_policy(
            phones=args.phones,
            steps=args.steps,
            u2_slots=args.u2_slots,
            policy=policy,  # type: ignore[arg-type]
            faults=faults,
            scale=args.time_scale,
            max_attempts=args.max_attempts,
        )
        rows.append(_summarize(policy, results))  # type: ignore[arg-type]
    _print_summary(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phones", type=int, default=100)
    parser.add_argument("--steps", type=int, default=28)
    parser.add_argument("--u2-slots", type=int, default=96)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--time-scale", type=float, default=0.02)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
