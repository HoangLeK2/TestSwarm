"""XML parsers used by agent-side extra-data ingest."""

from relay.extra_data.parsers.base import BasePlatformParser, ExtractedItem
from relay.extra_data.parsers.instagram import InstagramParser
from relay.extra_data.parsers.linkedin import LinkedInParser
from relay.extra_data.parsers.platform_detector import detect_from_hierarchy, detect_parser
from relay.extra_data.parsers.tiktok import TikTokParser

__all__ = [
    "BasePlatformParser",
    "ExtractedItem",
    "InstagramParser",
    "LinkedInParser",
    "TikTokParser",
    "detect_from_hierarchy",
    "detect_parser",
]
