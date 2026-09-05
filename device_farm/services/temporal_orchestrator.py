"""Temporal orchestration facade for execution-owned workflows.

This module is the small interface callers should learn for Temporal execution
control. It centralizes workflow identity, start metadata, resolution, and
signal fan-out so routes and campaign services do not each encode Temporal ID
rules themselves.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

ControlAction = Literal["pause", "resume", "cancel"]
log = logging.getLogger(__name__)

EXECUTION_WORKFLOW_PREFIX = "exec_"
LEGACY_CAMPAIGN_WORKFLOW_SUFFIX = ":scenario:__sequence__"

_SIGNAL_CONCURRENCY = 32
_SEARCH_ATTR_ENABLED = "TEMPORAL_WORKFLOW_SEARCH_ATTRIBUTES_ENABLED"


@dataclass(frozen=True)
class TemporalWorkflowMetadata:
    workflow_kind: str
    execution_id: str | None = None
    campaign_id: str | None = None
    org_id: str | None = None
    device_serial: str | None = None
    dispatch_id: str | None = None
    queue_role: str = "device"

    def memo(self) -> dict[str, Any]:
        """Safe workflow memo payload; never include secrets."""
        return {
            key: value
            for key, value in {
                "workflow_kind": self.workflow_kind,
                "execution_id": self.execution_id,
                "campaign_id": self.campaign_id,
                "org_id": self.org_id,
                "device_serial": self.device_serial,
                "dispatch_id": self.dispatch_id,
                "queue_role": self.queue_role,
            }.items()
            if value
        }

    def search_attributes(self) -> dict[str, list[str]]:
        """Optional custom Search Attributes.

        Temporal rejects unregistered custom attributes. Keep this opt-in so
        operators can register them first, while tests and local deployments keep
        the safer memo-only default.
        """
        enabled = os.getenv(_SEARCH_ATTR_ENABLED, "").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return {}
        mapping = {
            "WorkflowKind": self.workflow_kind,
            "ExecutionId": self.execution_id,
            "CampaignId": self.campaign_id,
            "OrgId": self.org_id,
            "DeviceSerial": self.device_serial,
            "DispatchId": self.dispatch_id,
            "QueueRole": self.queue_role,
        }
        return {
            key: [str(value)]
            for key, value in mapping.items()
            if value is not None and str(value) != ""
        }


def workflow_id_for_execution(execution_id: str) -> str:
    """Deterministic Temporal workflow ID for an execution row."""
    return f"{EXECUTION_WORKFLOW_PREFIX}{execution_id}"


def legacy_campaign_device_workflow_id(campaign_id: str, device_serial: str) -> str:
    """Legacy campaign/device workflow ID kept for in-flight compatibility."""
    return f"campaign:{campaign_id}:device:{device_serial}{LEGACY_CAMPAIGN_WORKFLOW_SUFFIX}"


def workflow_ids_from_meta(meta: dict | None) -> list[str]:
    raw = (meta or {}).get("workflow_ids") or []
    if not isinstance(raw, list):
        return []
    out = [str(wid) for wid in raw if wid]
    single = (meta or {}).get("workflow_id")
    if single and str(single) not in out:
        out.insert(0, str(single))
    return out


def _workflow_ids_for_campaign(
    campaign_id: str | None,
    workflow_ids: list[str],
) -> list[str]:
    if not campaign_id:
        return workflow_ids
    prefix = f"campaign:{campaign_id}:"
    return [
        workflow_id
        for workflow_id in workflow_ids
        if not workflow_id.startswith("campaign:") or workflow_id.startswith(prefix)
    ]


def workflow_ids_for_execution_meta(execution: Any, workflow_ids: list[str]) -> list[str]:
    campaign_ids = _workflow_ids_for_campaign(
        getattr(execution, "campaign_id", None),
        workflow_ids,
    )
    expected_exec_id = workflow_id_for_execution(str(getattr(execution, "id", "") or ""))
    return [
        workflow_id
        for workflow_id in campaign_ids
        if not workflow_id.startswith(EXECUTION_WORKFLOW_PREFIX) or workflow_id == expected_exec_id
    ]


def union_workflow_ids(*sources: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        for wid in source:
            if wid and wid not in seen:
                seen.add(wid)
                out.append(wid)
    return out


class TemporalExecutionOrchestrator:
    """Deep interface for execution workflow start, lookup, and control."""

    def __init__(self, temporal_client: Any | None) -> None:
        self._client = temporal_client

    async def start_scenario_workflow(
        self,
        *,
        workflow_run: Any,
        scenario_input: Any,
        execution_id: str,
        task_queue: str,
        id_reuse_policy: Any,
        metadata: TemporalWorkflowMetadata | None = None,
    ) -> str:
        if self._client is None:
            raise RuntimeError("Temporal client is unavailable")
        workflow_id = workflow_id_for_execution(execution_id)
        meta = metadata or TemporalWorkflowMetadata(
            workflow_kind="scenario",
            execution_id=execution_id,
            campaign_id=getattr(scenario_input, "campaign_id", None),
            device_serial=getattr(scenario_input, "device_serial", None),
            org_id=(getattr(scenario_input, "campaign_vars", None) or {}).get("__ORG_ID__"),
        )
        kwargs: dict[str, Any] = {
            "id": workflow_id,
            "task_queue": task_queue,
            "id_reuse_policy": id_reuse_policy,
            "memo": meta.memo(),
        }
        search_attributes = meta.search_attributes()
        if search_attributes:
            kwargs["search_attributes"] = search_attributes
        await self._client.start_workflow(workflow_run, scenario_input, **kwargs)
        return workflow_id

    async def list_running_campaign_workflow_ids(self, campaign_id: str) -> list[str]:
        if self._client is None:
            return []
        ids: list[str] = []
        wf_query = (
            f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" '
            f'AND ExecutionStatus="Running"'
        )
        async for wf in self._client.list_workflows(wf_query):
            if not wf.id.endswith(":steps"):
                ids.append(wf.id)
        return ids

    async def resolve_workflow_ids_for_execution(
        self,
        db: AsyncSession,
        execution: Any,
        *,
        campaign_scan_ids: list[str] | None = None,
    ) -> list[str]:
        from db.crud.execution import list_execution_devices

        ids = workflow_ids_for_execution_meta(
            execution,
            workflow_ids_from_meta(getattr(execution, "meta", None)),
        )
        fallback_ids = union_workflow_ids(
            ids,
            [workflow_id_for_execution(str(getattr(execution, "id", "") or ""))],
        )
        if ids:
            return fallback_ids

        campaign_id = getattr(execution, "campaign_id", None)
        if not campaign_id:
            return fallback_ids

        devices = await list_execution_devices(db, execution.id)
        expected = [
            legacy_campaign_device_workflow_id(str(campaign_id), d.serial)
            for d in devices
            if getattr(d, "serial", None)
        ]
        if expected:
            return union_workflow_ids(fallback_ids, expected)

        return union_workflow_ids(fallback_ids, list(campaign_scan_ids or []))

    async def resolve_workflow_ids_for_campaign(
        self,
        db: AsyncSession,
        campaign_id: str,
        executions: list[Any],
        ) -> list[str]:
        chunks: list[list[str]] = [
            workflow_ids_for_execution_meta(
                ex,
                workflow_ids_from_meta(getattr(ex, "meta", None)),
            )
            for ex in executions
        ]
        exec_ids = [
            workflow_id_for_execution(str(getattr(ex, "id", "") or ""))
            for ex in executions
        ]
        scan_ids = _workflow_ids_for_campaign(
            campaign_id,
            await self.list_running_campaign_workflow_ids(campaign_id),
        )

        if not any(chunks) and not scan_ids:
            from db.crud.execution import list_execution_devices

            all_serials: list[str] = []
            for ex in executions:
                devices = await list_execution_devices(db, ex.id)
                all_serials.extend(d.serial for d in devices if getattr(d, "serial", None))
            chunks.append(
                [
                    legacy_campaign_device_workflow_id(campaign_id, serial)
                    for serial in all_serials
                ]
            )

        return union_workflow_ids(*chunks, scan_ids, exec_ids)

    async def signal_workflow_ids(
        self,
        workflow_ids: list[str],
        action: ControlAction,
    ) -> int:
        if not workflow_ids or self._client is None:
            return 0

        from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

        signal_map = {
            "pause": (ScenarioWorkflow.pause, ScenarioStepsWorkflow.pause),
            "resume": (ScenarioWorkflow.resume, ScenarioStepsWorkflow.resume),
            "cancel": (ScenarioWorkflow.cancel_scenario, ScenarioStepsWorkflow.cancel_scenario),
        }
        parent_sig, child_sig = signal_map[action]
        sem = asyncio.Semaphore(_SIGNAL_CONCURRENCY)

        async def _signal_one(target_id: str, sig: Any) -> None:
            async with sem:
                try:
                    handle = self._client.get_workflow_handle(target_id)
                    await handle.signal(sig)
                except Exception as exc:
                    log.debug("workflow %s %s: %s", target_id, action, exc)

        tasks = []
        for workflow_id in workflow_ids:
            tasks.append(_signal_one(workflow_id, parent_sig))
            tasks.append(_signal_one(f"{workflow_id}:steps", child_sig))
        await asyncio.gather(*tasks, return_exceptions=True)
        return len(workflow_ids)
