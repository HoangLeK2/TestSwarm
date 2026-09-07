"""Temporal activity policy for scenario step execution.

The workflow should not know which step types are safe to retry at the Temporal
activity layer. Keep that classification here so side-effect rules and activity
identity stay consistent across single-step and batch dispatch.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from temporalio.common import RetryPolicy

SideEffectClass = Literal["read", "device_effect", "social_effect", "io_effect", "mixed_batch"]

_MAX_ACTIVITY_ID_LEN = 240
_DEFAULT_STEP_TIMEOUT_SECONDS = 120
_READ_STEP_TIMEOUT_SECONDS = 60
_HEARTBEAT_SECONDS = 30
_BATCH_HEARTBEAT_SECONDS = 60

_SAFE_PART_RE = re.compile(r"[^A-Za-z0-9_.:-]+")

_READ_STEP_TYPES = frozenset(
    {
        "wait",
        "wait_element",
        "wait_stable",
        "assert_element",
        "verify_screen",
        "check_element",
        "extract_text_hierarchy",
        "extract_text_ocr",
        "extract_text_ai",
        "extract_screen_data",
        "check_element_exists",
        "evaluate_condition",
        "evaluate_legacy_condition",
    }
)

_IO_EFFECT_STEP_TYPES = frozenset(
    {
        "pull_file",
        "push_file",
        "install_apk",
        "take_screenshot",
        "extract",
        "save_extraction",
    }
)

_SOCIAL_EFFECT_MARKERS = (
    "friend",
    "follow",
    "like",
    "comment",
    "message",
    "connect",
    "react",
    "share",
)

_DEVICE_EFFECT_STEP_TYPES = frozenset(
    {
        "launch_app",
        "stop_app",
        "clear_app",
        "wait_app",
        "open_url",
        "tap",
        "tap_ratio",
        "tap_position",
        "tap_selector",
        "long_tap_selector",
        "double_tap",
        "swipe_ratio",
        "scroll",
        "scroll_down",
        "scroll_to",
        "drag",
        "pinch",
        "key",
        "input_text",
        "input_selector",
        "set_clipboard",
    }
)

_NO_ACTIVITY_RETRY = RetryPolicy(maximum_attempts=1)
_READ_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=2,
    non_retryable_error_types=[
        "ValueError",
        "CampaignDeviceClaimLostError",
    ],
)


@dataclass(frozen=True)
class TemporalStepActivityPolicy:
    activity_id: str
    side_effect_class: SideEffectClass
    start_to_close_timeout: timedelta
    heartbeat_timeout: timedelta
    retry_policy: RetryPolicy
    attempt: int = 1


@dataclass(frozen=True)
class TemporalBatchActivityPolicy:
    activity_id: str
    step_activity_ids: list[str]
    side_effect_class: SideEffectClass
    start_to_close_timeout: timedelta
    heartbeat_timeout: timedelta
    retry_policy: RetryPolicy


def step_side_effect_class(step: dict[str, Any]) -> SideEffectClass:
    step_type = str(step.get("type") or "").strip().lower()
    if step_type in _READ_STEP_TYPES:
        return "read"
    if step_type in _IO_EFFECT_STEP_TYPES:
        return "io_effect"
    if step_type.startswith("social_") or any(
        marker in step_type for marker in _SOCIAL_EFFECT_MARKERS
    ):
        return "social_effect"
    if step_type in _DEVICE_EFFECT_STEP_TYPES:
        return "device_effect"
    return "device_effect"


def step_activity_id(
    *,
    execution_id: str | None,
    step: dict[str, Any],
    step_index: int,
    attempt: int = 1,
) -> str:
    exec_part = _safe_activity_part(execution_id or "preview")
    step_part = _safe_activity_part(
        step.get("id")
        or step.get("_id")
        or step.get("step_id")
        or step.get("step_path")
        or step_index
    )
    step_type = _safe_activity_part(step.get("type") or "step")
    raw = f"step:{exec_part}:{step_part}:{step_type}:attempt:{max(1, int(attempt or 1))}"
    return _fit_activity_id(raw)


def batch_activity_id(
    *,
    execution_id: str | None,
    steps: list[dict[str, Any]],
    step_indices: list[int],
) -> str:
    exec_part = _safe_activity_part(execution_id or "preview")
    first_index = step_indices[0] if step_indices else 0
    last_index = step_indices[-1] if step_indices else first_index
    first_step = steps[0] if steps else {}
    first_step_id = _safe_activity_part(
        first_step.get("id")
        or first_step.get("_id")
        or first_step.get("step_id")
        or first_index
    )
    raw = f"batch:{exec_part}:{first_step_id}:{first_index}-{last_index}:count:{len(steps)}"
    return _fit_activity_id(raw)


def workflow_activity_id(
    *,
    execution_id: str | None,
    activity_name: str,
    step: dict[str, Any] | None = None,
    step_index: int | None = None,
    qualifier: str | int | None = None,
) -> str:
    exec_part = _safe_activity_part(execution_id or "preview")
    name_part = _safe_activity_part(activity_name)
    parts = ["activity", exec_part, name_part]
    if step_index is not None:
        parts.append(str(max(0, int(step_index))))
    if step:
        parts.append(
            _safe_activity_part(
                step.get("id")
                or step.get("_id")
                or step.get("step_id")
                or step.get("step_path")
                or step_index
                or "step"
            )
        )
    if qualifier is not None:
        parts.append(_safe_activity_part(qualifier))
    return _fit_activity_id(":".join(parts))


def build_step_activity_policy(
    *,
    execution_id: str | None,
    step: dict[str, Any],
    step_index: int,
    attempt: int = 1,
    default_start_to_close_timeout: timedelta = timedelta(seconds=_DEFAULT_STEP_TIMEOUT_SECONDS),
) -> TemporalStepActivityPolicy:
    side_effect_class = step_side_effect_class(step)
    declared_timeout = _declared_timeout(step)
    default_seconds = int(default_start_to_close_timeout.total_seconds())
    if side_effect_class == "read":
        read_default = min(default_seconds, _READ_STEP_TIMEOUT_SECONDS)
        base_seconds = max(read_default, declared_timeout + 10)
        retry_policy = _READ_ACTIVITY_RETRY
        heartbeat_timeout = timedelta(seconds=_HEARTBEAT_SECONDS)
    else:
        base_seconds = max(default_seconds, declared_timeout + 20)
        retry_policy = _NO_ACTIVITY_RETRY
        heartbeat_timeout = timedelta(seconds=_BATCH_HEARTBEAT_SECONDS)
    return TemporalStepActivityPolicy(
        activity_id=step_activity_id(
            execution_id=execution_id,
            step=step,
            step_index=step_index,
            attempt=attempt,
        ),
        side_effect_class=side_effect_class,
        start_to_close_timeout=timedelta(seconds=min(max(base_seconds, 1), 3600)),
        heartbeat_timeout=heartbeat_timeout,
        retry_policy=retry_policy,
        attempt=max(1, int(attempt or 1)),
    )


def build_batch_activity_policy(
    *,
    execution_id: str | None,
    steps: list[dict[str, Any]],
    step_indices: list[int],
    start_to_close_timeout: timedelta,
) -> TemporalBatchActivityPolicy:
    return TemporalBatchActivityPolicy(
        activity_id=batch_activity_id(
            execution_id=execution_id,
            steps=steps,
            step_indices=step_indices,
        ),
        step_activity_ids=[
            step_activity_id(
                execution_id=execution_id,
                step=step,
                step_index=idx,
            )
            for step, idx in zip(steps, step_indices)
        ],
        side_effect_class="mixed_batch",
        start_to_close_timeout=start_to_close_timeout,
        heartbeat_timeout=timedelta(seconds=_BATCH_HEARTBEAT_SECONDS),
        retry_policy=_NO_ACTIVITY_RETRY,
    )


def _declared_timeout(step: dict[str, Any]) -> int:
    candidates = [
        step.get("timeout_seconds"),
        step.get("timeout_s"),
        step.get("timeout"),
        step.get("seconds") if str(step.get("type") or "") == "wait" else None,
    ]
    for value in candidates:
        seconds = _positive_seconds(value)
        if seconds > 0:
            return seconds
    for value in (step.get("timeout_ms"), step.get("duration_ms"), step.get("wait_ms")):
        try:
            ms = int(float(value))
        except (TypeError, ValueError):
            continue
        if ms > 0:
            return (ms + 999) // 1000
    return 0


def _positive_seconds(value: Any) -> int:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, seconds)


def _safe_activity_part(value: Any) -> str:
    raw = str(value or "").strip() or "none"
    cleaned = _SAFE_PART_RE.sub("_", raw).strip("_") or "none"
    if len(cleaned) <= 80:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:48]}:{digest}"


def _fit_activity_id(activity_id: str) -> str:
    if len(activity_id) <= _MAX_ACTIVITY_ID_LEN:
        return activity_id
    digest = hashlib.sha1(activity_id.encode("utf-8")).hexdigest()[:16]
    return f"{activity_id[: _MAX_ACTIVITY_ID_LEN - 17]}:{digest}"
