"""Structured Temporal tracing — activity lifecycle + hang diagnostics."""
from __future__ import annotations

import atexit
import contextlib
import importlib
import threading
import time
from collections.abc import Callable
from typing import Any

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)

trace_log = importlib.import_module("structlog").get_logger("temporal_trace")


class TemporalActivitySummary:
    """Aggregate activity outcomes into one compact payload per time window."""

    def __init__(
        self,
        *,
        interval_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 30.0 <= interval_s <= 60.0:
            raise ValueError("interval_s must be between 30 and 60 seconds")
        self._interval_s = interval_s
        self._clock = clock
        self._window_started_at: float | None = None
        self._stats: dict[str, dict[str, float | int]] = {}
        self._lock = threading.Lock()

    def record(
        self,
        *,
        activity_type: str,
        duration_ms: float,
        ok: bool,
        retried: bool,
    ) -> dict[str, Any] | None:
        """Record one completion and return a summary when the window is due."""
        with self._lock:
            now = self._clock()
            if self._window_started_at is None:
                self._window_started_at = now
            stats = self._stats.setdefault(
                activity_type,
                {
                    "completed": 0,
                    "failed": 0,
                    "retried": 0,
                    "total_duration_ms": 0.0,
                    "max_duration_ms": 0.0,
                },
            )
            stats["completed"] += 1
            stats["failed"] += int(not ok)
            stats["retried"] += int(retried)
            stats["total_duration_ms"] += duration_ms
            stats["max_duration_ms"] = max(
                float(stats["max_duration_ms"]),
                duration_ms,
            )

            window_s = now - self._window_started_at
            if window_s < self._interval_s:
                return None
            return self._drain_locked(now)

    def flush(self) -> dict[str, Any] | None:
        """Drain a non-empty window, including a quiet final window."""
        with self._lock:
            if not self._stats:
                return None
            return self._drain_locked(self._clock())

    def _drain_locked(self, now: float) -> dict[str, Any]:
        window_started_at = self._window_started_at
        if window_started_at is None:
            raise RuntimeError("cannot drain an activity summary without a window")
        activity_types = {
            name: {
                "completed": int(values["completed"]),
                "failed": int(values["failed"]),
                "retried": int(values["retried"]),
                "avg_duration_ms": round(
                    float(values["total_duration_ms"]) / int(values["completed"]),
                    1,
                ),
                "max_duration_ms": round(float(values["max_duration_ms"]), 1),
            }
            for name, values in sorted(self._stats.items())
        }
        window_s = now - window_started_at
        self._stats = {}
        self._window_started_at = None
        return {
            "window_s": round(window_s, 1),
            "activity_types": activity_types,
        }


_activity_summary = TemporalActivitySummary()
_activity_summary_stop = threading.Event()
_activity_summary_start_lock = threading.Lock()
_activity_summary_reporter_started = False


def _emit_activity_summary(summary: dict[str, Any] | None) -> None:
    if summary is not None:
        trace_log.info("temporal_activity_summary", **summary)


def _flush_activity_summary() -> None:
    _emit_activity_summary(_activity_summary.flush())


def _run_activity_summary_reporter() -> None:
    while not _activity_summary_stop.wait(60.0):
        _flush_activity_summary()


def _ensure_activity_summary_reporter() -> None:
    global _activity_summary_reporter_started
    if _activity_summary_reporter_started:
        return
    with _activity_summary_start_lock:
        if _activity_summary_reporter_started:
            return
        reporter = threading.Thread(
            target=_run_activity_summary_reporter,
            name="temporal-activity-summary",
            daemon=True,
        )
        reporter.start()
        _activity_summary_reporter_started = True


def _record_activity_outcome(
    *,
    activity_type: str,
    duration_ms: float,
    ok: bool,
    retried: bool,
) -> None:
    _ensure_activity_summary_reporter()
    _emit_activity_summary(
        _activity_summary.record(
            activity_type=activity_type,
            duration_ms=duration_ms,
            ok=ok,
            retried=retried,
        )
    )


def _shutdown_activity_summary_reporter() -> None:
    _activity_summary_stop.set()
    _flush_activity_summary()


atexit.register(_shutdown_activity_summary_reporter)


def activity_log_context() -> dict[str, Any]:
    """Best-effort context from the current Temporal activity."""
    ctx: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        if not activity.in_activity():
            return ctx
        info = activity.info()
        ctx.update(
            {
                "activity_type": info.activity_type,
                "activity_id": info.activity_id,
                "workflow_id": info.workflow_id,
                "workflow_type": info.workflow_type,
                "workflow_run_id": info.workflow_run_id,
                "attempt": info.attempt,
                "task_queue": info.task_queue,
                "start_to_close_timeout_s": (
                    info.start_to_close_timeout.total_seconds()
                    if info.start_to_close_timeout is not None
                    else None
                ),
            }
        )
    return ctx


def summarize_activity_input(args: tuple[Any, ...]) -> dict[str, Any]:
    """Extract safe, high-signal fields from activity input dataclasses."""
    if not args:
        return {}
    inp = args[0]
    summary: dict[str, Any] = {}
    for field in (
        "device_serial",
        "execution_id",
        "run_id",
        "campaign_id",
        "step_index",
        "timeout",
    ):
        if hasattr(inp, field):
            val = getattr(inp, field)
            if val is not None and val != "":
                summary[field] = val
    if hasattr(inp, "by") and hasattr(inp, "value"):
        summary["by"] = getattr(inp, "by")
        summary["value"] = getattr(inp, "value")
    steps = getattr(inp, "steps", None)
    if steps is not None:
        summary["batch_size"] = len(steps)
    step = getattr(inp, "step", None)
    if isinstance(step, dict) and step.get("type"):
        summary["step_type"] = step.get("type")
    return summary


class TemporalTraceInterceptor(Interceptor):
    """Log activity start/end with duration and cancellation hints."""

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        return _TemporalTraceActivityInbound(next)


class _TemporalTraceActivityInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        started = time.perf_counter()
        ctx = {
            **activity_log_context(),
            **summarize_activity_input(input.args),
            "fn": getattr(input.fn, "__name__", str(input.fn)),
        }
        retried = int(ctx.get("attempt") or 1) > 1
        trace_log.debug("temporal_activity_start", **ctx)
        if retried:
            trace_log.warning("temporal_activity_retry", **ctx)
        try:
            result = await self.next.execute_activity(input)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            duration_ms = round(elapsed_ms, 1)
            trace_log.debug(
                "temporal_activity_end",
                **ctx,
                duration_ms=duration_ms,
                ok=True,
            )
            _record_activity_outcome(
                activity_type=str(ctx.get("activity_type") or ctx["fn"]),
                duration_ms=duration_ms,
                ok=True,
                retried=retried,
            )
            return result
        except BaseException as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            duration_ms = round(elapsed_ms, 1)
            cancelled = False
            with contextlib.suppress(Exception):
                cancelled = activity.is_cancelled()
            trace_log.warning(
                "temporal_activity_end",
                **ctx,
                duration_ms=duration_ms,
                ok=False,
                cancelled=cancelled,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            _record_activity_outcome(
                activity_type=str(ctx.get("activity_type") or ctx["fn"]),
                duration_ms=duration_ms,
                ok=False,
                retried=retried,
            )
            raise
