"""Cancelling a run must hand the phone back to the fleet.

A device reads BUSY because of its device_reserve_session claim, and nothing
else. `_release_execution_devices` ended the account usage and dropped the
in-process session_store entry, then returned — leaving the claim open. So
pressing Cancel stopped the run but left the phone busy with nothing running on
it, for the full 1800s campaign TTL, and it could not be dispatched to again.

The claim is released through the same helper the normal terminal path uses, so
the two agree on what "this execution is over" means for a device.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


async def _cancel(execution, *, org_id: str | None = "org-1"):
    from services import execution_control

    release_claim = AsyncMock()
    with (
        patch(
            "db.crud.execution.list_execution_devices",
            AsyncMock(return_value=[SimpleNamespace(id="dev-1", serial="SN001")]),
        ),
        patch(
            "services.campaign.dispatcher.release_execution_device_claim",
            release_claim,
        ),
        patch.object(
            execution_control,
            "_resolve_org_id",
            AsyncMock(return_value=org_id),
        ),
    ):
        serials = await execution_control._release_execution_devices(
            AsyncMock(), execution
        )
    return serials, release_claim


@pytest.mark.asyncio
async def test_cancel_releases_the_reserve_claim():
    execution = SimpleNamespace(
        id="exec-1",
        meta={},
        user_id="user-1",
        device_config={"claim_session_id": "claim-1"},
    )

    serials, release_claim = await _cancel(execution)

    assert serials == ["SN001"]
    release_claim.assert_awaited_once()
    kwargs = release_claim.await_args.kwargs
    assert kwargs["org_id"] == "org-1"
    assert kwargs["actor_user_id"] == "user-1"
    assert kwargs["device_id"] == "dev-1"


@pytest.mark.asyncio
async def test_release_failure_does_not_break_the_cancel():
    """Cancel is the operator's stop button; it must not fail on cleanup.

    The claim still expires on its TTL and the orphan reaper sweeps it, so a
    failed release costs latency, not correctness — but a raised exception here
    would leave the run un-cancelled, which is the thing the operator asked for.
    """
    execution = SimpleNamespace(
        id="exec-1",
        meta={},
        user_id="user-1",
        device_config={"claim_session_id": "claim-1"},
    )
    from services import execution_control

    with (
        patch(
            "db.crud.execution.list_execution_devices",
            AsyncMock(return_value=[SimpleNamespace(id="dev-1", serial="SN001")]),
        ),
        patch(
            "services.campaign.dispatcher.release_execution_device_claim",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch.object(
            execution_control,
            "_resolve_org_id",
            AsyncMock(return_value="org-1"),
        ),
    ):
        serials = await execution_control._release_execution_devices(
            AsyncMock(), execution
        )

    assert serials == ["SN001"]


@pytest.mark.asyncio
async def test_no_org_means_no_claim_call():
    """Without a tenant there is nothing safe to release against."""
    execution = SimpleNamespace(
        id="exec-1",
        meta={},
        user_id="user-1",
        device_config={"claim_session_id": "claim-1"},
    )

    _serials, release_claim = await _cancel(execution, org_id=None)

    release_claim.assert_not_awaited()
