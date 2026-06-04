"""
graph_compiler.py — Bidirectional conversion between graph (nodes+edges) and flat steps[].

compile_graph_to_steps(nodes, edges) -> list[dict]
    Graph → flat steps[] for the executor (executor is unchanged).

    NOTE: The `edges` parameter is accepted for API symmetry and future use
    (conditional routing, error edges). Currently ordering within each scope
    is determined entirely by the fractional `order` field on each node.
    Edges are stored for visual rendering and future topological use but are
    NOT used to derive execution order in this version.

steps_to_graph(steps) -> tuple[list[dict], list[dict]]
    Flat steps[] → (nodes[], edges[]) for migration and seeding.

ensure_step_ids(steps) -> list[dict]
    Walk steps tree, stamp id + order on any step missing them. Idempotent.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

# ── Container node types ──────────────────────────────────────────────────────

_CONTAINER_STEP_TYPES = {"loop", "repeat", "repeat_until"}
_CONTAINER_IF_TYPES = {
    "if_element",
    "if_variable",
    "tap_fb_comment_button",
    "fb_tap_comment_button",
}
_CONTAINER_PICK_TYPES = {"random_pick"}
_CONTAINER_TYPES = _CONTAINER_STEP_TYPES | _CONTAINER_IF_TYPES | _CONTAINER_PICK_TYPES

# Keys removed from config when converting to nodes (handled as child scopes or top-level fields)
_NESTED_KEYS = ("steps", "then", "else", "branches", "else_steps")


# ── Fractional-indexing helpers ───────────────────────────────────────────────

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _generate_key_between(a: str | None, b: str | None) -> str:
    """Wrapper around fractional-indexing lib with pure-Python fallback."""
    try:
        from fractional_indexing import generate_key_between as _lib_gen
        return _lib_gen(a, b)
    except ImportError:
        pass

    # Fallback for seeding when lib not installed.
    # Uses a two-char "aX" scheme where X cycles through BASE62.
    if a is None and b is None:
        return "a0"
    if a is None:
        # Insert before b: use prefix one char lower
        return chr(ord(b[0]) - 1) + "z" if len(b) >= 2 else "a0"
    if b is None:
        # Append after a: increment the last BASE62 digit, or add a digit
        for pos in range(len(a) - 1, -1, -1):
            idx = _BASE62.find(a[pos])
            if idx < 0:
                break
            if idx < len(_BASE62) - 1:
                return a[:pos] + _BASE62[idx + 1]
        # Overflow: extend with next prefix letter
        return chr(ord(a[0]) + 1) + "0" if a[0] < "z" else a + "0"
    # Between: append midpoint suffix
    return a + "V"


def _generate_n_keys(n: int) -> list[str]:
    """Generate n distinct sequential fractional keys."""
    if n == 0:
        return []
    try:
        from fractional_indexing import generate_n_keys_between as _lib_n
        return _lib_n(None, None, n)
    except ImportError:
        pass

    keys: list[str] = []
    prev: str | None = None
    for _ in range(n):
        k = _generate_key_between(prev, None)
        keys.append(k)
        prev = k
    return keys


def _nanoid(size: int = 10) -> str:
    """Generate a URL-safe random ID (60-bit entropy, sufficient for internal IDs)."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_-"
    return "".join(alphabet[b & 63] for b in uuid.uuid4().bytes[:size])


# ── ensure_step_ids ───────────────────────────────────────────────────────────

def ensure_step_ids(steps: list[dict]) -> list[dict]:
    """
    Walk steps tree and stamp `id` + `order` on any step that lacks them.
    Mutates in-place and returns the same list. Idempotent.
    """
    def walk(step_list: list[dict]) -> None:
        orders = _generate_n_keys(len(step_list))
        for i, step in enumerate(step_list):
            if not step.get("id"):
                step["id"] = _nanoid(10)
            # Use `is None` not `not` — "a0" is a valid falsy-ish key in some locales
            if step.get("order") is None:
                step["order"] = orders[i]

            if "steps" in step and isinstance(step["steps"], list):
                walk(step["steps"])
            if "then" in step and isinstance(step["then"], list):
                walk(step["then"])
            if "else" in step and isinstance(step["else"], list):
                walk(step["else"])
            if "branches" in step and isinstance(step["branches"], list):
                for branch in step["branches"]:
                    if isinstance(branch, dict) and "steps" in branch:
                        walk(branch["steps"])

    walk(steps)
    return steps


# ── compile_graph_to_steps ────────────────────────────────────────────────────

