"""Instagram XML hierarchy parser.

Phase 3 stub — selectors here are best-effort from public documentation + past
captures. They WILL drift when Instagram ships app updates; store failures will
trigger LLM universal extractor (Phase 4) as fallback.

To tune selectors:
  1. Run `weditor` or dump via `adb shell uiautomator dump`
  2. Check resource-id patterns on feed posts / comments
  3. Update XPaths below and add regression test with the captured XML
"""
from __future__ import annotations

from typing import List

from lxml import etree

from relay.extra_data.parsers.base import BasePlatformParser, ExtractedItem


class InstagramParser(BasePlatformParser):
    platform = "instagram"
    package_names = ["com.instagram.android"]

    # XPath fragments — keep in one place for selector validation.
    _POST_CONTAINERS = (
        '//*[contains(@resource-id,"row_feed_item_anchor")]'
        ' | //*[contains(@resource-id,"feed_row")]'
        ' | //*[contains(@resource-id,"feed_unit_container")]'
    )
    _COMMENT_NODES = (
        '//*[contains(@resource-id,"comment_list_item")]'
        ' | //*[contains(@resource-id,"row_comment")]'
    )

    def parse_posts(self, xml_root: etree._Element) -> List[ExtractedItem]:
        items: List[ExtractedItem] = []
        for node in xml_root.xpath(self._POST_CONTAINERS):
            item = ExtractedItem(platform=self.platform, content_type="post")
            item.author = self.first_text(node, './/*[contains(@resource-id,"username")]')
            item.body = self.first_text(
                node,
                './/*[contains(@resource-id,"caption") or contains(@resource-id,"media_caption")]',
            )
            item.likes_count = self.parse_count(
                self.first_attr(
                    node,
                    './/*[contains(@content-desc,"like") or contains(@resource-id,"like_count")]',
                    "content-desc",
                )
                or self.first_text(node, './/*[contains(@resource-id,"like_count")]')
            )
            item.comments_count = self.parse_count(
                self.first_attr(
                    node,
                    './/*[contains(@content-desc,"comment") or contains(@resource-id,"comment_count")]',
                    "content-desc",
                )
                or self.first_text(node, './/*[contains(@resource-id,"comment_count")]')
            )
            item.content_date = self.first_text(
                node, './/*[contains(@resource-id,"timestamp") or contains(@resource-id,"post_time")]'
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
            item.author = self.first_text(node, './/*[contains(@resource-id,"commenter_username")]')
            item.body = self.first_text(node, './/*[contains(@resource-id,"comment_text")]')
            item.likes_count = self.parse_count(
                self.first_attr(node, './/*[contains(@content-desc,"like")]', "content-desc")
            )
            if item.author or item.body:
                items.append(item)
        return self.dedup(items)
