"""Production configuration and identifiers for continuous source-pool crawls."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Literal


CONTINUOUS_CRAWL_MODE = "continuous_source_pool"
FIXED_FAN_OUT_MODE = "fixed_fan_out"


class ContinuousCrawlConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ContinuousCrawlConfig:
    mode: Literal["fixed_fan_out", "continuous_source_pool"] = FIXED_FAN_OUT_MODE
    max_concurrency: int = 10
    source_page_size: int = 500
    max_targets: int = 100_000
    target_timeout_seconds: int = 600
    maximum_attempts: int = 4
    failure_policy: Literal["continue", "fail_fast"] = "continue"
    max_failure_ratio: float = 0.2
    max_consecutive_failures: int = 20

    @property
    def continuous(self) -> bool:
        return self.mode == CONTINUOUS_CRAWL_MODE


def parse_continuous_crawl_config(variables: dict[str, Any] | None) -> ContinuousCrawlConfig:
    raw = (variables or {}).get("_crawl") or {}
    if not isinstance(raw, dict):
        raise ContinuousCrawlConfigError("_crawl must be an object")
    retry = raw.get("target_retry") or {}
    if not isinstance(retry, dict):
        raise ContinuousCrawlConfigError("_crawl.target_retry must be an object")
    mode = str(raw.get("mode") or FIXED_FAN_OUT_MODE)
    if mode not in {FIXED_FAN_OUT_MODE, CONTINUOUS_CRAWL_MODE}:
        raise ContinuousCrawlConfigError(f"Unsupported crawl mode: {mode}")
    failure_policy = str(raw.get("failure_policy") or "continue")
    if failure_policy not in {"continue", "fail_fast"}:
        raise ContinuousCrawlConfigError(
            f"Unsupported failure policy: {failure_policy}"
        )

    def bounded_int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(raw.get(key, default))
        except (TypeError, ValueError) as exc:
            raise ContinuousCrawlConfigError(f"_crawl.{key} must be an integer") from exc
        if not low <= value <= high:
            raise ContinuousCrawlConfigError(
                f"_crawl.{key} must be between {low} and {high}"
            )
        return value

    try:
        failure_ratio = float(raw.get("max_failure_ratio", 0.2))
    except (TypeError, ValueError) as exc:
        raise ContinuousCrawlConfigError(
            "_crawl.max_failure_ratio must be a number"
        ) from exc
    if not 0 <= failure_ratio <= 1:
        raise ContinuousCrawlConfigError(
            "_crawl.max_failure_ratio must be between 0 and 1"
        )
    try:
        attempts = int(retry.get("maximum_attempts", 4))
    except (TypeError, ValueError) as exc:
        raise ContinuousCrawlConfigError(
            "_crawl.target_retry.maximum_attempts must be an integer"
        ) from exc
    if not 1 <= attempts <= 10:
        raise ContinuousCrawlConfigError(
            "_crawl.target_retry.maximum_attempts must be between 1 and 10"
        )
    return ContinuousCrawlConfig(
        mode=mode,  # type: ignore[arg-type]
        max_concurrency=bounded_int("max_concurrency", 10, 1, 200),
        source_page_size=bounded_int("source_page_size", 500, 10, 2_000),
        max_targets=bounded_int("max_targets", 100_000, 1, 1_000_000),
        target_timeout_seconds=bounded_int("target_timeout_seconds", 600, 30, 86_400),
        maximum_attempts=attempts,
        failure_policy=failure_policy,  # type: ignore[arg-type]
        max_failure_ratio=failure_ratio,
        max_consecutive_failures=bounded_int(
            "max_consecutive_failures", 20, 1, 10_000
        ),
    )


def source_filter_hash(source_pool: dict[str, Any]) -> str:
    canonical = json.dumps(source_pool, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def crawl_workflow_id(campaign_id: str, dispatch_id: str) -> str:
    return f"campaign:{campaign_id}:crawl:{dispatch_id}"


def crawl_target_workflow_id(
    campaign_id: str,
    dispatch_id: str,
    device_serial: str,
    external_entity_id: str,
) -> str:
    """ID of one target's child workflow.

    Must stay byte-identical to the ID ContinuousCrawlWorkflow._run_lane builds,
    including the device segment: the campaign and device workflow listings
    parse this shape to tell a running crawl target from its `:scenario` child.
    """
    return (
        f"campaign:{campaign_id}:crawl:{dispatch_id}"
        f":device:{device_serial}:target:{external_entity_id}"
    )


def crawl_execution_idempotency_key(
    campaign_id: str,
    dispatch_id: str,
    device_serial: str,
    external_entity_id: str,
) -> str:
    return (
        f"campaign-crawl:{campaign_id}:{dispatch_id}:"
        f"{device_serial}:{external_entity_id}"
    )
