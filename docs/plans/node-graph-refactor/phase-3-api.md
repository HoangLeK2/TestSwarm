# Phase 3: API + Validation

## Files to modify

| File | Action |
|------|--------|
| `device_farm/api/schemas/scenario.py` | Add FlowNodeModel, FlowEdgeModel, update ScenarioCreate/Update |
| `device_farm/api/routes/campaigns.py` | Accept nodes+edges, compile on save |
| `device_farm/common/scenario_schema.py` | Add graph-level validation |

## New Pydantic Models

```python
class ScopeModel(BaseModel):
    parentId: str
    branch: str = "steps"

class FlowNodeModel(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    type: str = Field(min_length=1)
    config: dict = {}
    order: str = Field(min_length=1, max_length=50)
    scope: Optional[ScopeModel] = None
    position: Optional[dict] = None
    title: Optional[str] = None
    description: Optional[str] = None

class FlowEdgeModel(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None
    type: str = "default"
    condition: Optional[str] = None
```

## API Contract Change

```python
class ScenarioUpdate(BaseModel):
    # Legacy (backward compat)
    steps: Optional[list] = None
    
    # Graph model (preferred)
    nodes: Optional[list[FlowNodeModel]] = None
    edges: Optional[list[FlowEdgeModel]] = None
```

## Save Logic

```python
# In PATCH handler:
if payload.nodes is not None:
    # Graph-first path
    validate_graph(payload.nodes, payload.edges or [])
    compiled = compile_graph_to_steps(payload.nodes, payload.edges or [])
    updates["nodes"] = [n.model_dump() for n in payload.nodes]
    updates["edges"] = [e.model_dump() for e in (payload.edges or [])]
    updates["steps"] = compiled
elif payload.steps is not None:
    # Legacy path: auto-convert to graph
    nodes, edges = steps_to_graph(payload.steps)
    updates["steps"] = payload.steps
    updates["nodes"] = nodes
    updates["edges"] = edges
```

## Graph Validation Rules

1. All node IDs unique
2. All edge source/target reference existing node IDs
3. No orphan nodes (every non-root node reachable via scope or edges)
4. Scope parentId references existing container node
5. Container nodes have valid branch names
6. No circular edges within same scope level
