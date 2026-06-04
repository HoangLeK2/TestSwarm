from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


class AnalyticsQueryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_METRICS = {"count", "success_count", "fail_count"}
_DIMENSIONS = {"event_type", "resource_type", "resource_id", "actor", "day"}
_FILTERS = {"event_type", "resource_type", "resource_id", "actor"}
_OPERATORS = {"eq"}


@dataclass
class AnalyticsQuery:
    metric: str
    dimensions: list[str]
    from_date: date
    to_date: date
    filters: dict[str, Any] = field(default_factory=dict)
    operator: str = "eq"
    limit: int = 100

    def __post_init__(self) -> None:
        if self.metric not in _METRICS:
            raise AnalyticsQueryError("UNSUPPORTED_METRIC", f"unsupported metric: {self.metric}")
        unknown_dimensions = [item for item in self.dimensions if item not in _DIMENSIONS]
        if unknown_dimensions:
            raise AnalyticsQueryError(
                "UNSUPPORTED_DIMENSION",
                f"unsupported dimension: {', '.join(unknown_dimensions)}",
            )
        unknown_filters = [item for item in self.filters if item not in _FILTERS]
        if unknown_filters:
            raise AnalyticsQueryError(
                "UNSUPPORTED_FILTER",
                f"unsupported filter: {', '.join(unknown_filters)}",
            )
        if self.operator not in _OPERATORS:
            raise AnalyticsQueryError("UNSUPPORTED_OPERATOR", f"unsupported operator: {self.operator}")
        if self.to_date < self.from_date:
            raise AnalyticsQueryError("INVALID_TIME_RANGE", "to_date must be on or after from_date")
        if (self.to_date - self.from_date).days > 90:
            raise AnalyticsQueryError("WINDOW_TOO_LARGE", "Max 90 days for ad-hoc analytics query")
        self.limit = min(max(int(self.limit or 100), 1), 1000)


def parse_date(value: Any, *, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise AnalyticsQueryError("INVALID_DATE", f"{field_name} must be YYYY-MM-DD") from exc
    raise AnalyticsQueryError("INVALID_DATE", f"{field_name} must be YYYY-MM-DD")


def analytics_query_from_payload(payload: dict[str, Any]) -> AnalyticsQuery:
    return AnalyticsQuery(
        metric=str(payload.get("metric") or ""),
        dimensions=list(payload.get("dimensions") or []),
        filters=dict(payload.get("filters") or {}),
        from_date=parse_date(payload.get("from_date"), field_name="from_date"),
        to_date=parse_date(payload.get("to_date"), field_name="to_date"),
        operator=str(payload.get("operator") or "eq"),
        limit=int(payload.get("limit") or 100),
    )
