"""Shared defaults for execution step capture."""
from __future__ import annotations

from typing import Any


EXTRA_CAPTURE_STEP_TYPES = frozenset(
    {
        "extract",
        "extract_text_hierarchy",
        "extract_text_ocr",
        "extract_text_ai",
        "extract_screen_data",
        "llm_extract",
        "extraction_content.extract",
        "extraction_content.extract_text_hierarchy",
        "extraction_content.extract_text_ocr",
    }
)


def default_capture_enabled_for_step(step_or_type: dict[str, Any] | str | None) -> bool:
    if isinstance(step_or_type, dict):
        step_type = str(step_or_type.get("type") or "")
    else:
        step_type = str(step_or_type or "")
    return step_type in EXTRA_CAPTURE_STEP_TYPES
