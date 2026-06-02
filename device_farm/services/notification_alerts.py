from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field


class AlertRuleConfig(BaseModel):
    metric: str
    comparator: str = Field(pattern="^(gt|gte|lt|lte|eq|ne)$")
    threshold: float
    window_minutes: int = Field(gt=0, le=1440)
    severity: str = Field(pattern="^(info|warning|critical)$")


def should_fire_alert(rule: AlertRuleConfig, *, observed_value: float) -> bool:
    if rule.comparator == "gt":
        return observed_value > rule.threshold
    if rule.comparator == "gte":
        return observed_value >= rule.threshold
    if rule.comparator == "lt":
        return observed_value < rule.threshold
    if rule.comparator == "lte":
        return observed_value <= rule.threshold
    if rule.comparator == "eq":
        return observed_value == rule.threshold
    if rule.comparator == "ne":
        return observed_value != rule.threshold
    return False


def should_suppress_alert(
    *,
    rule_id: str,
    now: datetime,
    last_sent_at: datetime | None,
    suppression_minutes: int,
    severity: str,
) -> bool:
    _ = rule_id
    if severity == "critical":
        return False
    if last_sent_at is None:
        return False
    return now < last_sent_at + timedelta(minutes=suppression_minutes)
