"""Normalized content output contract (DF-T-06-007)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NormalizedCounters:
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    views: int | None = None
    followers: int | None = None
    following: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "views": self.views,
            "followers": self.followers,
            "following": self.following,
        }


@dataclass
class NormalizedContent:
    content_type: str
    platform: str
    text_content: str | None = None
    title: str | None = None
    author_id: str | None = None
    author_name: str | None = None
    permalink: str | None = None
    external_id: str | None = None
    media_urls: list[str] = field(default_factory=list)
    counters: NormalizedCounters = field(default_factory=NormalizedCounters)
    posted_at: datetime | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_content_store_dict(self) -> dict[str, Any]:
        """Map to legacy content_store field names."""
        out: dict[str, Any] = {
            "content_type": self.content_type,
            "platform": self.platform,
            "body": self.text_content,
            "text": self.text_content,
            "title": self.title,
            "author": self.author_name,
            "author_id": self.author_id,
            "url": self.permalink,
            "permalink": self.permalink,
            "external_id": self.external_id,
            "media_urls": self.media_urls,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "likes_count": self.counters.likes,
            "comments_count": self.counters.comments,
            "shares_count": self.counters.shares,
            "views_count": self.counters.views,
            "followers_count": self.counters.followers,
            "following_count": self.counters.following,
        }
        out.update(self.raw_data)
        return out
