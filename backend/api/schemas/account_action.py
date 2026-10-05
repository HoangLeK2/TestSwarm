from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AccountActionOut(BaseModel):
    id: str
    account_id: str
    status: str
    action: str
    platform: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_label: str | None = None
    current_activity: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    # Where and when it ran. Present on the row all along; the projection just
    # never carried them, so the UI could not answer "which phone, which run".
    device_serial: str | None = None
    execution_id: str | None = None
    step_id: str | None = None
    artifact_refs: list[Any] = Field(default_factory=list)
    details: dict[str, Any]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AccountActionListOut(BaseModel):
    items: list[AccountActionOut]
    next_cursor: str | None = None
    has_more: bool


class AccountActionSummaryOut(BaseModel):
    total: int
    pending: int
    running: int
    succeeded: int
    failed: int
    current_activity: str | None = None
