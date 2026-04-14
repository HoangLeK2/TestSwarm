# Phase 2: Graph Compiler

## Files to create

| File | Action |
|------|--------|
| `device_farm/common/graph_compiler.py` | NEW: bidirectional conversion |
| `device_farm/tests/test_graph_compiler.py` | NEW: unit tests |

## Two functions needed

### 1. `steps_to_graph(steps) -> (nodes, edges)`

Converts flat steps[] → nodes[] + edges[]. Used by:
- Data migration (Phase 1)
- Template seeding (Phase 6)
- Legacy API fallback

### 2. `compile_graph_to_steps(nodes, edges) -> steps`

Converts nodes[] + edges[] → flat steps[]. Used by:
- API save (Phase 3) — keeps `steps[]` in sync for executor
- Must produce IDENTICAL output to original steps (round-trip fidelity)

## Container Type Mapping

| Step Type | Branches |
|-----------|----------|
| `loop` | `"steps"` |
| `repeat` | `"steps"` |
| `repeat_until` | `"steps"` |
| `if_element` | `"then"`, `"else"` |
| `if_variable` | `"then"`, `"else"` |
| `random_pick` | `"branch_0"`, `"branch_1"`, ... |

## Config Extraction

When converting step → node, separate structural fields from config:

```python
STRUCTURAL_FIELDS = {"type", "steps", "then", "else", "branches", "title", "description"}

def step_to_node_config(step: dict) -> dict:
    return {k: v for k, v in step.items() if k not in STRUCTURAL_FIELDS}
```

## Test Cases

1. Empty steps → empty nodes/edges
2. Linear 3-step flow → 3 nodes, 2 edges
3. Loop with 2 inner steps → 1 loop node + 2 child nodes (scope.branch="steps")
4. if_element with then/else → 1 if node + children in "then"/"else" branches
5. random_pick with 3 branches → 1 pick node + children in "branch_0"/"branch_1"/"branch_2"
6. Deeply nested (loop > if > repeat) → correct scope chains
7. Round-trip: steps → graph → steps === original (minus field ordering)
8. Real template round-trip: fb_group_1h steps → graph → steps → validate identical execution
