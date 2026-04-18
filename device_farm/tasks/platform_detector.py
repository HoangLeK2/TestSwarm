"""Platform auto-detection for multi-platform crawling.

Phase 3 — maps Android package name → parser class. Used by extraction step
to pick the right parser based on the currently-focused app.

To add a platform:
  1. Add parser in `tasks/<platform>_extract.py` (subclass BasePlatformParser)
  2. Import it here and add to `_REGISTRY` mapping package → class
  3. Update extraction.py step handler if strategy names are needed
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Type

from lxml import etree

from tasks.base_extract import BasePlatformParser
from tasks.ig_extract import InstagramParser
from tasks.linkedin_extract import LinkedInParser
from tasks.tiktok_extract import TikTokParser

log = logging.getLogger(__name__)


# Lazy FB parser hook — fb_extract.py has its own shape (non-OO); wrap on demand.
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


# package → parser class
_REGISTRY: Dict[str, Type[BasePlatformParser]] = {
    **{pkg: type("_FBParserShim", (), {})  # placeholder; resolved lazily
       for pkg in _FACEBOOK_PACKAGES},
    "com.instagram.android": InstagramParser,
    "com.zhiliaoapp.musically": TikTokParser,
    "com.ss.android.ugc.trill": TikTokParser,
    "com.linkedin.android": LinkedInParser,
}


def detect_parser(package_name: str) -> Optional[BasePlatformParser]:
    """Return a parser instance for the given Android package name.

    Facebook uses the legacy fb_extract module which is not OO-shaped; this
    function returns None for FB packages — callers should dispatch to the
    existing fb_extract pipeline when package is a Facebook one.
    """
    if not package_name:
        return None
    if package_name in _FACEBOOK_PACKAGES:
        # fb_extract uses module-level functions; caller dispatches directly.
        return None
    cls = _REGISTRY.get(package_name)
    if cls is None or cls.__name__ == "_FBParserShim":
        return None
    return _get_or_create(cls)


def is_facebook(package_name: str) -> bool:
    return package_name in _FACEBOOK_PACKAGES


def detect_from_hierarchy(xml_root: etree._Element) -> Optional[BasePlatformParser]:
    """Fallback detection from XML content when package name unavailable.

    Inspects resource-id namespaces in the hierarchy to guess platform.
    """
    try:
        xml_str = etree.tostring(xml_root, encoding="unicode")
    except Exception:
        return None
    low = xml_str.lower()
    if "com.facebook" in xml_str:
        return None  # caller handles FB explicitly
    if "com.instagram" in xml_str:
        return _get_or_create(InstagramParser)
    if "com.zhiliaoapp" in xml_str or "com.ss.android.ugc" in xml_str or "tiktok" in low:
        return _get_or_create(TikTokParser)
    if "com.linkedin" in xml_str:
        return _get_or_create(LinkedInParser)
    return None


def list_supported_platforms() -> Dict[str, str]:
    """Return {package_name: platform_label} for diagnostics."""
    out: Dict[str, str] = {}
    for pkg, cls in _REGISTRY.items():
        if pkg in _FACEBOOK_PACKAGES:
            out[pkg] = "facebook"
        elif cls.__name__ != "_FBParserShim":
            out[pkg] = cls.platform or cls.__name__.lower().replace("parser", "")
    return out
