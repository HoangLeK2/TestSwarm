"""Graph reachability helpers aligned with graph_compiler execution model."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

_TERMINAL_NODE_TYPES = frozenset({"success", "fail", "end", "terminal"})
_CONTAINER_TYPES = frozenset({
    "loop",
    "repeat",
    "repeat_until",
    "if_element",
    "if_variable",
    "social_open_comments",
    "social_open_comments",
    "random_pick",
})
_NATURAL_LEAF_TYPE_PREFIXES = (
    "verification.",
    "interaction.",
    "navigation.",
    "input_wait.",
    "extraction_content.",
    "platform_specific.",
    "composition.run_scenario",
    "extract",
    "tap",
    "wait",
    "scroll",
    "swipe",
    "open_app",
    "stop_app",
    "save_extraction",
    "verify_screen",
    "set_variable",
    "run_scenario",
)


def _node_scope(node: dict[str, Any]) -> dict[str, Any]:
    scope = node.get("scope")
    return scope if isinstance(scope, dict) else {}


def build_graph_indexes(
    nodes: list[dict],
    edges: list[dict],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]]:
    """Return node map, reachability adjacency, explicit edge adjacency, scoped children."""
    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        if not nid:
            continue
        node_by_id[str(nid)] = node

    reach_adj: dict[str, list[str]] = defaultdict(list)
    explicit_adj: dict[str, list[str]] = defaultdict(list)
    scoped_children: dict[str, list[str]] = defaultdict(list)

    for edge in edges or []:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        if src in node_by_id and tgt in node_by_id:
            reach_adj[src].append(tgt)
            explicit_adj[src].append(tgt)

    for nid, node in node_by_id.items():
        parent = _node_scope(node).get("parentId")
        if parent is None:
            continue
        pid = str(parent)
        if pid not in node_by_id:
            continue
        scoped_children[pid].append(nid)
        reach_adj[pid].append(nid)

    return node_by_id, reach_adj, explicit_adj, scoped_children


def reachable_from(start_id: str, reach_adj: dict[str, list[str]]) -> set[str]:
    visited: set[str] = set()
    queue: deque[str] = deque([start_id])
    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        for tgt in reach_adj.get(nid, []):
            if tgt not in visited:
                queue.append(tgt)
    return visited


def _sorted_root_nodes(nodes: list[dict]) -> list[dict[str, Any]]:
    roots = [
        n for n in nodes
        if isinstance(n, dict) and n.get("id") and not _node_scope(n).get("parentId")
    ]
    roots.sort(key=lambda n: n.get("order", ""))
    return roots


def campaign_start_node_id(nodes: list[dict], node_by_id: dict[str, dict[str, Any]]) -> str | None:
    root_nodes = _sorted_root_nodes(nodes)
    if not root_nodes:
        return None
    return str(root_nodes[0]["id"])


def last_root_node_id(nodes: list[dict]) -> str | None:
    """Last root-scope node by fractional order — valid scenario terminator without an outgoing edge."""
    root_nodes = _sorted_root_nodes(nodes)
    if not root_nodes:
        return None
    return str(root_nodes[-1]["id"])


def org_start_node_id(
    node_by_id: dict[str, dict[str, Any]],
    explicit_adj: dict[str, list[str]],
) -> str | None:
    incoming: dict[str, int] = {nid: 0 for nid in node_by_id}
    for src, targets in explicit_adj.items():
        for tgt in targets:
            if tgt in incoming:
                incoming[tgt] += 1
    start_ids = [nid for nid, count in incoming.items() if count == 0]
    if not start_ids:
        return next(iter(node_by_id), None)
    return start_ids[0]


def is_terminal_node_type(stype: str) -> bool:
    return stype in _TERMINAL_NODE_TYPES or stype.split(".")[-1] in _TERMINAL_NODE_TYPES


def is_natural_leaf_node_type(stype: str) -> bool:
    if stype in _NATURAL_LEAF_TYPE_PREFIXES:
        return True
    return any(stype.startswith(prefix) for prefix in _NATURAL_LEAF_TYPE_PREFIXES)


def is_container_node_type(stype: str) -> bool:
    if stype in _CONTAINER_TYPES:
        return True
    return stype.split(".")[-1] in _CONTAINER_TYPES


def is_graph_dead_end(
    node: dict[str, Any],
    *,
    explicit_adj: dict[str, list[str]],
    scoped_children: dict[str, list[str]],
    last_root_id: str | None = None,
) -> bool:
    nid = str(node.get("id"))
    stype = str(node.get("type") or "")
    if explicit_adj.get(nid):
        return False
    if scoped_children.get(nid):
        return False
    if _node_scope(node).get("parentId"):
        return False
    if last_root_id and nid == last_root_id:
        return False
    if is_terminal_node_type(stype):
        return False
    if is_natural_leaf_node_type(stype):
        return False
    if is_container_node_type(stype):
        return False
    return True
