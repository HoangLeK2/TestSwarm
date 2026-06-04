"""Secret scrub for content persistence (DF-T-06-015)."""
from __future__ import annotations

import re
from typing import Any

_OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")
_GEMINI_KEY = re.compile(r"AIzaSy[A-Za-z0-9_-]{20,}")


def scrub_secrets(value: Any) -> Any:
    """Recursively redact provider API key patterns from JSON-like structures."""
    if isinstance(value, str):
        redacted = _OPENAI_KEY.sub("[REDACTED_OPENAI_KEY]", value)
        return _GEMINI_KEY.sub("[REDACTED_GEMINI_KEY]", redacted)
    if isinstance(value, dict):
        return {k: scrub_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_secrets(v) for v in value]
    return value
