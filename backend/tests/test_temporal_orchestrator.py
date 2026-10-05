from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.temporal_orchestrator import (
    TemporalExecutionOrchestrator,
    TemporalWorkflowMetadata,
    legacy_campaign_device_workflow_id,
    workflow_id_for_execution,
)


def test_workflow_identity_helpers_are_canonical():
    assert workflow_id_for_execution("execution-1") == "exec_execution-1"
    assert (
        legacy_campaign_device_workflow_id("campaign-1", "SN001")
        == "campaign:campaign-1:device:SN001:scenario:__sequence__"
    )


def test_workflow_metadata_memo_is_safe_and_compact(monkeypatch):
    monkeypatch.delenv("TEMPORAL_WORKFLOW_SEARCH_ATTRIBUTES_ENABLED", raising=False)
    meta = TemporalWorkflowMetadata(
        workflow_kind="scenario",
        execution_id="execution-1",
        campaign_id="campaign-1",
        org_id="org-1",
        device_serial="SN001",
    )

    assert meta.memo() == {
        "workflow_kind": "scenario",
        "execution_id": "execution-1",
        "campaign_id": "campaign-1",
        "org_id": "org-1",
        "device_serial": "SN001",
        "queue_role": "device",
    }
    assert meta.search_attributes() == {}


def test_workflow_search_attributes_are_explicitly_opt_in(monkeypatch):
    monkeypatch.setenv("TEMPORAL_WORKFLOW_SEARCH_ATTRIBUTES_ENABLED", "1")
    meta = TemporalWorkflowMetadata(
        workflow_kind="scenario",
        execution_id="execution-1",
        campaign_id="campaign-1",
    )

    assert meta.search_attributes() == {
        "WorkflowKind": ["scenario"],
        "ExecutionId": ["execution-1"],
        "CampaignId": ["campaign-1"],
        "QueueRole": ["device"],
    }


@pytest.mark.asyncio
async def test_start_scenario_workflow_uses_canonical_id_and_memo(monkeypatch):
    monkeypatch.delenv("TEMPORAL_WORKFLOW_SEARCH_ATTRIBUTES_ENABLED", raising=False)
    client = SimpleNamespace(start_workflow=AsyncMock())
    scenario = SimpleNamespace(
        campaign_id="campaign-1",
        device_serial="SN001",
        campaign_vars={"__ORG_ID__": "org-1", "__ACCOUNT_PASSWORD__": "secret"},
    )

    workflow_id = await TemporalExecutionOrchestrator(client).start_scenario_workflow(
        workflow_run="ScenarioWorkflow.run",
        scenario_input=scenario,
        execution_id="execution-1",
        task_queue="device-scenario",
        id_reuse_policy="allow-duplicate",
    )

    assert workflow_id == "exec_execution-1"
    client.start_workflow.assert_awaited_once()
    _, started_scenario = client.start_workflow.await_args.args
    assert started_scenario is scenario
    kwargs = client.start_workflow.await_args.kwargs
    assert kwargs["id"] == "exec_execution-1"
    assert kwargs["task_queue"] == "device-scenario"
    assert kwargs["id_reuse_policy"] == "allow-duplicate"
    assert kwargs["memo"]["org_id"] == "org-1"
    assert "__ACCOUNT_PASSWORD__" not in str(kwargs["memo"])
    assert "search_attributes" not in kwargs


@pytest.mark.asyncio
async def test_resolve_execution_workflow_ids_keeps_legacy_compat(monkeypatch):
    db = AsyncMock()
    execution = SimpleNamespace(
        id="execution-1",
        campaign_id="campaign-1",
        meta={"workflow_ids": ["campaign:other:device:SN999:scenario:__sequence__"]},
    )

    monkeypatch.setattr(
        "db.crud.execution.list_execution_devices",
        AsyncMock(return_value=[SimpleNamespace(serial="SN001")]),
    )

    ids = await TemporalExecutionOrchestrator(None).resolve_workflow_ids_for_execution(
        db,
        execution,
    )

    assert set(ids) == {
        "exec_execution-1",
        "campaign:campaign-1:device:SN001:scenario:__sequence__",
    }


@pytest.mark.asyncio
async def test_signal_workflow_ids_signals_parent_and_child(monkeypatch):
    signals: list[tuple[str, object]] = []

    class Handle:
        def __init__(self, workflow_id: str) -> None:
            self.workflow_id = workflow_id

        async def signal(self, sig: object) -> None:
            signals.append((self.workflow_id, sig))

    client = SimpleNamespace(
        get_workflow_handle=lambda workflow_id: Handle(workflow_id)
    )

    count = await TemporalExecutionOrchestrator(client).signal_workflow_ids(
        ["exec_execution-1"],
        "pause",
    )

    assert count == 1
    assert [workflow_id for workflow_id, _sig in signals] == [
        "exec_execution-1",
        "exec_execution-1:steps",
    ]
