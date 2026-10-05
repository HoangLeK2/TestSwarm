"""UIAutomator hierarchy tree parser (DF-T-06-006)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from runtime.xml_utils import parse_xml


@dataclass
class HierarchyNode:
    tag: str
    attrs: dict[str, str]
    children: list["HierarchyNode"] = field(default_factory=list)
    parent: "HierarchyNode | None" = None

    @property
    def text(self) -> str:
        return (self.attrs.get("text") or "").strip()

    @property
    def resource_id(self) -> str:
        return (self.attrs.get("resource-id") or "").strip()

    @property
    def node_class(self) -> str:
        return (self.attrs.get("class") or "").strip()

    @property
    def content_desc(self) -> str:
        return (self.attrs.get("content-desc") or "").strip()

    @property
    def bounds(self) -> dict[str, int] | None:
        raw = self.attrs.get("bounds") or ""
        if len(raw) < 10 or not raw.startswith("["):
            return None
        try:
            left, right = raw[1:-1].split("][", 1)
            x1, y1 = left.split(",", 1)
            x2, y2 = right.split(",", 1)
            return {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
        except (ValueError, TypeError):
            return None

    def iter_descendants(self) -> Iterator["HierarchyNode"]:
        stack = list(self.children)
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)


def _build_node(element: Any, parent: HierarchyNode | None) -> HierarchyNode:
    attrs = {k: str(v) for k, v in (element.attrib or {}).items()}
    node = HierarchyNode(tag=element.tag, attrs=attrs, parent=parent)
    for child in element:
        if child.tag == "node":
            node.children.append(_build_node(child, node))
    return node


def parse_hierarchy_root(xml_str: str) -> HierarchyNode:
    root_el = parse_xml(xml_str)
    if root_el.tag == "hierarchy":
        children = [_build_node(c, None) for c in root_el if c.tag == "node"]
        wrapper = HierarchyNode(tag="hierarchy", attrs={}, children=children)
        for ch in children:
            ch.parent = wrapper
        return wrapper
    return _build_node(root_el, None)


def count_nodes(root: HierarchyNode) -> int:
    return 1 + sum(count_nodes(c) for c in root.children)
