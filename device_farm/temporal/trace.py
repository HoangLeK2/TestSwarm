"""Structured Temporal tracing — activity lifecycle + hang diagnostics."""
from __future__ import annotations

import contextlib
import importlib
import time
from typing import Any

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)

trace_log = importlib.import_module("structlog").get_logger("temporal_trace")


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
        trace_log.info("temporal_activity_start", **ctx)
        try:
            result = await self.next.execute_activity(input)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            trace_log.info(
                "temporal_activity_end",
                **ctx,
                duration_ms=round(elapsed_ms, 1),
                ok=True,
            )
            return result
        except BaseException as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            cancelled = False
            with contextlib.suppress(Exception):
                cancelled = activity.is_cancelled()
            trace_log.warning(
                "temporal_activity_end",
                **ctx,
                duration_ms=round(elapsed_ms, 1),
                ok=False,
                cancelled=cancelled,
                error_type=type(exc).__name__,
                error=str(exc)[:500],
            )
            raise
