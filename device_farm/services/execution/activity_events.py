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
) -> None:
    await enqueue_execution_event(
        db,
        event_type=STEP_STARTED,
        execution_id=execution_id,
        organization_id=org_id,
        campaign_id=campaign_id,
        step_id=_step_id(step, step_index),
        payload={
            "step_index": step_index,
            "step_type": step.get("type"),
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
                "step_type": step.get("type"),
                "attempt": rec.get("attempt"),
                "reason": rec.get("error_reason"),
                "wait_ms_before_next": rec.get("wait_ms_before_next"),
            },
        )

    ok = bool(step_result.get("ok", True))
    event_type = STEP_COMPLETED if ok else STEP_FAILED
    payload: dict[str, Any] = {
        "step_index": step_index,
        "step_type": step.get("type"),
        "ok": ok,
        "message": step_result.get("message"),
        "reason_code": step_result.get("reason_code"),
    }
    for key in ("output", "exit_code", "save_as", "output_truncated"):
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
