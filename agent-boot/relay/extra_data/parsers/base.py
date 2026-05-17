"""Base parser interface for platform-specific XML hierarchy extractors.

Phase 3 — crawling-enhancement. Common data shape + abstract interface so the
scenario engine can swap parsers based on detected platform package.

Each concrete platform parser lives in its own package under
`relay/extra_data/parsers/<platform>/` and is wired via
`relay/extra_data/parsers/platform_detector.py`.
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional

from lxml import etree


# ─── Unified output shape ───────────────────────────────────────────────────


@dataclass
class ExtractedItem:
    """Platform-agnostic content item. Superset of ContentItem DB columns."""
    platform: str
    content_type: str                 # post | comment | reply | video | story | reel
    author: str = ""
    author_id: str = ""
    body: str = ""
    title: str = ""
    url: str = ""
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    views_count: int = 0
    media_urls: List[str] = field(default_factory=list)
    parent_key: Optional[str] = None  # dedup key of parent post for comments
    item_level: int = 0               # 0=post, 1=comment, 2=reply
    raw_key: str = ""                 # stable dedup key
    content_date: Optional[str] = None  # raw date string; parsed downstream
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Dict payload for content_store.save_content_item."""
        return {
            "platform": self.platform,
            "content_type": self.content_type,
            "author": self.author,
            "author_id": self.author_id,
            "body": self.body,
            "title": self.title,
            "url": self.url,
            "likes_count": self.likes_count,
            "comments_count": self.comments_count,
            "shares_count": self.shares_count,
            "views_count": self.views_count,
            "media_urls": self.media_urls,
            "parent_key": self.parent_key,
            "item_level": self.item_level,
            "raw_key": self.raw_key,
            "content_date": self.content_date,
            **self.extra,
        }


# ─── Base parser ────────────────────────────────────────────────────────────


class BasePlatformParser(ABC):
    """Abstract parser. Subclasses set `platform` + `package_names` and
    implement `parse_posts` / `parse_comments`.
    """
    platform: str = ""
    package_names: List[str] = []

    @abstractmethod
    def parse_posts(self, xml_root: etree._Element) -> List[ExtractedItem]:
        """Parse main feed posts from UIAutomator2 XML hierarchy."""
        raise NotImplementedError

    def parse_comments(
        self, xml_root: etree._Element, post_key: str
    ) -> List[ExtractedItem]:
        """Parse comment thread for a post. Default: empty."""
        return []

    # ─── Shared helpers — concrete parsers reuse ───────────────────────

    def make_key(self, item: ExtractedItem) -> str:
        """Stable dedup key from platform + author_id + body prefix."""
        raw = f"{item.platform}:{item.author_id or item.author}:{(item.body or '')[:120]}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def dedup(self, items: List[ExtractedItem]) -> List[ExtractedItem]:
        """Remove duplicates by raw_key (computed if missing)."""
        seen: set[str] = set()
        out: List[ExtractedItem] = []
        for i in items:
            if not i.raw_key:
                i.raw_key = self.make_key(i)
            if i.raw_key and i.raw_key not in seen:
                seen.add(i.raw_key)
                out.append(i)
        return out

    _COUNT_RE = re.compile(r"([\d.,]+)\s*([KkMmBb])?")

    def parse_count(self, text: Any) -> int:
        """Parse "1,234", "1.2K", "45M", "123 likes" → int. Returns 0 on parse fail."""
        if text is None:
            return 0
        # Strip thousand separators before regex so "123,456" reads as 123456.
        s = str(text).replace(",", "").strip()
        if not s:
            return 0
        m = self._COUNT_RE.search(s)
        if not m:
            return 0
        try:
            val = float(m.group(1))
        except (ValueError, TypeError):
            return 0
        suffix = (m.group(2) or "").lower()
        if suffix == "k":
            val *= 1_000
        elif suffix == "m":
            val *= 1_000_000
        elif suffix == "b":
            val *= 1_000_000_000
        return int(val)

    # ─── XPath helpers ─────────────────────────────────────────────────

    @staticmethod
    def first_text(node: etree._Element, xpath: str) -> str:
        """Return .text of first matching node via XPath, or empty string."""
        found = node.xpath(xpath)
        if not found:
            return ""
        n = found[0]
        return (n.get("text") or n.get("content-desc") or "").strip()

    @staticmethod
    def first_attr(node: etree._Element, xpath: str, attr: str) -> str:
        found = node.xpath(xpath)
        if not found:
            return ""
        return (found[0].get(attr) or "").strip()
