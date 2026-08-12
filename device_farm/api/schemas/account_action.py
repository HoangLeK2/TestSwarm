from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AccountActionOut(BaseModel):
    id: str
    account_id: str
    status: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    target_label: str | None = None
    current_activity: str | None = None
    error_code: str | None = None
    error_message: str | None = None
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
