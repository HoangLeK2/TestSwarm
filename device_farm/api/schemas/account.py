from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from services.account_verification_hold import AccountVerificationHoldOut
from api.schemas.device import DeviceOut

# ``cooldown``/``disabled`` are legacy aliases kept accepting for old clients;
# both normalize below (see services.account_state.fsm.normalize_state).
_LEGACY_STATUS_ALIASES = {"disabled": "suspended", "cooldown": "active"}
_VALID_STATUSES = {
    "unassigned",
    "assigned",
    "active",
    "banned",
    "suspended",
    "retired",
    *_LEGACY_STATUS_ALIASES,
}
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

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in _VALID_STATUSES:
            allowed = _VALID_STATUSES - set(_LEGACY_STATUS_ALIASES)
            raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")
        return _LEGACY_STATUS_ALIASES.get(v, v)


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
    # What the phone last saw on this account's own profile. Kept separate from
    # `display_name` on purpose: that field is what the operator typed, and a
    # profile read must never overwrite it. Null until a scenario reads one.
    observed_display_name: Optional[str] = None
    friends_count: Optional[int] = None
    friends_observed_at: Optional[datetime] = None
    verification_hold: Optional[AccountVerificationHoldOut] = None
    verification_hold_until: Optional[datetime] = None
    # password_encrypted is intentionally excluded from all responses


class DeviceAccountOut(BaseModel):
    id: str
    device_id: str
    account_id: str
    is_primary: bool
    assigned_at: datetime
    verification_status: str = "unknown"
    verified_at: Optional[datetime] = None
    verification_attempted_at: Optional[datetime] = None
    verification_evidence: Dict[str, Any] = Field(default_factory=dict)


class AccountAvailableDevicesOut(BaseModel):
    items: List[DeviceOut] = Field(default_factory=list)
    total: int
    offset: int
    limit: int


class AccountVerificationOut(BaseModel):
    assignment_id: Optional[str] = None
    status: str
    reason: str
    attempted_at: datetime
    verified_at: Optional[datetime] = None
    attempt_id: str
    duration_ms: Optional[float] = None


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


class AccountImportFormatOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str = ""
    delimiter: str = "|"
    platform: str = "facebook"
    fields: List[str]
    is_active: bool = True
    is_builtin: bool = False
    created_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AccountImportFormatListOut(BaseModel):
    items: List[AccountImportFormatOut]


class AccountImportFormatCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    delimiter: str = Field(default="|", min_length=1, max_length=10)
    platform: str = Field(default="facebook", min_length=1, max_length=50)
    fields: List[str] = Field(min_length=1, max_length=50)
    is_active: bool = True


class AccountImportFormatUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=2000)
    delimiter: Optional[str] = Field(default=None, min_length=1, max_length=10)
    platform: Optional[str] = Field(default=None, min_length=1, max_length=50)
    fields: Optional[List[str]] = Field(default=None, min_length=1, max_length=50)
    is_active: Optional[bool] = None
