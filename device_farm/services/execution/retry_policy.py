"""Step-level retry policy — DF-T-04-011 / FR-04-07, FR-04-20."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Literal

MAX_BACKOFF_MS = 60_000
MAX_ATTEMPTS = 10

EPIC04_DEFAULT_RETRYABLE = frozenset({"timeout", "network", "element_not_ready"})
NON_RETRYABLE = frozenset({
    "permission_denied",
    "account_unavailable",
    "device_offline_permanent",
    "script_logic_error",
})

# Legacy F1.5 crawl scenarios often omit `on` / `retryable_reasons`.
LEGACY_DEFAULT_RETRYABLE = frozenset({
    "stale_frame",
    "no_candidates",
    "no_feed_container",
    "all_filtered_junk",
    "empty_cluster",
    "anchor_not_found",
    "no_nodes_in_band",
    "no_text_nodes",
})

BackoffStrategy = Literal["fixed", "exponential"]


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    backoff_ms: int
    backoff_strategy: BackoffStrategy
    jitter: float
    retryable_reasons: frozenset[str]
    backoff_cap_ms: int = MAX_BACKOFF_MS
    legacy_jitter_ms: float | None = None


@dataclass(frozen=True)
class WaitComputation:
    wait_ms: int
    backoff_capped: bool


def step_for_single_attempt(step: dict[str, Any]) -> dict[str, Any]:
    """Copy step without retry config — used when workflow owns attempt loop."""
    out = dict(step)
    out.pop("retry", None)
    return out


def parse_step_retry_policy(step: dict[str, Any]) -> RetryPolicy | None:
    """Return a retry policy only when the step explicitly declares retry with max_attempts > 1."""
    raw = step.get("retry")
    if not isinstance(raw, dict) or not raw:
        return None

    attempts_raw = raw.get("max_attempts", raw.get("attempts"))
    if attempts_raw is None:
        return None
    try:
        max_attempts = int(attempts_raw)
    except (TypeError, ValueError):
        return None
    if max_attempts <= 1:
        return None

    try:
        backoff_ms = int(float(raw.get("backoff_ms", 500)))
    except (TypeError, ValueError):
        backoff_ms = 500
    if backoff_ms < 0:
        backoff_ms = 500

    strategy_raw = str(raw.get("backoff_strategy", "exponential")).lower()
    strategy: BackoffStrategy = "fixed" if strategy_raw == "fixed" else "exponential"

    legacy_jitter_ms: float | None = None
    jitter = 0.0
    if "jitter" in raw:
        try:
            jitter = float(raw.get("jitter", 0))
        except (TypeError, ValueError):
            jitter = 0.0
    elif raw.get("jitter_ms") is not None:
        try:
            legacy_jitter_ms = float(raw.get("jitter_ms"))
        except (TypeError, ValueError):
            legacy_jitter_ms = None

    reasons_raw = raw.get("retryable_reasons") or raw.get("on")
    if reasons_raw:
        retryable = frozenset(str(r) for r in reasons_raw if r)
    else:
        retryable = LEGACY_DEFAULT_RETRYABLE

    try:
        cap_ms = int(float(raw.get("backoff_cap_ms", MAX_BACKOFF_MS)))
    except (TypeError, ValueError):
        cap_ms = MAX_BACKOFF_MS
    cap_ms = min(max(0, cap_ms), MAX_BACKOFF_MS)

    return RetryPolicy(
        max_attempts=min(max_attempts, MAX_ATTEMPTS),
        backoff_ms=backoff_ms,
        backoff_strategy=strategy,
        jitter=max(0.0, min(1.0, jitter)),
        retryable_reasons=retryable,
        backoff_cap_ms=cap_ms,
        legacy_jitter_ms=legacy_jitter_ms,
    )


def is_step_failure_retryable(
    step_result: dict[str, Any],
    policy: RetryPolicy,
) -> bool:
    if step_result.get("ok", True):
        return False
    if step_result.get("cancelled") is True:
        return False
    code = str(step_result.get("reason_code") or "")
    if code in NON_RETRYABLE:
        return False
    if step_result.get("retryable") is True:
        return True
    if not code:
        return False
    return code in policy.retryable_reasons


def compute_wait_ms(
    attempt: int,
    policy: RetryPolicy,
    *,
    rng: Any | None = None,
) -> WaitComputation:
    """Compute inter-attempt delay. attempt is 1-based.

    Pass ``rng`` (e.g. ``workflow.random()``) for Temporal workflow timers so
    replay stays deterministic. Omit for in-process executor / unit tests.
    """
    roll = rng.uniform if rng is not None else random.uniform
    base = float(policy.backoff_ms)
    if policy.backoff_strategy == "exponential":
        raw = base * (2 ** (attempt - 1))
    else:
        raw = base

    cap = min(float(policy.backoff_cap_ms), float(MAX_BACKOFF_MS))
    capped = min(raw, cap)
    backoff_capped = raw > cap

    if policy.legacy_jitter_ms is not None:
        delay = capped + roll(0, max(0.0, policy.legacy_jitter_ms))
    else:
        j = policy.jitter
        factor = 1 + roll(-j, j)
        delay = capped * factor

    return WaitComputation(wait_ms=max(0, int(delay)), backoff_capped=backoff_capped)


def record_attempt(
    attempt_records: list[dict[str, Any]],
    *,
    attempt: int,
    error_reason: str | None,
    wait_ms_before_next: int | None,
) -> None:
    attempt_records.append(
        {
            "attempt": attempt,
            "timestamp": time.time(),
            "error_reason": error_reason,
            "wait_ms_before_next": wait_ms_before_next,
        }
    )


def emit_retry_metrics(
    *,
    step_type: str,
    reason_code: str | None,
    backoff_capped: bool,
) -> None:
    try:
        from web.metrics import step_retry_attempt_count, step_retry_backoff_capped_count

        step_retry_attempt_count.labels(
            step_type=step_type or "unknown",
            reason=str(reason_code or "unknown"),
        ).inc()
        if backoff_capped:
            step_retry_backoff_capped_count.inc()
    except Exception:
        pass
