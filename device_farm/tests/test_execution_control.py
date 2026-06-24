"""Tests for execution pause/resume/cancel control (DF-T-04-016)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.execution_control import (
    CANCEL_UNDO_WARNING,
    ExecutionControlError,
    cancel_execution,
    pause_campaign_executions,
    pause_execution,
    resume_execution,
    _resolve_workflow_ids_for_campaign,
    _resolve_workflow_ids_for_execution,
)


def _execution(
    *,
    status: str = "running",
    meta: dict | None = None,
    campaign_id: str = "camp-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="exec-1",
        status=status,
        campaign_id=campaign_id,
        user_id="user-1",
        meta=meta or {"workflow_ids": ["campaign:camp-1:device:SN:scenario:__sequence__"]},
        pause_signal_received_at=None,
        cancel_signal_received_at=None,
        cancelled_at=None,
        cancel_reason=None,
    )


@pytest.mark.asyncio
async def test_emit_execution_event_enqueues_and_logs_activity():
    db = AsyncMock()
    ex = _execution(status="paused", meta={"org_id": "org-1"})
    event_row = SimpleNamespace(event_id="evt-1")

    with patch(
        "services.execution.event_publisher.enqueue_execution_event",
        AsyncMock(return_value=event_row),
    ) as enqueue:
        with patch(
            "services.execution_control.log_activity",
            AsyncMock(),
        ) as activity:
            with patch(
                "services.execution_control._resolve_org_id",
                AsyncMock(return_value="org-1"),
            ):
                with patch("services.webhook_dispatcher.dispatch_webhook", AsyncMock()):
                    from services.execution_control import _emit_execution_event

                    await _emit_execution_event(
                        db,
                        ex,
                        "execution.paused",
                        user_id="user-1",
                        before_status="running",
                        details={"workflows_signalled": 1},
                    )

    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["event_type"] == "execution.paused"
    activity.assert_awaited_once()
    assert activity.await_args.kwargs["before_state"] == {"status": "running"}
    assert activity.await_args.kwargs["event_id"] == "evt-1"


@pytest.mark.asyncio
async def test_pause_completed_rejected():
    db = AsyncMock()
    ex = _execution(status="completed")
    with patch("services.execution_control.get_execution", AsyncMock(return_value=ex)):
        with pytest.raises(ExecutionControlError) as err:
            await pause_execution(db, "exec-1", user_id="user-1", temporal_client=None)
    assert err.value.status_code == 409
    assert err.value.code == "INVALID_ACTION"


@pytest.mark.asyncio
async def test_pause_idempotent_skips_temporal_signal():
    db = AsyncMock()
    ex = _execution(status="paused")
    with patch("services.execution_control.get_execution", AsyncMock(return_value=ex)):
        with patch("services.execution_control._signal_workflow_ids", AsyncMock()) as sig:
            result = await pause_execution(db, "exec-1", user_id="user-1", temporal_client=MagicMock())
    assert result.effective_transition is False
    assert result.workflows_signalled == 0
    sig.assert_not_awaited()


@pytest.mark.asyncio
async def test_pause_running_signals_once():
    db = AsyncMock()
    ex = _execution(status="running")
    paused_ex = _execution(status="paused")

    with patch("services.execution_control.get_execution", AsyncMock(return_value=ex)):
        with patch("services.execution_control._has_open_dlq", AsyncMock(return_value=False)):
            with patch(
                "services.execution_control.pause_execution_record",
                AsyncMock(return_value=(paused_ex, True)),
            ):
                with patch(
                    "services.execution_control._resolve_workflow_ids_for_execution",
                    AsyncMock(return_value=["wf-1"]),
                ):
                    with patch(
                        "services.execution_control._signal_workflow_ids",
                        AsyncMock(return_value=1),
                    ) as sig:
                        with patch(
                            "services.execution_control._emit_execution_event",
                            AsyncMock(),
                        ) as audit:
                            result = await pause_execution(
                                db, "exec-1", user_id="user-1", temporal_client=MagicMock(),
                            )
    assert result.effective_transition is True
    sig.assert_awaited_once()
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_from_paused():
    db = AsyncMock()
    ex = _execution(status="paused")
    running_ex = _execution(status="running")

    with patch("services.execution_control.get_execution", AsyncMock(return_value=ex)):
        with patch(
            "services.execution_control.resume_execution_record",
            AsyncMock(return_value=running_ex),
        ):
            with patch(
                "services.execution_control._resolve_workflow_ids_for_execution",
                AsyncMock(return_value=["wf-1"]),
            ):
                with patch(
                    "services.execution_control._signal_workflow_ids",
                    AsyncMock(return_value=1),
                ):
                    with patch("services.execution_control._emit_execution_event", AsyncMock()):
                        result = await resume_execution(
                            db, "exec-1", user_id="user-1", temporal_client=MagicMock(),
                        )
    assert result.status == "running"
    assert result.effective_transition is True


@pytest.mark.asyncio
async def test_cancel_returns_undo_warning():
    db = AsyncMock()
    ex = _execution(status="running")
    cancelled_ex = _execution(status="cancelled")
    cancelled_ex.cancel_reason = "emergency"

    with patch("services.execution_control.get_execution", AsyncMock(return_value=ex)):
        with patch(
            "services.execution_control.cancel_execution_record",
            AsyncMock(return_value=(cancelled_ex, True)),
        ):
            with patch(
                "services.execution_control._resolve_workflow_ids_for_execution",
                AsyncMock(return_value=["wf-1"]),
            ):
                with patch(
                    "services.execution_control._signal_workflow_ids",
                    AsyncMock(return_value=1),
                ):
                    with patch(
                        "services.execution_control._release_execution_devices",
                        AsyncMock(return_value=["SN001"]),
                    ):
                        with patch(
                            "services.execution_control._emit_execution_event",
                            AsyncMock(),
                        ):
                            result = await cancel_execution(
                                db,
                                "exec-1",
                                user_id="user-1",
                                reason="emergency",
                                temporal_client=MagicMock(),
                            )
    assert result.warning == CANCEL_UNDO_WARNING
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_idempotent():
    db = AsyncMock()
    ex = _execution(status="cancelled")
    with patch("services.execution_control.get_execution", AsyncMock(return_value=ex)):
        result = await cancel_execution(db, "exec-1", user_id="user-1", temporal_client=None)
    assert result.effective_transition is False
    assert result.workflows_signalled == 0


@pytest.mark.asyncio
async def test_campaign_pause_signals_once():
    db = AsyncMock()
    ex = _execution(status="running")
    paused_ex = _execution(status="paused")

    with patch(
        "services.execution_control.list_running_executions_for_campaign",
        AsyncMock(return_value=[ex]),
    ):
        with patch(
            "services.execution_control._resolve_workflow_ids_for_campaign",
            AsyncMock(return_value=["wf-1", "wf-2"]),
        ):
            with patch(
                "services.execution_control.pause_execution",
                AsyncMock(return_value=SimpleNamespace(
                    execution_id="exec-1",
                    status="paused",
                    effective_transition=True,
                )),
            ) as pause_one:
                with patch(
                    "services.execution_control._signal_workflow_ids",
                    AsyncMock(return_value=2),
                ) as sig:
                    with patch(
                        "services.execution_control.update_campaign_status",
                        AsyncMock(),
                    ):
                        out = await pause_campaign_executions(
                            db, "camp-1", user_id="u1", temporal_client=MagicMock(),
                        )

    pause_one.assert_awaited_once()
    assert pause_one.await_args.kwargs.get("signal_temporal") is False
    sig.assert_awaited_once()
    assert sig.await_args[0][1] == ["wf-1", "wf-2"]
    assert out["workflows_signalled"] == 2


@pytest.mark.asyncio
async def test_campaign_workflow_resolution_ignores_other_campaign_meta():
    db = AsyncMock()
    ex = _execution(
        campaign_id="camp-2",
        meta={
            "workflow_ids": [
                "exec_other",
                "campaign:camp-1:device:SN001:scenario:shared",
            ],
        },
    )

    with patch(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    ):
        ids = await _resolve_workflow_ids_for_campaign(
            db,
            "camp-2",
            [ex],
            temporal_client=None,
        )

    assert ids == ["campaign:camp-2:device:SN001:scenario:__sequence__"]


@pytest.mark.asyncio
async def test_execution_workflow_resolution_ignores_other_campaign_meta():
    db = AsyncMock()
    ex = _execution(
        campaign_id="camp-2",
        meta={
            "workflow_ids": [
                "exec_other",
                "campaign:camp-1:device:SN001:scenario:shared",
            ],
        },
    )

    with patch(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    ):
        ids = await _resolve_workflow_ids_for_execution(
            db,
            ex,
            temporal_client=None,
        )

    assert ids == ["campaign:camp-2:device:SN001:scenario:__sequence__"]
