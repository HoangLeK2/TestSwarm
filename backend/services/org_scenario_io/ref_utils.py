"""Shared helpers for walking org scenario bodies (DF-T-04-005)."""

from __future__ import annotations

import copy
from typing import Any, Iterator

from db.models.enums import ScenarioKind
from services.scenario_dsl.ref_cache import extract_run_scenario_id, steps_from_body
from services.scenario_dsl.step_family import COMPOSITION_RUN_SCENARIO


def iter_run_scenario_steps(body: dict[str, Any], kind: str) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """Yield (step, config) for each composition.run_scenario step."""
    for step in steps_from_body(kind, body):
        if str(step.get("type") or "") != COMPOSITION_RUN_SCENARIO:
            continue
        config = step.get("config")
        if not isinstance(config, dict):
            config = step
        yield step, config


def collect_run_scenario_ids(body: dict[str, Any], kind: str) -> set[str]:
    refs: set[str] = set()
    for _, config in iter_run_scenario_steps(body, kind):
        ref_id = extract_run_scenario_id({"type": COMPOSITION_RUN_SCENARIO, "config": config})
        if ref_id:
            refs.add(ref_id)
    return refs


def collect_run_scenario_names(body: dict[str, Any], kind: str) -> set[str]:
    names: set[str] = set()
    for _, config in iter_run_scenario_steps(body, kind):
        name = str(config.get("scenario_name") or step_name(config) or "").strip()
        if name:
            names.add(name)
    return names


def step_name(config: dict[str, Any]) -> str:
    return str(config.get("scenario_name") or "").strip()


def scrub_export_dict(data: dict[str, Any], *, scrub_fields: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in scrub_fields}


def rewrite_run_scenario_refs_for_export(
    body: dict[str, Any],
    kind: str,
    *,
    id_to_name: dict[str, str],
) -> dict[str, Any]:
    """Replace scenario_id with portable scenario_name; drop org-local ids."""
    out = copy.deepcopy(body)
    steps_key = "nodes" if kind == ScenarioKind.GRAPH.value else "steps"
    items = out.get(steps_key) or []
    if not isinstance(items, list):
        return out
    for step in items:
        if not isinstance(step, dict):
            continue
        if str(step.get("type") or "") != COMPOSITION_RUN_SCENARIO:
            continue
        config = step.get("config")
        if not isinstance(config, dict):
            config = step
            step["config"] = config
        ref_id = str(config.get("scenario_id") or "").strip()
        ref_name = str(config.get("scenario_name") or "").strip()
        if ref_id and ref_id in id_to_name:
            config["scenario_name"] = id_to_name[ref_id]
        elif ref_id and not ref_name:
            config["scenario_name"] = ref_id
        config.pop("scenario_id", None)
        config.pop("scenario_version", None)
        step.pop("scenario_id", None)
        step.pop("scenario_version", None)
    return out


def rewrite_run_scenario_refs_for_import(
    body: dict[str, Any],
    kind: str,
    *,
    name_to_id: dict[str, str],
) -> dict[str, Any]:
    """Resolve scenario_name to scenario_id for org-local validation and execution."""
    out = copy.deepcopy(body)
    steps_key = "nodes" if kind == ScenarioKind.GRAPH.value else "steps"
    items = out.get(steps_key) or []
    if not isinstance(items, list):
        return out
    for step in items:
        if not isinstance(step, dict):
            continue
        if str(step.get("type") or "") != COMPOSITION_RUN_SCENARIO:
            continue
        config = step.get("config")
        if not isinstance(config, dict):
            config = step
            step["config"] = config
        ref_name = str(config.get("scenario_name") or "").strip()
        if ref_name:
            resolved = name_to_id.get(ref_name.lower()) or name_to_id.get(ref_name)
            if resolved:
                config["scenario_id"] = resolved
        config.pop("scenario_name", None)
        step.pop("scenario_name", None)
    return out
