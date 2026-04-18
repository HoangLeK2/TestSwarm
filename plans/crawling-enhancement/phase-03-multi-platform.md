# Phase 3: Multi-Platform Extraction

## Objective

Add parsers for Instagram, TikTok, LinkedIn. Add platform auto-detection from app package name. Unify all parsers under common interface so `extraction.py` step handler works the same regardless of platform.

## Problem

Currently only Facebook XML parser exists (`tasks/fb_extract.py`). Every new platform requires manual selector research + custom parser. No standard interface.

## Parser Interface (Base)

**File**: `tasks/base_extract.py` (new)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from lxml import etree

@dataclass
class ExtractedItem:
    platform: str
    content_type: str          # post | comment | reply | video | story
    author: str = ""
    author_id: str = ""
    body: str = ""
    title: str = ""
    url: str = ""
    likes_count: int = 0
    comments_count: int = 0
    shares_count: int = 0
    views_count: int = 0
    media_urls: list = field(default_factory=list)
    parent_key: Optional[str] = None
    item_level: int = 0        # 0=post, 1=comment, 2=reply
    raw_key: str = ""          # dedup key
    extra: dict = field(default_factory=dict)

class BasePlatformParser(ABC):
    platform: str = ""
    package_names: list[str] = []

    @abstractmethod
    def parse_posts(self, xml_root: etree._Element) -> list[ExtractedItem]:
        """Parse main feed posts from XML hierarchy"""
        ...

    @abstractmethod
    def parse_comments(self, xml_root: etree._Element, post_key: str) -> list[ExtractedItem]:
        """Parse comment thread for a post"""
        ...

    def make_key(self, item: ExtractedItem) -> str:
        import hashlib
        raw = f"{item.platform}:{item.author_id}:{item.body[:100]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

## Platform Auto-Detection

**File**: `tasks/platform_detector.py` (new)

```python
from tasks.fb_extract import FacebookParser
from tasks.ig_extract import InstagramParser
from tasks.tiktok_extract import TikTokParser
from tasks.linkedin_extract import LinkedInParser

PARSERS: dict[str, "BasePlatformParser"] = {
    "com.facebook.katana": FacebookParser(),
    "com.facebook.lite": FacebookParser(),
    "com.instagram.android": InstagramParser(),
    "com.zhiliaoapp.musically": TikTokParser(),   # TikTok global
    "com.ss.android.ugc.trill": TikTokParser(),   # TikTok some regions
    "com.linkedin.android": LinkedInParser(),
}

def detect_parser(package_name: str) -> "BasePlatformParser | None":
    return PARSERS.get(package_name)

def detect_from_hierarchy(xml_root) -> "BasePlatformParser | None":
    """Fallback: detect from XML content patterns"""
    xml_str = etree.tostring(xml_root, encoding="unicode")
    if "com.facebook" in xml_str:
        return PARSERS["com.facebook.katana"]
    if "com.instagram" in xml_str:
        return PARSERS["com.instagram.android"]
    if "com.zhiliaoapp" in xml_str or "tiktok" in xml_str.lower():
        return PARSERS["com.zhiliaoapp.musically"]
    return None
```

## Instagram Parser

**File**: `tasks/ig_extract.py` (new)

Instagram XML hierarchy key patterns (from uiautomator2 dump):
- Posts container: `resource-id="com.instagram.android:id/clips_viewer_view_pager"` or `"recycler_view"`
- Post item: `content-desc` contains username + "photo"
- Like count: sibling node with `content-desc` like "1,234 likes"
- Caption: `resource-id` contains `"caption"` or `"media_caption_text"`
- Comment count: `content-desc` like "123 comments"

