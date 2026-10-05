from unittest.mock import AsyncMock, patch

import pytest

from services.execution.activity_events import emit_temporal_activity_event
from services.execution.event_types import (
    ALL_EXECUTION_EVENT_TYPES,
    TEMPORAL_ACTIVITY_COMPLETED,
    TEMPORAL_ACTIVITY_EVENTS,
    TEMPORAL_ACTIVITY_SCHEDULED,
)


def test_temporal_activity_event_types_are_registered():
    assert TEMPORAL_ACTIVITY_SCHEDULED in TEMPORAL_ACTIVITY_EVENTS
    assert TEMPORAL_ACTIVITY_COMPLETED in TEMPORAL_ACTIVITY_EVENTS
    assert TEMPORAL_ACTIVITY_EVENTS.issubset(ALL_EXECUTION_EVENT_TYPES)


@pytest.mark.asyncio
async def test_emit_temporal_activity_event_enqueues_bounded_payload():
    db = AsyncMock()

    with patch(
        "services.execution.activity_events.enqueue_execution_event",
        AsyncMock(),
    ) as enqueue:
        await emit_temporal_activity_event(
            db,
            execution_id="exec-1",
            org_id="org-1",
            campaign_id="camp-1",
            event_type=TEMPORAL_ACTIVITY_SCHEDULED,
            step_id="tap-primary",
            step_index=7,
            step_type="tap",
            depth=1,
            trace_context={"step_path": "root/tap-primary"},
            payload={
                "activity_id": "step:exec-1:tap-primary:tap:attempt:1",
                "step_activity_id": "step:exec-1:tap-primary:tap:attempt:1",
                "side_effect_class": "device_effect",
                "activity_attempt": 1,
                "phase": "scheduled",
                "stalled_reason": "temporal_activity_timeout",
                "batch_step_activity_ids": [
                    "step:exec-1:tap-primary:tap:attempt:1",
                ],
                "not_allowed": "drop-me",
            },
        )

    enqueue.assert_awaited_once()
    kwargs = enqueue.await_args.kwargs
    assert kwargs["event_type"] == TEMPORAL_ACTIVITY_SCHEDULED
    assert kwargs["execution_id"] == "exec-1"
    assert kwargs["organization_id"] == "org-1"
    assert kwargs["campaign_id"] == "camp-1"
    assert kwargs["step_id"] == "tap-primary"
    payload = kwargs["payload"]
    assert payload["temporal_activity"] is True
    assert payload["activity_id"] == "step:exec-1:tap-primary:tap:attempt:1"
    assert payload["side_effect_class"] == "device_effect"
    assert payload["activity_attempt"] == 1
    assert payload["phase"] == "scheduled"
    assert payload["stalled_reason"] == "temporal_activity_timeout"
    assert payload["step_index"] == 7
    assert payload["step_type"] == "tap"
    assert payload["trace"]["step_path"] == "root/tap-primary"
    assert "not_allowed" not in payload


@pytest.mark.asyncio
async def test_emit_temporal_activity_event_ignores_unknown_event_type():
    db = AsyncMock()

    with patch(
        "services.execution.activity_events.enqueue_execution_event",
        AsyncMock(),
    ) as enqueue:
        await emit_temporal_activity_event(
            db,
            execution_id="exec-1",
            org_id="org-1",
            campaign_id="camp-1",
            event_type="step.started",
            step_id="tap-primary",
            step_index=7,
            step_type="tap",
        )

    enqueue.assert_not_awaited()
