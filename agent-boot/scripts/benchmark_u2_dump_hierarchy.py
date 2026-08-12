from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DumpCase:
    name: str
    compressed: bool
    max_depth: int | None
    pretty: bool = False


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) < 20:
        return max(values)
    return statistics.quantiles(values, n=100, method="inclusive")[94]


def _set_configurator(dev: Any, *, wait_for_idle_ms: int | None, selector_timeout_ms: int | None) -> dict[str, Any] | None:
    updates: dict[str, int] = {}
    if wait_for_idle_ms is not None:
        updates["waitForIdleTimeout"] = int(wait_for_idle_ms)
    if selector_timeout_ms is not None:
        updates["waitForSelectorTimeout"] = int(selector_timeout_ms)
    if not updates:
        return None
    try:
        before = dev.jsonrpc.getConfigurator()
    except Exception:
        before = None
    dev.jsonrpc.setConfigurator(updates)
    return before if isinstance(before, dict) else None


def _restore_configurator(dev: Any, before: dict[str, Any] | None) -> None:
    if not before:
        return
    restore = {
        key: int(value)
        for key, value in before.items()
        if key in {"waitForIdleTimeout", "waitForSelectorTimeout"}
        and isinstance(value, int)
    }
    if restore:
        try:
            dev.jsonrpc.setConfigurator(restore)
        except Exception:
            pass


def _dump_once(dev: Any, case: DumpCase) -> tuple[float, int, int]:
    kwargs: dict[str, Any] = {
        "compressed": case.compressed,
        "pretty": case.pretty,
    }
    if case.max_depth is not None:
        kwargs["max_depth"] = case.max_depth
    started = time.perf_counter()
    xml = dev.dump_hierarchy(**kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not isinstance(xml, str) or "<hierarchy" not in xml:
        raise RuntimeError(f"{case.name}: invalid hierarchy dump")
    return elapsed_ms, len(xml.encode("utf-8")), xml.count("<node")


def _bench_case(dev: Any, case: DumpCase, *, iterations: int, warmup: int) -> dict[str, Any]:
    for _ in range(warmup):
        _dump_once(dev, case)
    timings: list[float] = []
    bytes_values: list[int] = []
    node_values: list[int] = []
    failures = 0
    for _ in range(iterations):
        try:
            elapsed_ms, xml_bytes, nodes = _dump_once(dev, case)
        except Exception:
            failures += 1
            continue
        timings.append(elapsed_ms)
        bytes_values.append(xml_bytes)
        node_values.append(nodes)
    if not timings:
        return {
            "case": case.name,
            "iterations": iterations,
            "success": 0,
            "failures": failures,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
            "avg_bytes": 0,
            "avg_nodes": 0,
        }
    return {
        "case": case.name,
        "iterations": iterations,
        "success": len(timings),
        "failures": failures,
        "p50_ms": statistics.median(timings),
        "p95_ms": _p95(timings),
        "max_ms": max(timings),
        "avg_bytes": int(statistics.mean(bytes_values)),
        "avg_nodes": int(statistics.mean(node_values)),
    }


def _cases(max_depths: list[int]) -> list[DumpCase]:
    cases = [
        DumpCase("raw_depth_default", compressed=False, max_depth=None),
        DumpCase("compressed_depth_default", compressed=True, max_depth=None),
    ]
    for depth in max_depths:
        cases.append(DumpCase(f"raw_depth_{depth}", compressed=False, max_depth=depth))
        cases.append(DumpCase(f"compressed_depth_{depth}", compressed=True, max_depth=depth))
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark uiautomator2 dump_hierarchy speed.")
    parser.add_argument("--serial", required=True, help="ADB/uiautomator2 serial or atx-agent endpoint.")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--max-depth", action="append", type=int, default=[30, 20])
    parser.add_argument("--wait-for-idle-ms", type=int, default=None)
    parser.add_argument("--selector-timeout-ms", type=int, default=None)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args()

    import uiautomator2 as u2

    dev = u2.connect(args.serial)
    before = _set_configurator(
        dev,
        wait_for_idle_ms=args.wait_for_idle_ms,
        selector_timeout_ms=args.selector_timeout_ms,
    )
    rows: list[dict[str, Any]] = []
    try:
        for case in _cases(args.max_depth):
            rows.append(_bench_case(dev, case, iterations=args.iterations, warmup=args.warmup))
    finally:
        _restore_configurator(dev, before)

    fieldnames = ["case", "iterations", "success", "failures", "p50_ms", "p95_ms", "max_ms", "avg_bytes", "avg_nodes"]
    print(",".join(fieldnames))
    for row in rows:
        print(
            f"{row['case']},{row['iterations']},{row['success']},{row['failures']},"
            f"{row['p50_ms']:.3f},{row['p95_ms']:.3f},{row['max_ms']:.3f},"
            f"{row['avg_bytes']},{row['avg_nodes']}"
        )
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
