"""Loop bodies must stop themselves before Temporal terminates the run.

continue_as_new is unreachable from inside a loop: _execute_child_steps recurses
into run() at depth+1 within the same workflow, and the depth==0 guard never
runs again once a loop is entered. A 200-iteration loop therefore grew event
history until the server killed the run — losing the whole trace, including the
iterations that had already succeeded.

These tests pin the alternative: stop deliberately, keep what ran.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services.execution.reason_codes import LOOP_HISTORY_LIMIT
from temporal.shared import StepsInput, StepsResult
from temporal.workflows import ScenarioStepsWorkflow


class _FakeInfo:
    """workflow.info() stand-in that trips the suggestion at a given call."""

    def __init__(self, suggest_after_calls: int, history_length: int = 0) -> None:
        self._suggest_after = suggest_after_calls
        self._history_length = history_length
        self.calls = 0

    def is_continue_as_new_suggested(self) -> bool:
        self.calls += 1
        return self.calls > self._suggest_after

    def get_current_history_length(self) -> int:
        return self._history_length


def _inp(steps: list[dict]) -> StepsInput:
    return StepsInput(
        device_serial="dev1",
        steps=steps,
        campaign_id="camp-1",
        run_id="run-1",
        execution_id="exec-1",
    )


async def _run_handler(handler_name: str, step: dict, *, suggest_after: int):
    wf = ScenarioStepsWorkflow()
    info = _FakeInfo(suggest_after)
    iterations_started: list[int] = []

    async def fake_child_steps(parent_inp, steps, runtime_vars, runtime_context, **kw):
        iterations_started.append(len(iterations_started))
        return StepsResult(success=True, steps_executed=len(steps))

    wf._execute_child_steps = fake_child_steps  # type: ignore[method-assign]

    with patch("temporal.workflows.workflow.info", return_value=info), patch(
        "temporal.workflows.workflow.now",
        return_value=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ), patch(
        "temporal.workflows.workflow.patched", return_value=True
    ):
        result = await getattr(wf, handler_name)(
            _inp([step]), step, {}, {}, 0,
        )
    return result, iterations_started


@pytest.mark.asyncio
async def test_loop_stops_at_the_history_limit_and_keeps_finished_iterations():
    step = {"type": "loop", "count": 100, "steps": [{"type": "tap"}]}
    (ok, message, sub_results, _ctx, payload), started = await _run_handler(
        "_handle_loop", step, suggest_after=3,
    )

    assert ok is False
    assert payload["reason_code"] == LOOP_HISTORY_LIMIT
    assert payload["stopped_by"] == "history_limit"
    # Every iteration that ran succeeded — this is a budget stop, not a failure.
    assert payload["partial"] is True
    # Three iterations were allowed through; the fourth check stopped the loop.
    assert len(started) == 3
    assert payload["iterations_run"] == 3
    assert len(sub_results) == 3
    assert LOOP_HISTORY_LIMIT in message
    # The message lands in Temporal history, where it can never be corrected for
    # a run already in flight. Ship the code; the UI owns the wording.
    assert message.isascii()


@pytest.mark.asyncio
async def test_loop_runs_to_completion_when_history_is_healthy():
    step = {"type": "loop", "count": 4, "steps": [{"type": "tap"}]}
    (ok, _message, sub_results, _ctx, payload), started = await _run_handler(
        "_handle_loop", step, suggest_after=1_000,
    )

    assert ok is True
    assert payload["stopped_by"] == "count"
    assert len(started) == 4
    assert len(sub_results) == 4


@pytest.mark.asyncio
async def test_repeat_stops_at_the_history_limit():
    step = {"type": "repeat", "count": 100, "steps": [{"type": "tap"}]}
    (ok, message, sub_results, _ctx, payload), started = await _run_handler(
        "_handle_repeat", step, suggest_after=2,
    )

    assert ok is False
    assert payload["reason_code"] == LOOP_HISTORY_LIMIT
    assert payload["stopped_by"] == "history_limit"
    assert payload["partial"] is True
    assert message.isascii()
    assert len(started) == 2
    assert len(sub_results) == 2


@pytest.mark.asyncio
async def test_repeat_until_stops_at_the_history_limit():
    step = {
        "type": "repeat_until",
        "condition": {"type": "element_exists", "by": "text", "value": "Done"},
        "max_iterations": 100,
        "steps": [{"type": "tap"}],
    }
    wf = ScenarioStepsWorkflow()
    info = _FakeInfo(2)

    async def never_met(*_a, **_kw):
        return False

    async def fake_child_steps(parent_inp, steps, runtime_vars, runtime_context, **kw):
        return StepsResult(success=True, steps_executed=len(steps))

    wf._execute_child_steps = fake_child_steps  # type: ignore[method-assign]

    with patch("temporal.workflows.workflow.info", return_value=info), patch(
        "temporal.workflows.workflow.now",
        return_value=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ), patch(
        "temporal.workflows.workflow.patched", return_value=True
    ), patch("temporal.workflows.workflow.execute_activity", new=never_met), patch(
        "temporal.workflows.control_task_queue", return_value="device-control"
    ):
        ok, message, _ctx, payload = await wf._handle_repeat_until(
            _inp([step]), step, {}, {}, 0,
        )

    assert ok is False
    assert payload["reason_code"] == LOOP_HISTORY_LIMIT
    assert payload["stopped_by"] == "history_limit"
    assert payload["partial"] is True
    assert payload["iterations_run"] == 2
    assert message.isascii()
