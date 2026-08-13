"""Unified execution trace read-model for campaign monitoring.

This module intentionally stays off the runtime event write path. It enriches
existing execution, step, event, device, account, and DLQ rows at read time so a
monitoring UI can trace: campaign -> execution -> phone -> account -> step.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud.execution import get_execution, list_executions
from db.models.account import Account
from db.models.device import Device
from db.models.execution import Execution, ExecutionDevice
from db.models.execution_dlq import ExecutionDLQ
from db.models.execution_event import ExecutionEvent
from db.models.execution_step import ExecutionStep
from tenancy.context import use_tenant_scope

TERMINAL_STEP_STATUSES = {"completed", "passed", "skipped"}
FAILED_STEP_STATUSES = {"failed", "error"}
RUNNING_STEP_STATUSES = {"running", "in_progress"}
ACTION_COUNTER_KEYS = ("matched", "liked", "commented", "skipped")


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _workflow_id(execution: Execution) -> str:
    meta = _safe_dict(execution.meta)
    return _first_text(meta.get("workflow_id"), f"exec_{execution.id}") or f"exec_{execution.id}"


def _account_label(account: Account | None, account_id: str | None) -> str | None:
    if account is None:
        return f"Account #{account_id[:8]}" if account_id else None
    return _first_text(account.display_name, account.username, f"Account #{account.id[:8]}")


def _device_serial_from_execution(
    execution: Execution,
    devices: list[Device],
) -> str | None:
    if devices:
        device = devices[0]
        return _first_text(device.serial, device.device_serial, device.relay_serial)
    cfg = _safe_dict(execution.device_config)
    meta = _safe_dict(execution.meta)
    return _first_text(
        cfg.get("device_serial"),
        cfg.get("serial"),
        meta.get("device_serial"),
        meta.get("serial"),
    )


async def _load_devices_by_execution(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, list[Device]]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    result = await db.execute(
        select(ExecutionDevice.execution_id, Device)
        .join(Device, Device.id == ExecutionDevice.device_id)
        .where(ExecutionDevice.execution_id.in_(ids))
        .order_by(ExecutionDevice.execution_id, Device.serial)
    )
    out: dict[str, list[Device]] = defaultdict(list)
    for execution_id, device in result.all():
        out[execution_id].append(device)
    return dict(out)


async def _load_accounts_by_id(
    db: AsyncSession,
    account_ids: list[str | None],
) -> dict[str, Account]:
    ids = [account_id for account_id in dict.fromkeys(account_ids) if account_id]
    if not ids:
        return {}
    result = await db.execute(select(Account).where(Account.id.in_(ids)))
    return {account.id: account for account in result.scalars().all()}


def _build_context(
    execution: Execution,
    devices_by_execution: dict[str, list[Device]],
    accounts_by_id: dict[str, Account],
) -> dict[str, Any]:
    devices = devices_by_execution.get(execution.id, [])
    device = devices[0] if devices else None
    account = accounts_by_id.get(execution.account_id or "")
    return {
        "org_id": execution.org_id,
        "campaign_id": execution.campaign_id,
        "execution_id": execution.id,
        "workflow_id": _workflow_id(execution),
        "scenario_id": execution.scenario_id,
        "scenario_version_id": execution.scenario_version_id,
        "device_id": device.id if device else None,
        "device_serial": _device_serial_from_execution(execution, devices),
        "device_name": device.name if device else None,
        "account_id": execution.account_id,
        "account_label": _account_label(account, execution.account_id),
        "account_platform": account.platform if account else None,
    }


def _normalize_step(row: ExecutionStep) -> dict[str, Any]:
    return {
        "id": row.id,
        "execution_id": row.execution_id,
        "device_id": row.device_id,
        "step_index": row.step_index,
        "step_id": row.step_id,
        "step_type": row.step_type,
        "status": row.status,
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "duration_ms": row.duration_ms,
        "error_json": _safe_dict(row.error_json),
        "effective_config_json": _safe_dict(row.effective_config_json),
        "artifacts_json": _safe_list(row.artifacts_json),
        "attempts_json": _safe_list(row.attempts_json),
        "marked_ignored": row.marked_ignored,
        "message": row.message,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _merge_payload_context(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    payload_context = _safe_dict(payload.get("context"))
    merged = {key: value for key, value in context.items() if value is not None}
    merged.update(payload_context)
    out = dict(payload)
    out["context"] = merged
    return out


def _normalize_event(row: ExecutionEvent, context: dict[str, Any]) -> dict[str, Any]:
    envelope = row.to_envelope()
    payload = _safe_dict(envelope.get("payload"))
    envelope["payload"] = _merge_payload_context(payload, context)
    return envelope


def _step_summary(steps: list[ExecutionStep]) -> dict[str, Any]:
    completed = 0
    failed = 0
    running = 0
    current_step_index: int | None = None
    last_step_index: int | None = None
    counters = {key: 0 for key in ACTION_COUNTER_KEYS}

    for step in steps:
        status = str(step.status or "").lower()
        last_step_index = step.step_index
        if status in TERMINAL_STEP_STATUSES:
            completed += 1
        elif status in FAILED_STEP_STATUSES:
            failed += 1
        elif status in RUNNING_STEP_STATUSES:
            running += 1
            current_step_index = step.step_index

        cfg = _safe_dict(step.effective_config_json)
        result = _safe_dict(cfg.get("result"))
        step_counters = _safe_dict(result.get("counters"))
        for key in ACTION_COUNTER_KEYS:
            value = step_counters.get(key)
            if isinstance(value, (int, float)):
                counters[key] += int(value)

    if current_step_index is None and last_step_index is not None:
        current_step_index = min(last_step_index + 1, len(steps))

    return {
        "total_steps": len(steps),
        "completed_steps": completed,
        "failed_steps": failed,
        "running_steps": running,
        "current_step_index": current_step_index,
        "counters": {**counters, "errors": failed},
    }


def _event_counters(events: list[ExecutionEvent]) -> dict[str, int]:
    counters = {key: 0 for key in ACTION_COUNTER_KEYS}
    for event in events:
        payload = _safe_dict(event.payload)
        result = _safe_dict(payload.get("result"))
        for source in (
            _safe_dict(payload.get("counters_delta")),
            _safe_dict(result.get("counters_delta")),
            _safe_dict(result.get("counters")),
        ):
            for key in ACTION_COUNTER_KEYS:
                value = source.get(key)
                if isinstance(value, (int, float)):
                    counters[key] += int(value)
        action = _first_text(payload.get("action"), payload.get("action_performed"))
        if action in counters:
            counters[action] += 1
    return counters


def _merge_counters(base: dict[str, Any], extra: dict[str, int]) -> dict[str, int]:
    merged = {key: int(base.get(key, 0) or 0) for key in ACTION_COUNTER_KEYS}
    for key, value in extra.items():
        merged[key] = max(merged.get(key, 0), int(value))
    merged["errors"] = int(base.get("errors", 0) or 0)
    return merged


async def _latest_dlq(db: AsyncSession, execution_id: str) -> dict[str, Any] | None:
    result = await db.execute(
        select(ExecutionDLQ)
        .where(ExecutionDLQ.execution_id == execution_id)
        .order_by(ExecutionDLQ.failed_at.desc(), ExecutionDLQ.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "device_serial": row.device_serial,
        "error": row.error,
        "failed_step_id": row.failed_step_id,
        "failure_reason": row.failure_reason,
        "failed_at": row.failed_at,
        "artifact_refs": _safe_dict(row.artifact_refs),
        "retry_count": row.retry_count,
    }


async def _list_execution_event_page(
    db: AsyncSession,
    execution_id: str,
    *,
    since_event_id: str | None,
    page_size: int,
) -> tuple[list[ExecutionEvent], bool]:
    since_row_id: int | None = None
    if since_event_id:
        anchor = await db.execute(
            select(ExecutionEvent.id).where(
                ExecutionEvent.execution_id == execution_id,
                ExecutionEvent.event_id == since_event_id,
            )
        )
        since_row_id = anchor.scalar_one_or_none()

    q = select(ExecutionEvent).where(ExecutionEvent.execution_id == execution_id)
    if since_row_id is not None:
        q = q.where(ExecutionEvent.id > since_row_id)
        q = q.order_by(ExecutionEvent.id.asc())
        result = await db.execute(q.limit(page_size + 1))
        rows = list(result.scalars().all())
        return rows[:page_size], len(rows) > page_size

    result = await db.execute(q.order_by(ExecutionEvent.id.desc()).limit(page_size + 1))
    rows = list(result.scalars().all())
    bounded = list(reversed(rows[:page_size]))
    return bounded, len(rows) > page_size


async def _list_execution_step_page(
    db: AsyncSession,
    execution_id: str,
    *,
    page_size: int,
) -> tuple[list[ExecutionStep], bool]:
    result = await db.execute(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.step_index.desc())
        .limit(page_size + 1)
    )
    rows = list(result.scalars().all())
    return list(reversed(rows[:page_size])), len(rows) > page_size


async def _execution_step_summary(db: AsyncSession, execution_id: str) -> dict[str, Any]:
    result = await db.execute(
        select(ExecutionStep.status, func.count(), func.max(ExecutionStep.step_index))
        .where(ExecutionStep.execution_id == execution_id)
        .group_by(ExecutionStep.status)
    )
    counts: dict[str, int] = {}
    latest_step_index: int | None = None
    for status, count, max_index in result.all():
        counts[str(status or "").lower()] = int(count or 0)
        if isinstance(max_index, int):
            latest_step_index = (
                max_index
                if latest_step_index is None
                else max(latest_step_index, max_index)
            )
    return _counts_summary(counts, latest_step_index)


async def build_execution_task_log(
    db: AsyncSession,
    execution_id: str,
    *,
    since_event_id: str | None = None,
    event_limit: int = 200,
    step_limit: int = 500,
) -> dict[str, Any]:
    """Return a bounded execution trace with enriched phone/account context."""
    execution = await get_execution(db, execution_id)
    if execution is None:
        raise ValueError(f"execution not found: {execution_id}")

    limit = max(1, min(int(event_limit or 200), 500))
    with use_tenant_scope(execution.org_id):
        devices_by_execution = await _load_devices_by_execution(db, [execution.id])
        accounts_by_id = await _load_accounts_by_id(db, [execution.account_id])
    context = _build_context(execution, devices_by_execution, accounts_by_id)
    bounded_step_limit = max(1, min(int(step_limit or 500), 2000))
    steps, has_more_steps = await _list_execution_step_page(
        db,
        execution.id,
        page_size=bounded_step_limit,
    )
    bounded_events, has_more = await _list_execution_event_page(
        db,
        execution.id,
        since_event_id=since_event_id,
        page_size=limit,
    )
    summary = await _execution_step_summary(db, execution.id)
    recent_step_counters = _step_summary(steps)["counters"]
    counters = _merge_counters(recent_step_counters, _event_counters(bounded_events))
    counters["errors"] = int(_safe_dict(summary.get("counters")).get("errors", 0) or 0)
    summary["counters"] = counters
    last_event_id = bounded_events[-1].event_id if bounded_events else None

    return {
        "execution_id": execution.id,
        "status": execution.status,
        "context": context,
        "summary": summary,
        "steps": [_normalize_step(step) for step in steps],
        "events": [_normalize_event(event, context) for event in bounded_events],
        "has_more_steps": has_more_steps,
        "has_more_events": has_more,
        "last_event_id": last_event_id,
        "dlq": await _latest_dlq(db, execution.id),
        "created_at": execution.created_at,
        "started_at": execution.started_at,
        "finished_at": execution.finished_at,
    }


async def _step_status_counts(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, dict[str, int]]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    result = await db.execute(
        select(ExecutionStep.execution_id, ExecutionStep.status, func.count())
        .where(ExecutionStep.execution_id.in_(ids))
        .group_by(ExecutionStep.execution_id, ExecutionStep.status)
    )
    out: dict[str, dict[str, int]] = defaultdict(dict)
    for execution_id, status, count in result.all():
        out[execution_id][str(status or "").lower()] = int(count or 0)
    return dict(out)


async def _latest_step_by_execution(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, tuple[int | None, str | None, str | None]]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    max_step_subq = (
        select(
            ExecutionStep.execution_id.label("execution_id"),
            func.max(ExecutionStep.step_index).label("step_index"),
        )
        .where(ExecutionStep.execution_id.in_(ids))
        .group_by(ExecutionStep.execution_id)
        .subquery()
    )
    result = await db.execute(
        select(
            ExecutionStep.execution_id,
            ExecutionStep.step_index,
            ExecutionStep.step_type,
            ExecutionStep.message,
        )
        .join(
            max_step_subq,
            (ExecutionStep.execution_id == max_step_subq.c.execution_id)
            & (ExecutionStep.step_index == max_step_subq.c.step_index),
        )
    )
    return {
        execution_id: (step_index, step_type, message)
        for execution_id, step_index, step_type, message in result.all()
    }


async def _latest_events_by_execution(
    db: AsyncSession,
    execution_ids: list[str],
) -> dict[str, datetime | None]:
    ids = [execution_id for execution_id in dict.fromkeys(execution_ids) if execution_id]
    if not ids:
        return {}
    result = await db.execute(
        select(ExecutionEvent.execution_id, func.max(ExecutionEvent.occurred_at))
        .where(ExecutionEvent.execution_id.in_(ids))
        .group_by(ExecutionEvent.execution_id)
    )
    return {execution_id: occurred_at for execution_id, occurred_at in result.all()}


def _counts_summary(counts: dict[str, int], latest_step_index: int | None) -> dict[str, Any]:
    completed = sum(counts.get(status, 0) for status in TERMINAL_STEP_STATUSES)
    failed = sum(counts.get(status, 0) for status in FAILED_STEP_STATUSES)
    running = sum(counts.get(status, 0) for status in RUNNING_STEP_STATUSES)
    total = sum(counts.values())
    current = latest_step_index
    if current is None:
        current = 0 if total else None
    elif running == 0:
        current = min(current + 1, total)
    return {
        "total_steps": total,
        "completed_steps": completed,
        "failed_steps": failed,
        "running_steps": running,
        "current_step_index": current,
        "counters": {
            "matched": 0,
            "liked": 0,
            "commented": 0,
            "skipped": 0,
            "errors": failed,
        },
    }


async def build_campaign_monitor(
    db: AsyncSession,
    campaign_id: str,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    """Return a campaign monitor snapshot without scanning full event logs."""
    bounded_limit = max(1, min(int(limit or 200), 500))
    executions, total = await list_executions(
        db,
        campaign_id=campaign_id,
        offset=0,
        limit=bounded_limit,
    )
    execution_ids = [execution.id for execution in executions]
    org_id = executions[0].org_id if executions else None
    with use_tenant_scope(org_id):
        devices_by_execution = await _load_devices_by_execution(db, execution_ids)
        accounts_by_id = await _load_accounts_by_id(
            db,
            [execution.account_id for execution in executions],
        )
    step_counts = await _step_status_counts(db, execution_ids)
    latest_steps = await _latest_step_by_execution(db, execution_ids)
    latest_events = await _latest_events_by_execution(db, execution_ids)

    rows: list[dict[str, Any]] = []
    for execution in executions:
        context = _build_context(execution, devices_by_execution, accounts_by_id)
        latest_index, latest_step_type, latest_message = latest_steps.get(
            execution.id, (None, None, None)
        )
        rows.append(
            {
                "execution_id": execution.id,
                "status": execution.status,
                "context": context,
                "summary": _counts_summary(step_counts.get(execution.id, {}), latest_index),
                "current_step_type": latest_step_type,
                "message": latest_message,
                "created_at": execution.created_at,
                "started_at": execution.started_at,
                "finished_at": execution.finished_at,
                "last_event_at": latest_events.get(execution.id),
            }
        )

    return {
        "campaign_id": campaign_id,
        "total": total,
        "limit": bounded_limit,
        "executions": rows,
    }
