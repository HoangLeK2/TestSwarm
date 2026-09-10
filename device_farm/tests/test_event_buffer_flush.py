"""Buffered telemetry must also ship on age, not only on batch size.

Batching workflow-side events cut two activities per step out of event history,
but a scenario shorter than _EVENT_BUFFER_FLUSH_AT events showed the operator a
blank trace until the run ended. workflow.now() is deterministic on replay, so
an age-based flush stays replay-safe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from temporal.shared import StepsInput
from temporal.workflows import (
    _EVENT_BUFFER_FLUSH_AT,
    _EVENT_BUFFER_MAX_AGE,
    ScenarioStepsWorkflow,
)


_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _inp() -> StepsInput:
    return StepsInput(
        device_serial="dev1",
        steps=[],
        campaign_id="camp-1",
        run_id="run-1",
        execution_id="exec-1",
    )


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


async def _buffer_at(offsets: list[timedelta]) -> list[list[dict]]:
    """Buffer one event at each offset from T0; return the batches that shipped."""
    wf = ScenarioStepsWorkflow()
    clock = _Clock()
    batches: list[list[dict]] = []

    async def fake_activity(_name, arg, **_kw):
        batches.append(list(arg["events"]))

    with patch("temporal.workflows.workflow.now", new=clock), patch(
        "temporal.workflows.workflow.execute_activity", new=fake_activity
    ), patch("temporal.workflows.control_task_queue", return_value="device-control"):
        for offset in offsets:
            clock.now = _T0 + offset
            await wf._buffer_event(_inp(), "step", {"step_index": len(batches)})
    return batches


@pytest.mark.asyncio
async def test_buffer_holds_events_that_are_still_fresh():
    batches = await _buffer_at(
        [timedelta(0), timedelta(seconds=1), timedelta(seconds=2)]
    )

    assert batches == []


@pytest.mark.asyncio
async def test_buffer_flushes_once_the_oldest_event_is_overdue():
    batches = await _buffer_at(
        [
            timedelta(0),
            timedelta(seconds=1),
            _EVENT_BUFFER_MAX_AGE + timedelta(seconds=1),
        ]
    )

    # All three ship together on the third call — well short of the size trigger.
    assert len(batches) == 1
    assert len(batches[0]) == 3
    assert len(batches[0]) < _EVENT_BUFFER_FLUSH_AT


@pytest.mark.asyncio
async def test_flush_restarts_the_age_window():
    batches = await _buffer_at(
        [
            timedelta(0),
            _EVENT_BUFFER_MAX_AGE + timedelta(seconds=1),
            _EVENT_BUFFER_MAX_AGE + timedelta(seconds=2),
            2 * _EVENT_BUFFER_MAX_AGE + timedelta(seconds=3),
        ]
    )

    assert [len(batch) for batch in batches] == [2, 2]


@pytest.mark.asyncio
async def test_buffer_still_flushes_on_size_within_the_age_window():
    batches = await _buffer_at([timedelta(0)] * _EVENT_BUFFER_FLUSH_AT)

    assert len(batches) == 1
    assert len(batches[0]) == _EVENT_BUFFER_FLUSH_AT


@pytest.mark.asyncio
async def test_buffered_events_carry_their_own_occurred_at():
    wf = ScenarioStepsWorkflow()
    clock = _Clock()
    shipped: list[dict] = []

    async def fake_activity(_name, arg, **_kw):
        shipped.extend(arg["events"])

    with patch("temporal.workflows.workflow.now", new=clock), patch(
        "temporal.workflows.workflow.execute_activity", new=fake_activity
    ), patch("temporal.workflows.control_task_queue", return_value="device-control"):
        clock.now = _T0
        await wf._buffer_event(_inp(), "step", {"step_index": 0})
        clock.now = _T0 + timedelta(seconds=5)
        await wf._buffer_event(_inp(), "step", {"step_index": 1})
        await wf._flush_events(_inp())

    assert [event["occurred_at"] for event in shipped] == [
        _T0.isoformat(),
        (_T0 + timedelta(seconds=5)).isoformat(),
    ]
