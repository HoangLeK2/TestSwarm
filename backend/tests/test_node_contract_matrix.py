from __future__ import annotations

import re
import typing
from pathlib import Path

from common.node_catalog import NODE_FIELD_METADATA, build_node_catalog
from common.scenario_schema import SCENARIO_STEP_TYPES, STEP_SCHEMA, _STEP_SCHEMA_BASE
from tasks.scenario.steps import _STEP_HANDLERS


_ROOT = Path(__file__).resolve().parents[2]

_WORKFLOW_HANDLED = {
    "repeat",
    "repeat_until",
    "if_element",
    "if_variable",
    "loop",
    "break_if",
    "random_pick",
    "run_scenario",
}

_RUNTIME_ALIASES = {
    "if": "if_element",
    "set_var": "set_variable",
}

_UI_PRESETS = {
    "extract_comments": "extract",
    "extract_posts": "extract",
    "key_back": "key",
}


def _pydantic_step_tags() -> set[str]:
    from api.schemas.scenario import StepModel

    tags: set[str] = set()
    union = typing.get_args(StepModel)[0]
    for member in typing.get_args(union):
        _model, *meta = typing.get_args(member)
        for tag in meta:
            name = getattr(tag, "tag", None)
            if name:
                tags.add(name)
    return tags


def _ts_string_set(path: str, export_name: str) -> set[str]:
    source = (_ROOT / path).read_text(encoding="utf-8")
    match = re.search(
        rf"export const {export_name}.*?=\s*\[(.*?)\]\s*(?:as const)?;",
        source,
        re.S,
    )
    assert match is not None, f"{export_name} not found in {path}"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _all_step_type_values() -> set[str]:
    source = (
        _ROOT
        / "front-end/src/features/campaigns/components/scenario-steps/types.ts"
    ).read_text(encoding="utf-8")
    match = re.search(r"export const ALL_STEP_TYPES:.*?=\s*\[(.*?)\];", source, re.S)
    assert match is not None, "ALL_STEP_TYPES not found"
    return set(re.findall(r"value:\s*'([^']+)'", match.group(1)))


def _create_default_step_switch() -> str:
    source = (
        _ROOT
        / "front-end/src/features/campaigns/components/scenario-steps/types.ts"
    ).read_text(encoding="utf-8")
    match = re.search(r"export function createDefaultStep\(.*?switch \(type\) \{(.*?)\n\s+default:", source, re.S)
    assert match is not None, "createDefaultStep switch not found"
    return match.group(1)


def _create_default_step_cases() -> set[str]:
    return set(re.findall(r"case '([^']+)'", _create_default_step_switch()))