```python
class InstagramParser(BasePlatformParser):
    platform = "instagram"
    package_names = ["com.instagram.android"]

    def parse_posts(self, xml_root) -> list[ExtractedItem]:
        items = []
        # Find post containers
        posts = xml_root.xpath(
            '//*[@resource-id="com.instagram.android:id/row_feed_item_anchor"]'
            '| //*[contains(@resource-id,"feed_row")]'
        )
        for post_node in posts:
            item = ExtractedItem(platform="instagram", content_type="post")
            
            # Author
            author_nodes = post_node.xpath(
                './/*[contains(@resource-id,"username")]'
            )
            if author_nodes:
                item.author = author_nodes[0].get("text", "")
            
            # Caption
            caption_nodes = post_node.xpath(
                './/*[contains(@resource-id,"caption") or '
                'contains(@resource-id,"media_caption")]'
            )
            if caption_nodes:
                item.body = caption_nodes[0].get("text", "")
            
            # Likes
            like_nodes = post_node.xpath(
                './/*[contains(@content-desc,"like") or '
                'contains(@resource-id,"like_count")]'
            )
            if like_nodes:
                item.likes_count = self._parse_count(
                    like_nodes[0].get("text", "") or 
                    like_nodes[0].get("content-desc", "")
                )
            
            # Comments count
            comment_nodes = post_node.xpath(
                './/*[contains(@content-desc,"comment") or '
                'contains(@resource-id,"comment_count")]'
            )
            if comment_nodes:
                item.comments_count = self._parse_count(
                    comment_nodes[0].get("content-desc", "")
                )
            
            item.raw_key = self.make_key(item)
            if item.author or item.body:
                items.append(item)
        
        return self._dedup(items)

    def parse_comments(self, xml_root, post_key: str) -> list[ExtractedItem]:
        items = []
        comment_nodes = xml_root.xpath(
            '//*[contains(@resource-id,"comment_list_item")]'
            '| //*[contains(@resource-id,"row_comment")]'
        )
        for node in comment_nodes:
            item = ExtractedItem(
                platform="instagram", content_type="comment",
                parent_key=post_key, item_level=1
            )
            # Author
            author = node.xpath('.//*[contains(@resource-id,"commenter_username")]')
            if author:
                item.author = author[0].get("text", "")
            # Text
            text = node.xpath('.//*[contains(@resource-id,"comment_text")]')
            if text:
                item.body = text[0].get("text", "")
            # Likes on comment
            likes = node.xpath('.//*[contains(@content-desc,"like")]')
            if likes:
                item.likes_count = self._parse_count(likes[0].get("content-desc", ""))
            
            item.raw_key = self.make_key(item)
            if item.author or item.body:
                items.append(item)
        return items

    def _parse_count(self, text: str) -> int:
        import re
        text = text.replace(",", "").strip()
        m = re.search(r"[\d.]+[KkMm]?", text)
        if not m:
            return 0
        val = m.group()
        if val.endswith(("K","k")):
            return int(float(val[:-1]) * 1000)
        if val.endswith(("M","m")):
            return int(float(val[:-1]) * 1_000_000)
        return int(float(val))

    def _dedup(self, items):
        seen = set()
        out = []
        for i in items:
            if i.raw_key not in seen:
                seen.add(i.raw_key)
                out.append(i)
        return out
```

## TikTok Parser

**File**: `tasks/tiktok_extract.py` (new)

TikTok key XML patterns:
- Video item: `content-desc` with username + description
- Like button: `resource-id` contains `"like_count"` or `"digg_count"`
- Comment count: `content-desc` like "123 comments"
- Author: `resource-id` contains `"author_name"` or `"nickname"`

```python
class TikTokParser(BasePlatformParser):
    platform = "tiktok"
    package_names = ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"]

    def parse_posts(self, xml_root) -> list[ExtractedItem]:
        items = []
        # TikTok video cards
        video_nodes = xml_root.xpath(
            '//*[contains(@resource-id,"feed_item")]'
            '| //*[contains(@resource-id,"video_card")]'
        )
        if not video_nodes:
            # Fallback: parse from content-desc (TikTok puts lot in content-desc)
            return self._parse_from_content_desc(xml_root)
        
        for node in video_nodes:
            item = ExtractedItem(platform="tiktok", content_type="video")
            
            # Author handle
            author = node.xpath('.//*[contains(@resource-id,"nickname") or contains(@resource-id,"author")]')
            item.author = author[0].get("text","") if author else ""
            
            # Caption / description
            desc = node.xpath('.//*[contains(@resource-id,"desc") or contains(@resource-id,"caption")]')
            item.body = desc[0].get("text","") if desc else ""
            
            # Counts
            likes = node.xpath('.//*[contains(@resource-id,"digg") or contains(@resource-id,"like_count")]')
            if likes:
                item.likes_count = self._parse_count(likes[0].get("text",""))
            
            comments = node.xpath('.//*[contains(@resource-id,"comment_count")]')
            if comments:
                item.comments_count = self._parse_count(comments[0].get("text",""))
            
            item.raw_key = self.make_key(item)
            items.append(item)
        
        return self._dedup(items)

    def parse_comments(self, xml_root, post_key: str) -> list[ExtractedItem]:
        items = []
        nodes = xml_root.xpath('//*[contains(@resource-id,"comment_item")]')
        for node in nodes:
            item = ExtractedItem(platform="tiktok", content_type="comment",
                                  parent_key=post_key, item_level=1)
            author = node.xpath('.//*[contains(@resource-id,"author_name")]')
            item.author = author[0].get("text","") if author else ""
            text = node.xpath('.//*[contains(@resource-id,"comment_text")]')
            item.body = text[0].get("text","") if text else ""
            item.raw_key = self.make_key(item)
            if item.author or item.body:
                items.append(item)
        return items

    def _parse_from_content_desc(self, xml_root) -> list[ExtractedItem]:
        """TikTok often encodes everything in content-desc of video container"""
        import re
        items = []
        nodes = xml_root.xpath('//*[@content-desc and string-length(@content-desc)>20]')
        for node in nodes:
            desc = node.get("content-desc","")
            if "likes" in desc.lower() or "comments" in desc.lower():
                item = ExtractedItem(platform="tiktok", content_type="video")
                item.body = desc[:500]
                m_likes = re.search(r"([\d,]+)\s*likes?", desc, re.I)
                m_comments = re.search(r"([\d,]+)\s*comments?", desc, re.I)
                if m_likes:
                    item.likes_count = int(m_likes.group(1).replace(",",""))
                if m_comments:
                    item.comments_count = int(m_comments.group(1).replace(",",""))
                item.raw_key = self.make_key(item)
                items.append(item)
        return self._dedup(items)

    def _parse_count(self, text: str) -> int:
        # reuse same logic as InstagramParser
        ...

    def _dedup(self, items): ...
```

