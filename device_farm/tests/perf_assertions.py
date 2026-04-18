from __future__ import annotations

import os
import tracemalloc
from dataclasses import dataclass


def perf_budget(env_name: str, default: float) -> float:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    pos = max(0.0, min(1.0, p)) * (len(vals) - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= len(vals) - 1:
        return vals[-1]
    return vals[idx] + (vals[idx + 1] - vals[idx]) * frac


def assert_p95(values_ms: list[float], budget_ms: float, *, label: str) -> None:
    p95 = percentile(values_ms, 0.95)
    assert p95 <= budget_ms, (
        f"{label}: p95={p95:.2f}ms exceeds budget={budget_ms:.2f}ms "
        f"(n={len(values_ms)})"
    )


def assert_queue_growth(max_pending: int, end_pending: int, max_budget: int, *, label: str) -> None:
    assert max_pending <= max_budget, (
        f"{label}: max_pending={max_pending} exceeds budget={max_budget}"
    )
    assert end_pending == 0, f"{label}: queue not drained (end_pending={end_pending})"


def assert_peak_memory(peak_mb: float, budget_mb: float, *, label: str) -> None:
    assert peak_mb <= budget_mb, (
        f"{label}: peak={peak_mb:.2f}MB exceeds budget={budget_mb:.2f}MB"
    )


@dataclass
class MemoryTracker:
    enabled: bool = True
    _started: bool = False
    peak_bytes: int = 0

    def __enter__(self) -> "MemoryTracker":
        if self.enabled:
            tracemalloc.start()
            self._started = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._started:
            _current, peak = tracemalloc.get_traced_memory()
            self.peak_bytes = int(peak)
            tracemalloc.stop()
            self._started = False

    @property
    def peak_mb(self) -> float:
        return self.peak_bytes / (1024.0 * 1024.0)