def _object_literal_keys(body: str) -> set[str]:
    """Top-level keys of the first object literal in ``body``."""
    start = body.find("{")
    if start < 0:
        return set()
    keys: set[str] = set()
    depth = 0
    quote = ""
    i = start
    while i < len(body):
        ch = body[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                break
        elif depth == 1:
            key = re.match(r"([A-Za-z_]\w*)\s*:", body[i:])
            if key and not re.match(r"\w", body[i - 1]):
                keys.add(key.group(1))
        i += 1
    return keys


def _create_default_step_fields() -> dict[str, set[str]]:
    """Map each ``createDefaultStep`` case to the keys it writes on the step."""
    switch = _create_default_step_switch()
    marks = list(re.finditer(r"case '([^']+)':", switch))
    fields: dict[str, set[str]] = {}
    pending: list[str] = []
    for i, mark in enumerate(marks):
        pending.append(mark.group(1))
        end = marks[i + 1].start() if i + 1 < len(marks) else len(switch)
        body = switch[mark.end() : end]
        if not body.strip():
            continue  # fallthrough to the next case's return
        keys = _object_literal_keys(body)
        for label in pending:
            fields[label] = keys
        pending = []
    return fields


def test_backend_canonical_node_surfaces_match():
    declared = set(SCENARIO_STEP_TYPES)

    assert set(STEP_SCHEMA) == declared
    assert _pydantic_step_tags() == declared

    missing_handlers = declared - set(_STEP_HANDLERS) - _WORKFLOW_HANDLED
    assert missing_handlers == set()

    orphan_handlers = set(_STEP_HANDLERS) - declared
    assert orphan_handlers == set(_RUNTIME_ALIASES)


def test_node_catalog_is_complete_for_declared_nodes():
    catalog = build_node_catalog(step_types=SCENARIO_STEP_TYPES, step_schema=STEP_SCHEMA)
    nodes = catalog["nodes"]
    by_type = {node["node_type"]: node for node in nodes}

    assert list(by_type) == SCENARIO_STEP_TYPES
    assert set(by_type) == set(SCENARIO_STEP_TYPES)

    for step_type, schema in STEP_SCHEMA.items():
        node = by_type[step_type]
        assert node["runtime_step_type"] == step_type
        assert node["description"] == schema.get("description", "")
        assert node.get("required", []) == schema.get("required", [])
        assert node.get("optional", []) == schema.get("optional", [])


def test_catalog_field_metadata_drives_step_schema_fields():
    catalog = build_node_catalog(step_types=SCENARIO_STEP_TYPES, step_schema=STEP_SCHEMA)
    catalog_fields = {
        node["node_type"]: {field["name"]: field for field in node.get("fields", [])}
        for node in catalog["nodes"]
    }

    for step_type, schema in STEP_SCHEMA.items():
        fields = schema.get("fields") or {}
        if not fields:
            continue
        assert set(catalog_fields[step_type]) == set(fields)
        for name, spec in fields.items():
            assert catalog_fields[step_type][name]["type"] == spec.get("type", "string")


def test_catalog_owned_metadata_is_not_duplicated_in_base_schema():
    for step_type in NODE_FIELD_METADATA:
        schema = _STEP_SCHEMA_BASE[step_type]
        assert "fields" not in schema
        assert "defaults" not in schema


def test_frontend_insert_menu_and_defaults_cover_declared_nodes():
    insert_values = _ts_string_set(
        "front-end/src/features/campaigns/components/flow-editor/constants.ts",
        "INSERT_MENU_DEF",
    ) - {"dataCollection", "actions", "flow", "social"}
    default_cases = _create_default_step_cases()

    assert set(SCENARIO_STEP_TYPES) - insert_values == set()
    assert insert_values - set(SCENARIO_STEP_TYPES) == set(_RUNTIME_ALIASES) | set(_UI_PRESETS)
    assert insert_values - default_cases == set()


# Nodes whose Pydantic model carries a model_validator that is NOT a
# "one of these fields is required" rule, so there is nothing to mirror into
# required_any. Anything else must declare the rule in STEP_SCHEMA, which is
# what /scenario/schema publishes to the editor.
_NO_REQUIRED_ANY_REASON = {
    # at_least_one_source only rejects using MORE than one source; zero is
    # explicitly allowed ("value=None is allowed (sets variable to None)").
    # Declaring required_any here would reject steps the API accepts.
    "set_variable": "validator forbids >1 source, does not require >=1",
}


def _pydantic_step_models() -> dict[str, type]:
    from api.schemas.scenario import StepModel

    models: dict[str, type] = {}
    union = typing.get_args(StepModel)[0]
    for member in typing.get_args(union):
        model, *meta = typing.get_args(member)
        for tag in meta:
            name = getattr(tag, "tag", None)
            if name:
                models[name] = model
    return models


def test_pydantic_required_field_rules_are_published_in_step_schema():
    """A rule the editor cannot see is a rule the user discovers at save time."""
    missing: dict[str, list[str]] = {}
    for step_type, model in _pydantic_step_models().items():
        validators = list(model.__pydantic_decorators__.model_validators)
        if not validators or step_type in _NO_REQUIRED_ANY_REASON:
            continue
        if not STEP_SCHEMA[step_type].get("required_any"):
            missing[step_type] = validators

    assert missing == {}


def test_no_required_any_allowlist_only_covers_nodes_that_have_a_validator():
    models = _pydantic_step_models()
    for step_type in _NO_REQUIRED_ANY_REASON:
        assert list(models[step_type].__pydantic_decorators__.model_validators), step_type


def test_create_default_step_only_writes_declared_fields():
    """A default the executor never reads is a lie the editor tells the user.

    ``createDefaultStep('tap')`` used to seed ``wait_after: true``; ``handle_tap``
    has no such branch, and the two nodes that do read ``wait_after`` read it as
    a number of seconds.
    """
    aliases = {**_RUNTIME_ALIASES, **_UI_PRESETS}
    editor_internal = {"id", "order", "type"}

    undeclared: dict[str, set[str]] = {}
    for case, keys in _create_default_step_fields().items():
        if case in _RUNTIME_ALIASES and case not in STEP_SCHEMA:
            continue
        step_type = aliases.get(case, case)
        schema = STEP_SCHEMA.get(step_type)
        if schema is None:
            continue
        declared = (
            set(schema.get("required") or ())
            | set(schema.get("optional") or ())
            | set(schema.get("fields") or ())
            | {name for group in schema.get("required_any") or () for name in group}
        )
        extra = keys - declared - editor_internal
        if extra:
            undeclared[case] = extra

    assert undeclared == {}


def test_frontend_dropdown_does_not_invent_unknown_nodes():
    dropdown_values = _all_step_type_values()

    assert dropdown_values - set(SCENARIO_STEP_TYPES) == set(_RUNTIME_ALIASES)
