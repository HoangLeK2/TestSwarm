# Phase 4: Frontend Data Layer

## Files to create/modify

| File | Action |
|------|--------|
| `front-end/src/features/campaigns/types/graph.ts` | NEW: FlowNode, FlowEdge types |
| `front-end/src/features/campaigns/hooks/use-scenario-graph.ts` | NEW: graph CRUD hook |
| `front-end/src/features/campaigns/utils/graph-helpers.ts` | NEW: utility functions |
| `front-end/package.json` | Add `fractional-indexing`, `nanoid` |

## Dependencies

```bash
cd front-end && npm install fractional-indexing nanoid
```

## TypeScript Types

```typescript
// types/graph.ts
export interface FlowNodeScope {
  parentId: string;
  branch: string;  // "steps" | "then" | "else" | "branch_0" | ...
}

export interface FlowNode {
  id: string;
  type: string;
  config: Record<string, any>;
  order: string;
  scope: FlowNodeScope | null;
  position?: { x: number; y: number };
  title?: string;
  description?: string;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  type: "default" | "conditional" | "error" | "fallback";
  condition?: string;
}
```

## Hook: useScenarioGraph

Core operations:
- `addNode(type, afterNodeId?, scope?)` — Create node with fractional order
- `updateNode(id, configPatch)` — Partial config update
- `removeNode(id)` — Remove + reconnect edges + remove children
- `moveNode(id, afterNodeId, newScope?)` — Reorder/reparent
- `duplicateNode(id)` — Deep copy with new IDs

## Helper: getNodesByScope

```typescript
function getNodesByScope(nodes: FlowNode[], scope: FlowNodeScope | null): FlowNode[] {
  return nodes
    .filter(n => {
      if (scope === null) return n.scope === null;
      return n.scope?.parentId === scope.parentId && n.scope?.branch === scope.branch;
    })
    .sort((a, b) => a.order.localeCompare(b.order));
}
```

## Helper: buildNodeTree (for rendering)

```typescript
interface NodeTreeItem {
  node: FlowNode;
  children: Record<string, NodeTreeItem[]>;  // branch → children
}

function buildNodeTree(nodes: FlowNode[]): NodeTreeItem[] {
  const roots = getNodesByScope(nodes, null);
  
  function buildChildren(parentId: string): Record<string, NodeTreeItem[]> {
    const branches: Record<string, NodeTreeItem[]> = {};
    const childNodes = nodes.filter(n => n.scope?.parentId === parentId);
    
    for (const child of childNodes) {
      const branch = child.scope!.branch;
      if (!branches[branch]) branches[branch] = [];
      branches[branch].push({
        node: child,
        children: isContainer(child.type) ? buildChildren(child.id) : {},
      });
    }
    
    // Sort each branch
    for (const branch of Object.keys(branches)) {
      branches[branch].sort((a, b) => a.node.order.localeCompare(b.node.order));
    }
    
    return branches;
  }
  
  return roots.map(n => ({
    node: n,
    children: isContainer(n.type) ? buildChildren(n.id) : {},
  }));
}
```

## Migration Path

The hook should also support converting legacy `steps[]` to graph on load:

```typescript
function legacyStepsToGraph(steps: FlowStep[]): { nodes: FlowNode[]; edges: FlowEdge[] } {
  // Same algorithm as Python steps_to_graph
  // Used when loading old scenarios that only have steps[]
}
```
