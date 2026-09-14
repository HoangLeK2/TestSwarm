"""Remove the legacy account-cooldown Temporal schedule.

The account cooldown checker was removed from the worker registration set, but
Temporal keeps Schedule definitions and already-started workflow executions in
its own persistence. If the old schedule/workflow is left behind, the current
worker still receives activations for ``AccountCooldownTickWorkflow`` and logs
``Workflow class AccountCooldownTickWorkflow is not registered`` forever.
"""
from __future__ import annotations

import logging
from typing import Any

from core.config import load_config

log = logging.getLogger(__name__)

LEGACY_SCHEDULE_ID = "df-account-cooldown-tick"
LEGACY_WORKFLOW_TYPE = "AccountCooldownTickWorkflow"
_CLEANUP_REASON = "removed AccountCooldownTickWorkflow"


async def upgrade(conn) -> None:
    """Delete the obsolete Temporal schedule and terminate its running jobs."""
    del conn  # This migration cleans Temporal state, not application SQL.

    cfg = load_config()
    temporal_cfg = getattr(cfg, "temporal", None)
    if not getattr(temporal_cfg, "enabled", False):
        log.info(
            "legacy account cooldown Temporal cleanup skipped: Temporal disabled"
        )
        return

    client = await _connect_temporal_client(temporal_cfg)
    await _cleanup_legacy_account_cooldown(client)


async def _connect_temporal_client(temporal_cfg: Any):
    from temporalio.client import Client

    return await Client.connect(
        temporal_cfg.server_url,
        namespace=temporal_cfg.namespace,
    )


async def _cleanup_legacy_account_cooldown(client: Any) -> None:
    deleted_schedule = await _delete_legacy_schedule(client)
    terminated_count = await _terminate_legacy_workflows(client)
    log.info(
        "legacy account cooldown Temporal cleanup finished: schedule_deleted=%s "
        "terminated_workflows=%s",
        deleted_schedule,
        terminated_count,
    )


async def _delete_legacy_schedule(client: Any) -> bool:
    handle = client.get_schedule_handle(LEGACY_SCHEDULE_ID)

    try:
        await handle.describe()
    except Exception as exc:
        if _is_temporal_not_found(exc):
            log.info(
                "legacy account cooldown Temporal schedule absent: %s",
                LEGACY_SCHEDULE_ID,
            )
            return False
        raise

    try:
        await handle.delete()
    except Exception as exc:
        if _is_temporal_not_found(exc):
            return False
        raise

    return True


async def _terminate_legacy_workflows(client: Any) -> int:
    query = (
        f'WorkflowType = "{LEGACY_WORKFLOW_TYPE}" '
        'AND ExecutionStatus = "Running"'
    )
    terminated = 0

    async for workflow in client.list_workflows(query):
        workflow_id = _workflow_id(workflow)
        if not workflow_id or not _is_running(workflow):
            continue
        run_id = _workflow_run_id(workflow)
        handle = client.get_workflow_handle(
            workflow_id,
            run_id=run_id or None,
        )
        try:
            await handle.terminate(reason=_CLEANUP_REASON)
        except Exception as exc:
            if _is_temporal_not_found(exc):
                continue
            raise
        terminated += 1

    return terminated


def _workflow_id(workflow: Any) -> str:
    workflow_id = getattr(workflow, "id", None)
    if workflow_id:
        return str(workflow_id)
    execution = getattr(workflow, "execution", None)
    return str(getattr(execution, "workflow_id", "") or "")


def _workflow_run_id(workflow: Any) -> str:
    run_id = getattr(workflow, "run_id", None)
    if run_id:
        return str(run_id)
    execution = getattr(workflow, "execution", None)
    return str(getattr(execution, "run_id", "") or "")


def _is_running(workflow: Any) -> bool:
    status = getattr(workflow, "status", None)
    name = getattr(status, "name", status)
    if name is None:
        return True
    return str(name).upper() in {
        "RUNNING",
        "WORKFLOW_EXECUTION_STATUS_RUNNING",
    }


def _is_temporal_not_found(exc: Exception) -> bool:
    try:
        from temporalio.service import RPCError, RPCStatusCode
    except Exception:
        return False

    return isinstance(exc, RPCError) and exc.status == RPCStatusCode.NOT_FOUND
