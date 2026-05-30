"""DF-010: Content Pipeline — Pydantic schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ContentArtifactOut(BaseModel):
    id: str
    kind: str
    label: str
    source: str
    url: str | None = None
    inline: bool = False
    size_bytes: int | None = None
    status: str = "available"
    mime_type: str | None = None


class ContentItemOut(BaseModel):
    id: str
    collection: str
    platform: str | None = None
    content_type: str
    title: str | None = None
    body: str | None = None
    author: str | None = None
    author_id: str | None = None
    url: str | None = None
    likes_count: int | None = None
    comments_count: int | None = None
    shares_count: int | None = None
    views_count: int | None = None
    media_urls: list[str] = []
    screenshot_path: str | None = None
    tags: str = ""
    raw_data: dict[str, Any] | None = None
    device_serial: str | None = None
    campaign_id: str | None = None
    execution_id: str | None = None
    scenario_name: str | None = None
    extracted_at: datetime | None = None
    content_date: datetime | None = None
    created_at: datetime | None = None
    content_hash: str | None = None
    parent_id: str | None = None
    item_level: int = 0


class ContentDetailOut(ContentItemOut):
    artifacts: list[ContentArtifactOut] = []
    payload: dict[str, Any] = {}


class ContentPermalinkOut(BaseModel):
    token: str
    path: str


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
