"""Hierarchy tree traversal utilities (DF-T-06-006)."""
from __future__ import annotations

from typing import Callable, Iterator

from services.content.extraction.hierarchy.parser import HierarchyNode


def find_by_resource_id(root: HierarchyNode, resource_id: str) -> list[HierarchyNode]:
    rid = resource_id.strip()
    return [n for n in root.iter_descendants() if n.resource_id == rid]


def find_by_class(root: HierarchyNode, class_name: str) -> list[HierarchyNode]:
    cls = class_name.strip()
    return [n for n in root.iter_descendants() if n.node_class == cls]


def find_by_text(root: HierarchyNode, text: str, *, exact: bool = False) -> list[HierarchyNode]:
    needle = text.strip()
    if exact:
        return [n for n in root.iter_descendants() if n.text == needle]
    return [n for n in root.iter_descendants() if needle and needle in n.text]


def xpath(root: HierarchyNode, expr: str) -> list[HierarchyNode]:
    """Minimal xpath: //node[@resource-id='...'] or //node[@class='...']."""
    expr = expr.strip()
    if expr.startswith("//node[@resource-id="):
        value = expr.split("=", 1)[1].strip().strip("'\"")
        return find_by_resource_id(root, value)
    if expr.startswith("//node[@class="):
        value = expr.split("=", 1)[1].strip().strip("'\"")
        return find_by_class(root, value)
    return []


def iter_children(node: HierarchyNode) -> Iterator[HierarchyNode]:
    yield from node.children
