"""Shared campaign failure classification.

The goal is not to predict every root cause.  It is to keep retry, DLQ text,
event payloads, and benchmarks using the same small set of operational classes.
"""
from __future__ import annotations

import unicodedata

from dataclasses import dataclass
from typing import Any

U2_TRANSIENT_REASON = "u2_transient_error"


@dataclass(frozen=True)
class FailureClassification:
    failure_class: str
    reason_code: str | None
    retryable: bool
    retry_hint: str
    operator_summary: str


# Account-level walls. Retrying these is how a recoverable account becomes an
# unrecoverable one, so they are checked before anything else — including the
# transient class, whose markers a checkpoint screen can otherwise resemble.
_ACCOUNT_BLOCKED_MARKERS = (
    "account_blocked",
    "account-level block",
    "tam thoi bi chan",
    "temporarily blocked",
    "xac nhan danh tinh",
    "confirm your identity",
    "xac minh danh tinh",
    "verify your identity",
    "da bi vo hieu hoa",
    "account has been disabled",
    "dang nhap lai",
    "log in again",
    "unusual activity",
    "going too fast",
)

_U2_TRANSIENT_MARKERS = (
    U2_TRANSIENT_REASON,
    "json-rpc http 502",
    "json-rpc http 503",
    "json-rpc http 504",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway",
    "uiautomator not connected",
    "uiautomator not running",
    "uiautomation not connected",
    "instrumentation process is not running",
    "uiautomationservice already registered",
    "ui automation not connected",
)

_DEVICE_LOST_MARKERS = (
    "device offline",
    "device disconnected",
    "no relay",
    "relay disconnected",
    "claim lost",
    "campaigndeviceclaimlosterror",
    "no adb relay",
    "no u2 for serial",
    "no control channel",
    "device not available",
    "transport endpoint",
    "transport is offline",
)

_SELECTOR_MISS_MARKERS = (
    "selector not found",
    "element not found",
    "target not found",
    "target_not_found",
    "post_open_target_not_found",
    "comment_button_not_found",
    "scroll_target_missing",
    "no fallback position",
)

_CRAWL_TIMEOUT_MARKERS = (
    "edge extra_data failed",
    "extra_data timeout",
    "comment wall-clock cap",
    "comment_scroll_wall_s",
    "crawl timeout",
    "collection timeout",
)

_SYSTEM_TIMEOUT_MARKERS = (
    "activity timeout",
    "start_to_close",
    "deadline exceeded",
    "temporal timeout",
    "timed out",
)


def _norm(value: object) -> str:
    return str(value or "").strip()


def _fold(value: str) -> str:
    """Lowercase and strip Vietnamese diacritics before matching.

    Mobile apps may talk to the operator in Vietnamese, so a classifier that only
    lowercased could not recognise messages the platform actually shows
    — "Bạn tạm thời bị chặn" never matched anything. Existing markers are ASCII
    and fold to themselves.
    """
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return without_marks.replace("đ", "d").replace("Đ", "D").lower()


def _combined_text(
    result: dict[str, Any] | None,
    *,
    message: str | None = None,
    reason_code: str | None = None,
) -> str:
    parts: list[str] = []
    if result:
        for key in (
            "failure_class",
            "reason_code",
            "message",
            "failed_message",
            "error",
            "recovery_failed_message",
        ):
            value = result.get(key)
            if value:
                parts.append(str(value))
        edge = result.get("edge_extra_summary")
        if isinstance(edge, dict):
            diagnostic = edge.get("diagnostic")
            if isinstance(diagnostic, dict):
                for key in ("reason_code", "message", "error"):
                    value = diagnostic.get(key)
                    if value:
                        parts.append(str(value))
    if reason_code:
        parts.append(reason_code)
    if message:
        parts.append(message)
    return _fold(" ".join(parts))


def _step_type(result: dict[str, Any] | None, explicit: str | None) -> str:
    return _norm(explicit or (result or {}).get("type")).lower()


