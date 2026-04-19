from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


_STRATEGY_PATTERN = r"^(round_robin|least_recent)$"


class AccountGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    platform: str = Field(min_length=1, max_length=50)
    rotation_strategy: str = Field(default="round_robin", pattern=_STRATEGY_PATTERN)


class AccountGroupUpdate(BaseModel):
    # `platform` is intentionally immutable to preserve the invariant that
    # every member's platform matches the group's platform.
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    rotation_strategy: Optional[str] = Field(default=None, pattern=_STRATEGY_PATTERN)


class AccountGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: Optional[str]
    name: str
    description: str
    platform: str
    rotation_strategy: str
    rotation_cursor: int
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class AccountGroupMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: str
    username: str
    display_name: str
    status: str
    position: int
    last_used_at: Optional[datetime]
    added_at: datetime


class AccountGroupMemberBatchAdd(BaseModel):
    """Body for POST /account-groups/{id}/members. Idempotent; duplicates ignored."""

    account_ids: List[str] = Field(min_length=1, max_length=500)


class AccountGroupMemberBatchResult(BaseModel):
    added: int
    skipped: int
