# Phase 1: Data Model + Migration

## Files to modify

| File | Action |
|------|--------|
| `device_farm/db/models/campaign.py` | Add `nodes`, `edges` columns to `Scenario` |
| `device_farm/db/migrations/versions/xxx_add_graph_columns.py` | NEW: Alembic migration |
| `device_farm/pyproject.toml` | Add `fractional-indexing`, `nanoid` |

## Schema Changes

```python
# device_farm/db/models/campaign.py
class Scenario(Base):
    # ... existing ...
    steps: Mapped[list] = mapped_column(JSON, default=list)       # KEEP (executor input)
    nodes: Mapped[list] = mapped_column(JSON, default=list)       # NEW
    edges: Mapped[list] = mapped_column(JSON, default=list)       # NEW
```

## Migration Script

```python
"""Add nodes and edges columns to scenario table."""

def upgrade():
    op.add_column('scenario', sa.Column('nodes', sa.JSON(), server_default='[]'))
    op.add_column('scenario', sa.Column('edges', sa.JSON(), server_default='[]'))

def downgrade():
    op.drop_column('scenario', 'edges')
    op.drop_column('scenario', 'nodes')
```

## Data Migration (populate existing)

After adding columns, run a one-time migration to populate `nodes`/`edges` from existing `steps`:

```python
async def backfill_graph_data():
    """Convert all existing scenario steps[] to nodes[] + edges[]."""
    from common.graph_compiler import steps_to_graph
    
    scenarios = await db.execute(select(Scenario))
    for scenario in scenarios.scalars():
        if scenario.steps and not scenario.nodes:
            nodes, edges = steps_to_graph(scenario.steps)
            scenario.nodes = nodes
            scenario.edges = edges
    await db.commit()
```

## Acceptance Criteria

- [ ] `nodes` and `edges` columns exist on `Scenario`
- [ ] Existing scenarios have populated graph data
- [ ] `steps[]` remains unchanged and functional
- [ ] `fractional-indexing` importable in Python
