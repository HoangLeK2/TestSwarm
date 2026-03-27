"""
CrawlJob: one crawl session (one FB group, one device run)
CrawlPost: one row per extracted post
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base
from .utils import _now, _uuid


class CrawlJob(Base):

    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), default="")
    device_serial: Mapped[str] = mapped_column(String(255), default="")
    campaign_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    group_id: Mapped[str] = mapped_column(String(255), default="")
    app: Mapped[str] = mapped_column(String(50), default="chrome")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    scenario_steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    total_posts: Mapped[int] = mapped_column(Integer, default=0)
    total_scrolls: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)

    posts: Mapped[List["CrawlPost"]] = relationship(
        "CrawlPost", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<CrawlJob {self.name} status={self.status}>"


class CrawlPost(Base):

    __tablename__ = "crawl_posts"
    __table_args__ = (Index("ix_crawl_posts_job_id", "job_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False
    )
    author: Mapped[str] = mapped_column(String(512), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    timestamp_raw: Mapped[str] = mapped_column(String(255), default="")
    reactions: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    comments: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    shares: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_index: Mapped[int] = mapped_column(Integer, default=0)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    post_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    image_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    job: Mapped["CrawlJob"] = relationship("CrawlJob", back_populates="posts")

    def __repr__(self) -> str:  # pragma: no cover - repr
        return f"<CrawlPost job={self.job_id} author={self.author!r}>"
