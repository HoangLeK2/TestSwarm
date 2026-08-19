"""Stable, platform-neutral identity keys for social profiles.

Both discovery paths must agree on what "the same person" means, or the system
double-sends: content-author discovery mints one key while the on-device UI scan
mints another, and neither can see the other's requests. This module owns that
single definition.

An `external_id` is always preferred — it is the platform's own identifier and
survives a display-name change. A name-only key is a deliberate fallback: it is
weaker (two people can share a name, especially with Vietnamese given names),
which is why callers persist `identity_confidence` alongside it and upgrade to
an external id once a profile is actually opened.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

# Platforms whose profile keys were minted before this module existed. Their
# prefix must not change or every stored identity_key would stop matching.
_LEGACY_PREFIXES = {"facebook": "fb"}


def normalize_display_name(value: str) -> str:
    """Case-fold, strip diacritics, and collapse separators to single spaces."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_marks = (
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .replace("đ", "d")
        .replace("Đ", "D")
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks.casefold()).strip()


def profile_identity_key(
    platform: str,
    *,
    external_id: str | None = None,
    display_name: str | None = None,
    normalized_name: str | None = None,
) -> str:
    """Identity key for one profile on one platform.

    Pass `normalized_name` when the caller already normalized it, otherwise pass
    `display_name` and let this function normalize — mixing the two is what
    causes silent key mismatches between call sites.
    """
    normalized = str(platform or "").strip().casefold()
    if not normalized:
        raise ValueError("platform is required for a profile identity key")
    prefix = _LEGACY_PREFIXES.get(normalized, normalized)

    resolved_name = (
        normalized_name
        if normalized_name is not None
        else normalize_display_name(display_name or "")
    )
    clean_external_id = str(external_id or "").strip()
    if not clean_external_id and not resolved_name:
        raise ValueError("external_id or display_name is required")

    source = (
        f"id:{clean_external_id}" if clean_external_id else f"name:{resolved_name}"
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"{prefix}-profile:{digest}"


def identity_confidence(external_id: str | None) -> str:
    """Confidence label stored on ExternalEntity for a minted key."""
    return "external_id" if str(external_id or "").strip() else "name_only"
