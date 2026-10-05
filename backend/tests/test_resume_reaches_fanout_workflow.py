"""Pause/resume/cancel must resolve the workflow a fan-out run actually uses.

When a batch is paused mid-flight the scenario workflow parks on

    await workflow.wait_condition(... self._resume_generation > resume_generation)

which only a Temporal *signal* can satisfy — it does not poll the Redis pause
flag. So resume works only if the signal reaches the right workflow ID.

A fan-out dispatch names its workflow `exec_<execution_id>` and does not record
that name in the execution's meta. The resolver built IDs from meta (empty) and
from the campaign/device template `campaign:<id>:device:<serial>:scenario:…`
(which no fan-out run uses), and `_signal_one` swallows a signal sent to a
workflow that does not exist. Every control call reported success while reaching
nothing; resume was the visible casualty — the scenario simply never continued.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.execution_control import (
    _resolve_workflow_ids_for_campaign,
    _resolve_workflow_ids_for_execution,
)


def _fan_out_execution(execution_id: str = "exec-42") -> SimpleNamespace:
    """A dispatched execution: rich meta, but no workflow_id in it."""
    return SimpleNamespace(
        id=execution_id,
        status="running",
        campaign_id="camp-1",
        user_id="user-1",
        meta={
            "dispatch_id": "disp-1",
            "dispatch_strategy": "parallel",
            "source_kind": "explicit",
        },
    )


@pytest.mark.asyncio
async def test_execution_resolver_reaches_the_fan_out_workflow():
    ex = _fan_out_execution()

    with patch(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    ):
        ids = await _resolve_workflow_ids_for_execution(
            AsyncMock(), ex, temporal_client=None
        )

    assert "exec_exec-42" in ids


@pytest.mark.asyncio
async def test_campaign_resolver_reaches_the_fan_out_workflow():
    ex = _fan_out_execution()

    with patch(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    ):
        ids = await _resolve_workflow_ids_for_campaign(
            AsyncMock(), "camp-1", [ex], temporal_client=None
        )

    assert "exec_exec-42" in ids


@pytest.mark.asyncio
async def test_legacy_device_workflow_ids_are_still_produced():
    """The reconstruction is additive.

    Older campaign runs really are campaign:<id>:device:<serial>:scenario:…, and
    dropping those in favour of the exec_ name would break pause on every one of
    them — trading one broken shape for another.
    """
    ex = _fan_out_execution()

    with patch(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    ):
        ids = await _resolve_workflow_ids_for_execution(
            AsyncMock(), ex, temporal_client=None
        )

    assert "campaign:camp-1:device:SN001:scenario:__sequence__" in ids


@pytest.mark.asyncio
async def test_meta_recorded_workflow_id_still_wins_and_is_kept():
    """When the dispatcher does record the name, it must survive."""
    ex = _fan_out_execution()
    ex.meta = {**ex.meta, "workflow_id": "exec-42-custom"}

    with patch(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    ):
        ids = await _resolve_workflow_ids_for_execution(
            AsyncMock(), ex, temporal_client=None
        )

    assert "exec-42-custom" in ids
    assert "exec_exec-42" in ids
