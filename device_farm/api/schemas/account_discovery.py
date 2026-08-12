"""Platform-neutral account discovery API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AccountDiscoveryStatus = Literal[
    "uninitialized",
    "discovery_requested",
    "discovering",
    "ready",
    "active",
    "error",
]


class AccountDiscoveryCompleteIn(BaseModel):
    candidate_count: int = Field(ge=0)


class AccountDiscoveryFailedIn(BaseModel):
    error: str = Field(min_length=1, max_length=1000)


class AccountDiscoveryStateOut(BaseModel):
    id: str
    org_id: str
    account_id: str
    platform: str
    status: AccountDiscoveryStatus
    initialized_at: datetime | None = None
    discovery_requested_at: datetime | None = None
    discovery_started_at: datetime | None = None
    last_discovery_at: datetime | None = None
    next_discovery_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    request_created: bool | None = None
