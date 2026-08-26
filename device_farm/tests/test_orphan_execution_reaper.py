"""Safety guards for the orphan execution reaper.

This worker force-fails executions and releases the phones behind them, so the
question it asks — "is this workflow gone?" — has to be answered from evidence,
never from the absence of an answer. A Temporal server that is briefly
unreachable must read as "I don't know", not "the fleet is idle": the second
reading would tear down healthy runs mid-scenario across the whole fleet at
once. These tests pin that asymmetry.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from temporalio.service import RPCError, RPCStatusCode

from services.campaign.orphan_execution_reaper import (
    _execution_workflow_id,
    _workflow_is_gone,
)


class _Handle:
    def __init__(self, *, status_name=None, error=None):
        self._status_name = status_name
        self._error = error

    async def describe(self):
        if self._error is not None:
            raise self._error
        status = (
            SimpleNamespace(name=self._status_name) if self._status_name else None
        )
        return SimpleNamespace(status=status, run_id="run-1", start_time=None)


class _Client:
    def __init__(self, handle):
        self._handle = handle

    def get_workflow_handle(self, _workflow_id):
        return self._handle


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("boom", status, b"")


@pytest.mark.asyncio
async def test_not_found_is_a_positive_answer_that_the_workflow_is_gone():
    client = _Client(_Handle(error=_rpc_error(RPCStatusCode.NOT_FOUND)))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        RPCStatusCode.UNAVAILABLE,
        RPCStatusCode.DEADLINE_EXCEEDED,
        RPCStatusCode.PERMISSION_DENIED,
        RPCStatusCode.INTERNAL,
    ],
)
async def test_transport_faults_never_reap(status):
    """An unreachable or unhappy server is not evidence that a run has ended."""
    client = _Client(_Handle(error=_rpc_error(status)))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is False


@pytest.mark.asyncio
async def test_non_rpc_exceptions_never_reap():
    client = _Client(_Handle(error=TimeoutError("no route to host")))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is False


@pytest.mark.asyncio
async def test_running_workflow_is_left_alone():
    client = _Client(_Handle(status_name="RUNNING"))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is False


@pytest.mark.asyncio
async def test_unknown_status_is_not_an_answer():
    client = _Client(_Handle(status_name="UNKNOWN"))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is False


@pytest.mark.asyncio
async def test_missing_status_is_not_an_answer():
    client = _Client(_Handle(status_name=None))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_name", ["COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"]
)
async def test_closed_workflow_leaves_no_execution_open(status_name):
    """The workflow ended without closing its execution — settle the row."""
    client = _Client(_Handle(status_name=status_name))

    assert await _workflow_is_gone(client, "campaign:c:crawl:d") is True


def test_workflow_id_prefers_the_recorded_one():
    execution = SimpleNamespace(
        id="exec-1",
        meta={"workflow_id": "campaign:c:crawl:d:device:S1:target:g9"},
    )

    assert _execution_workflow_id(execution) == (
        "campaign:c:crawl:d:device:S1:target:g9"
    )


def test_workflow_id_falls_back_for_rows_written_before_it_was_recorded():
    """Pre-fix crawl executions have no workflow_id; the fallback is exec_<id>.

    Those IDs will not resolve in Temporal, which is the correct verdict for
    them — they are exactly the stuck rows this worker exists to clear.
    """
    execution = SimpleNamespace(id="exec-1", meta={})

    assert _execution_workflow_id(execution) == "exec_exec-1"
