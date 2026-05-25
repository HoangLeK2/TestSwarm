"""TikTok XML hierarchy parser.

Phase 3 stub — TikTok encodes a lot of info inside `content-desc` of the video
container (e.g. "Username, video description, 123 likes, 45 comments"). The
parser tries structured selectors first, falls back to content-desc scraping.

Package names:
  - com.zhiliaoapp.musically (global)
  - com.ss.android.ugc.trill  (regional)
"""
from __future__ import annotations

import re
from typing import List

from lxml import etree

from relay.extra_data.parsers.base import BasePlatformParser, ExtractedItem


class TikTokParser(BasePlatformParser):
    platform = "tiktok"
    package_names = ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"]

    _VIDEO_CONTAINERS = (
        '//*[contains(@resource-id,"feed_item")]'
        ' | //*[contains(@resource-id,"video_card")]'
    )
    _COMMENT_NODES = '//*[contains(@resource-id,"comment_item")]'

    _RE_LIKES = re.compile(r"([\d.,]+[KkMmBb]?)\s*likes?", re.IGNORECASE)
    _RE_COMMENTS = re.compile(r"([\d.,]+[KkMmBb]?)\s*comments?", re.IGNORECASE)
    _RE_VIEWS = re.compile(r"([\d.,]+[KkMmBb]?)\s*(?:views?|plays?)", re.IGNORECASE)

    def parse_posts(self, xml_root: etree._Element) -> List[ExtractedItem]:
        items = [
            item
            for node in xml_root.xpath(self._VIDEO_CONTAINERS)
            if (item := self._parse_node(node))
        ]
        if not items:
            items = self._parse_from_content_desc(xml_root)
        return self.dedup(items)

    def _parse_node(self, node: etree._Element) -> ExtractedItem | None:
        item = ExtractedItem(platform=self.platform, content_type="video")
        item.author = self.first_text(
            node,
            './/*[contains(@resource-id,"nickname") or contains(@resource-id,"author_name")]',
        )
        item.body = self.first_text(
            node,
            './/*[contains(@resource-id,"desc") or contains(@resource-id,"caption")]',
        )
        item.likes_count = self.parse_count(
            self.first_text(
                node,
                './/*[contains(@resource-id,"digg") or contains(@resource-id,"like_count")]',
            )
        )
        item.comments_count = self.parse_count(
            self.first_text(node, './/*[contains(@resource-id,"comment_count")]')
        )
        item.shares_count = self.parse_count(
            self.first_text(node, './/*[contains(@resource-id,"share_count")]')
        )
        if item.author or item.body:
            return item
        return None

    def _parse_from_content_desc(self, xml_root: etree._Element) -> List[ExtractedItem]:
        """TikTok often puts everything in content-desc. Example:
        "JohnDoe, Funny dog video, 1.2K likes, 45 comments, 3M views"
        """
        items: List[ExtractedItem] = []
        for node in xml_root.xpath(
            '//*[@content-desc and string-length(@content-desc) > 20]'
        ):
            desc = node.get("content-desc", "")
            low = desc.lower()
            if "likes" not in low and "comments" not in low:
                continue
            item = ExtractedItem(platform=self.platform, content_type="video")
            item.body = desc[:500]
            if m := self._RE_LIKES.search(desc):
                item.likes_count = self.parse_count(m.group(1))
            if m := self._RE_COMMENTS.search(desc):
                item.comments_count = self.parse_count(m.group(1))
            if m := self._RE_VIEWS.search(desc):
                item.views_count = self.parse_count(m.group(1))
            items.append(item)
        return items

    def parse_comments(
        self, xml_root: etree._Element, post_key: str
    ) -> List[ExtractedItem]:
        items: List[ExtractedItem] = []
        for node in xml_root.xpath(self._COMMENT_NODES):
            item = ExtractedItem(
                platform=self.platform,
                content_type="comment",
                parent_key=post_key,
                item_level=1,
            )
            item.author = self.first_text(node, './/*[contains(@resource-id,"author_name")]')
            item.body = self.first_text(node, './/*[contains(@resource-id,"comment_text")]')
            item.likes_count = self.parse_count(
                self.first_text(node, './/*[contains(@resource-id,"digg_count")]')
            )
            if item.author or item.body:
                items.append(item)
        return self.dedup(items)
