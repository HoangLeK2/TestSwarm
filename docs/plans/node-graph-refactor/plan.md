# Plan: Node/Graph Refactor — Step Management

**Date:** 2026-04-12
**Status:** Draft
**Complexity:** High — touches DB, API, executor, frontend

---

## Problem

Steps hiện tại lưu dưới dạng **flat JSON array** với nested arrays cho control flow. Issues:

- Không có node ID → identify bằng array index → reorder/insert = rebuild array
- CRUD = gửi toàn bộ array mỗi lần save
- Concurrent edit sẽ conflict
- Nested phức tạp (if/else, multi-branch) khó quản lý khi scale

## Target Data Model

### Node

```typescript
interface FlowNode {
  id: string;                    // nanoid(10)
  type: string;                  // "tap_selector", "extract", "loop", ...
  config: Record<string, any>;   // step-specific params (by, value, strategy, ...)
  
  // ── Positioning ──
  position?: { x: number; y: number };  // cho visual editor (tương lai)
  
  // ── Ordering (fractional indexing) ──
  order: string;                 // lexicographic: "a0", "a0V", "a1" — fractional-indexing lib
  
  // ── Scoping / Nesting ──
  scope?: {
    parentId: string;            // ID của container node (loop, if, repeat, random_pick)
    branch?: string;             // "then" | "else" | "branch_0" | "branch_1" | "steps"
  } | null;                      // null = root level
  
  // ── Metadata ──
  title?: string;
  description?: string;
}
```

### Edge

```typescript
interface FlowEdge {
  id: string;                    // nanoid(10)
  source: string;                // node.id
  target: string;                // node.id
  sourceHandle?: string;         // "success" | "error" | "true" | "false" | "default"
  targetHandle?: string;         // "input" | custom
  type: "default" | "conditional" | "error" | "fallback";
  condition?: string;            // expression cho conditional edges
}
```

### Scenario (DB)

```python
class Scenario(Base):
    # ... existing fields ...
    
    # NEW: Graph model
    nodes: list = mapped_column(JSON, default=list)    # FlowNode[]
    edges: list = mapped_column(JSON, default=list)    # FlowEdge[]
    
    # KEEP: Legacy flat array (backward compat, executor input)
    steps: list = mapped_column(JSON, default=list)    # auto-compiled from nodes+edges
```

---

## Key Design Decisions

### 1. Fractional Indexing for Order

**Lib:** `fractional-indexing` (npm + PyPI — same algorithm, interoperable)

```python
# Python
from fractional_indexing import generate_key_between
generate_key_between(None, None)   # "a0" (first)
generate_key_between("a0", "a1")   # "a0V" (between)
```

```typescript
// TypeScript
import { generateKeyBetween } from 'fractional-indexing';
generateKeyBetween(null, null);    // "a0"
generateKeyBetween("a0", "a1");    // "a0V"
```

**Why:** Insert between = 0 rows updated. Reorder = update 1 row. No shift needed.

### 2. Scope Model for Nesting (not just parentId)

```
scope: { parentId: "node_loop_1", branch: "steps" }       // inside loop body
scope: { parentId: "node_if_1", branch: "then" }          // inside if-then
scope: { parentId: "node_if_1", branch: "else" }          // inside if-else
scope: { parentId: "node_pick_1", branch: "branch_0" }    // random_pick branch 0
scope: null                                                 // root level
```

**Container nodes** (loop, repeat, if_element, if_variable, random_pick) define branches:
- `loop` / `repeat` / `repeat_until`: branch = `"steps"`
- `if_element` / `if_variable`: branch = `"then"` | `"else"`
- `random_pick`: branch = `"branch_0"` | `"branch_1"` | ...

**Query children:** `nodes.filter(n => n.scope?.parentId === id && n.scope?.branch === branch)`

### 3. Edges with Full Metadata

```typescript
// Sequential flow
{ source: "A", target: "B", type: "default" }

// Conditional branching
{ source: "if_1", target: "C", type: "conditional", sourceHandle: "then" }
{ source: "if_1", target: "D", type: "conditional", sourceHandle: "else" }

// Error handling (future)
{ source: "E", target: "F", type: "error", sourceHandle: "error" }
```

### 4. Compilation: nodes+edges → flat steps array

Executor continues to consume flat `steps[]` array. A **compiler** function converts graph → array:

```python
def compile_graph_to_steps(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """
    1. Topological sort nodes by edges (within each scope/branch)
    2. For container nodes, recursively compile children into nested steps[]
    3. Return flat steps array compatible with existing executor
    """
```

This means **executor changes = 0**. All existing step execution logic stays.

---

## Phases

### Phase 1: Data Model + Migration (Backend)

