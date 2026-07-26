"""Helpers to emit step events from Temporal activities (DF-T-04-013)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.execution.effective_config import build_effective_config_snapshot
from services.execution.event_publisher import enqueue_execution_event
from services.execution.event_types import (
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_RETRIED,
    STEP_STARTED,
)


def _step_id(step: dict[str, Any], step_index: int) -> str:
    return str(step.get("id") or step.get("_id") or step_index)


async def emit_step_started(
    db: AsyncSession,
    *,
    execution_id: str,
    org_id: str,
    campaign_id: str | None,
    step: dict[str, Any],
    step_index: int,
    depth: int = 0,
) -> None:
    step_id = _step_id(step, step_index)
    await enqueue_execution_event(
        db,
        event_type=STEP_STARTED,
        execution_id=execution_id,
        organization_id=org_id,
        campaign_id=campaign_id,
        step_id=step_id,
        payload={
            "step_index": step_index,
            "step_id": step_id,
            "step_type": step.get("type"),
            "depth": depth,
        },
    )


async def emit_step_finished(
    db: AsyncSession,
    *,
    execution_id: str,
    org_id: str,
    campaign_id: str | None,
    step: dict[str, Any],
    step_index: int,
    step_result: dict[str, Any],
    depth: int = 0,
) -> None:
    step_id = _step_id(step, step_index)
    retry_attempts = step_result.get("retry_attempts") or []
    for rec in retry_attempts[:-1]:
        await enqueue_execution_event(
            db,
            event_type=STEP_RETRIED,
            execution_id=execution_id,
            organization_id=org_id,
            campaign_id=campaign_id,
            step_id=step_id,
            payload={
                "step_index": step_index,
                "step_id": step_id,
                "step_type": step.get("type"),
                "depth": depth,
                "attempt": rec.get("attempt"),
                "reason": rec.get("error_reason"),
                "wait_ms_before_next": rec.get("wait_ms_before_next"),
            },
        )

    ok = bool(step_result.get("ok", True))
    event_type = STEP_COMPLETED if ok else STEP_FAILED
    payload: dict[str, Any] = {
        "step_index": step_index,
        "step_id": step_id,
        "step_type": step.get("type"),
        "depth": depth,
        "ok": ok,
        "message": step_result.get("message"),
        "reason_code": step_result.get("reason_code"),
    }
    for key in (
        "output",
        "exit_code",
        "save_as",
        "output_truncated",
        "duration_ms",
        "activity_duration_ms",
        "u2_batch_duration_ms",
        "u2_batch_action_duration_ms",
        "relay_total_ms",
        "relay_queue_wait_ms",
        "extra_data_total_ms",
        "extra_data_dump_ms",
        "extra_data_parse_ms",
        "extra_data_click_ms",
        "extra_data_wait_ms",
        "extra_data_sleep_ms",
        "extra_data_steps",
        "edge_extra_summary",
        "edge_filter_summary",
        "nested_failure",
        "nested_failure_context",
        "scroll_to_flow_ms",
        "scroll_to_swipes",
    ):
        if key in step_result:
            payload[key] = step_result.get(key)
    if ok:
        payload["effective_config"] = build_effective_config_snapshot(
            step, step_index=step_index,
        )
    await enqueue_execution_event(
        db,
        event_type=event_type,
        execution_id=execution_id,
        organization_id=org_id,
        campaign_id=campaign_id,
        step_id=step_id,
        payload=payload,
    )

    for rec in step_result.get("recovery_events") or []:
        if not isinstance(rec, dict):
            continue
        incident_type = str(rec.get("event_type") or "").strip()
        incident_payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        if not incident_type.startswith("incident."):
            continue
        await enqueue_execution_event(
            db,
            event_type=incident_type,
            execution_id=execution_id,
            organization_id=org_id,
            campaign_id=campaign_id,
            step_id=step_id,
            payload={
                "step_index": step_index,
                "step_id": step_id,
                "step_type": step.get("type"),
                "depth": depth,
                **incident_payload,
            },
        )