def compile_graph_to_steps(nodes: list[dict], edges: list[dict]) -> list[dict]:  # noqa: ARG001
    """
    Compile nodes+edges → flat steps[] compatible with the existing executor.

    Ordering is determined by the fractional `order` field on each node.
    The `edges` parameter is currently unused for ordering (reserved for future
    conditional/error routing). See module docstring for rationale.
    """
    if not nodes:
        return []

    children_by_scope: dict[tuple, list[dict]] = defaultdict(list)
    root_nodes: list[dict] = []

    for node in nodes:
        scope = node.get("scope")
        if scope and scope.get("parentId"):
            key = (scope["parentId"], scope.get("branch", "steps"))
            children_by_scope[key].append(node)
        else:
            root_nodes.append(node)

    for key in children_by_scope:
        children_by_scope[key].sort(key=lambda n: n.get("order", ""))
    root_nodes.sort(key=lambda n: n.get("order", ""))

    def compile_node(node: dict) -> dict:
        step: dict[str, Any] = {"type": node["type"], **node.get("config", {})}
        nid = node["id"]
        t = node["type"]

        if node.get("title"):
            step["title"] = node["title"]
        if node.get("description"):
            step["description"] = node["description"]

        if t in _CONTAINER_STEP_TYPES:
            step["steps"] = [compile_node(c) for c in children_by_scope.get((nid, "steps"), [])]

        elif t in _CONTAINER_IF_TYPES:
            step["then"] = [compile_node(c) for c in children_by_scope.get((nid, "then"), [])]
            else_nodes = children_by_scope.get((nid, "else"), [])
            if else_nodes:
                step["else"] = [compile_node(c) for c in else_nodes]

        elif t == "random_pick":
            cfg = node.get("config", {})
            # Branch weights are stored as a list in config["branch_weights"]
            # for stable ordering (not index-keyed). Fall back to per-index keys
            # for nodes migrated before this fix.
            branch_weights: list = cfg.get("branch_weights", [])
            branch_keys = sorted(
                {k[1] for k in children_by_scope if k[0] == nid},
                key=lambda b: int(b.split("_")[1]) if b.startswith("branch_") else 0,
            )
            branches = []
            for bi, branch_key in enumerate(branch_keys):
                branch_nodes = children_by_scope.get((nid, branch_key), [])
                # Prefer list-based weight (new), fall back to legacy per-key weight
                if bi < len(branch_weights):
                    weight = branch_weights[bi]
                else:
                    weight = cfg.get(f"weight_{branch_key}", 1)
                branches.append({
                    "weight": weight,
                    "steps": [compile_node(c) for c in branch_nodes],
                })
            # Always emit branches array (even empty branches are valid random_pick arms)
            step["branches"] = branches

        return step

    return [compile_node(n) for n in root_nodes]


# ── steps_to_graph ────────────────────────────────────────────────────────────

def steps_to_graph(steps: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Convert flat steps[] → (nodes[], edges[]).

    random_pick branch weights are stored as config["branch_weights"] (a list),
    preserving order and surviving branch reordering.
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    def walk(step_list: list[dict], parent_scope: dict | None = None) -> None:
        orders = _generate_n_keys(len(step_list))
        prev_id: str | None = None

        for i, step in enumerate(step_list):
            node_id = _nanoid(10)
            step_type = step.get("type", "unknown")

            config: dict[str, Any] = {
                k: v for k, v in step.items()
                if k not in ("type", "title", "description", *_NESTED_KEYS)
            }

            # Store branch weights as an ordered list for stability
            if step_type == "random_pick":
                config["branch_weights"] = [
                    b.get("weight", 1) for b in step.get("branches", [])
                ]

            node: dict[str, Any] = {
                "id": node_id,
                "type": step_type,
                "config": config,
                "order": orders[i],
                "scope": parent_scope,
            }
            if step.get("title"):
                node["title"] = step["title"]
            if step.get("description"):
                node["description"] = step["description"]

            nodes.append(node)

            if prev_id:
                edges.append({
                    "id": _nanoid(10),
                    "source": prev_id,
                    "target": node_id,
                    "type": "default",
                })
            prev_id = node_id

            if step_type in _CONTAINER_STEP_TYPES:
                walk(step.get("steps", []), {"parentId": node_id, "branch": "steps"})
            elif step_type in _CONTAINER_IF_TYPES:
                walk(step.get("then", []), {"parentId": node_id, "branch": "then"})
                else_steps = step.get("else") or step.get("else_steps") or []
                if else_steps:
                    walk(else_steps, {"parentId": node_id, "branch": "else"})
            elif step_type == "random_pick":
                for bi, branch in enumerate(step.get("branches", [])):
                    # Always create scope for every branch — even if steps is empty —
                    # so branch count is preserved across round-trips.
                    walk(branch.get("steps", []), {"parentId": node_id, "branch": f"branch_{bi}"})

    walk(steps)
    return nodes, edges
