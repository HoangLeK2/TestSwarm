"""Tests for temporal/trace.py structured logging helpers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import temporal.trace as temporal_trace
from temporal.shared import ElementCheckInput
from temporal.trace import TemporalActivitySummary, summarize_activity_input


@dataclass
class _BatchInput:
    device_serial: str
    execution_id: str
    steps: list[dict]


def test_summarize_activity_input_element_check():
    summary = summarize_activity_input(
        (
            ElementCheckInput(
                device_serial="10AE7S00HD002JK",
                by="text",
                value="OK",
                timeout=5.0,
                execution_id="exec-1",
            ),
        )
    )
    assert summary["device_serial"] == "10AE7S00HD002JK"
    assert summary["execution_id"] == "exec-1"
    assert summary["by"] == "text"
    assert summary["value"] == "OK"
    assert summary["timeout"] == 5.0


def test_summarize_activity_input_batch():
    summary = summarize_activity_input(
        (
            _BatchInput(
                device_serial="dev-1",
                execution_id="exec-2",
                steps=[{"type": "tap"}, {"type": "scroll"}],
            ),
        )
    )
    assert summary["batch_size"] == 2
    assert summary["device_serial"] == "dev-1"


def test_activity_summary_emits_one_grouped_info_payload_per_window():
    now = [100.0]
    summary = TemporalActivitySummary(interval_s=60.0, clock=lambda: now[0])

    assert (
        summary.record(
            activity_type="check_element_exists",
            duration_ms=100.0,
            ok=True,
            retried=False,
        )
        is None
    )
    now[0] = 130.0
    assert (
        summary.record(
            activity_type="execute_extract",
            duration_ms=400.0,
            ok=False,
            retried=True,
        )
        is None
    )

    now[0] = 160.0
    payload = summary.record(
        activity_type="check_element_exists",
        duration_ms=200.0,
        ok=True,
        retried=False,
    )

    assert payload == {
        "window_s": 60.0,
        "activity_types": {
            "check_element_exists": {
                "completed": 2,
                "failed": 0,
                "retried": 0,
                "avg_duration_ms": 150.0,
                "max_duration_ms": 200.0,
            },
            "execute_extract": {
                "completed": 1,
                "failed": 1,
                "retried": 1,
                "avg_duration_ms": 400.0,
                "max_duration_ms": 400.0,
            },
        },
    }

    now[0] = 161.0
    assert (
        summary.record(
            activity_type="execute_extract",
            duration_ms=50.0,
            ok=True,
            retried=False,
        )
        is None
    )


def test_activity_summary_flushes_a_nonempty_idle_window_without_a_new_completion():
    now = [100.0]
    summary = TemporalActivitySummary(interval_s=60.0, clock=lambda: now[0])
    summary.record(
        activity_type="execute_extract",
        duration_ms=250.0,
        ok=True,
        retried=False,
    )

    now[0] = 160.0
    payload = summary.flush()

    assert payload == {
        "window_s": 60.0,
        "activity_types": {
            "execute_extract": {
                "completed": 1,
                "failed": 0,
                "retried": 0,
                "avg_duration_ms": 250.0,
                "max_duration_ms": 250.0,
            }
        },
    }
    assert summary.flush() is None


def test_activity_summary_reporter_flushes_on_the_60_second_clock(monkeypatch):
    stop_event = Mock()
    stop_event.wait.side_effect = [False, True]
    flush = Mock()
    monkeypatch.setattr(temporal_trace, "_activity_summary_stop", stop_event)
    monkeypatch.setattr(temporal_trace, "_flush_activity_summary", flush)

    temporal_trace._run_activity_summary_reporter()

    assert [call.args for call in stop_event.wait.call_args_list] == [
        (60.0,),
        (60.0,),
    ]
    flush.assert_called_once_with()


def test_activity_summary_starts_a_fresh_window_after_a_long_idle_period():
    now = [100.0]
    summary = TemporalActivitySummary(interval_s=60.0, clock=lambda: now[0])

    now[0] = 500.0
    assert (
        summary.record(
            activity_type="execute_extract",
            duration_ms=100.0,
            ok=True,
            retried=False,
        )
        is None
    )

    now[0] = 560.0
    payload = summary.flush()
    assert payload is not None
    assert payload["window_s"] == 60.0


@pytest.mark.asyncio
async def test_successful_activity_lifecycle_is_debug_only(monkeypatch):
    logger = Mock()
    aggregate = Mock()
    aggregate.record.return_value = None
    next_inbound = SimpleNamespace(execute_activity=AsyncMock(return_value="done"))
    interceptor = temporal_trace._TemporalTraceActivityInbound(next_inbound)
    input_data = SimpleNamespace(args=(), fn=lambda: None)

    monkeypatch.setattr(temporal_trace, "trace_log", logger)
    monkeypatch.setattr(
        temporal_trace,
        "activity_log_context",
        lambda: {"activity_type": "execute_extract", "attempt": 1},
    )
    monkeypatch.setattr(temporal_trace, "_activity_summary", aggregate)

    assert await interceptor.execute_activity(input_data) == "done"

    assert [call.args[0] for call in logger.debug.call_args_list] == [
        "temporal_activity_start",
        "temporal_activity_end",
    ]
    logger.info.assert_not_called()
    logger.warning.assert_not_called()
    aggregate.record.assert_called_once_with(
        activity_type="execute_extract",
        duration_ms=pytest.approx(aggregate.record.call_args.kwargs["duration_ms"]),
        ok=True,
        retried=False,
    )


@pytest.mark.asyncio
async def test_retry_and_failure_remain_warning(monkeypatch):
    logger = Mock()
    aggregate = Mock()
    aggregate.record.return_value = None
    next_inbound = SimpleNamespace(
        execute_activity=AsyncMock(side_effect=TimeoutError("activity timed out"))
    )
    interceptor = temporal_trace._TemporalTraceActivityInbound(next_inbound)
    input_data = SimpleNamespace(args=(), fn=lambda: None)

    monkeypatch.setattr(temporal_trace, "trace_log", logger)
    monkeypatch.setattr(
        temporal_trace,
        "activity_log_context",
        lambda: {"activity_type": "execute_extract", "attempt": 2},
    )
    monkeypatch.setattr(temporal_trace, "_activity_summary", aggregate)

    with pytest.raises(TimeoutError, match="activity timed out"):
        await interceptor.execute_activity(input_data)

    assert [call.args[0] for call in logger.warning.call_args_list] == [
        "temporal_activity_retry",
        "temporal_activity_end",
    ]
    assert logger.warning.call_args_list[-1].kwargs["error_type"] == "TimeoutError"
    logger.info.assert_not_called()
    aggregate.record.assert_called_once()
    assert aggregate.record.call_args.kwargs["ok"] is False
    assert aggregate.record.call_args.kwargs["retried"] is True


@pytest.mark.asyncio
async def test_due_summary_is_the_only_info_lifecycle_event(monkeypatch):
    logger = Mock()
    aggregate = Mock()
    aggregate.record.return_value = {
        "window_s": 60.0,
        "activity_types": {"execute_extract": {"completed": 1}},
    }
    next_inbound = SimpleNamespace(execute_activity=AsyncMock(return_value="done"))
    interceptor = temporal_trace._TemporalTraceActivityInbound(next_inbound)

    monkeypatch.setattr(temporal_trace, "trace_log", logger)
    monkeypatch.setattr(
        temporal_trace,
        "activity_log_context",
        lambda: {"activity_type": "execute_extract", "attempt": 1},
    )
    monkeypatch.setattr(temporal_trace, "_activity_summary", aggregate)

    await interceptor.execute_activity(SimpleNamespace(args=(), fn=lambda: None))

    logger.info.assert_called_once_with(
        "temporal_activity_summary",
        window_s=60.0,
        activity_types={"execute_extract": {"completed": 1}},
    )


@pytest.mark.asyncio
async def test_cancelled_activity_end_remains_warning(monkeypatch):
    logger = Mock()
    aggregate = Mock()
    aggregate.record.return_value = None
    next_inbound = SimpleNamespace(
        execute_activity=AsyncMock(side_effect=asyncio.CancelledError())
    )
    interceptor = temporal_trace._TemporalTraceActivityInbound(next_inbound)

    monkeypatch.setattr(temporal_trace, "trace_log", logger)
    monkeypatch.setattr(
        temporal_trace,
        "activity_log_context",
        lambda: {"activity_type": "execute_extract", "attempt": 1},
    )
    monkeypatch.setattr(temporal_trace, "_activity_summary", aggregate)
    monkeypatch.setattr(temporal_trace.activity, "is_cancelled", lambda: True)

    with pytest.raises(asyncio.CancelledError):
        await interceptor.execute_activity(SimpleNamespace(args=(), fn=lambda: None))

    logger.warning.assert_called_once()
    assert logger.warning.call_args.args[0] == "temporal_activity_end"
    assert logger.warning.call_args.kwargs["cancelled"] is True
    assert logger.warning.call_args.kwargs["error_type"] == "CancelledError"
