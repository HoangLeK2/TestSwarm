"""Small, redacted execution trace snapshots for audit surfaces."""
from __future__ import annotations

from typing import Any

from services.user_action_audit import sanitize_audit_value

TRACE_CONTEXT_KEY = "__scenario_trace__"

_TRACE_KEYS = (
    "org_id",
    "dispatch_id",
    "campaign_id",
    "execution_id",
    "workflow_id",
    "device_id",
    "device_serial",
    "device_name",
    "account_id",
    "account_platform",
    "account_label",
    "scenario_id",
    "scenario_name",
    "scenario_ref_index",
    "scenario_sequence_index",
    "repeat_index",
    "repeat_count",
    "step_path",
    "loop_iter",
    "loop_id",
    "branch",
    "step_index",
    "step_id",
    "step_type",
    "depth",
)

_ACTION_KEYS = (
    "account_action_id",
    "account_action_ids",
    "action",
    "action_type",
    "action_performed",
    "outcome",
    "platform",
    "target_type",
    "target_id",
    "display_name",
    "external_entity_id",
    "target_count",
    "interacted_count",
    "liked_count",
    "commented_count",
    "candidate_count",
    "screens_scanned",
    "scrolls",
)


def _clean(key: str, value: Any) -> Any:
    cleaned = sanitize_audit_value(key, value)
    if cleaned in ("", None, [], {}):
        return None
    return cleaned


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    cleaned = _clean(key, value)
    if cleaned is not None:
        out[key] = cleaned


def trace_from_runtime_context(runtime_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(runtime_context, dict):
        return {}
    raw = runtime_context.get(TRACE_CONTEXT_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def _step_segment(
    step_id: str,
    *,
    loop_iter: int | None = None,
    branch: str | None = None,
) -> str:
    segment = str(step_id or "").strip()
    if loop_iter is not None:
        segment = f"{segment}#{loop_iter}"
    if branch:
        segment = f"{segment}.{branch}"
    return segment


def push_step_path(
    ctx: dict[str, Any] | None,
    *,
    step_id: str,
    loop_iter: int | None = None,
    branch: str | None = None,
    step_type: str | None = None,
    step_index: int | None = None,
    scenario_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a new runtime context with one scenario-trace path segment appended."""
    base_ctx = dict(ctx or {})
    trace = trace_from_runtime_context(base_ctx)
    segment = _step_segment(step_id, loop_iter=loop_iter, branch=branch)
    parent_path = str(trace.get("step_path") or "").strip()
    if segment:
        trace["step_path"] = f"{parent_path}/{segment}" if parent_path else segment
    if loop_iter is not None:
        trace["loop_iter"] = loop_iter
        trace["loop_id"] = str(step_id)
    if branch:
        trace["branch"] = branch
    if step_type:
        trace["step_type"] = step_type
    if step_index is not None:
        trace["step_index"] = step_index
    if step_id:
        trace["step_id"] = str(step_id)
    if scenario_updates:
        trace.update(
            {
                key: value
                for key, value in scenario_updates.items()
                if value not in (None, "", [], {})
            }
        )
    trace = {
        key: value
        for key, value in trace.items()
        if value not in (None, "", [], {})
    }
    base_ctx[TRACE_CONTEXT_KEY] = trace
    return base_ctx


def step_trace_from_context(
    ctx: dict[str, Any] | None,
    *,
    step: dict[str, Any],
    step_index: int,
) -> dict[str, Any]:
    step_id = str(step.get("id") or step.get("_id") or step.get("step_id") or step_index)
    return push_step_path(
        ctx,
        step_id=step_id,
        step_type=str(step.get("type") or step.get("step_type") or ""),
        step_index=step_index,
    )


def build_step_trace_context(
    *,
    step: dict[str, Any] | None,
    step_index: int,
    depth: int = 0,
    runtime_context: dict[str, Any] | None = None,
    base_context: dict[str, Any] | None = None,
    step_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact audit context without credential-bearing values."""
    out: dict[str, Any] = {}
    for source in (base_context, trace_from_runtime_context(runtime_context), step):
        if not isinstance(source, dict):
            continue
        for key in _TRACE_KEYS:
            if key in source:
                _put(out, key, source.get(key))

    _put(out, "step_index", step_index)
    if isinstance(step, dict):
        _put(out, "step_id", step.get("id") or step.get("_id") or step.get("step_id"))
        _put(out, "step_type", step.get("type") or step.get("step_type"))
    _put(out, "depth", depth)

    action: dict[str, Any] = {}
    for source in (step_result, step):
        if not isinstance(source, dict):
            continue
        for key in _ACTION_KEYS:
            if key in source:
                _put(action, key, source.get(key))
    if isinstance(step_result, dict):
        ledger = step_result.get("account_action_ledger")
        if isinstance(ledger, dict):
            _put(action, "account_action_id", ledger.get("action_id"))
            _put(action, "account_id", ledger.get("account_id"))
            _put(action, "account_action_status", ledger.get("status"))
        ledgers = step_result.get("account_action_ledgers")
        if isinstance(ledgers, list):
            action_ids = [
                item.get("action_id")
                for item in ledgers
                if isinstance(item, dict) and item.get("action_id")
            ]
            _put(action, "account_action_ids", action_ids)
    if action:
        out["action"] = action
    return out
