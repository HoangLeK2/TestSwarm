"""Platform auto-detection for multi-platform crawling.

Phase 3 — maps Android package name → parser class. Used by extraction step
to pick the right parser based on the currently-focused app.

To add a platform:
  1. Add parser in `relay/extra_data/parsers/<platform>/parser.py` (subclass BasePlatformParser)
  2. Import it here and add to `_REGISTRY` mapping package → class
  3. Update extraction.py step handler if strategy names are needed
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Type

from lxml import etree

from relay.extra_data.parsers.base import BasePlatformParser
from relay.extra_data.parsers.instagram import InstagramParser
from relay.extra_data.parsers.linkedin import LinkedInParser
from relay.extra_data.parsers.tiktok import TikTokParser

log = logging.getLogger(__name__)


# Facebook extraction is owned by agent-boot edge extra-data.
_FACEBOOK_PACKAGES = {
    "com.facebook.katana",
    "com.facebook.lite",
    "com.facebook.orca",  # Messenger — same hierarchy patterns for posts
}

# Keep instances at module level; parsers are stateless so shared is safe.
_INSTANCES: Dict[str, BasePlatformParser] = {}


def _get_or_create(parser_cls: Type[BasePlatformParser]) -> BasePlatformParser:
    key = parser_cls.__name__
    inst = _INSTANCES.get(key)
    if inst is None:
        inst = parser_cls()
        _INSTANCES[key] = inst
    return inst


# package → parser class. Facebook is deliberately absent: its extraction runs
# through the dedicated `parsers/facebook` pipeline, not a BasePlatformParser.
# Callers detect it with `detect_platform` / `is_facebook` and route accordingly.
_REGISTRY: Dict[str, Type[BasePlatformParser]] = {
    "com.instagram.android": InstagramParser,
    "com.zhiliaoapp.musically": TikTokParser,
    "com.ss.android.ugc.trill": TikTokParser,
    "com.linkedin.android": LinkedInParser,
}


def detect_parser(package_name: str) -> Optional[BasePlatformParser]:
    """Return a parser instance for the given Android package name.

    Facebook packages return None because Facebook extraction is routed through
    the `parsers/facebook` pipeline. Use :func:`detect_platform` when you need to
    know *which* platform is on screen, including Facebook.
    """
    if not package_name:
        return None
    cls = _REGISTRY.get(package_name)
    if cls is None:
        return None
    return _get_or_create(cls)


def detect_platform(package_name: str) -> Optional[str]:
    """Return the platform name for a package, including Facebook."""
    if not package_name:
        return None
    if package_name in _FACEBOOK_PACKAGES:
        return "facebook"
    cls = _REGISTRY.get(package_name)
    if cls is None:
        return None
    return cls.platform or cls.__name__.lower().replace("parser", "")


def is_facebook(package_name: str) -> bool:
    return package_name in _FACEBOOK_PACKAGES


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


_PLATFORM_PARSERS: Dict[str, Type[BasePlatformParser]] = {
    "instagram": InstagramParser,
    "tiktok": TikTokParser,
    "linkedin": LinkedInParser,
}


def detect_from_hierarchy(xml_root: etree._Element) -> Optional[BasePlatformParser]:
    """Fallback detection from XML content when package name unavailable.

    Returns None for Facebook — the caller routes that to the facebook pipeline.
    """
    platform = detect_platform_from_hierarchy(xml_root)
    cls = _PLATFORM_PARSERS.get(platform or "")
    if cls is None:
        return None
    return _get_or_create(cls)


def list_supported_platforms() -> Dict[str, str]:
    """Return {package_name: platform_label} for diagnostics."""
    out: Dict[str, str] = {pkg: "facebook" for pkg in _FACEBOOK_PACKAGES}
    for pkg, cls in _REGISTRY.items():
        out[pkg] = cls.platform or cls.__name__.lower().replace("parser", "")
    return out