**Files:**
- `device_farm/db/models/campaign.py` — Add `nodes`, `edges` columns
- `device_farm/db/migrations/` — New migration: add columns, populate from existing steps
- `device_farm/pyproject.toml` — Add `fractional-indexing` dependency

**Migration strategy:**
```python
async def migrate_steps_to_graph(scenario):
    """Convert existing steps[] to nodes[] + edges[]"""
    nodes, edges = [], []
    
    def walk(steps, parent_scope=None):
        prev_id = None
        for i, step in enumerate(steps):
            node_id = nanoid(10)
            node = {
                "id": node_id,
                "type": step["type"],
                "config": {k: v for k, v in step.items() if k not in ("type", "steps", "then", "else", "branches")},
                "order": generate_n_keys_between(None, None, len(steps))[i],
                "scope": parent_scope,
            }
            nodes.append(node)
            
            if prev_id:
                edges.append({"id": nanoid(10), "source": prev_id, "target": node_id, "type": "default"})
            prev_id = node_id
            
            # Recurse into nested steps
            if "steps" in step:
                walk(step["steps"], {"parentId": node_id, "branch": "steps"})
            if "then" in step:
                walk(step["then"], {"parentId": node_id, "branch": "then"})
            if "else" in step:
                walk(step["else"], {"parentId": node_id, "branch": "else"})
            if "branches" in step:
                for bi, branch in enumerate(step["branches"]):
                    walk(branch.get("steps", []), {"parentId": node_id, "branch": f"branch_{bi}"})
    
    walk(scenario.steps)
    return nodes, edges
```

### Phase 2: Compiler (graph → steps)

**Files:**
- `device_farm/common/graph_compiler.py` — NEW file

```python
def compile_graph_to_steps(nodes: list, edges: list) -> list:
    """Compile nodes+edges back to flat steps[] for executor."""
    
    # Build adjacency + scope index
    children_by_scope = defaultdict(list)  # (parentId, branch) → [nodes sorted by order]
    root_nodes = []
    
    for node in nodes:
        scope = node.get("scope")
        if scope:
            key = (scope["parentId"], scope.get("branch", "steps"))
            children_by_scope[key].append(node)
        else:
            root_nodes.append(node)
    
    # Sort each group by fractional order
    for key in children_by_scope:
        children_by_scope[key].sort(key=lambda n: n["order"])
    root_nodes.sort(key=lambda n: n["order"])
    
    def compile_node(node):
        step = {"type": node["type"], **node.get("config", {})}
        nid = node["id"]
        
        # Attach title/description if present
        if node.get("title"): step["title"] = node["title"]
        if node.get("description"): step["description"] = node["description"]
        
        # Compile children based on container type
        t = node["type"]
        if t in ("loop", "repeat", "repeat_until"):
            step["steps"] = [compile_node(c) for c in children_by_scope.get((nid, "steps"), [])]
        elif t in ("if_element", "if_variable"):
            step["then"] = [compile_node(c) for c in children_by_scope.get((nid, "then"), [])]
            else_nodes = children_by_scope.get((nid, "else"), [])
            if else_nodes:
                step["else"] = [compile_node(c) for c in else_nodes]
        elif t == "random_pick":
            # Reconstruct branches
            branch_keys = sorted([k for k in children_by_scope if k[0] == nid], key=lambda k: k[1])
            branches = []
            for _, branch_key in branch_keys:
                branch_nodes = children_by_scope.get((nid, branch_key), [])
                # Weight is stored in container config
                weight = node.get("config", {}).get(f"weight_{branch_key}", 1)
                branches.append({"weight": weight, "steps": [compile_node(c) for c in branch_nodes]})
            if branches:
                step["branches"] = branches
        
        return step
    
    return [compile_node(n) for n in root_nodes]
```

### Phase 3: API + Validation (Backend)

**Files:**
- `device_farm/api/schemas/scenario.py` — Add `FlowNodeModel`, `FlowEdgeModel`
- `device_farm/api/routes/campaigns.py` — Accept nodes+edges, compile to steps on save
- `device_farm/common/scenario_schema.py` — Add graph validation

**API contract:**

```python
class ScenarioUpdate(BaseModel):
    # Existing (backward compat)
    steps: Optional[list] = None
    
    # NEW: Graph model (preferred)
    nodes: Optional[list[FlowNodeModel]] = None
    edges: Optional[list[FlowEdgeModel]] = None

# On PATCH:
if updates.nodes is not None:
    compiled_steps = compile_graph_to_steps(updates.nodes, updates.edges or [])
    scenario.nodes = updates.nodes
    scenario.edges = updates.edges or []
    scenario.steps = compiled_steps  # keep steps in sync for executor
elif updates.steps is not None:
    # Legacy: flat array update
    scenario.steps = updates.steps
```

