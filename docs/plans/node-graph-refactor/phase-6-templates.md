# Phase 6: Template Migration

## Files to modify

| File | Action |
|------|--------|
| `device_farm/db/seeds/scenario_templates.py` | Use steps_to_graph on seed |

## Strategy

Templates **continue to define steps as flat arrays** in code. This is intentional — flat arrays are much easier to read and maintain for template authors.

The seeding function converts to nodes+edges automatically:

```python
async def seed_builtin_templates(db) -> int:
    from common.graph_compiler import steps_to_graph, compile_graph_to_steps
    
    for spec in BUILTIN_TEMPLATES:
        nodes, edges = steps_to_graph(spec["steps"])
        
        existing = await get_template_by_name(db, spec["name"])
        if existing is None:
            await create_template(
                db,
                name=spec["name"],
                steps=spec["steps"],      # keep flat for executor
                nodes=nodes,              # graph model
                edges=edges,
                variables=spec.get("variables", {}),
                ...
            )
        else:
            await update_template(
                db, existing.id,
                steps=spec["steps"],
                nodes=nodes,
                edges=edges,
                ...
            )
```

## ScenarioTemplate Model Change

Add `nodes` and `edges` columns to `ScenarioTemplate` model (same as `Scenario`).

## No Template Rewrite Needed

The flat array format in `scenario_templates.py` stays as-is. Conversion happens at runtime during seeding. This keeps templates readable and maintainable.
