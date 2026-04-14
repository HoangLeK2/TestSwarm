# Phase 5: Frontend UI Migration

## Files to modify

| File | Action |
|------|--------|
| `flow-editor/flow-editor.tsx` | Consume graph hook instead of steps[] |
| `flow-editor/step-card.tsx` | Render from `node.config` instead of raw step |
| `flow-editor/bracket-block.tsx` | Render from tree structure (scope-based children) |
| `flow-editor/flow-dnd-ids.ts` | Simplify: DnD IDs = node.id (not path-based) |
| `flow-editor/step-detail-panel.tsx` | Edit `node.config` via `updateNode(id, patch)` |
| `scenario-dialog.tsx` | Send nodes+edges on save |
| `hooks/use-campaigns.ts` | Update mutation to send graph format |

## Strategy

**Keep list-based UI.** The graph model runs underneath but the UI stays the same sortable list with nested bracket blocks. No visual canvas in this phase.

## Key Changes

### FlowEditor Props

```typescript
// Before
interface Props {
  steps: FlowStep[];
  onChange: (steps: FlowStep[]) => void;
}

// After
interface Props {
  nodes: FlowNode[];
  edges: FlowEdge[];
  onChangeNodes: (nodes: FlowNode[]) => void;
  onChangeEdges: (edges: FlowEdge[]) => void;
  // Legacy fallback (optional)
  steps?: FlowStep[];
  onChange?: (steps: FlowStep[]) => void;
}
```

### Rendering

```typescript
// Before: iterate steps[], recurse into step.steps/then/else
// After:
const tree = buildNodeTree(nodes);

function renderTree(items: NodeTreeItem[]) {
  return items.map(item => {
    if (isContainer(item.node.type)) {
      return (
        <BracketBlock node={item.node} key={item.node.id}>
          {Object.entries(item.children).map(([branch, children]) => (
            <BranchSection key={branch} branch={branch}>
              {renderTree(children)}
            </BranchSection>
          ))}
        </BracketBlock>
      );
    }
    return <StepCard node={item.node} key={item.node.id} />;
  });
}
```

### DnD Simplification

```typescript
// Before: FlowListRef with complex path encoding
// { kind: 'nested', rootIndex: 3, pathToBracket: [{listKey: 'steps', childIndex: 1}], listKey: 'then' }

// After: Just node.id + target scope
interface DragData {
  nodeId: string;
}
interface DropTarget {
  afterNodeId: string | null;
  scope: FlowNodeScope | null;
}

// On drop:
graph.moveNode(dragData.nodeId, dropTarget.afterNodeId, dropTarget.scope);
```

### StepDetailPanel

```typescript
// Before: onChange({ ...step, ...fields })
// After:
const handleChange = (configPatch: Record<string, any>) => {
  graph.updateNode(selectedNodeId, { config: { ...node.config, ...configPatch } });
};
```

### Save Flow

```typescript
// scenario-dialog.tsx
const handleSave = async () => {
  await updateScenario({
    nodes: graph.nodes,
    edges: graph.edges,
    // steps[] is auto-compiled by backend
  });
};
```

## Backward Compatibility

On load, if scenario has `nodes` → use graph model.
If only `steps` → auto-convert via `legacyStepsToGraph()`.
