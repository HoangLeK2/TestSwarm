"""DF-010: Content Pipeline — Pydantic schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ContentItemOut(BaseModel):
    id: str
    collection: str
    platform: str | None = None
    content_type: str
    title: str | None = None
    body: str | None = None
    author: str | None = None
    url: str | None = None
    likes_count: int | None = None
    comments_count: int | None = None
    shares_count: int | None = None
    views_count: int | None = None
    tags: str = ""
    device_serial: str | None = None
    campaign_id: str | None = None
    extracted_at: datetime | None = None


class ContentQueryParams(BaseModel):
    collection: str | None = None
    platform: str | None = None
    content_type: str | None = None
    search: str | None = None
    device_serial: str | None = None
    campaign_id: str | None = None
    limit: int = 50
    offset: int = 0


class SaveContentBody(BaseModel):
    data: dict[str, Any]
    collection: str = "default"
    platform: str | None = None
    content_type: str = "post"
    dedupe_field: str | None = None
    tags: str = ""
    device_serial: str | None = None
    campaign_id: str | None = None


class CollectionOut(BaseModel):
    id: str
    name: str
    description: str
    platform: str | None = None
    item_count: int
    created_at: datetime


class CollectionCreate(BaseModel):
    name: str
    description: str = ""
    platform: str | None = None


class ContentStatsOut(BaseModel):
    total_items: int
    by_platform: dict[str, int]
    by_collection: dict[str, int]
    latest_extraction: str | None = None