## LinkedIn Parser

**File**: `tasks/linkedin_extract.py` (new)

```python
class LinkedInParser(BasePlatformParser):
    platform = "linkedin"
    package_names = ["com.linkedin.android"]

    def parse_posts(self, xml_root) -> list[ExtractedItem]:
        items = []
        # LinkedIn feed cards
        post_nodes = xml_root.xpath(
            '//*[contains(@resource-id,"feed_mini_update_content")]'
            '| //*[contains(@resource-id,"update-components")]'
        )
        for node in post_nodes:
            item = ExtractedItem(platform="linkedin", content_type="post")
            
            # Author name
            author = node.xpath('.//*[contains(@resource-id,"actor-name")]')
            item.author = author[0].get("text","") if author else ""
            
            # Post body
            body = node.xpath('.//*[contains(@resource-id,"attributed-text-view")]')
            item.body = body[0].get("text","") if body else ""
            
            # Reactions (LinkedIn uses reactions not just likes)
            reactions = node.xpath('.//*[contains(@content-desc,"reaction")]')
            if reactions:
                item.likes_count = self._parse_count(reactions[0].get("content-desc",""))
            
            item.raw_key = self.make_key(item)
            items.append(item)
        return self._dedup(items)

    def parse_comments(self, xml_root, post_key: str) -> list[ExtractedItem]:
        items = []
        nodes = xml_root.xpath('//*[contains(@resource-id,"comment-list-item")]')
        for node in nodes:
            item = ExtractedItem(platform="linkedin", content_type="comment",
                                  parent_key=post_key, item_level=1)
            author = node.xpath('.//*[contains(@resource-id,"commenter-name")]')
            item.author = author[0].get("text","") if author else ""
            text = node.xpath('.//*[contains(@resource-id,"comment-text")]')
            item.body = text[0].get("text","") if text else ""
            item.raw_key = self.make_key(item)
            items.append(item)
        return items
```

## Integrate with Extraction Step

**File**: `tasks/scenario/steps/extraction.py` (modify)

```python
from tasks.platform_detector import detect_parser, detect_from_hierarchy

async def handle_extract(ctx: ScenarioContext, step, idx, result):
    strategy = step.config.get("strategy", "auto")
    
    if strategy == "auto":
        # Auto-detect platform from running app
        current_pkg = await ctx.device.current_app()
        parser = detect_parser(current_pkg.package)
        if not parser:
            # Get hierarchy and try pattern detection
            xml_root = await ctx.get_hierarchy_xml()
            parser = detect_from_hierarchy(xml_root)
    elif strategy == "fb_posts":
        parser = FacebookParser()
    elif strategy == "ig_posts":
        parser = InstagramParser()
    elif strategy == "tiktok_posts":
        parser = TikTokParser()
    # ... etc
    
    if not parser:
        # Fallback to LLM universal extractor (Phase 4)
        return await handle_llm_extract(ctx, step, idx, result)
    
    xml_root = await ctx.get_hierarchy_xml()
    items = parser.parse_posts(xml_root)
    
    # Save items
    if step.config.get("collection"):
        for item in items:
            await content_store.save(item, collection=step.config["collection"])
    
    result.data = [asdict(i) for i in items]
    result.item_count = len(items)
```

## Files Summary

| File | Action |
|------|--------|
| `tasks/base_extract.py` | New — base class + ExtractedItem dataclass |
| `tasks/platform_detector.py` | New — package→parser mapping + auto-detect |
| `tasks/ig_extract.py` | New — Instagram parser |
| `tasks/tiktok_extract.py` | New — TikTok parser |
| `tasks/linkedin_extract.py` | New — LinkedIn parser |
| `tasks/fb_extract.py` | Modify — make FacebookParser extend BasePlatformParser |
| `tasks/scenario/steps/extraction.py` | Modify — auto-detect parser; fallback to LLM |
| `services/content_store.py` | Modify — accept ExtractedItem directly |

## Note on XML Selectors

**XPath selectors will break when apps update.** Mitigation:
- Keep selectors in `config/platform_selectors.yaml` (not hardcoded)
- Fall through to LLM extractor (Phase 4) when 0 items found
- Log XML hierarchy on parse failure for debugging
- Run weekly selector validation tests
