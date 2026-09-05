"""Helpers to emit step events from Temporal activities (DF-T-04-013)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.execution.effective_config import build_effective_config_snapshot
from services.execution.event_publisher import enqueue_execution_event
from services.execution.trace_context import build_step_trace_context
from services.execution.event_types import (
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_RETRIED,
    STEP_STARTED,
    TEMPORAL_ACTIVITY_EVENTS,
)
from services.user_action_audit import sanitize_audit_value

_RUNTIME_EVIDENCE_KEYS = (
    "reason_code",
    "failure_class",
    "retry_hint",
    "operator_summary",
    "device_id",
    "device_serial",
    "account_id",
    "account_platform",
    "account_label",
    "scenario_id",
    "scenario_name",
    "scenario_sequence_index",
    "step_path",
    "step_id",
    "step_type",
    "platform",
    "action",
    "outcome",
)

_NODE_PREFLIGHT_KEYS = ("node_capability_preflight", "preflight")


def _step_id(step: dict[str, Any], step_index: int) -> str:
    return str(step.get("id") or step.get("_id") or step_index)


def _runtime_evidence_payload(
    step_result: dict[str, Any] | None,
    trace: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    sources = (
        trace if isinstance(trace, dict) else {},
        step_result if isinstance(step_result, dict) else {},
    )
    for source in sources:
        for key in _RUNTIME_EVIDENCE_KEYS:
            if key not in source:
                continue
            value = sanitize_audit_value(key, source.get(key))
            if value not in (None, "", [], {}):
                evidence[key] = value

    result = step_result if isinstance(step_result, dict) else {}
    preflight = next(
        (
            result.get(key)
            for key in _NODE_PREFLIGHT_KEYS
            if isinstance(result.get(key), dict)
        ),
        None,
    )
    if isinstance(preflight, dict):
        evidence["node_capability_preflight"] = sanitize_audit_value(
            "node_capability_preflight",
            preflight,
        )
        issues = preflight.get("issues")
        first_issue = (
            issues[0]
            if isinstance(issues, list) and issues and isinstance(issues[0], dict)
            else {}
        )
        missing = first_issue.get("missing")
        if isinstance(missing, list) and missing:
            evidence["missing_capabilities"] = sanitize_audit_value(
                "missing_capabilities",
                missing,
            )
        if first_issue.get("path") and "step_path" not in evidence:
            evidence["step_path"] = sanitize_audit_value(
                "step_path",
                first_issue.get("path"),
            )
        if first_issue.get("step_type") and "step_type" not in evidence:
            evidence["step_type"] = sanitize_audit_value(
                "step_type",
                first_issue.get("step_type"),
            )

    missing_capabilities = result.get("missing_capabilities")
    if isinstance(missing_capabilities, list) and missing_capabilities:
        evidence["missing_capabilities"] = sanitize_audit_value(
            "missing_capabilities",
            missing_capabilities,
        )
    return evidence


async def emit_control_flow_step_event(
    db: AsyncSession,
    *,
    execution_id: str,
    org_id: str,
    campaign_id: str | None,
    event_type: str,
    step_id: str,
    step_index: int,
    step_type: str,
    depth: int = 0,
    trace_context: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    trace = build_step_trace_context(
        step={"id": step_id, "type": step_type},
        step_index=step_index,
        depth=depth,
        base_context=trace_context,
        step_result=payload,
    )
    event_payload: dict[str, Any] = {
        "step_index": step_index,
        "step_id": step_id,
        "step_type": step_type,
        "depth": depth,
        "control_flow": True,
        "trace": trace,
    }
    for key, value in (payload or {}).items():
        if value is not None:
            event_payload[key] = value
    evidence = _runtime_evidence_payload(payload, trace)
    if evidence:
        event_payload["evidence"] = evidence
    await enqueue_execution_event(
        db,
        event_type=event_type,
        execution_id=execution_id,
        organization_id=org_id,
        campaign_id=campaign_id,
        step_id=step_id,
        payload=event_payload,
    )


async def emit_temporal_activity_event(
    db: AsyncSession,
    *,
    execution_id: str,
    org_id: str,
    campaign_id: str | None,
    event_type: str,
    step_id: str,
    step_index: int,
    step_type: str,
    depth: int = 0,
    trace_context: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    event_type = str(event_type or "")
    if event_type not in TEMPORAL_ACTIVITY_EVENTS:
        return
    payload = payload if isinstance(payload, dict) else {}
    trace = build_step_trace_context(
        step={"id": step_id, "type": step_type},
        step_index=step_index,
        depth=depth,
        base_context=trace_context,
        step_result=payload,
    )
    event_payload: dict[str, Any] = {
        "step_index": step_index,
        "step_id": step_id,
        "step_type": step_type,
        "depth": depth,
        "temporal_activity": True,
        "trace": trace,
    }
    allowed_keys = {
        "activity_id",
        "step_activity_id",
        "side_effect_class",
        "activity_attempt",
        "phase",
        "duration_ms",
        "ok",
        "message",
        "reason_code",
        "stalled_reason",
        "batch_size",
        "batch_first_step_index",
        "batch_last_step_index",
        "batch_step_activity_ids",
        "paused_mid_batch",
        "cancelled_mid_batch",
    }
    for key in allowed_keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            event_payload[key] = sanitize_audit_value(key, value)
    evidence = _runtime_evidence_payload(payload, trace)
    if evidence:
        event_payload["evidence"] = evidence
    await enqueue_execution_event(
        db,
        event_type=event_type,
        execution_id=execution_id,
        organization_id=org_id,
        campaign_id=campaign_id,
        step_id=step_id,
        payload=event_payload,
    )


async def emit_step_started(
    db: AsyncSession,
    *,
    execution_id: str,
    org_id: str,
    campaign_id: str | None,
    step: dict[str, Any],
    step_index: int,
    depth: int = 0,
    trace_context: dict[str, Any] | None = None,
) -> None:
    step_id = _step_id(step, step_index)
    trace = build_step_trace_context(
        step=step,
        step_index=step_index,
        depth=depth,
        base_context=trace_context,
    )
    evidence = _runtime_evidence_payload(None, trace)
    payload: dict[str, Any] = {
        "step_index": step_index,
        "step_id": step_id,
        "step_type": step.get("type"),
        "depth": depth,
        "trace": trace,
    }
    if evidence:
        payload["evidence"] = evidence
    await enqueue_execution_event(
        db,
        event_type=STEP_STARTED,
        execution_id=execution_id,
        organization_id=org_id,
        campaign_id=campaign_id,
        step_id=step_id,
        payload=payload,
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
    trace_context: dict[str, Any] | None = None,
) -> None:
    step_id = _step_id(step, step_index)
    retry_attempts = step_result.get("retry_attempts") or []
    for rec in retry_attempts[:-1]:
        retry_reason = rec.get("reason_code") or rec.get("error_reason")
        retry_payload: dict[str, Any] = {
            "step_index": step_index,
            "step_id": step_id,
            "step_type": step.get("type"),
            "depth": depth,
            "attempt": rec.get("attempt"),
            "reason": rec.get("error_reason"),
            "reason_code": retry_reason,
            "wait_ms_before_next": rec.get("wait_ms_before_next"),
        }
        retry_evidence = _runtime_evidence_payload(
            {
                "reason_code": retry_reason,
                "retry_hint": "retry_scheduled",
                "operator_summary": rec.get("error_reason"),
            },
            None,
        )
        if retry_evidence:
            retry_payload["evidence"] = retry_evidence
        await enqueue_execution_event(
            db,
            event_type=STEP_RETRIED,
            execution_id=execution_id,
            organization_id=org_id,
            campaign_id=campaign_id,
            step_id=step_id,
            payload=retry_payload,
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
    trace = build_step_trace_context(
        step=step,
        step_index=step_index,
        depth=depth,
        base_context=trace_context,
        step_result=step_result,
    )
    if trace:
        payload["trace"] = trace
    evidence = _runtime_evidence_payload(step_result, trace)
    if evidence:
        payload["evidence"] = evidence
    for key in ("failure_class", "retry_hint", "operator_summary"):
        if step_result.get(key) is not None:
            payload[key] = step_result.get(key)
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
        "outcome",
        "state",
        "action",
        "platform",
        "action_performed",
        "action_bounds",
        "matched_label",
        "account_action_id",
        "external_entity_id",
        "display_name",
        "iterations",
        "account_action_ledger",
        "candidate_guard",
        "candidate_completion",
        "missing_capabilities",
        "node_capability_preflight",
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
                "trace": trace,
                **incident_payload,
            },
        )
