"""Resolve human-readable DLQ messages for operators."""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.execution_step import ExecutionStep

_DEFAULT_DLQ_MESSAGE = (
    "Execution failed without a recorded error message "
    "(inspect execution_steps, worker logs, or Temporal history)"
)

_DIRECT_U2_TRANSIENT_MARKERS = (
    "json-rpc http 502",
    "json-rpc http 503",
    "json-rpc http 504",
    "502 bad gateway",
    "504 gateway",
)

_U2_TRANSIENT_MARKERS = (
    *_DIRECT_U2_TRANSIENT_MARKERS,
    "uiautomator",
    "uiautomation",
    "already registered",
    "uiautomation not connected",
    "illegalstateexception",
)


def summarize_edge_extra_error(error: object) -> str:
    """Collapse noisy UiAutomator stack traces into a short operator code."""
    text = str(error or "").strip() or "unknown"
    lowered = text.lower()
    if any(marker in lowered for marker in _U2_TRANSIENT_MARKERS):
        return "u2_transient_error"
    if len(text) > 240:
        first = text.splitlines()[0].strip()
        if len(first) > 240:
            return first[:240] + "…"
        return first
    return text


def _is_u2_transient_extra_data_error(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _DIRECT_U2_TRANSIENT_MARKERS):
        return True
    if "edge extra_data failed:" not in lowered:
        return False
    return "java.lang." in lowered and (
        "uiautomation" in lowered or "uiautomator" in lowered
    )


def _direct_u2_transient_prefix(text: str) -> str | None:
    lowered = text.lower()
    positions = [
        lowered.find(marker)
        for marker in _DIRECT_U2_TRANSIENT_MARKERS
        if marker in lowered
    ]
    if not positions:
        return None
    idx = min(positions)
    return text[:idx].rstrip(" —:-")


def sanitize_operator_dlq_text(text: str | None) -> str | None:
    """Hide transient UiAutomator stack traces from operator-facing DLQ text."""
    if not text:
        return text
    msg = str(text).strip()
    if not msg or not _is_u2_transient_extra_data_error(msg):
        return msg
    if "edge extra_data failed:" not in msg:
        prefix = _direct_u2_transient_prefix(msg)
        return f"{prefix} — u2_transient_error" if prefix else "u2_transient_error"
    head, _, _tail = msg.partition("edge extra_data failed:")
    prefix = f"{head}edge extra_data failed:" if head else "edge extra_data failed:"
    return f"{prefix} u2_transient_error"


def coalesce_dlq_text(*parts: str | None) -> str:
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            return text
    return _DEFAULT_DLQ_MESSAGE


def pick_richer_message(current: str | None, new: str | None) -> str | None:
    cur = (current or "").strip()
    nxt = (new or "").strip()
    if not nxt:
        return current
    if not cur:
        return nxt
    return nxt if len(nxt) >= len(cur) else current


def failure_from_step_results(
    step_results: list[dict[str, Any]],
    error_msg: str | None,
) -> tuple[str | None, str | None]:
    from services.execution.step_store import normalize_workflow_step_result

    failed = [s for s in step_results if not s.get("ok", True)]
    if not failed:
        text = (error_msg or "").strip() or None
        return None, text
    last = normalize_workflow_step_result(failed[-1])
    step_id = str(last.get("step_id") or last.get("id") or last.get("index") or "") or None
    reason = str(
        last.get("message")
        or last.get("failed_message")
        or last.get("reason_code")
        or error_msg
        or ""
    ).strip() or None
    return step_id, reason


def resolve_dlq_message(
    *,
    error: str | None,
    failure_reason: str | None,
    failed_step_id: str | None = None,
    execution_id: str | None = None,
    step_message: str | None = None,
) -> str:
    base = coalesce_dlq_text(error, failure_reason, step_message)
    if base != _DEFAULT_DLQ_MESSAGE:
        return sanitize_operator_dlq_text(base) or base
    hints: list[str] = []
    if failed_step_id:
        hints.append(f"failed_step_id={failed_step_id}")
    if execution_id:
        hints.append(f"execution_id={execution_id}")
    if hints:
        return f"{_DEFAULT_DLQ_MESSAGE} ({', '.join(hints)})"
    return _DEFAULT_DLQ_MESSAGE


async def last_failed_step_for_execution(
    db: AsyncSession,
    execution_id: str,
) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(ExecutionStep.message, ExecutionStep.step_id)
            .where(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.status == "failed",
            )
            .order_by(ExecutionStep.step_index.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None
    msg = str(row[0]).strip() if row[0] else None
    step_id = str(row[1]).strip() if row[1] else None
    return msg or None, step_id or None


async def load_failed_step_messages(
    db: AsyncSession,
    execution_ids: Iterable[str],
) -> dict[str, tuple[str | None, str | None]]:
    ids = [eid for eid in dict.fromkeys(execution_ids) if eid]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                ExecutionStep.execution_id,
                ExecutionStep.message,
                ExecutionStep.step_id,
                ExecutionStep.step_index,
            )
            .where(
                ExecutionStep.execution_id.in_(ids),
                ExecutionStep.status == "failed",
            )
            .order_by(ExecutionStep.execution_id, ExecutionStep.step_index.desc())
        )
    ).all()
    out: dict[str, tuple[str | None, str | None]] = {}
    for execution_id, message, step_id, _idx in rows:
        if execution_id in out:
            continue
        msg = str(message).strip() if message else None
        sid = str(step_id).strip() if step_id else None
        out[str(execution_id)] = (msg or None, sid or None)
    return out


async def enrich_dlq_display_messages(
    db: AsyncSession,
    entries: Sequence[Any],
) -> list[str]:
    missing_exec_ids = [
        entry.execution_id
        for entry in entries
        if not (entry.error or "").strip() and not (entry.failure_reason or "").strip()
    ]
    step_lookup = await load_failed_step_messages(db, missing_exec_ids)
    messages: list[str] = []
    for entry in entries:
        step_msg, step_id_from_row = step_lookup.get(entry.execution_id, (None, None))
        failed_step_id = entry.failed_step_id or step_id_from_row
        messages.append(
            resolve_dlq_message(
                error=entry.error,
                failure_reason=entry.failure_reason,
                failed_step_id=failed_step_id,
                execution_id=entry.execution_id,
                step_message=step_msg,
            )
        )
    return messages
