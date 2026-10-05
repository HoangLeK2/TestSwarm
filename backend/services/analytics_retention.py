from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field, field_validator


class RetentionPolicy(BaseModel):
    org_id: str
    data_type: str = Field(pattern="^(activity_log|notifications|metric_rollup|webhook_dlq)$")
    retention_days: int = Field(ge=30, le=3650)
    action: str = Field(pattern="^(purge|archive|aggregate)$")
    legal_hold: bool = False

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("org_id is required")
        return cleaned


def select_retention_cutoff(policy: RetentionPolicy, *, now: datetime) -> datetime | None:
    if policy.legal_hold:
        return None
    return now - timedelta(days=policy.retention_days)
