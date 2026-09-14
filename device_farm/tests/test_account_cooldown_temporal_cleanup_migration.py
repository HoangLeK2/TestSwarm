from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace

import pytest
from temporalio.service import RPCError, RPCStatusCode


migration = import_module(
    "db.migrations.129_cleanup_account_cooldown_temporal_schedule"
)


class _ScheduleHandle:
    def __init__(self, *, describe_error: Exception | None = None) -> None:
        self.describe_error = describe_error
        self.deleted = False

    async def describe(self):
        if self.describe_error:
            raise self.describe_error
        return SimpleNamespace()

    async def delete(self):
        self.deleted = True


class _WorkflowHandle:
    def __init__(self, workflow_id: str, run_id: str | None) -> None:
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.terminated_reason: str | None = None

    async def terminate(self, *, reason: str | None = None):
        self.terminated_reason = reason


class _Client:
    def __init__(
        self,
        *,
        schedule: _ScheduleHandle,
        workflows: list[SimpleNamespace] | None = None,
    ) -> None:
        self.schedule = schedule
        self.workflows = workflows or []
        self.workflow_handles: dict[tuple[str, str | None], _WorkflowHandle] = {}
        self.workflow_query = ""

    def get_schedule_handle(self, schedule_id: str):
        assert schedule_id == migration.LEGACY_SCHEDULE_ID
        return self.schedule

    async def _iter_workflows(self):
        for workflow in self.workflows:
            yield workflow

    def list_workflows(self, query: str):
        self.workflow_query = query
        return self._iter_workflows()

    def get_workflow_handle(self, workflow_id: str, *, run_id: str | None = None):
        handle = _WorkflowHandle(workflow_id, run_id)
        self.workflow_handles[(workflow_id, run_id)] = handle
        return handle


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("boom", status, b"")


@pytest.mark.asyncio
async def test_upgrade_skips_when_temporal_is_disabled(monkeypatch):
    async def fail_connect(_temporal_cfg):
        raise AssertionError("Temporal should not be contacted when disabled")

    monkeypatch.setattr(
        migration,
        "load_config",
        lambda: SimpleNamespace(temporal=SimpleNamespace(enabled=False)),
    )
    monkeypatch.setattr(migration, "_connect_temporal_client", fail_connect)

    await migration.upgrade(SimpleNamespace())


@pytest.mark.asyncio
async def test_cleanup_deletes_schedule_and_terminates_running_legacy_workflows():
    client = _Client(
        schedule=_ScheduleHandle(),
        workflows=[
            SimpleNamespace(
                id="df-account-cooldown-tick-run-2026-09-10T17:47:00Z",
                run_id="01a08c6e-1652-7e7e-a6a9-411d921080f9",
                status=SimpleNamespace(name="RUNNING"),
            ),
            SimpleNamespace(
                id="df-account-cooldown-tick-run-closed",
                run_id="closed-run",
                status=SimpleNamespace(name="COMPLETED"),
            ),
        ],
    )

    await migration._cleanup_legacy_account_cooldown(client)

    assert client.schedule.deleted is True
    assert migration.LEGACY_WORKFLOW_TYPE in client.workflow_query
    assert 'ExecutionStatus = "Running"' in client.workflow_query
    handle = client.workflow_handles[
        (
            "df-account-cooldown-tick-run-2026-09-10T17:47:00Z",
            "01a08c6e-1652-7e7e-a6a9-411d921080f9",
        )
    ]
    assert handle.terminated_reason == "removed AccountCooldownTickWorkflow"
    assert (
        "df-account-cooldown-tick-run-closed",
        "closed-run",
    ) not in client.workflow_handles


@pytest.mark.asyncio
async def test_missing_schedule_is_noop_but_running_workflows_are_still_terminated():
    client = _Client(
        schedule=_ScheduleHandle(
            describe_error=_rpc_error(RPCStatusCode.NOT_FOUND),
        ),
        workflows=[
            SimpleNamespace(
                id="df-account-cooldown-tick-run-1",
                run_id="run-1",
                status=SimpleNamespace(name="RUNNING"),
            ),
        ],
    )

    await migration._cleanup_legacy_account_cooldown(client)

    assert client.schedule.deleted is False
    assert ("df-account-cooldown-tick-run-1", "run-1") in client.workflow_handles


@pytest.mark.asyncio
async def test_temporal_transport_errors_fail_the_migration():
    client = _Client(
        schedule=_ScheduleHandle(
            describe_error=_rpc_error(RPCStatusCode.UNAVAILABLE),
        ),
    )

    with pytest.raises(RPCError):
        await migration._cleanup_legacy_account_cooldown(client)
