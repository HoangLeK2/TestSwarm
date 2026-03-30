"""
Hierarchy Extractor — Extract text from Android UI Hierarchy XML.

Fastest and free strategy. Works for native views (TextView, EditText, etc.)
but NOT for WebView content, Canvas-rendered text, or images.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

log = logging.getLogger(__name__)

# Bounds pattern: [x1,y1][x2,y2]
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# Default classes to extract text from
DEFAULT_TEXT_CLASSES = {
    "android.widget.TextView",
    "android.widget.EditText",
    "android.widget.Button",
    "android.widget.CheckedTextView",
    "android.widget.AutoCompleteTextView",
}


class HierarchyExtractor:
    """Extract structured text data from UI Hierarchy XML."""

    @staticmethod
    def extract_texts(
        xml_str: str,
        filter_class: list[str] | None = None,
        exclude_empty: bool = True,
        include_content_desc: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Extract text elements from UI hierarchy XML.

        Args:
            xml_str:              Raw XML from device.hierarchy_xml()
            filter_class:         Only include these widget classes (None = all)
            exclude_empty:        Skip nodes with empty text
            include_content_desc: Also extract content-desc as text

        Returns:
            List of dicts: {text, class, resource_id, content_desc, bounds, bounds_rect}
        """
        if not xml_str or not xml_str.strip():
            return []

        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as exc:
            log.warning(f"Failed to parse hierarchy XML: {exc}")
            return []

        allowed_classes = set(filter_class) if filter_class else None
        results: list[dict[str, Any]] = []

        for node in root.iter("node"):
            cls = node.get("class", "")
            if allowed_classes and cls not in allowed_classes:
                continue

            text = (node.get("text") or "").strip()
            desc = (node.get("content-desc") or "").strip()
            rid = (node.get("resource-id") or "").strip()

            if exclude_empty and not text and (not include_content_desc or not desc):
                continue

            # Parse bounds
            bounds_str = node.get("bounds", "")
            bounds_rect = _parse_bounds(bounds_str)

            entry: dict[str, Any] = {
                "text": text,
                "class": cls,
                "resource_id": rid,
            }
            if include_content_desc and desc:
                entry["content_desc"] = desc
            if bounds_rect:
                entry["bounds"] = [bounds_rect["x1"], bounds_rect["y1"],
                                   bounds_rect["x2"], bounds_rect["y2"]]
                entry["bounds_rect"] = bounds_rect

            # Use content_desc as text fallback
            if not text and desc and include_content_desc:
                entry["text"] = desc

            if exclude_empty and not entry["text"]:
                continue

            results.append(entry)

        return results

    @staticmethod
    def extract_plain_text(
        xml_str: str,
        filter_class: list[str] | None = None,
        separator: str = "\n",
    ) -> str:
        """Extract all text as a single joined string."""
        items = HierarchyExtractor.extract_texts(
            xml_str, filter_class=filter_class, exclude_empty=True
        )
        return separator.join(item["text"] for item in items if item["text"])


def _parse_bounds(bounds_str: str) -> dict[str, int] | None:
    m = _BOUNDS_RE.search(bounds_str)
    if not m:
        return None
    return {
        "x1": int(m.group(1)),
        "y1": int(m.group(2)),
        "x2": int(m.group(3)),
        "y2": int(m.group(4)),
    }
