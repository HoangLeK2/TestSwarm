"""LinkedIn XML hierarchy parser.

Phase 3 stub — LinkedIn uses "reactions" vocabulary instead of likes; some
feed items are promoted posts vs user posts.
"""
from __future__ import annotations

from typing import List

from lxml import etree

from tasks.base_extract import BasePlatformParser, ExtractedItem


class LinkedInParser(BasePlatformParser):
    platform = "linkedin"
    package_names = ["com.linkedin.android"]

    _POST_CONTAINERS = (
        '//*[contains(@resource-id,"feed_mini_update_content")]'
        ' | //*[contains(@resource-id,"update-components")]'
        ' | //*[contains(@resource-id,"feed-card")]'
    )
    _COMMENT_NODES = (
        '//*[contains(@resource-id,"comment-list-item")]'
        ' | //*[contains(@resource-id,"feed-comment")]'
    )

    def parse_posts(self, xml_root: etree._Element) -> List[ExtractedItem]:
        items: List[ExtractedItem] = []
        for node in xml_root.xpath(self._POST_CONTAINERS):
            item = ExtractedItem(platform=self.platform, content_type="post")
            item.author = self.first_text(
                node,
                './/*[contains(@resource-id,"actor-name") or contains(@resource-id,"actor_name")]',
            )
            item.body = self.first_text(
                node,
                './/*[contains(@resource-id,"attributed-text-view")'
                ' or contains(@resource-id,"post-text")]',
            )
            item.likes_count = self.parse_count(
                self.first_attr(
                    node,
                    './/*[contains(@content-desc,"reaction") or contains(@content-desc,"like")]',
                    "content-desc",
                )
                or self.first_text(node, './/*[contains(@resource-id,"social-count")]')
            )
            item.comments_count = self.parse_count(
                self.first_text(node, './/*[contains(@resource-id,"comment-count")]')
            )
            if item.author or item.body:
                items.append(item)
        return self.dedup(items)

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
            item.author = self.first_text(
                node, './/*[contains(@resource-id,"commenter-name")]'
            )
            item.body = self.first_text(
                node, './/*[contains(@resource-id,"comment-text")]'
            )
            if item.author or item.body:
                items.append(item)
        return self.dedup(items)
