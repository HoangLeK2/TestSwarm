from __future__ import annotations

"""Generic builtin scenario template registry and idempotent seed helpers."""

from typing import Any, Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# Aggregate list
# ─────────────────────────────────────────────────────────────────────────────

BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "Generic - Launch application",
        "description": "Launch the configured Android package and wait for a stable screen.",
        "category": "device-testing",
        "tags": "generic,app,smoke",
        "variables": {"APP_PACKAGE": "com.example.app"},
        "steps": [
            {"id": "launch_app", "type": "launch_app", "package": "${APP_PACKAGE}"},
            {"id": "wait_stable", "type": "wait_stable", "timeout": 10},
        ],
    },
    {
        "name": "Generic - Open web URL",
        "description": "Open a neutral web page and wait for rendering to settle.",
        "category": "device-testing",
        "tags": "generic,browser,smoke",
        "variables": {},
        "steps": [
            {"id": "open_url", "type": "open_url", "url": "https://example.com"},
            {"id": "wait_stable", "type": "wait_stable", "timeout": 10},
        ],
    },
    {
        "name": "Generic - Find and tap element",
        "description": "Wait for a configured text label, tap it, and wait for the result.",
        "category": "device-testing",
        "tags": "generic,ui,interaction",
        "variables": {"TARGET_TEXT": "Continue"},
        "steps": [
            {"id": "wait_target", "type": "wait_element", "by": "text", "value": "${TARGET_TEXT}"},
            {"id": "tap_target", "type": "tap_selector", "by": "text", "value": "${TARGET_TEXT}"},
            {"id": "wait_result", "type": "wait_stable", "timeout": 10},
        ],
    },
    {
        "name": "Generic - Enter text",
        "description": "Enter configurable text into the currently focused field.",
        "category": "device-testing",
        "tags": "generic,ui,input",
        "variables": {"INPUT_TEXT": "sample input"},
        "steps": [
            {"id": "input_text", "type": "input_text", "text": "${INPUT_TEXT}"},
            {"id": "wait_stable", "type": "wait_stable", "timeout": 10},
        ],
    },
    {
        "name": "Generic - Capture screen evidence",
        "description": "Capture a screenshot and visible hierarchy text for test evidence.",
        "category": "device-testing",
        "tags": "generic,evidence,capture",
        "variables": {},
        "steps": [
            {"id": "screenshot", "type": "take_screenshot"},
            {"id": "hierarchy", "type": "extract_text_hierarchy", "save_as": "VISIBLE_TEXT"},
        ],
    },
]

BUILTIN_TEMPLATE_BY_NAME: Dict[str, Dict[str, Any]] = {
    spec["name"]: spec for spec in BUILTIN_TEMPLATES
}


def _spec_for_template_row(tmpl) -> Dict[str, Any] | None:
    """Match DB row to code-managed builtin spec (by technical name)."""
    if tmpl.name in BUILTIN_TEMPLATE_BY_NAME:
        return BUILTIN_TEMPLATE_BY_NAME[tmpl.name]
    key = str(tmpl.name or "").strip().lower()
    for spec in BUILTIN_TEMPLATES:
        if str(spec.get("name", "")).strip().lower() == key:
            return spec
    return None


def _graph_mirror_from_steps(steps: list) -> tuple[list, list]:
    """
    Derive nodes/edges from steps for a future flow editor (not used at runtime today).
    Canonical execution format remains flat steps[] (sequence).
    """
    if not steps:
        return [], []
    from common.graph_compiler import steps_to_graph

    nodes, edges = steps_to_graph(steps)
    return nodes, edges


def _seedable_steps(steps: list) -> list:
    """Steps as they should land in the DB: every authored step carrying an id.

    Templates are authored by hand here, and nothing in this file mints ids —
    that only ever happened in the flow editor. The seeded row is what a
    campaign actually runs, and the durable ledger refuses a claim from a step
    with no id, so the fill happens on the way to the database.

    The returned list is new; the module-level spec is left exactly as written
    so a template's authored ids remain the ones a reader sees in code.
    """
    from services.scenario_dsl.step_tree import assign_missing_step_ids

    return assign_missing_step_ids(list(steps or []))


