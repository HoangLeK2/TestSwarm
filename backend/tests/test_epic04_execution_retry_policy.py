"""DF-T-04-011 — step retry policy unit tests."""
from __future__ import annotations

import statistics
from unittest.mock import patch

import pytest

from services.execution.retry_policy import (
    MAX_BACKOFF_MS,
    NON_RETRYABLE,
    compute_wait_ms,
    is_step_failure_retryable,
    parse_step_retry_policy,
)
from services.scenario_validation.checks import check_retry_config
from services.scenario_validation.models import ValidationResult
from services.scenario_validation.step_index import StepIndex


def _step_index(*steps: dict) -> StepIndex:
    return StepIndex.build(list(steps))


class TestParseStepRetryPolicy:
    def test_no_retry_field_returns_none(self):
        assert parse_step_retry_policy({"type": "wait"}) is None

    def test_empty_retry_dict_returns_none(self):
        assert parse_step_retry_policy({"retry": {}}) is None

    def test_max_attempts_one_returns_none(self):
        assert parse_step_retry_policy({"retry": {"max_attempts": 1}}) is None

    def test_valid_epic04_policy(self):
        policy = parse_step_retry_policy(
            {
                "retry": {
                    "max_attempts": 3,
                    "backoff_ms": 1000,
                    "backoff_strategy": "exponential",
                    "jitter": 0.2,
                    "retryable_reasons": ["timeout", "network"],
                }
            }
        )
        assert policy is not None
        assert policy.max_attempts == 3
        assert policy.backoff_ms == 1000
        assert policy.backoff_strategy == "exponential"
        assert policy.jitter == 0.2
        assert policy.retryable_reasons == frozenset({"timeout", "network"})

    def test_legacy_attempts_and_on(self):
        policy = parse_step_retry_policy(
            {
                "retry": {
                    "attempts": 3,
                    "on": ["stale_frame"],
                }
            }
        )
        assert policy is not None
        assert policy.max_attempts == 3
        assert policy.retryable_reasons == frozenset({"stale_frame"})


class TestErrorClassifier:
    @pytest.fixture
    def policy(self):
        return parse_step_retry_policy(
            {
                "retry": {
                    "max_attempts": 3,
                    "retryable_reasons": ["timeout"],
                }
            }
        )

    def test_non_retryable_fails_immediately(self, policy):
        result = {"ok": False, "reason_code": "permission_denied"}
        assert is_step_failure_retryable(result, policy) is False
        assert "permission_denied" in NON_RETRYABLE

    def test_retryable_reason_matches(self, policy):
        result = {"ok": False, "reason_code": "timeout"}
        assert is_step_failure_retryable(result, policy) is True

    def test_unlisted_reason_not_retryable(self, policy):
        result = {"ok": False, "reason_code": "network"}
        assert is_step_failure_retryable(result, policy) is False

    def test_legacy_retryable_flag(self, policy):
        result = {"ok": False, "reason_code": "timeout", "retryable": True}
        assert is_step_failure_retryable(result, policy) is True

    def test_cancelled_result_is_never_retryable(self, policy):
        result = {
            "ok": False,
            "reason_code": "timeout",
            "retryable": True,
            "cancelled": True,
        }
        assert is_step_failure_retryable(result, policy) is False


class TestBackoffCalculator:
    def test_exponential_attempt_one_near_base(self):
        policy = parse_step_retry_policy(
            {"retry": {"max_attempts": 3, "backoff_ms": 1000, "jitter": 0}}
        )
        wait = compute_wait_ms(1, policy)
        assert wait.wait_ms == 1000
        assert wait.backoff_capped is False

    def test_exponential_attempt_two_doubles(self):
        policy = parse_step_retry_policy(
            {"retry": {"max_attempts": 3, "backoff_ms": 1000, "jitter": 0}}
        )
        wait = compute_wait_ms(2, policy)
        assert wait.wait_ms == 2000

    def test_backoff_capped_at_max(self):
        policy = parse_step_retry_policy(
            {
                "retry": {
                    "max_attempts": 10,
                    "backoff_ms": 1000,
                    "backoff_strategy": "exponential",
                    "jitter": 0,
                }
            }
        )
        wait = compute_wait_ms(10, policy)
        assert wait.wait_ms == MAX_BACKOFF_MS
        assert wait.backoff_capped is True

    def test_jitter_fraction_bounds(self):
        policy = parse_step_retry_policy(
            {"retry": {"max_attempts": 3, "backoff_ms": 1000, "jitter": 0.5}}
        )
        with patch(
            "services.execution.retry_policy.random.uniform",
            side_effect=[-0.5, 0.5, 0.0],
        ):
            assert compute_wait_ms(1, policy).wait_ms == 500
            assert compute_wait_ms(1, policy).wait_ms == 1500
            assert compute_wait_ms(1, policy).wait_ms == 1000

    def test_jitter_distribution_mean(self):
        policy = parse_step_retry_policy(
            {"retry": {"max_attempts": 3, "backoff_ms": 1000, "jitter": 0.5}}
        )
        samples = [compute_wait_ms(1, policy).wait_ms for _ in range(1000)]
        mean = statistics.mean(samples)
        assert 900 <= mean <= 1100


class TestValidation:
    def test_max_attempts_out_of_range_code(self):
        result = ValidationResult()
        check_retry_config(
            _step_index({"retry": {"max_attempts": 20}}),
            result,
        )
        assert any(
            e.code == "RETRY_MAX_ATTEMPTS_OUT_OF_RANGE" for e in result.errors
        )

    def test_invalid_backoff_strategy(self):
        result = ValidationResult()
        check_retry_config(
            _step_index({"retry": {"max_attempts": 2, "backoff_strategy": "linear"}}),
            result,
        )
        assert any(e.code == "RETRY_BACKOFF_INVALID" for e in result.errors)


class TestFr0420Guard:
    """Step without retry field must not produce a retry policy (no hidden default retry)."""

    def test_fail_timeout_no_implicit_retry(self):
        policy = parse_step_retry_policy({"type": "wait"})
        assert policy is None

    def test_fail_with_reason_but_no_retry_block(self):
        step = {"type": "interaction.tap", "ok": False, "reason_code": "timeout"}
        assert parse_step_retry_policy(step) is None
