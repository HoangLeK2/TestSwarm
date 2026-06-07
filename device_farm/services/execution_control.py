"""Pause / resume / cancel orchestration for executions and campaigns (DF-T-04-016)."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import campaign_entity as campaign_entity_repo
from db.crud.campaign import update_campaign_status
from db.models.enums import CampaignStatus
from db.crud.execution import (
    cancel_execution_record,
    get_execution,
    list_running_executions_for_campaign,
    pause_execution_record,
    resume_execution_record,
)
from db.crud.execution_dlq import list_dlq_entries
from db.models.execution import Execution
from services.activity_logger import log_activity

log = logging.getLogger(__name__)

CANCEL_UNDO_WARNING = (
    "Cancel does not undo posted side effects on external platforms "
    "(e.g. comments, likes, messages already sent)."
)

_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_PAUSE_BLOCKED = _TERMINAL

ControlAction = Literal["pause", "resume", "cancel"]


class ExecutionControlError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class ControlResult:
    execution_id: str
    status: str
    action: str
    effective_transition: bool
    workflows_signalled: int = 0
    warning: str | None = None


def _workflow_ids_from_meta(meta: dict | None) -> list[str]:
    raw = (meta or {}).get("workflow_ids") or []
    if not isinstance(raw, list):
        return []
    out = [str(wid) for wid in raw if wid]
    single = (meta or {}).get("workflow_id")
    if single and str(single) not in out:
        out.insert(0, str(single))
    return out


def _expected_workflow_ids(campaign_id: str, device_serials: list[str]) -> list[str]:
    """Deterministic Temporal workflow IDs (no server scan)."""
    return [
        f"campaign:{campaign_id}:device:{serial}:scenario:__sequence__"
        for serial in device_serials
        if serial
    ]


async def _list_campaign_running_workflow_ids(
    temporal_client: Any,
    campaign_id: str,
) -> list[str]:
    if temporal_client is None:
        return []
    ids: list[str] = []
    wf_query = (
        f'WorkflowId STARTS_WITH "campaign:{campaign_id}:" '
        f'AND ExecutionStatus="Running"'
    )
    async for wf in temporal_client.list_workflows(wf_query):
        # Top-level workflows only (skip :steps children in listing if present)
        if wf.id.endswith(":steps"):
            continue
        ids.append(wf.id)
    return ids


def _union_workflow_ids(*sources: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for source in sources:
        for wid in source:
            if wid and wid not in seen:
                seen.add(wid)
                out.append(wid)
    return out


async def _resolve_workflow_ids_for_execution(
    db: AsyncSession,
    execution: Execution,
    temporal_client: Any | None,
    *,
    campaign_scan_ids: list[str] | None = None,
) -> list[str]:
    """Workflow IDs to signal for one execution — meta first, then device-derived IDs."""
    from db.crud.execution import list_execution_devices

    ids = _workflow_ids_from_meta(execution.meta)
    if ids:
        return ids

    if not execution.campaign_id:
        return []

    devices = await list_execution_devices(db, execution.id)
    serials = [d.serial for d in devices if d.serial]
    ids = _expected_workflow_ids(execution.campaign_id, serials)
    if ids:
        return ids

    return list(campaign_scan_ids or [])


async def _resolve_workflow_ids_for_campaign(
    db: AsyncSession,
    campaign_id: str,
    executions: list[Execution],
    temporal_client: Any | None,
) -> list[str]:
    """One union of workflow IDs for a campaign fan-out (single Temporal pass)."""
    chunks: list[list[str]] = []
    for ex in executions:
        chunks.append(_workflow_ids_from_meta(ex.meta))

    scan_ids: list[str] = []
    if temporal_client is not None:
        scan_ids = await _list_campaign_running_workflow_ids(temporal_client, campaign_id)

    if not any(chunks) and not scan_ids:
        from db.crud.execution import list_execution_devices

        all_serials: list[str] = []
        for ex in executions:
            devices = await list_execution_devices(db, ex.id)
            all_serials.extend(d.serial for d in devices if d.serial)
        chunks.append(_expected_workflow_ids(campaign_id, all_serials))

    return _union_workflow_ids(*chunks, scan_ids)


_SIGNAL_CONCURRENCY = 32


async def _signal_workflow_ids(
    temporal_client: Any | None,
    workflow_ids: list[str],
    action: ControlAction,
) -> int:
    if not workflow_ids or temporal_client is None:
        return 0

    from temporal.workflows import ScenarioStepsWorkflow, ScenarioWorkflow

    signal_map = {
        "pause": (ScenarioWorkflow.pause, ScenarioStepsWorkflow.pause),
        "resume": (ScenarioWorkflow.resume, ScenarioStepsWorkflow.resume),
        "cancel": (ScenarioWorkflow.cancel_scenario, ScenarioStepsWorkflow.cancel_scenario),
    }
    parent_sig, child_sig = signal_map[action]
    sem = asyncio.Semaphore(_SIGNAL_CONCURRENCY)

    async def _signal_one(target_id: str, sig) -> None:
        async with sem:
            try:
                handle = temporal_client.get_workflow_handle(target_id)
                await handle.signal(sig)
            except Exception as exc:
                log.debug("workflow %s %s: %s", target_id, action, exc)

    tasks = []
    for wf_id in workflow_ids:
        tasks.append(_signal_one(wf_id, parent_sig))
        tasks.append(_signal_one(f"{wf_id}:steps", child_sig))

    await asyncio.gather(*tasks, return_exceptions=True)
    return len(workflow_ids)


def _record_control_metrics(action: ControlAction, *, effective: bool, elapsed_sec: float) -> None:
    try:
        from web.metrics import execution_control_total, execution_control_duration_seconds

        execution_control_total.labels(action=action, effective=str(effective).lower()).inc()
        execution_control_duration_seconds.labels(action=action).observe(elapsed_sec)
    except Exception:
        pass


async def _has_open_dlq(db: AsyncSession, execution_id: str) -> bool:
    entries = await list_dlq_entries(
        db, execution_id=execution_id, status="pending", limit=1,
    )
    return bool(entries)


async def _assert_pause_allowed(db: AsyncSession, execution: Execution) -> None:
    if execution.status in _PAUSE_BLOCKED:
        raise ExecutionControlError(
            409,
            "INVALID_ACTION",
            f"Cannot pause {execution.status} execution",
        )
    if execution.status not in ("running", "paused"):
        raise ExecutionControlError(
            409,
            "INVALID_ACTION",
            f"Cannot pause execution in status {execution.status!r}",
        )
    if await _has_open_dlq(db, execution.id):
        raise ExecutionControlError(
            409,
            "INVALID_ACTION",
            "Cannot pause execution with open DLQ entry; resolve or cancel instead",
        )


async def _assert_resume_allowed(execution: Execution) -> None:
    if execution.status == "paused":
        return
    if execution.status in _TERMINAL:
        raise ExecutionControlError(
            409,
            "INVALID_ACTION",
            f"Cannot resume {execution.status} execution",
        )
    raise ExecutionControlError(
        409,
        "INVALID_ACTION",
        f"Cannot resume execution in status {execution.status!r}",
    )


async def _assert_cancel_allowed(execution: Execution) -> None:
    if execution.status in _TERMINAL:
        raise ExecutionControlError(
            409,
            "INVALID_ACTION",
            f"Cannot cancel {execution.status} execution",
        )


async def _release_execution_devices(
    db: AsyncSession,
    execution: Execution,
    *,
    session_store: Any | None = None,
) -> list[str]:
    from db.crud.execution import list_execution_devices
    from services.account_manager import end_account_usage

    released_serials: list[str] = []
    usage_map = (execution.meta or {}).get("account_usage") or {}
    now = datetime.now(timezone.utc)

    for serial, info in usage_map.items():
        if not isinstance(info, dict):
            continue
        account_id = info.get("account_id")
        if not account_id:
            continue
        started_raw = info.get("started_at")
        duration_min = 0.0
        if started_raw:
            try:
                started = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
                duration_min = max(0.0, (now - started).total_seconds() / 60.0)
            except (TypeError, ValueError):
                pass
        try:
            await end_account_usage(
                str(account_id),
                duration_min,
                device_serial=serial,
                entity_type="execution",
                entity_id=execution.id,
                end_reason="cancelled",
            )
        except Exception as exc:
            log.warning("cancel release account %s: %s", account_id, exc)

    devices = await list_execution_devices(db, execution.id)
    for device in devices:
        serial = device.serial
        if session_store is not None:
            try:
                session_store.release_device(serial)
            except Exception as exc:
                log.debug("release_device %s: %s", serial, exc)
        released_serials.append(serial)

    return released_serials


async def _resolve_org_id(db: AsyncSession, execution: Execution) -> str | None:
    from services.execution.event_publisher import resolve_execution_org_id

    org_id = await resolve_execution_org_id(db, execution)
    return org_id or None


_CONTROL_EVENT_TYPES = {
    "execution.paused": "execution.paused",
    "execution.resumed": "execution.resumed",
    "execution.cancelled": "execution.cancelled",
}


async def _emit_execution_event(
    db: AsyncSession,
    execution: Execution,
    event: str,
    *,
    user_id: str | None,
    before_status: str | None = None,
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    org_id = await _resolve_org_id(db, execution)
    payload = {
        "campaign_id": execution.campaign_id,
        "status": execution.status,
        **(details or {}),
    }
    before_state = {"status": before_status} if before_status else {}
    after_state = {"status": execution.status, **(details or {})}

    execution_event = None
    mapped_type = _CONTROL_EVENT_TYPES.get(event)
    if mapped_type:
        from services.execution.event_publisher import enqueue_execution_event

        execution_event = await enqueue_execution_event(
            db,
            event_type=mapped_type,
            execution_id=execution.id,
            payload=payload,
            organization_id=org_id,
            execution=execution,
        )

    if org_id:
        await log_activity(
            db,
            action=event,
            entity_type="execution",
            entity_id=execution.id,
            user_id=user_id,
            org_id=org_id,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            event_id=execution_event.event_id if execution_event else None,
            details=details or payload,
        )
    else:
        await log_activity(
            db,
            action=event,
            entity_type="execution",
            entity_id=execution.id,
            user_id=user_id,
            details=payload,
        )

    if org_id:
        try:
            from services.webhook_dispatcher import dispatch_webhook

            await dispatch_webhook(
                org_id,
                event,
                {
                    "execution_id": execution.id,
                    **payload,
                },
            )
        except Exception as exc:
            log.debug("webhook %s: %s", event, exc)


async def pause_execution(
    db: AsyncSession,
    execution_id: str,
    *,
    user_id: str | None,
    temporal_client: Any | None = None,
    workflow_ids: list[str] | None = None,
    signal_temporal: bool = True,
) -> ControlResult:
    t0 = time.perf_counter()
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise ExecutionControlError(404, "EXECUTION_NOT_FOUND", "Execution not found")

    if execution.status == "paused":
        result = ControlResult(
            execution_id=execution_id,
            status="paused",
            action="pause",
            effective_transition=False,
            workflows_signalled=0,
        )
        _record_control_metrics("pause", effective=False, elapsed_sec=time.perf_counter() - t0)
        return result

    await _assert_pause_allowed(db, execution)
    execution, transitioned = await pause_execution_record(db, execution_id)
    assert execution is not None

    if transitioned:
        from services.execution_pause_flags import set_execution_paused

        await set_execution_paused(execution_id)

    wf_count = 0
    if signal_temporal and transitioned:
        wf_ids = workflow_ids or await _resolve_workflow_ids_for_execution(
            db, execution, temporal_client,
        )
        wf_count = await _signal_workflow_ids(temporal_client, wf_ids, "pause")

    if transitioned:
        await _emit_execution_event(
            db, execution, "execution.paused", user_id=user_id,
            before_status="running",
            details={"workflows_signalled": wf_count},
        )

    result = ControlResult(
        execution_id=execution_id,
        status=execution.status,
        action="pause",
        effective_transition=transitioned,
        workflows_signalled=wf_count,
    )
    _record_control_metrics("pause", effective=transitioned, elapsed_sec=time.perf_counter() - t0)
    return result


async def resume_execution(
    db: AsyncSession,
    execution_id: str,
    *,
    user_id: str | None,
    temporal_client: Any | None = None,
    workflow_ids: list[str] | None = None,
    signal_temporal: bool = True,
) -> ControlResult:
    t0 = time.perf_counter()
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise ExecutionControlError(404, "EXECUTION_NOT_FOUND", "Execution not found")

    if execution.status == "running":
        result = ControlResult(
            execution_id=execution_id,
            status="running",
            action="resume",
            effective_transition=False,
            workflows_signalled=0,
        )
        _record_control_metrics("resume", effective=False, elapsed_sec=time.perf_counter() - t0)
        return result

    await _assert_resume_allowed(execution)
    prev_paused = execution.status == "paused"
    execution = await resume_execution_record(db, execution_id)
    assert execution is not None

    if prev_paused:
        from services.execution_pause_flags import clear_execution_paused

        await clear_execution_paused(execution_id)

    wf_count = 0
    if signal_temporal and prev_paused:
        wf_ids = workflow_ids or await _resolve_workflow_ids_for_execution(
            db, execution, temporal_client,
        )
        wf_count = await _signal_workflow_ids(temporal_client, wf_ids, "resume")

    if prev_paused:
        await _emit_execution_event(
            db, execution, "execution.resumed", user_id=user_id,
            before_status="paused",
            details={"workflows_signalled": wf_count},
        )

    result = ControlResult(
        execution_id=execution_id,
        status=execution.status,
        action="resume",
        effective_transition=prev_paused,
        workflows_signalled=wf_count,
    )
    _record_control_metrics("resume", effective=prev_paused, elapsed_sec=time.perf_counter() - t0)
    return result


async def cancel_execution(
    db: AsyncSession,
    execution_id: str,
    *,
    user_id: str | None,
    reason: str | None = None,
    temporal_client: Any | None = None,
    session_store: Any | None = None,
    workflow_ids: list[str] | None = None,
    signal_temporal: bool = True,
) -> ControlResult:
    t0 = time.perf_counter()
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise ExecutionControlError(404, "EXECUTION_NOT_FOUND", "Execution not found")

    if execution.status == "cancelled":
        result = ControlResult(
            execution_id=execution_id,
            status="cancelled",
            action="cancel",
            effective_transition=False,
            warning=CANCEL_UNDO_WARNING,
            workflows_signalled=0,
        )
        _record_control_metrics("cancel", effective=False, elapsed_sec=time.perf_counter() - t0)
        return result

    await _assert_cancel_allowed(execution)
    before_status = execution.status
    execution, transitioned = await cancel_execution_record(
        db, execution_id, reason=reason,
    )
    assert execution is not None

    if transitioned:
        from services.execution_pause_flags import clear_execution_paused, set_execution_cancelled

        await clear_execution_paused(execution_id)
        await set_execution_cancelled(execution_id)

    wf_count = 0
    if signal_temporal and transitioned:
        wf_ids = workflow_ids or await _resolve_workflow_ids_for_execution(
            db, execution, temporal_client,
        )
        wf_count = await _signal_workflow_ids(temporal_client, wf_ids, "cancel")

    released: list[str] = []
    if transitioned:
        released = await _release_execution_devices(
            db, execution, session_store=session_store,
        )
        await _emit_execution_event(
            db, execution, "execution.cancelled", user_id=user_id,
            before_status=before_status,
            reason=reason,
            details={
                "reason": reason,
                "workflows_signalled": wf_count,
                "devices_released": released,
            },
        )

    result = ControlResult(
        execution_id=execution_id,
        status=execution.status,
        action="cancel",
        effective_transition=transitioned,
        workflows_signalled=wf_count,
        warning=CANCEL_UNDO_WARNING,
    )
    _record_control_metrics("cancel", effective=transitioned, elapsed_sec=time.perf_counter() - t0)
    return result


async def pause_campaign_executions(
    db: AsyncSession,
    campaign_id: str,
    *,
    user_id: str | None,
    temporal_client: Any | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    executions = await list_running_executions_for_campaign(db, campaign_id)
    wf_ids = await _resolve_workflow_ids_for_campaign(
        db, campaign_id, executions, temporal_client,
    )

    results: list[dict] = []
    for ex in executions:
        if ex.status not in ("running", "paused"):
            continue
        try:
            r = await pause_execution(
                db,
                ex.id,
                user_id=user_id,
                temporal_client=temporal_client,
                workflow_ids=wf_ids,
                signal_temporal=False,
            )
            results.append({
                "execution_id": r.execution_id,
                "status": r.status,
                "effective_transition": r.effective_transition,
            })
        except ExecutionControlError as exc:
            if exc.code != "INVALID_ACTION":
                raise
            results.append({
                "execution_id": ex.id,
                "status": ex.status,
                "effective_transition": False,
                "error": exc.message,
            })

    wf_count = await _signal_workflow_ids(temporal_client, wf_ids, "pause")
    await update_campaign_status(db, campaign_id, "paused")

    _record_control_metrics(
        "pause",
        effective=any(r.get("effective_transition") for r in results),
        elapsed_sec=time.perf_counter() - t0,
    )
    return {
        "campaign_id": campaign_id,
        "status": "paused",
        "executions": results,
        "executions_affected": len(results),
        "workflows_signalled": wf_count,
    }


async def resume_campaign_executions(
    db: AsyncSession,
    campaign_id: str,
    *,
    user_id: str | None,
    temporal_client: Any | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    executions = await list_running_executions_for_campaign(db, campaign_id)
    wf_ids = await _resolve_workflow_ids_for_campaign(
        db, campaign_id, executions, temporal_client,
    )

    results: list[dict] = []
    for ex in executions:
        if ex.status != "paused":
            continue
        r = await resume_execution(
            db,
            ex.id,
            user_id=user_id,
            temporal_client=temporal_client,
            workflow_ids=wf_ids,
            signal_temporal=False,
        )
        results.append({
            "execution_id": r.execution_id,
            "status": r.status,
            "effective_transition": r.effective_transition,
        })

    wf_count = await _signal_workflow_ids(temporal_client, wf_ids, "resume")
    await update_campaign_status(db, campaign_id, "running")

    _record_control_metrics(
        "resume",
        effective=any(r.get("effective_transition") for r in results),
        elapsed_sec=time.perf_counter() - t0,
    )
    return {
        "campaign_id": campaign_id,
        "status": "running",
        "executions": results,
        "executions_affected": len(results),
        "workflows_signalled": wf_count,
    }


async def cancel_campaign_executions(
    db: AsyncSession,
    campaign_id: str,
    *,
    user_id: str | None,
    reason: str | None = None,
    temporal_client: Any | None = None,
    session_store: Any | None = None,
) -> dict[str, Any]:
    from services.campaign.lifecycle import (
        CampaignInvalidTransitionError,
        apply_campaign_transition,
    )
    from services.campaign.errors import CampaignNotFoundError

    campaign_row = await campaign_entity_repo.get_campaign_entity(db, campaign_id)
    if campaign_row is None:
        raise ExecutionControlError(404, "CAMPAIGN_NOT_FOUND", "Campaign not found")

    try:
        transition = await apply_campaign_transition(
            db,
            campaign_row,
            CampaignStatus.CANCELLED,
            org_id=campaign_row.org_id,
            user_id=user_id,
            reason=reason,
        )
    except CampaignNotFoundError as exc:
        raise ExecutionControlError(404, "CAMPAIGN_NOT_FOUND", str(exc)) from exc
    except CampaignInvalidTransitionError as exc:
        raise ExecutionControlError(409, "INVALID_TRANSITION", str(exc)) from exc

    t0 = time.perf_counter()
    executions = await list_running_executions_for_campaign(db, campaign_id)
    all_active = list(executions)
    pending_result = await db.execute(
        select(Execution).where(
            Execution.campaign_id == campaign_id,
            Execution.status == "pending",
        )
    )
    seen_ids = {e.id for e in all_active}
    for row in pending_result.scalars().all():
        if row.id not in seen_ids:
            all_active.append(row)
            seen_ids.add(row.id)

    wf_ids = await _resolve_workflow_ids_for_campaign(
        db, campaign_id, all_active, temporal_client,
    )

    results: list[dict] = []
    for ex in all_active:
        if ex.status in _TERMINAL:
            continue
        r = await cancel_execution(
            db,
            ex.id,
            user_id=user_id,
            reason=reason,
            temporal_client=temporal_client,
            session_store=session_store,
            workflow_ids=wf_ids,
            signal_temporal=False,
        )
        results.append({
            "execution_id": r.execution_id,
            "status": r.status,
            "effective_transition": r.effective_transition,
        })

    wf_count = await _signal_workflow_ids(temporal_client, wf_ids, "cancel")

    _record_control_metrics(
        "cancel",
        effective=transition.changed or any(r.get("effective_transition") for r in results),
        elapsed_sec=time.perf_counter() - t0,
    )
    return {
        "campaign_id": campaign_id,
        "status": CampaignStatus.CANCELLED.value,
        "executions": results,
        "executions_affected": len(results),
        "workflows_signalled": wf_count,
        "warning": CANCEL_UNDO_WARNING,
    }
