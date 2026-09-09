"""Platform auto-detection for multi-platform crawling.

Phase 3 — maps Android package name → parser class. Used by extraction step
to pick the right parser based on the currently-focused app.

To add a platform:
  1. Add parser in `relay/extra_data/parsers/<platform>/parser.py` (subclass BasePlatformParser)
  2. Import it here and add to `_REGISTRY` mapping package → class, plus
     `_PLATFORM_PARSERS` mapping platform label → class
  3. Update extraction.py step handler if strategy names are needed
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Type

from lxml import etree

from relay.extra_data.parsers.base import BasePlatformParser
from relay.extra_data.parsers.facebook.adapter import FacebookParser
from relay.extra_data.parsers.instagram import InstagramParser
from relay.extra_data.parsers.linkedin import LinkedInParser
from relay.extra_data.parsers.tiktok import TikTokParser

log = logging.getLogger(__name__)


# Keep instances at module level; parsers are stateless so shared is safe.
_INSTANCES: Dict[str, BasePlatformParser] = {}


def _get_or_create(parser_cls: Type[BasePlatformParser]) -> BasePlatformParser:
    key = parser_cls.__name__
    inst = _INSTANCES.get(key)
    if inst is None:
        inst = parser_cls()
        _INSTANCES[key] = inst
    return inst


# package → parser class.
_REGISTRY: Dict[str, Type[BasePlatformParser]] = {
    "com.facebook.katana": FacebookParser,
    "com.facebook.lite": FacebookParser,
    "com.facebook.orca": FacebookParser,
    "com.instagram.android": InstagramParser,
    "com.zhiliaoapp.musically": TikTokParser,
    "com.ss.android.ugc.trill": TikTokParser,
    "com.linkedin.android": LinkedInParser,
}

_PLATFORM_PARSERS: Dict[str, Type[BasePlatformParser]] = {
    "facebook": FacebookParser,
    "instagram": InstagramParser,
    "tiktok": TikTokParser,
    "linkedin": LinkedInParser,
}


def detect_parser(package_name: str) -> Optional[BasePlatformParser]:
    """Return a parser instance for the given Android package name."""
    if not package_name:
        return None
    cls = _REGISTRY.get(package_name)
    if cls is None:
        return None
    return _get_or_create(cls)


def parser_for_platform(platform: str) -> Optional[BasePlatformParser]:
    """Return a parser instance for a platform label (``"facebook"``, …)."""
    cls = _PLATFORM_PARSERS.get(platform or "")
    if cls is None:
        return None
    return _get_or_create(cls)


def detect_platform(package_name: str) -> Optional[str]:
    """Return the platform name for a package."""
    if not package_name:
        return None
    cls = _REGISTRY.get(package_name)
    if cls is None:
        return None
    return cls.platform or cls.__name__.lower().replace("parser", "")


def detect_platform_from_hierarchy(xml_root: etree._Element) -> Optional[str]:
    """Guess the platform from resource-id namespaces in the hierarchy."""
    try:
        xml_str = etree.tostring(xml_root, encoding="unicode")
    except Exception:
        return None
    low = xml_str.lower()
    if "com.facebook" in xml_str:
        return "facebook"
    if "com.instagram" in xml_str:
        return "instagram"
    if "com.zhiliaoapp" in xml_str or "com.ss.android.ugc" in xml_str or "tiktok" in low:
        return "tiktok"
    if "com.linkedin" in xml_str:
        return "linkedin"
    return None


def detect_from_hierarchy(xml_root: etree._Element) -> Optional[BasePlatformParser]:
    """Fallback detection from XML content when package name unavailable."""
    return parser_for_platform(detect_platform_from_hierarchy(xml_root) or "")


def list_supported_platforms() -> Dict[str, str]:
    """Return {package_name: platform_label} for diagnostics."""
    return {
        pkg: cls.platform or cls.__name__.lower().replace("parser", "")
        for pkg, cls in _REGISTRY.items()
    }