def classify_campaign_failure(
    result: dict[str, Any] | None = None,
    *,
    message: str | None = None,
    reason_code: str | None = None,
    step_type: str | None = None,
) -> FailureClassification:
    """Return an operational class for a failed campaign/step result."""
    text = _combined_text(result, message=message, reason_code=reason_code)
    explicit_reason = _norm(reason_code or (result or {}).get("reason_code")) or None
    if explicit_reason and explicit_reason.lower() == "ok":
        # Extraction steps default their diagnostic reason_code to "ok"; when
        # the step later fails, that stale value rode into the DB and produced
        # 15 failed rows reading reason_code='ok'. A failed step has no reason
        # code of "ok" — let the classifier name one.
        explicit_reason = None
    stype = _step_type(result, step_type)

    if any(marker in text for marker in _ACCOUNT_BLOCKED_MARKERS):
        return FailureClassification(
            failure_class="account_blocked",
            reason_code=explicit_reason or "account_blocked",
            retryable=False,
            retry_hint="freeze_account_operator_review_required",
            operator_summary="account_blocked",
        )
    if any(marker in text for marker in _U2_TRANSIENT_MARKERS):
        return FailureClassification(
            failure_class="u2_transient",
            reason_code=U2_TRANSIENT_REASON,
            retryable=True,
            retry_hint="retry_with_single_recovery",
            operator_summary="u2_transient_error",
        )
    if any(marker in text for marker in _DEVICE_LOST_MARKERS):
        return FailureClassification(
            failure_class="device_lost",
            reason_code=explicit_reason or "device_lost",
            retryable=False,
            retry_hint="isolate_device_wait_for_reconnect",
            operator_summary="device_lost",
        )
    if any(marker in text for marker in _SELECTOR_MISS_MARKERS):
        return FailureClassification(
            failure_class="business_selector_miss",
            reason_code=explicit_reason or "selector_not_found",
            retryable=False,
            retry_hint="operator_review_selector_or_screen_state",
            operator_summary="business_selector_miss",
        )
    crawl_like = stype in {"extract", "comments", "loop"} or "comment" in stype
    if (
        any(marker in text for marker in _CRAWL_TIMEOUT_MARKERS)
        or (crawl_like and "timed out" in text)
    ):
        return FailureClassification(
            failure_class="crawl_timeout",
            reason_code=explicit_reason or "crawl_timeout",
            retryable=False,
            retry_hint="keep_checkpoint_review_crawl_budget",
            operator_summary="crawl_timeout",
        )
    if any(marker in text for marker in _SYSTEM_TIMEOUT_MARKERS):
        return FailureClassification(
            failure_class="system_timeout",
            reason_code=explicit_reason or "timeout",
            retryable=True,
            retry_hint="retry_if_policy_allows",
            operator_summary="system_timeout",
        )
    return FailureClassification(
        failure_class="unknown",
        reason_code=explicit_reason,
        retryable=False,
        retry_hint="operator_review_required",
        operator_summary=_norm(message or (result or {}).get("message") or explicit_reason)
        or "unknown_failure",
    )


def annotate_step_failure(step_result: dict[str, Any], *, step_type: str | None = None) -> dict[str, Any]:
    """Add classification fields to a failed step result in-place."""
    if not isinstance(step_result, dict) or step_result.get("ok", True):
        return step_result
    classified = classify_campaign_failure(step_result, step_type=step_type)
    if not _norm(step_result.get("failure_class")):
        step_result["failure_class"] = classified.failure_class
    if not _norm(step_result.get("retry_hint")):
        step_result["retry_hint"] = classified.retry_hint
    if not _norm(step_result.get("operator_summary")):
        step_result["operator_summary"] = classified.operator_summary
    if classified.reason_code and not _norm(step_result.get("reason_code")):
        step_result["reason_code"] = classified.reason_code
    elif _norm(step_result.get("reason_code")).lower() == "ok":
        if classified.reason_code:
            step_result["reason_code"] = classified.reason_code
        else:
            step_result.pop("reason_code", None)
    if classified.retryable and step_result.get("retryable") is None:
        step_result["retryable"] = True
    return step_result