async def repair_builtin_templates_to_sequence(db) -> int:
    """
    Sync builtin templates: steps are canonical; nodes/edges are a derived graph mirror.

    - Code specs win when the row name matches BUILTIN_TEMPLATES.
    - If only graph exists, compile → steps then refresh the graph mirror from steps.
    - Never wipe nodes/edges without regenerating them from steps.
    """
    import logging

    from sqlalchemy import select

    from common.graph_compiler import compile_graph_to_steps
    from db.crud.scenario_template import update_template
    from db.models.scenario_template import ScenarioTemplate

    log = logging.getLogger(__name__)
    changed = 0
    result = await db.execute(
        select(ScenarioTemplate).where(ScenarioTemplate.is_builtin.is_(True))
    )
    for tmpl in result.scalars().all():
        spec = _spec_for_template_row(tmpl)
        steps = list(tmpl.steps) if isinstance(tmpl.steps, list) else []
        nodes = list(tmpl.nodes) if isinstance(tmpl.nodes, list) else []
        edges = list(tmpl.edges) if isinstance(tmpl.edges, list) else []

        new_steps: list = []
        if spec and spec.get("steps"):
            new_steps = list(spec["steps"])
        elif steps:
            new_steps = steps
        elif nodes or edges:
            try:
                new_steps = compile_graph_to_steps(nodes, edges)
            except Exception as exc:
                log.warning(
                    "Could not compile graph for builtin template %r: %s",
                    tmpl.name,
                    exc,
                )
                new_steps = []

        if not new_steps:
            if nodes or edges:
                log.warning(
                    "Builtin template %r still graph-only with no steps — "
                    "add to BUILTIN_TEMPLATES or restore from code spec",
                    tmpl.name,
                )
            continue

        new_steps = _seedable_steps(new_steps)
        graph_nodes, graph_edges = _graph_mirror_from_steps(new_steps)
        updates: Dict[str, Any] = {
            "steps": new_steps,
            "nodes": graph_nodes,
            "edges": graph_edges,
        }
        if spec:
            if spec.get("display_name") is not None:
                updates["display_name"] = spec.get("display_name", "")
            if spec.get("description") is not None:
                updates["description"] = spec.get("description", "")
            if spec.get("category") is not None:
                updates["category"] = spec.get("category", "general")
            if spec.get("variables") is not None:
                updates["variables"] = spec.get("variables", {})
            if spec.get("tags") is not None:
                updates["tags"] = spec.get("tags", "")
            updates["is_builtin"] = spec.get("is_builtin", True)

        await update_template(db, tmpl.id, **updates)
        changed += 1

    return changed


async def seed_builtin_templates(db) -> int:
    """
    Upsert BUILTIN_TEMPLATES: insert if not found, update steps/variables/description
    if already exists (so template fixes are applied on every restart).

    Returns the number of templates inserted or updated.
    """
    from db.crud.scenario_template import create_template, get_template_by_name, update_template

    changed = 0
    for spec in BUILTIN_TEMPLATES:
        spec_is_builtin = spec.get("is_builtin", True)
        raw_steps = spec.get("steps", [])
        if not raw_steps:
            continue
        raw_steps = _seedable_steps(raw_steps)
        graph_nodes, graph_edges = _graph_mirror_from_steps(raw_steps)
        existing = await get_template_by_name(db, spec["name"])
        if existing is None:
            await create_template(
                db,
                name=spec["name"],
                display_name=spec.get("display_name", ""),
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=raw_steps,
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                user_id=None,
                nodes=graph_nodes,
                edges=graph_edges,
            )
            changed += 1
        else:
            # Sync steps from code; refresh graph mirror from steps (future flow editor).
            await update_template(
                db,
                existing.id,
                display_name=spec.get("display_name", ""),
                description=spec.get("description", ""),
                category=spec.get("category", "general"),
                steps=raw_steps,
                variables=spec.get("variables", {}),
                tags=spec.get("tags", ""),
                is_builtin=spec_is_builtin,
                nodes=graph_nodes,
                edges=graph_edges,
            )
            changed += 1

    changed += await repair_builtin_templates_to_sequence(db)

    if changed:
        await db.commit()

    return changed
