"""Built-in screen_data hierarchy strategy (DF-T-06-006)."""
from __future__ import annotations

from typing import Any

from services.content.extraction.hierarchy.parser import HierarchyNode

_TEXT_CLASSES = {
    "android.widget.TextView",
    "android.widget.EditText",
    "android.widget.Button",
    "android.widget.CheckedTextView",
    "android.widget.AutoCompleteTextView",
}


def screen_data_strategy(root: HierarchyNode, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    filter_class = config.get("filter_class")
    allowed = set(filter_class) if filter_class else None
    exclude_empty = bool(config.get("exclude_empty", True))
    items: list[dict[str, Any]] = []
    for node in root.iter_descendants():
        if allowed is not None and node.node_class not in allowed:
            continue
        if not allowed and node.node_class not in _TEXT_CLASSES:
            continue
        text = (node.text or node.content_desc or "").strip()
        if exclude_empty and not text:
            continue
        entry: dict[str, Any] = {
            "text": text,
            "class": node.node_class,
            "resource_id": node.resource_id,
        }
        if node.content_desc and node.content_desc != text:
            entry["content_desc"] = node.content_desc
        bounds = node.bounds
        if bounds:
            entry["bbox"] = {
                "x": bounds["x1"],
                "y": bounds["y1"],
                "w": bounds["x2"] - bounds["x1"],
                "h": bounds["y2"] - bounds["y1"],
            }
            entry["bounds"] = f"[{bounds['x1']},{bounds['y1']}][{bounds['x2']},{bounds['y2']}]"
        items.append(entry)
    raw = {"strategy": "screen_data", "node_count": len(list(root.iter_descendants()))}
    return items, raw
