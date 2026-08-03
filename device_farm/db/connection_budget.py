"""Pure connection-budget validation shared by web and Temporal workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class ConnectionBudgetError(RuntimeError):
    """Raised when configured pools can consume the database recovery reserve."""


def _int_value(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError) as exc:
        raise ConnectionBudgetError(f"{name} must be a non-negative integer") from exc


@dataclass(frozen=True)
class ConnectionBudget:
    limit: int | None
    reserve: int
    web_max: int
    activity_max: int
    temporal_max: int

    @property
    def configured_demand(self) -> int:
        return self.web_max + self.activity_max + self.temporal_max

    @property
    def total_with_reserve(self) -> int:
        return self.configured_demand + self.reserve

    @property
    def headroom(self) -> int | None:
        if self.limit is None:
            return None
        return self.limit - self.total_with_reserve


def validate_connection_budget(env: Mapping[str, str]) -> ConnectionBudget:
    """Validate aggregate web, activity, and Temporal connection demand.

    Validation is advisory when ``DB_CONNECTION_LIMIT`` is absent. Deployments
    that share PostgreSQL with Temporal should set the limit explicitly so an
    unsafe pool change fails before workers start.
    """

    configured_limit = _int_value(env, "DB_CONNECTION_LIMIT", 0)
    limit = configured_limit or None
    reserve = _int_value(env, "DB_CONNECTION_RESERVE", 15)
    worker_count = _int_value(env, "TEMPORAL_WORKER_COUNT", 7)
    web_max = _int_value(env, "DB_POOL_SIZE", 12) + _int_value(
        env, "DB_MAX_OVERFLOW", 3
    )
    activity_pool_max = _int_value(env, "DB_ACTIVITY_POOL_SIZE", 4) + _int_value(
        env, "DB_ACTIVITY_MAX_OVERFLOW", 0
    )
    budget = ConnectionBudget(
        limit=limit,
        reserve=reserve,
        web_max=web_max,
        activity_max=worker_count * activity_pool_max,
        temporal_max=_int_value(env, "TEMPORAL_DB_MAX_CONNECTIONS", 0),
    )
    if limit is not None and budget.total_with_reserve > limit:
        raise ConnectionBudgetError(
            "unsafe database connection budget: "
            f"{budget.configured_demand} configured + {reserve} reserved > {limit}"
        )
    return budget