### Phase 4: Frontend — Core Data Layer

**Files:**
- `front-end/src/features/campaigns/components/scenario-steps/types.ts` — New types
- `front-end/src/features/campaigns/hooks/use-scenario-graph.ts` — NEW hook
- `front-end/package.json` — Add `fractional-indexing`, `nanoid`

```typescript
// use-scenario-graph.ts
export function useScenarioGraph(initialNodes: FlowNode[], initialEdges: FlowEdge[]) {
  const [nodes, setNodes] = useState(initialNodes);
  const [edges, setEdges] = useState(initialEdges);
  
  const addNode = (type: string, afterNodeId?: string, scope?: Scope) => {
    const id = nanoid(10);
    // Calculate order using fractional indexing
    const siblings = getNodesByScope(nodes, scope);
    const afterIdx = afterNodeId ? siblings.findIndex(n => n.id === afterNodeId) : siblings.length - 1;
    const prevOrder = siblings[afterIdx]?.order ?? null;
    const nextOrder = siblings[afterIdx + 1]?.order ?? null;
    const order = generateKeyBetween(prevOrder, nextOrder);
    
    const node: FlowNode = { id, type, config: getDefaultConfig(type), order, scope };
    setNodes(prev => [...prev, node]);
    
    // Auto-create edges
    if (afterNodeId) {
      // Insert edge: afterNode → newNode, reconnect afterNode's outgoing
      ...
    }
    return id;
  };
  
  const updateNode = (id: string, patch: Partial<FlowNode>) => {
    setNodes(prev => prev.map(n => n.id === id ? { ...n, ...patch } : n));
  };
  
  const removeNode = (id: string) => {
    // Remove node + reconnect edges (prev → next)
    // Remove children if container node
    ...
  };
  
  const moveNode = (id: string, afterNodeId: string | null, newScope?: Scope) => {
    // Update order using fractional indexing
    // Update scope if moving between containers
    ...
  };
  
  return { nodes, edges, addNode, updateNode, removeNode, moveNode, setNodes, setEdges };
}
```

### Phase 5: Frontend — Flow Editor UI Migration

**Files:**
- `front-end/src/features/campaigns/components/flow-editor/flow-editor.tsx`
- `front-end/src/features/campaigns/components/flow-editor/step-card.tsx`
- `front-end/src/features/campaigns/components/flow-editor/bracket-block.tsx`
- `front-end/src/features/campaigns/components/flow-editor/flow-dnd-ids.ts`
- `front-end/src/features/campaigns/components/scenario-dialog.tsx`

**Strategy:** Keep the current **list-based UI** (not visual canvas). The graph model runs underneath but renders as the same sortable list. Visual canvas editor is a future phase.

Changes:
- `FlowEditor` receives `nodes + edges` instead of `steps[]`
- Rendering: group nodes by scope, sort by `order`, render recursively
- DnD: reorder = update `order` field (fractional), move between scopes = update `scope`
- Step cards: pass `node.config` instead of raw step object
- Save: send `nodes + edges` to API (not flat steps)

### Phase 6: Template Migration

**Files:**
- `device_farm/db/seeds/scenario_templates.py`

Templates continue to define steps as flat arrays (easier to read/write). The seeding function converts to nodes+edges on insert:

```python
async def seed_builtin_templates(db):
    for spec in BUILTIN_TEMPLATES:
        nodes, edges = steps_to_graph(spec["steps"])
        compiled_steps = spec["steps"]  # keep original as steps
        # Save both nodes/edges AND steps
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Executor breaks | Executor reads `steps[]` only — compiled from graph. Zero executor changes |
| Data loss during migration | Migration is additive (new columns). `steps[]` stays populated |
| Frontend regression | Graph model renders in same list UI. Visual diff = 0 |
| Template compat | Templates keep flat format, auto-convert on seed |
| Concurrent edit conflict | Fractional indexing = no index shifting. Scope-based = isolated edits |

## Dependencies

- `fractional-indexing` (npm + PyPI)
- `nanoid` (npm, Python: `nanoid` or inline)

## Estimated Effort

| Phase | Effort | Risk |
|-------|--------|------|
| 1. Data Model + Migration | Medium | Low (additive) |
| 2. Compiler | Medium | Medium (correctness) |
| 3. API + Validation | Low | Low |
| 4. Frontend Data Layer | High | Medium |
| 5. Frontend UI Migration | High | High (DnD refactor) |
| 6. Template Migration | Low | Low |

**Recommended order:** Phase 1 → 2 → 3 → 6 → 4 → 5

Phase 1-3 + 6 can deploy without frontend changes (steps[] stays populated). Frontend migration (4-5) can follow independently.
