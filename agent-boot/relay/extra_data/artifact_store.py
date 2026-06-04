"""Attach capture evidence (hierarchy XML, screenshot refs) to parsed content rows."""
from __future__ import annotations

import os
from typing import Any

# Keep inline hierarchy under raw_data budget (1 MB total per item on farm normalizer).
_DEFAULT_MAX_HIERARCHY_BYTES = 400_000


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _inline_hierarchy_enabled() -> bool:
    return _env_bool("AGENT_BOOT_INLINE_HIERARCHY_ENABLED", False)


def _max_hierarchy_bytes() -> int:
    try:
        return max(32_768, int(os.getenv("AGENT_BOOT_INLINE_HIERARCHY_MAX_BYTES", str(_DEFAULT_MAX_HIERARCHY_BYTES))))
    except ValueError:
        return _DEFAULT_MAX_HIERARCHY_BYTES


def _truncate_hierarchy(xml: str) -> tuple[str, bool]:
    limit = _max_hierarchy_bytes()
    encoded = xml.encode("utf-8")
    if len(encoded) <= limit:
        return xml, False
    truncated = encoded[:limit].decode("utf-8", errors="ignore")
    return truncated, True


def merge_evidence_into_item(item: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """Merge capture evidence into a parsed item dict before DB insert."""
    if not evidence:
        return item
    out = dict(item)
    xml = evidence.get("hierarchy_xml")
    if _inline_hierarchy_enabled() and isinstance(xml, str) and "<hierarchy" in xml:
        trimmed, was_truncated = _truncate_hierarchy(xml)
        out["hierarchy_xml"] = trimmed
        if was_truncated:
            out["hierarchy_xml_truncated"] = True
    screenshot_path = evidence.get("screenshot_path")
    if isinstance(screenshot_path, str) and screenshot_path.strip():
        out["_screenshot_path"] = screenshot_path.strip()[:1000]
    return out
