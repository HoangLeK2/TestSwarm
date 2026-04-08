"""
Hierarchy Extractor — Extract text from Android UI Hierarchy XML.

Fastest and free strategy. Works for native views (TextView, EditText, etc.)
but NOT for WebView content, Canvas-rendered text, or images.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

from runtime.xml_utils import parse_xml as _parse_xml, XML_PARSE_ERRORS as _XML_PARSE_EXCEPTIONS

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
            root = _parse_xml(xml_str)
        except _XML_PARSE_EXCEPTIONS as exc:
            log.warning(f"Failed to parse hierarchy XML: {exc}")
            return []

        allowed_classes = set(filter_class) if filter_class else None
        results: list[dict[str, Any]] = []
        append_result = results.append
        include_desc = include_content_desc
        should_exclude_empty = exclude_empty

        for node in root.iter("node"):
            node_get = node.get
            cls = node_get("class", "")
            if allowed_classes and cls not in allowed_classes:
                continue

            text = (node_get("text") or "").strip()
            desc = ""
            if include_desc:
                desc = (node_get("content-desc") or "").strip()
            rid = (node_get("resource-id") or "").strip()

            if not text and desc and include_desc:
                text = desc

            if should_exclude_empty and not text:
                continue

            # Parse bounds
            bounds_str = node_get("bounds", "")
            bounds_rect = _parse_bounds(bounds_str)

            entry: dict[str, Any] = {
                "text": text,
                "class": cls,
                "resource_id": rid,
            }
            if include_desc and desc:
                entry["content_desc"] = desc
            if bounds_rect:
                entry["bounds"] = [bounds_rect["x1"], bounds_rect["y1"],
                                   bounds_rect["x2"], bounds_rect["y2"]]
                entry["bounds_rect"] = bounds_rect

            append_result(entry)

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
    # Expected format: [x1,y1][x2,y2]
    if len(bounds_str) < 10 or not bounds_str.startswith("[") or not bounds_str.endswith("]"):
        return None
    try:
        left, right = bounds_str[1:-1].split("][", 1)
        x1_str, y1_str = left.split(",", 1)
        x2_str, y2_str = right.split(",", 1)
        return {
            "x1": int(x1_str),
            "y1": int(y1_str),
            "x2": int(x2_str),
            "y2": int(y2_str),
        }
    except (ValueError, TypeError):
        return None


