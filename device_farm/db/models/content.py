"""DF-010: Content Pipeline — SQLAlchemy models for crawled content storage."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class ContentItem(Base):
    """Crawled content item (post, profile, video, comment, etc.)."""

    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    collection: Mapped[str] = mapped_column(String(100), nullable=False, default="default", index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    content_type: Mapped[str] = mapped_column(String(50), default="post", index=True)

    # Content fields
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    author_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Metrics
    likes_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shares_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    views_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Media
    media_urls: Mapped[list] = mapped_column(JSON, default=list)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Metadata
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[str] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Source tracking
    device_serial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scenario_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Timestamps
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    content_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("idx_ci_hash_collection", "content_hash", "collection", unique=True),
        Index("idx_ci_extracted_at", "extracted_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "collection": self.collection,
            "platform": self.platform,
            "content_type": self.content_type,
            "title": self.title,
            "body": self.body,
            "author": self.author,
            "author_id": self.author_id,
            "url": self.url,
            "likes_count": self.likes_count,
            "comments_count": self.comments_count,
            "shares_count": self.shares_count,
            "views_count": self.views_count,
            "tags": self.tags,
            "device_serial": self.device_serial,
            "campaign_id": self.campaign_id,
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
        }


class ContentCollection(Base):
    """Named collection for grouping content items."""

    __tablename__ = "content_collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ContentExport(Base):
    """Export job record."""

    __tablename__ = "content_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    collection: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="csv")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
