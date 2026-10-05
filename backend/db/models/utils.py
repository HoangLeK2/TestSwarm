from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

# Unicode spaces that render like an ASCII space but are not one. Mobile apps
# draws group names with NBSP (U+00A0); a scenario variable copied off the
# screen carries it into the selector, where UiSelector compares byte-exact on
# the device, never matches, and the step waits out its whole timeout. Narrow
# NBSP, the typographic spaces, and the BOM are the same trap. Listed as
# codepoints on purpose — as literals they would be invisible in this file.
_SPACE_TRANSLATION = {
    cp: " "
    for cp in (
        0x00A0,  # NO-BREAK SPACE
        0x1680,  # OGHAM SPACE MARK
        *range(0x2000, 0x200B),  # EN QUAD .. HAIR SPACE
        0x202F,  # NARROW NO-BREAK SPACE
        0x205F,  # MEDIUM MATHEMATICAL SPACE
        0x3000,  # IDEOGRAPHIC SPACE
        0xFEFF,  # ZERO WIDTH NO-BREAK SPACE (BOM)
    )
}


def normalize_variable_spaces(value: Any) -> Any:
    """Replace exotic Unicode spaces with a plain space, recursively.

    Deliberately does NOT collapse whitespace runs or strip: variable values
    also hold captions, passwords, and multi-line text where that would be
    corruption. Only the invisible lookalikes are touched.
    """
    if isinstance(value, str):
        return value.translate(_SPACE_TRANSLATION)
    if isinstance(value, dict):
        return {k: normalize_variable_spaces(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_variable_spaces(v) for v in value]
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


def _api_key() -> str:
    return secrets.token_urlsafe(32)
