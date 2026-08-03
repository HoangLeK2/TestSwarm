from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

_VALID_STATUSES = {"active", "banned", "cooldown", "suspended", "retired", "disabled"}
_VALID_PLATFORMS = {"facebook", "tiktok", "google", "instagram", "twitter", "youtube"}


class AccountCreate(BaseModel):
    platform: str
    username: str
    password: Optional[str] = None          # plaintext — encrypted before storage
    display_name: str = ""
    notes: str = ""
    tags: str = ""
    proxy_id: Optional[str] = None
    account_metadata: Dict[str, Any] = {}

    @field_validator("platform")
    @classmethod
    def _platform_lower(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("username")
    @classmethod
    def _username_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username cannot be empty")
        return v


class AccountUpdate(BaseModel):
    password: Optional[str] = None          # plaintext — re-encrypted before storage
    display_name: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None
    proxy_id: Optional[str] = None
    account_metadata: Optional[Dict[str, Any]] = None


class AccountStatusUpdate(BaseModel):
    """Legacy status update — routed through FSM (maps ``disabled`` → ``suspended``)."""

    status: str
    reason: str = "legacy PATCH /status"
    ttl_seconds: Optional[int] = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(_VALID_STATUSES - {'disabled'}))}"
            )
        return "suspended" if v == "disabled" else v


class AccountOut(BaseModel):
    id: str
    platform: str
    username: str
    display_name: str
    status: str
    state: str
    state_reason: Optional[str] = None
    state_changed_at: Optional[datetime] = None
    cooldown_until: Optional[datetime]
    proxy_id: Optional[str]
    notes: str
    tags: str
    user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_used_at: Optional[datetime]
    total_usage_minutes: float
    usage_today_minutes: float
    usage_reset_date: Optional[date]
    # password_encrypted is intentionally excluded from all responses


class DeviceAccountOut(BaseModel):
    id: str
    device_id: str
    account_id: str
    is_primary: bool
    assigned_at: datetime


class AccountWithLinksOut(AccountOut):
    """Detailed account response that includes the list of device links."""
    device_links: List[DeviceAccountOut] = []


class AssignAccountBody(BaseModel):
    """Used by POST /devices/{device_id}/accounts — assigns an account to a device."""
    account_id: str
    is_primary: bool = False


class AssignDeviceBody(BaseModel):
    """Used by POST /accounts/{account_id}/devices — assigns a device to an account."""
    device_id: str
    is_primary: bool = False


class SetPrimaryBody(BaseModel):
    account_id: str


class RoundRobinBody(BaseModel):
    account_ids: List[str]
    device_ids: List[str]

    @field_validator("account_ids", "device_ids")
    @classmethod
    def _not_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("list cannot be empty")
        return v


class BulkImportRow(BaseModel):
    platform: str
    username: str
    password: Optional[str] = None
    display_name: str = ""
    tags: str = ""
    notes: str = ""
    email: Optional[str] = None
    totp_secret: Optional[str] = None
    cookies: Optional[str] = None
    token: Optional[str] = None
    account_metadata: Dict[str, Any] = {}

    @field_validator("platform")
    @classmethod
    def _platform_lower(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("username")
    @classmethod
    def _username_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("username cannot be empty")
        return v


class BulkImportBody(BaseModel):
    """JSON bulk import body."""
    accounts: List[BulkImportRow]


class BulkImportResult(BaseModel):
    created: int
    skipped: int
    total: int
