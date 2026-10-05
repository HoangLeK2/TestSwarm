"""Per-account, per-action rate budget for device actions.

The limiter existed but had no callers, so nothing bounded how fast an account
sent friend requests. These tests pin the two properties that matter: connection
requests get their own much tighter budget, and a throttled account skips the
action instead of tapping.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services import rate_limiter


class _FakeRedis:
    """Minimal sorted-set subset used by the limiter."""

    def __init__(self) -> None:
        self.sets: dict[str, dict[str, float]] = {}

    def pipeline(self) -> "_FakePipeline":
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list = []

    def zremrangebyscore(self, key: str, low: float, high: float) -> None:
        self._ops.append(("zrem", key, low, high))

    def zcount(self, key: str, low: float, high: float) -> None:
        self._ops.append(("zcount", key, low, high))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._ops.append(("zadd", key, mapping))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", key, seconds))

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            kind, key = op[0], op[1]
            bucket = self._redis.sets.setdefault(key, {})
            if kind == "zrem":
                _, _, low, high = op
                for member, score in list(bucket.items()):
                    if low <= score <= high:
                        del bucket[member]
                results.append(0)
            elif kind == "zcount":
                _, _, low, high = op
                results.append(
                    sum(1 for score in bucket.values() if low <= score <= high)
                )
            elif kind == "zadd":
                bucket.update(op[2])
                results.append(len(op[2]))
            else:
                results.append(True)
        self._ops = []
        return results


def _redis_patches(redis: _FakeRedis):
    return (
        patch("services.redis_store.enabled", return_value=True),
        patch("services.redis_store.client", return_value=redis),
        patch("services.redis_store.key", side_effect=lambda name: f"df:{name}"),
    )


async def _allow_n(platform: str, account: str, action: str, times: int) -> list[bool]:
    return [
        await rate_limiter.allow(platform, account, action) for _ in range(times)
    ]


def test_connection_requests_get_a_tighter_budget_than_browsing():
    connection = rate_limiter.limits_for("instagram", "connection_request")
    default = rate_limiter.limits_for("instagram")
    assert connection["per_hour"] < default["per_hour"]
    assert connection["per_day"] < default["per_day"]


def test_unknown_action_falls_back_to_the_platform_default():
    assert rate_limiter.limits_for("instagram", "content_interaction") == (
        rate_limiter.limits_for("instagram")
    )


def test_legacy_flat_config_still_applies():
    """Older config.yaml wrote limits without an action level."""
    original = rate_limiter._LIMITS
    try:
        rate_limiter.configure({"instagram": {"per_hour": 7}})
        assert rate_limiter.limits_for("instagram")["per_hour"] == 7
        assert rate_limiter.limits_for("instagram", "connection_request")["per_hour"] == 7
    finally:
        rate_limiter._LIMITS = original


@pytest.mark.asyncio
async def test_hourly_cap_blocks_further_requests():
    redis = _FakeRedis()
    original = rate_limiter._LIMITS
    rate_limiter.configure(
        {"instagram": {"connection_request": {"per_hour": 3, "per_day": 100}}}
    )
    try:
        enabled, client, key = _redis_patches(redis)
        with enabled, client, key:
            verdicts = await _allow_n("instagram", "acc-1", "connection_request", 5)
    finally:
        rate_limiter._LIMITS = original

    assert verdicts == [True, True, True, False, False]


@pytest.mark.asyncio
async def test_budgets_are_tracked_per_action_and_per_account():
    redis = _FakeRedis()
    original = rate_limiter._LIMITS
    rate_limiter.configure(
        {
            "instagram": {
                "default": {"per_hour": 50},
                "connection_request": {"per_hour": 1},
            }
        }
    )
    try:
        enabled, client, key = _redis_patches(redis)
        with enabled, client, key:
            assert await rate_limiter.allow("instagram", "acc-1", "connection_request")
            # Same account, exhausted for this action only.
            assert not await rate_limiter.allow(
                "instagram", "acc-1", "connection_request"
            )
            assert await rate_limiter.allow("instagram", "acc-1", "content_interaction")
            # A different account has its own budget.
            assert await rate_limiter.allow("instagram", "acc-2", "connection_request")
    finally:
        rate_limiter._LIMITS = original


@pytest.mark.asyncio
async def test_limiter_is_a_no_op_without_redis():
    with patch("services.redis_store.enabled", return_value=False):
        assert await rate_limiter.allow("instagram", "acc-1", "connection_request")


def test_pacing_skips_the_database_when_the_limiter_is_off():
    """Otherwise every action pays a tenant lookup that can only answer 'allowed'."""
    from services import action_pacing

    def _explode(*_args, **_kwargs):
        raise AssertionError("must not touch the database when Redis is disabled")

    with patch("services.redis_store.enabled", return_value=False), patch(
        "services.account_actions.coordinator._resolve_tenant", _explode
    ):
        verdict = action_pacing.check_action_allowed(
            identity={"execution_id": "e", "step_id": "s"},
            action_type="connection_request",
            platform="instagram",
        )

    assert verdict["allowed"] is True
    assert verdict["reason"] == "limiter_disabled"


def test_pacing_failure_allows_the_action():
    """Infrastructure trouble must not stop the farm from working."""
    from services import action_pacing

    def _fail(coro):
        coro.close()  # keep the event loop quiet about an un-awaited coroutine
        raise RuntimeError("no database")

    with patch("services.redis_store.enabled", return_value=True), patch(
        "db.database.run_activity_coro_blocking", _fail
    ):
        verdict = action_pacing.check_action_allowed(
            identity={"execution_id": "e", "step_id": "s"},
            action_type="connection_request",
            platform="instagram",
        )

    assert verdict["allowed"] is True
    assert verdict["reason"] == "pacing_unavailable"
