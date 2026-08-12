#!/usr/bin/env python3
"""Benchmark a heavy campaign scenario against 100 simulated phones.

The harness intentionally does not require physical devices.  It loads a heavy
scenario from the local database when available, models the expensive campaign
steps with bounded shared resources, and calls the real scenario tap resolver
for selector+fallback behavior.  This makes it useful for catching regressions
like "selector has fallback but still waits and fails".

Example:

    uv run python scripts/benchmark_campaign_100_heavy.py \
      --scenario-id c1d4bdf3-b94c-42cc-bbc8-8dec3eb2fa3c --phones 100
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, p)) * (len(ordered) - 1)
    index = int(pos)
    fraction = pos - index
    if index >= len(ordered) - 1:
        return ordered[-1]
    return ordered[index] + (ordered[index + 1] - ordered[index]) * fraction


def _coerce_steps(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, str):
        body = json.loads(body)
    if isinstance(body, dict):
        steps = body.get("steps")
    else:
        steps = body
    return [step for step in (steps or []) if isinstance(step, dict)]


def _iter_steps(steps: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for step in steps:
        yield step
        nested = step.get("steps")
        if isinstance(nested, list):
            yield from _iter_steps([item for item in nested if isinstance(item, dict)])
        for branch_key in ("then", "else"):
            branch = step.get(branch_key)
            if isinstance(branch, list):
                yield from _iter_steps([item for item in branch if isinstance(item, dict)])


def _apply_comment_fast_scroll_profile(
    steps: list[dict[str, Any]],
    *,
    swipes_per_dump: int,
    distance: float,
    duration_ms: int,
) -> None:
    for step in _iter_steps(steps):
        if step.get("type") != "extract":
            continue
        if step.get("strategy") != "fb_comments":
            continue
        step["comment_large_target_fast_scroll"] = True
        step["comment_large_target_swipes_per_dump"] = swipes_per_dump
        step["comment_large_target_scroll_distance"] = distance
        step["comment_large_target_duration_ms"] = duration_ms


def _fallback_heavy_scenario() -> list[dict[str, Any]]:
    """Built-in copy shaped like the current heavy FB group crawl scenario."""
    return [
        {"id": "s-1", "type": "launch_app", "package": "com.facebook.katana", "stop_before": True},
        {
            "id": "s-2",
            "type": "if_element",
            "selector": {"by": "description", "value": "Tìm kiếm"},
            "then": [
                {
                    "id": "s-2-then-1",
                    "type": "tap_selector",
                    "selector": {"by": "description", "value": "Tìm kiếm"},
                    "timeout": 4,
                }
            ],
            "else": [{"id": "s-2-else-1", "type": "tap_ratio", "x": 0.87, "y": 0.035}],
        },
        {"id": "s-4", "type": "input_text", "via": "u2", "text": "openclaw vn"},
        {"id": "s-5", "type": "key", "key": "enter"},
        {
            "id": "s-6",
            "type": "if_element",
            "selector": {"by": "description", "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7"},
            "then": [
                {
                    "id": "s-6-then-1",
                    "type": "tap_selector",
                    "selector": {"by": "description", "value": "Kết quả tìm kiếm trong tab Nhóm, 3 trong số 7"},
                    "timeout": 4,
                }
            ],
        },
        {
            "id": "s-8",
            "type": "tap_selector",
            "selector": {
                "by": "description",
                "value": "Công khai · 98K thành viên · 5 bài viết/ngày",
                "conditions": {"packageName": "com.facebook.katana"},
            },
            "fallback": {"rx": 0.6, "ry": 0.246},
            "timeout": 8,
        },
        {"id": "s-9", "type": "scroll_down", "repeats": 2},
        {
            "id": "s-11",
            "type": "loop",
            "count": 10,
            "steps": [
                {
                    "id": "posts",
                    "type": "extract",
                    "strategy": "fb_posts",
                    "max_items": 50,
                    "open_post_before_extract": True,
                    "require_open_post_detail": True,
                },
                {
                    "id": "comments-scroll",
                    "type": "scroll_to",
                    "value": "Bình luận",
                    "max_swipes": 50,
                    "selector": {
                        "by": "description",
                        "value": "Bình luận",
                        "conditions": {
                            "className": "android.widget.Button",
                            "clickable": True,
                            "packageName": "com.facebook.katana",
                        },
                    },
                },
                {
                    "id": "comment-target",
                    "type": "fb_tap_comment_target",
                    "comment_target_verify": True,
                    "require_post_before_comment": True,
                },
                {"id": "filter", "type": "fb_apply_comment_filter", "comment_filter": "newest"},
                {
                    "id": "comments",
                    "type": "extract",
                    "strategy": "fb_comments",
                    "max_items": 500,
                    "comment_max_snapshots": 12,
                    "comment_scroll_passes": 16,
                    "comment_swipes_per_dump": 4,
                    "comment_scroll_wall_s": 25,
                    "comment_require_complete": True,
                },
                {"id": "next", "type": "scroll_down", "repeats": 2, "duration_ms": 520},
            ],
        },
    ]


async def _load_scenario_steps(database_url: str, scenario_id: str) -> list[dict[str, Any]]:
    import asyncpg

    conn = await asyncpg.connect(database_url)
    try:
        body = await conn.fetchval(
            "select body_json from org_scenarios where id=$1 and deleted_at is null",
            scenario_id,
        )
        if body is not None:
            return _coerce_steps(body)
        steps = await conn.fetchval("select steps from scenarios where id=$1", scenario_id)
        if steps is not None:
            return _coerce_steps(steps)
    finally:
        await conn.close()
    raise RuntimeError(f"scenario_id not found: {scenario_id}")


@dataclass
class _Resource:
    name: str
    slots: int
    sem: threading.BoundedSemaphore = field(init=False)
    wait_ms: list[float] = field(default_factory=list)
    active_samples: list[int] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: int = 0
    max_active: int = 0

    def __post_init__(self) -> None:
        self.sem = threading.BoundedSemaphore(max(1, self.slots))

    def run(self, virtual_ms: float, scale: float) -> tuple[float, float]:
        started_wait = time.perf_counter()
        self.sem.acquire()
        waited_ms = (time.perf_counter() - started_wait) * 1000.0
        with self.lock:
            self.wait_ms.append(waited_ms)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.active_samples.append(self.active)
        try:
            if virtual_ms > 0:
                time.sleep(virtual_ms * scale / 1000.0)
        finally:
            with self.lock:
                self.active = max(0, self.active - 1)
            self.sem.release()
        return virtual_ms, waited_ms


@dataclass
class _BenchStats:
    resource_virtual_ms: dict[str, float] = field(default_factory=dict)
    resource_wait_ms: dict[str, float] = field(default_factory=dict)
    phase_virtual_ms: dict[str, float] = field(default_factory=dict)
    phase_wait_ms: dict[str, float] = field(default_factory=dict)
    step_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add(self, resource: str, step_type: str, virtual_ms: float, wait_ms: float = 0.0) -> None:
        phase = _phase_for_step(resource, step_type)
        self.resource_virtual_ms[resource] = self.resource_virtual_ms.get(resource, 0.0) + virtual_ms
        self.resource_wait_ms[resource] = self.resource_wait_ms.get(resource, 0.0) + wait_ms
        self.phase_virtual_ms[phase] = self.phase_virtual_ms.get(phase, 0.0) + virtual_ms
        self.phase_wait_ms[phase] = self.phase_wait_ms.get(phase, 0.0) + wait_ms
        self.step_counts[step_type] = self.step_counts.get(step_type, 0) + 1


def _phase_for_step(resource: str, step_type: str) -> str:
    if step_type == "extract:fb_comments":
        return "crawl_comments"
    if step_type == "extract:fb_posts":
        return "crawl_posts"
    if resource == "extract":
        return "crawl_other"
    if step_type in {"scroll_to", "scroll_down", "fb_tap_comment_target", "fb_apply_comment_filter"}:
        return "u2_navigation"
    if step_type in {"tap_selector", "tap_ratio", "input_text", "key"}:
        return "u2_interaction"
    if step_type in {"launch_app", "stop_app", "if_element"}:
        return "u2_app_state"
    return resource


class _ScenarioU2:
    """Small deterministic U2 double for the heavy FB search flow.

    Stable navigation selectors are present.  The group-info selector is treated
    as missing because member/post-count text changes frequently in real runs;
    this is the case where a recorded fallback position must save the campaign.
    """

    def find_element(self, _by: str, value: str, timeout: float | None = None) -> str | None:
        if "Công khai" in value:
            return None
        return f"eid::{value}"

    def find_element_with_bounds(self, _by: str, value: str) -> dict[str, Any] | None:
        if "Công khai" in value:
            return None
        if value == "Tìm kiếm":
            return {"eid": "search", "bounds": {"left": 938, "top": 133, "right": 1092, "bottom": 287}}
        return {"eid": "group-tab", "bounds": {"left": 675, "top": 308, "right": 915, "bottom": 434}}


class _SimDevice:
    serial: str
    screen_width = 1080
    screen_height = 1920
    model = "CampaignBenchPhone"

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.u2 = _ScenarioU2()
        self.taps: list[tuple[int, int]] = []

    def _batch_enabled(self) -> bool:
        return False

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return "<hierarchy />"

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))


class _CampaignSimulator:
    def __init__(
        self,
        *,
        resources: dict[str, _Resource],
        time_scale: float,
        tap_wait_timeout_s: float,
    ) -> None:
        self.resources = resources
        self.time_scale = time_scale
        self.tap_wait_timeout_s = tap_wait_timeout_s

    def _run_resource(self, stats: _BenchStats, resource: str, step_type: str, virtual_ms: float) -> None:
        elapsed, wait_ms = self.resources[resource].run(virtual_ms, self.time_scale)
        stats.add(resource, step_type, elapsed, wait_ms)

    def _tap_selector(self, device: _SimDevice, step: dict[str, Any], stats: _BenchStats) -> bool:
        from tasks.scenario.steps.interaction import resolve_step_selector_fields
        from tasks.scenario.utils import _execute_tap

        spec, by, value, (fallback_rx, fallback_ry) = resolve_step_selector_fields(step)
        started = time.perf_counter()
        ok, message, _bounds = _execute_tap(
            device,
            by=by,
            value=value,
            fallback_rx=fallback_rx,
            fallback_ry=fallback_ry,
            timeout=float(step.get("timeout", 8.0) or 8.0),
            retries=1,
            implicit_wait_timeout=self.tap_wait_timeout_s,
            implicit_wait_poll=min(0.05, self.tap_wait_timeout_s),
            spec=spec,
        )
        real_ms = (time.perf_counter() - started) * 1000.0
        stats.add("u2", "tap_selector", real_ms)
        if not ok:
            stats.errors.append(message)
        return ok

    def _extract_virtual_ms(self, step: dict[str, Any]) -> tuple[str, float]:
        strategy = str(step.get("strategy") or "fb_posts")
        if strategy == "fb_comments":
            snapshots = int(step.get("comment_max_snapshots") or 8)
            swipe_budget = int(step.get("comment_scroll_passes") or 8)
            swipes_per_dump = int(step.get("comment_swipes_per_dump") or 2)
            if step.get("comment_large_target_fast_scroll"):
                swipes_per_dump = max(
                    swipes_per_dump,
                    int(step.get("comment_large_target_swipes_per_dump") or swipes_per_dump),
                )
            max_items = int(step.get("max_items") or 100)
            wall_s = float(step.get("comment_scroll_wall_s") or 10.0)
            dump_cycles = max(1, math.ceil(max(1, swipe_budget) / max(1, swipes_per_dump)))
            swipe_ms = float(
                step.get(
                    "comment_large_target_duration_ms"
                    if step.get("comment_large_target_fast_scroll")
                    else "comment_scroll_duration_ms",
                    step.get("comment_scroll_duration_ms", 180),
                )
                or 180
            )
            distance = float(
                step.get(
                    "comment_large_target_scroll_distance"
                    if step.get("comment_large_target_fast_scroll")
                    else "comment_scroll_distance",
                    step.get("comment_scroll_distance", 0.35),
                )
                or 0.35
            )
            distance_gain = max(0.55, min(1.25, 0.60 / max(0.08, distance)))
            virtual_ms = min(
                wall_s * 1000.0,
                120.0
                + min(snapshots, dump_cycles + 1) * 70.0
                + swipe_budget * max(18.0, swipe_ms * 0.35) * distance_gain
                + math.log2(max_items + 1) * 45.0,
            )
            return "extract", virtual_ms
        if strategy == "fb_posts":
            max_items = int(step.get("max_items") or 30)
            open_detail = bool(step.get("open_post_before_extract"))
            virtual_ms = 180.0 + min(max_items, 80) * 8.0 + (320.0 if open_detail else 0.0)
            return "extract", virtual_ms
        return "extract", 120.0

    def _run_steps(self, device: _SimDevice, steps: Iterable[dict[str, Any]], stats: _BenchStats) -> bool:
        for step in steps:
            step_type = str(step.get("type") or "")
            if step_type == "loop":
                count = int(step.get("count") or 1)
                nested = _coerce_steps(step.get("steps") or [])
                for _ in range(max(0, count)):
                    if not self._run_steps(device, nested, stats):
                        return False
                continue
            if step_type == "if_element":
                branch = _coerce_steps(step.get("then") or step.get("else") or [])
                self._run_resource(stats, "u2", step_type, 45.0)
                if branch and not self._run_steps(device, branch, stats):
                    return False
                continue
            if step_type == "tap_selector":
                if not self._tap_selector(device, step, stats):
                    return False
                continue
            if step_type == "extract":
                resource, virtual_ms = self._extract_virtual_ms(step)
                self._run_resource(stats, resource, f"extract:{step.get('strategy')}", virtual_ms)
                continue
            if step_type == "scroll_to":
                max_swipes = min(int(step.get("max_swipes") or 5), 8)
                self._run_resource(stats, "u2", step_type, 60.0 + max_swipes * 35.0)
                continue
            if step_type in {"launch_app", "stop_app"}:
                self._run_resource(stats, "u2", step_type, 450.0 if step_type == "launch_app" else 160.0)
                continue
            if step_type in {"input_text", "key", "tap_ratio", "scroll_down", "fb_tap_comment_target", "fb_apply_comment_filter"}:
                default = {
                    "input_text": 120.0,
                    "key": 80.0,
                    "tap_ratio": 60.0,
                    "scroll_down": 180.0 * int(step.get("repeats") or 1),
                    "fb_tap_comment_target": 180.0,
                    "fb_apply_comment_filter": 220.0,
                }[step_type]
                self._run_resource(stats, "u2", step_type, default)
                continue
            self._run_resource(stats, "cpu", step_type or "unknown", 20.0)
        return True

    def run_phone(self, serial: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        device = _SimDevice(serial)
        stats = _BenchStats()
        started = time.perf_counter()
        ok = self._run_steps(device, steps, stats)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "serial": serial,
            "ok": ok,
            "elapsed_ms": elapsed_ms,
            "virtual_ms": sum(stats.resource_virtual_ms.values()),
            "resources": stats.resource_virtual_ms,
            "resource_wait_ms": stats.resource_wait_ms,
            "phases": stats.phase_virtual_ms,
            "phase_wait_ms": stats.phase_wait_ms,
            "steps": stats.step_counts,
            "errors": stats.errors[:3],
            "taps": len(device.taps),
        }


def _summarize(samples: list[dict[str, Any]], resources: dict[str, _Resource]) -> dict[str, Any]:
    elapsed = [float(sample["elapsed_ms"]) for sample in samples]
    virtual = [float(sample["virtual_ms"]) for sample in samples]
    resource_totals: dict[str, float] = {}
    resource_wait_totals: dict[str, float] = {}
    phase_totals: dict[str, float] = {}
    phase_wait_totals: dict[str, float] = {}
    step_counts: dict[str, int] = {}
    errors: dict[str, int] = {}
    for sample in samples:
        for key, value in sample["resources"].items():
            resource_totals[key] = resource_totals.get(key, 0.0) + float(value)
        for key, value in sample.get("resource_wait_ms", {}).items():
            resource_wait_totals[key] = resource_wait_totals.get(key, 0.0) + float(value)
        for key, value in sample.get("phases", {}).items():
            phase_totals[key] = phase_totals.get(key, 0.0) + float(value)
        for key, value in sample.get("phase_wait_ms", {}).items():
            phase_wait_totals[key] = phase_wait_totals.get(key, 0.0) + float(value)
        for key, value in sample["steps"].items():
            step_counts[key] = step_counts.get(key, 0) + int(value)
        for error in sample["errors"]:
            errors[error] = errors.get(error, 0) + 1
    tail_samples = sorted(samples, key=lambda item: float(item["elapsed_ms"]), reverse=True)[:5]
    resource_pressure = {
        name: {
            "slots": resource.slots,
            "wait_p50_ms": _percentile(resource.wait_ms, 0.50),
            "wait_p95_ms": _percentile(resource.wait_ms, 0.95),
            "wait_max_ms": max(resource.wait_ms, default=0.0),
            "samples": len(resource.wait_ms),
            "max_active": resource.max_active,
            "active_p95": _percentile([float(v) for v in resource.active_samples], 0.95),
        }
        for name, resource in sorted(resources.items())
    }
    return {
        "phones": len(samples),
        "ok": sum(1 for sample in samples if sample["ok"]),
        "failed": sum(1 for sample in samples if not sample["ok"]),
        "elapsed_ms": {
            "p50": _percentile(elapsed, 0.50),
            "p95": _percentile(elapsed, 0.95),
            "max": max(elapsed, default=0.0),
            "mean": statistics.fmean(elapsed) if elapsed else 0.0,
        },
        "virtual_phone_ms": {
            "p50": _percentile(virtual, 0.50),
            "p95": _percentile(virtual, 0.95),
        },
        "resource_virtual_ms_total": dict(sorted(resource_totals.items())),
        "resource_wait_ms_total": dict(sorted(resource_wait_totals.items())),
        "resource_wait_ms_p95": {
            name: _percentile(resource.wait_ms, 0.95)
            for name, resource in sorted(resources.items())
        },
        "resource_pressure": resource_pressure,
        "critical_path_virtual_ms_total": dict(
            sorted(phase_totals.items(), key=lambda item: item[1], reverse=True)
        ),
        "critical_path_wait_ms_total": dict(
            sorted(phase_wait_totals.items(), key=lambda item: item[1], reverse=True)
        ),
        "top_critical_phases": sorted(
            phase_totals.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:8],
        "tail_phones": [
            {
                "serial": sample["serial"],
                "elapsed_ms": sample["elapsed_ms"],
                "virtual_ms": sample["virtual_ms"],
                "top_resources": sorted(
                    sample["resources"].items(),
                    key=lambda item: float(item[1]),
                    reverse=True,
                )[:4],
                "top_phases": sorted(
                    sample.get("phases", {}).items(),
                    key=lambda item: float(item[1]),
                    reverse=True,
                )[:4],
                "errors": sample["errors"],
            }
            for sample in tail_samples
        ],
        "step_counts": dict(sorted(step_counts.items())),
        "top_errors": sorted(errors.items(), key=lambda item: item[1], reverse=True)[:5],
    }


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario-id", default=os.getenv("CAMPAIGN_BENCH_SCENARIO_ID", ""))
    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "BENCH_DATABASE_URL",
            os.getenv("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5433/device_farm"),
        ),
    )
    parser.add_argument("--phones", type=int, default=100)
    parser.add_argument("--workers", type=int, default=100)
    parser.add_argument("--u2-slots", type=int, default=64)
    parser.add_argument("--extract-slots", type=int, default=64)
    parser.add_argument("--cpu-slots", type=int, default=8)
    parser.add_argument("--time-scale", type=float, default=0.01)
    parser.add_argument("--tap-wait-timeout-s", type=float, default=3.0)
    parser.add_argument("--comment-large-target-fast-scroll", action="store_true")
    parser.add_argument("--comment-large-target-swipes-per-dump", type=int, default=12)
    parser.add_argument("--comment-large-target-scroll-distance", type=float, default=0.68)
    parser.add_argument("--comment-large-target-duration-ms", type=int, default=80)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()

    if args.scenario_id:
        try:
            steps = await _load_scenario_steps(args.database_url, args.scenario_id)
            scenario_source = f"db:{args.scenario_id}"
        except Exception as exc:
            print(f"[campaign-100-heavy] DB scenario load failed: {exc}; using built-in heavy scenario")
            steps = _fallback_heavy_scenario()
            scenario_source = "built-in"
    else:
        steps = _fallback_heavy_scenario()
        scenario_source = "built-in"

    if args.comment_large_target_fast_scroll:
        _apply_comment_fast_scroll_profile(
            steps,
            swipes_per_dump=args.comment_large_target_swipes_per_dump,
            distance=args.comment_large_target_scroll_distance,
            duration_ms=args.comment_large_target_duration_ms,
        )

    resources = {
        "u2": _Resource("u2", args.u2_slots),
        "extract": _Resource("extract", args.extract_slots),
        "cpu": _Resource("cpu", args.cpu_slots),
    }
    simulator = _CampaignSimulator(
        resources=resources,
        time_scale=max(0.0, args.time_scale),
        tap_wait_timeout_s=max(0.01, args.tap_wait_timeout_s),
    )

    started = time.perf_counter()
    samples: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(simulator.run_phone, f"bench-{idx:04d}", steps)
            for idx in range(max(1, args.phones))
        ]
        for future in as_completed(futures):
            samples.append(future.result())
    wall_ms = (time.perf_counter() - started) * 1000.0

    summary = _summarize(samples, resources)
    result = {
        "kind": "campaign_100_heavy_benchmark",
        "scenario_source": scenario_source,
        "step_count": len(steps),
        "settings": {
            "phones": args.phones,
            "workers": args.workers,
            "u2_slots": args.u2_slots,
            "extract_slots": args.extract_slots,
            "cpu_slots": args.cpu_slots,
            "time_scale": args.time_scale,
            "tap_wait_timeout_s": args.tap_wait_timeout_s,
            "comment_large_target_fast_scroll": args.comment_large_target_fast_scroll,
            "comment_large_target_swipes_per_dump": args.comment_large_target_swipes_per_dump,
            "comment_large_target_scroll_distance": args.comment_large_target_scroll_distance,
            "comment_large_target_duration_ms": args.comment_large_target_duration_ms,
        },
        "wall_ms": wall_ms,
        "summary": summary,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_output:
        Path(args.json_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
