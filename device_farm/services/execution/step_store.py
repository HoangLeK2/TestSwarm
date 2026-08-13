"""Persist per-step rows to execution_steps (DF-T-04-010 / DF-T-04-014)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from services.execution.effective_config import build_effective_config_snapshot
from services.execution.trace_context import build_step_trace_context, trace_from_runtime_context

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

_ARTIFACT_HEAVY_KEYS = frozenset({
    "artifacts",
    "artifacts_json",
    "screenshot",
    "screenshot_pre",
    "screenshot_post",
    "capture_warnings",
})

_ERROR_DETAIL_KEYS = (
    "message",
    "reason_code",
    "failure_class",
    "retry_hint",
    "operator_summary",
    "retryable",
    "edge_extra_summary",
    "edge_filter_summary",
    "nested_failure",
    "nested_failure_context",
    "extra_data_total_ms",
    "extra_data_dump_ms",
    "extra_data_parse_ms",
    "extra_data_click_ms",
    "extra_data_wait_ms",
    "extra_data_sleep_ms",
    "extra_data_steps",
)


def normalize_workflow_step_result(step_result: dict[str, Any]) -> dict[str, Any]:
    """Flatten Temporal workflow envelope (top-level + nested ``details``)."""
    if not isinstance(step_result, dict):
        return {}
    details = step_result.get("details")
    if not isinstance(details, dict):
        return dict(step_result)
    return {
        **details,
        **{k: v for k, v in step_result.items() if k != "details"},
    }


def extract_artifacts_json(step_result: dict[str, Any]) -> list[dict[str, Any]]:
    flat = normalize_workflow_step_result(step_result)
    raw = flat.get("artifacts_json") or flat.get("artifacts") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def slim_step_result(step_result: dict[str, Any]) -> dict[str, Any]:
    """Strip artifact blobs before writing passed_steps / failed_steps JSON."""
    details = step_result.get("details")
    if isinstance(details, dict):
        slim_details = {k: v for k, v in details.items() if k not in _ARTIFACT_HEAVY_KEYS}
        out = {
            k: v
            for k, v in step_result.items()
            if k not in _ARTIFACT_HEAVY_KEYS and k != "details"
        }
        if slim_details:
            out["details"] = slim_details
        return out
    return {k: v for k, v in step_result.items() if k not in _ARTIFACT_HEAVY_KEYS}


def slim_step_results(step_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [slim_step_result(item) for item in step_results]


def _step_status(step_result: dict[str, Any]) -> str:
    step_type = str(step_result.get("type") or "")
    if step_type == "cancelled":
        return "cancelled"
    if step_type == "resumed":
        return "skipped"
    return "passed" if step_result.get("ok", True) else "failed"


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_execution_step_payload(
    execution_id: str,
    step: dict[str, Any],
    step_result: dict[str, Any],
    *,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    duration_ms: float | None = None,
    runtime_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flat = normalize_workflow_step_result(step_result)
    idx = int(flat.get("index", step_result.get("index", 0)))
    ok = bool(flat.get("ok", True))
    step_id = step.get("id") or step.get("_id") or flat.get("step_id") or flat.get("id")
    error_json: dict[str, Any] = {}
    if not ok:
        error_json = {
            k: flat.get(k)
            for k in _ERROR_DETAIL_KEYS
            if flat.get(k) is not None
        }
    merged_step = {**step, **{k: v for k, v in flat.items() if k in ("type", "id", "_id")}}
    artifacts = extract_artifacts_json(step_result)

    trace_base = flat.get("trace") if isinstance(flat.get("trace"), dict) else None
    trace = build_step_trace_context(
        step=merged_step,
        step_index=idx,
        depth=_int_or_default(
            flat.get(
                "depth",
                trace_from_runtime_context(runtime_context).get("depth", 0),
            )
        ),
        runtime_context=runtime_context,
        base_context=trace_base,
        step_result=flat,
    )
    effective_config = build_effective_config_snapshot(merged_step, step_index=idx)
    if trace:
        effective_config["trace"] = trace

    payload: dict[str, Any] = {
        "execution_id": execution_id,
        "step_index": idx,
        "step_id": str(step_id) if step_id else None,
        "step_type": flat.get("type") or step.get("type"),
        "status": _step_status(flat),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_ms": duration_ms,
        "error_json": error_json,
        "effective_config_json": effective_config,
        "attempts_json": list(flat.get("retry_attempts") or []),
        "marked_ignored": bool(flat.get("marked_ignored")),
        "message": flat.get("message"),
    }
    if artifacts:
        payload["artifacts_json"] = artifacts
    return payload


def build_execution_step_payload_from_result(
    execution_id: str,
    step_result: dict[str, Any],
    *,
    ended_at: datetime | None = None,
) -> dict[str, Any]:
    """Finalize path when the original resolved step dict is unavailable."""
    return build_execution_step_payload(
        execution_id,
        step_result,
        step_result,
        ended_at=ended_at,
    )


def schedule_persist_step(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_result: dict[str, Any],
    *,
    started_at: datetime,
    ended_at: datetime,
    duration_ms: float,
) -> None:
    """Best-effort async write after each step. Never blocks or raises."""
    if sc.depth > 0 or not sc.execution_id:
        return
    loop = getattr(sc.device, "_loop", None)
    if loop is None or loop.is_closed():
        return

    payload = build_execution_step_payload(
        sc.execution_id,
        step,
        step_result,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        runtime_context=sc.ctx,
    )

    async def _do() -> None:
        try:
            from db.crud.execution_steps import upsert_execution_step
            from db.database import activity_session

            async with activity_session() as db:
                await upsert_execution_step(db, **payload)
                await db.commit()
        except Exception as exc:
            log.debug("execution_step write failed (non-fatal): %s", exc)

    try:
        fut = asyncio.run_coroutine_threadsafe(_do(), loop)
        fut.add_done_callback(
            lambda f: log.warning(
                "execution_step future failed exec_id=%s step=%s: %s",
                sc.execution_id,
                payload.get("step_index"),
                f.exception(),
            )
            if f.exception() is not None
            else None
        )
    except Exception as exc:
        log.debug("execution_step schedule failed (non-fatal): %s", exc)


def schedule_sync_step_artifacts(sc: "ScenarioContext") -> None:
    """Refresh artifacts_json after async post-capture flush."""
    if sc.depth > 0 or not sc.execution_id or not sc.step_results:
        return
    loop = getattr(sc.device, "_loop", None)
    if loop is None or loop.is_closed():
        return

    updates = [
        (int(result.get("index", 0)), extract_artifacts_json(result))
        for result in sc.step_results
        if isinstance(result, dict)
    ]

    async def _do() -> None:
        try:
            from db.crud.execution_steps import update_execution_step_artifacts
            from db.database import activity_session

            async with activity_session() as db:
                for step_index, artifacts in updates:
                    await update_execution_step_artifacts(
                        db,
                        execution_id=sc.execution_id,
                        step_index=step_index,
                        artifacts_json=artifacts,
                    )
                await db.commit()
        except Exception as exc:
            log.debug("execution_step artifact sync failed (non-fatal): %s", exc)

    try:
        asyncio.run_coroutine_threadsafe(_do(), loop)
    except Exception as exc:
        log.debug("execution_step artifact sync schedule failed (non-fatal): %s", exc)


async def persist_execution_steps_from_results(
    db,
    *,
    execution_id: str,
    step_results: list[dict[str, Any]],
    default_ended_at: datetime | None = None,
) -> None:
    """Bulk upsert when only in-memory step_results are available (finalize path)."""
    from db.crud.execution_steps import bulk_upsert_execution_steps

    ended_at = default_ended_at or datetime.now(timezone.utc)
    rows = [
        build_execution_step_payload_from_result(execution_id, result, ended_at=ended_at)
        for result in step_results
        if isinstance(result, dict)
    ]
    if rows:
        await bulk_upsert_execution_steps(db, rows)


def execution_step_to_legacy_dict(row: Any) -> dict[str, Any]:
    """Shape compatible with _extract_step_artifacts and DLQ helpers."""
    legacy: dict[str, Any] = {
        "index": row.step_index,
        "type": row.step_type,
        "ok": row.status in ("passed", "skipped"),
        "message": row.message,
        "artifacts_json": list(row.artifacts_json or []),
        "artifacts": list(row.artifacts_json or []),
    }
    if row.error_json:
        legacy.update({k: v for k, v in row.error_json.items() if v is not None})
    return legacy
