"""Helpers for bubbling nested scenario failure diagnostics."""
from __future__ import annotations

from typing import Any


_SUMMARY_KEYS = (
    "edge_extra_summary",
    "edge_filter_summary",
)

_TIMING_KEYS = (
    "extra_data_total_ms",
    "extra_data_dump_ms",
    "extra_data_parse_ms",
    "extra_data_click_ms",
    "extra_data_sleep_ms",
    "extra_data_steps",
)


def _failure_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if entry.get("type") is not None:
        meta["step_type"] = entry.get("type")
    if entry.get("index") is not None:
        meta["step_index"] = entry.get("index")
    if entry.get("message") is not None:
        meta["message"] = entry.get("message")
    if entry.get("reason_code") is not None:
        meta["reason_code"] = entry.get("reason_code")
    return meta


def extract_nested_failure_details(result: dict[str, Any] | None) -> dict[str, Any]:
    """Return the first useful diagnostic from a failed nested scenario result."""
    if not isinstance(result, dict):
        return {}

    details: dict[str, Any] = {}
    for key in _SUMMARY_KEYS:
        value = result.get(key)
        if isinstance(value, dict):
            details[key] = value
    for key in _TIMING_KEYS:
        if key in result:
            details[key] = result.get(key)
    if details:
        details.setdefault("nested_failure", _failure_metadata(result))
        return details

    sub = result.get("sub_result")
    sub_details = extract_nested_failure_details(sub if isinstance(sub, dict) else None)
    if sub_details:
        sub_details.setdefault("nested_failure", _failure_metadata(result))
        return sub_details

    for entry in result.get("step_results") or []:
        if not isinstance(entry, dict) or entry.get("ok", True):
            continue
        entry_details = extract_nested_failure_details(entry)
        if entry_details:
            entry_details.setdefault("nested_failure", _failure_metadata(entry))
            return entry_details

    for item in result.get("sub_results") or []:
        if not isinstance(item, dict):
            continue
        nested = item.get("result")
        item_details = extract_nested_failure_details(nested if isinstance(nested, dict) else None)
        if item_details:
            marker = {
                key: item.get(key)
                for key in ("iteration", "branch", "choice")
                if item.get(key) is not None
            }
            if marker:
                item_details["nested_failure_context"] = marker
            return item_details

    return {}


def attach_nested_failure_details(
    target: dict[str, Any],
    nested_result: dict[str, Any] | None,
) -> None:
    """Copy slim nested failure diagnostics onto a parent step result."""
    details = extract_nested_failure_details(nested_result)
    if not details:
        return
    for key, value in details.items():
        target.setdefault(key, value)
