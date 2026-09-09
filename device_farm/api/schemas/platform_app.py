from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PlatformAppReleaseOut(BaseModel):
    id: str
    platform: str
    package_name: str
    version_name: str
    version_code: Optional[str] = None
    sha256: str
    size_bytes: int
    object_key: str
    original_filename: Optional[str] = None
    content_type_mime: str
    status: str
    notes: Optional[str] = None
    uploaded_by_user_id: Optional[str] = None
    published_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlatformAppReleaseListOut(BaseModel):
    items: list[PlatformAppReleaseOut]
    total: int
    offset: int
    limit: int


class PlatformAppDownloadOut(BaseModel):
    release: PlatformAppReleaseOut
    download_url: str
    expires_seconds: int


class PlatformAppPublishOut(BaseModel):
    release: PlatformAppReleaseOut


class PlatformAppInstallRequest(BaseModel):
    serial: str
    timeout_seconds: int = 600


class PlatformAppInstallOut(BaseModel):
    ok: bool
    serial: str
    release: PlatformAppReleaseOut
