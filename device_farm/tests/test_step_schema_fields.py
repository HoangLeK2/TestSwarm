"""Guard: STEP_SCHEMA "fields" entries must describe declared fields.

`fields` is optional and additive — a node without it validates exactly as it
did before. But a node *with* it now drives both save-time validation and the
frontend form, so a field declared there and nowhere else is a config the editor
renders and the API rejects.
"""
from __future__ import annotations

import re
import typing

import pytest

from common.scenario_schema import STEP_FIELD_TYPES, STEP_SCHEMA, validate_step

_WITH_FIELDS = sorted(t for t, s in STEP_SCHEMA.items() if s.get("fields"))


def _pydantic_step_models() -> dict[str, type]:
    """Unpack the discriminated StepModel union into {step type: model}."""
    from api.schemas.scenario import StepModel

    models: dict[str, type] = {}
    # Annotated[Union[Annotated[Model, Tag("x")], ...], Discriminator(...)]
    union = typing.get_args(StepModel)[0]
    for member in typing.get_args(union):
        model, *meta = typing.get_args(member)
        for tag in meta:
            name = getattr(tag, "tag", None)
            if name:
                models[name] = model
    return models


def _field_bounds(annotation: object, metadata: list[object]) -> dict[str, float]:
    bounds = {
        type(m).__name__: getattr(m, name, None)
        for m in metadata
        for name in ("ge", "le", "gt", "lt")
        if getattr(m, name, None) is not None
    }
    for arg in typing.get_args(annotation):
        if typing.get_origin(arg) is typing.Annotated:
            _, *annotated_meta = typing.get_args(arg)
            bounds.update(_field_bounds(object, list(annotated_meta)))
    return bounds


def test_at_least_one_node_declares_fields():
    assert _WITH_FIELDS, "no node declares 'fields' — the migration regressed"


@pytest.mark.parametrize("step_type", _WITH_FIELDS)
def test_declared_fields_are_not_orphans(step_type: str):
    schema = STEP_SCHEMA[step_type]
    declared = set(schema.get("required") or [])
    declared |= set(schema.get("optional") or [])
    for group in schema.get("required_any") or []:
        declared |= set(group)

    orphans = sorted(set(schema["fields"]) - declared)
    assert not orphans, (
        f"{step_type}: {orphans} appear in 'fields' but not in "
        f"required/optional/required_any — the editor would offer a config the "
        f"API rejects."
    )


@pytest.mark.parametrize("step_type", _WITH_FIELDS)
def test_field_specs_are_well_formed(step_type: str):
    for name, spec in STEP_SCHEMA[step_type]["fields"].items():
        kind = spec.get("type", "string")
        assert kind in STEP_FIELD_TYPES, f"{step_type}.{name}: unknown type {kind!r}"
        if kind == "enum":
            assert spec.get("values"), f"{step_type}.{name}: enum needs 'values'"
        if spec.get("pattern"):
            re.compile(spec["pattern"])  # raises if the pattern is malformed


def test_type_errors_are_caught_at_save_time():
    assert validate_step({"type": "launch_app", "package": "x", "wait_after": "abc"}, 0)
    assert validate_step({"type": "launch_app", "package": "x", "wait_after": -1}, 0)
    assert validate_step({"type": "tap_position", "pos": "nowhere"}, 0)
    assert validate_step({"type": "open_url", "url": "ftp://x"}, 0)
    assert validate_step({"type": "adb_shell", "command": "ls", "timeout": 9_999}, 0)


def test_valid_steps_still_pass():
    assert validate_step({"type": "launch_app", "package": "x", "wait_after": 3}, 0) == []
    assert validate_step({"type": "tap_position", "pos": "Top_Center"}, 0) == []
    assert validate_step({"type": "open_url", "url": "HTTPS://a.example"}, 0) == []
    assert validate_step({"type": "wait", "seconds": 0.5}, 0) == []


def test_variable_tokens_are_not_type_checked():
    # ${VAR} resolves at run time; rejecting it at save time would break every
    # scenario that parameterises a timeout.
    assert validate_step({"type": "wait", "seconds": "${DELAY}"}, 0) == []
    assert validate_step({"type": "tap_position", "pos": "${WHERE}"}, 0) == []


@pytest.mark.parametrize("step_type", _WITH_FIELDS)
def test_schema_bounds_match_the_model_that_actually_gates_saves(step_type: str):
    """STEP_SCHEMA and the Pydantic step models must agree on type and bounds.

    validate_scenario prefers api.schemas.scenario.ScenarioModel and only falls
    back to validate_step when that import fails — so Pydantic is the real save
    gate. STEP_SCHEMA is what the editor renders. A field the editor lets you
    set to 300 and the API rejects at 30 is a save error with no visible cause,
    which is the failure this schema exists to remove.
    """
    model = _pydantic_step_models().get(step_type)
    if model is None:
        pytest.skip(f"{step_type} has no Pydantic step model")

    for name, spec in STEP_SCHEMA[step_type]["fields"].items():
        model_field = model.model_fields.get(name)
        assert model_field is not None, f"{step_type}.{name} is not in {model.__name__}"
        bounds = _field_bounds(model_field.annotation, list(model_field.metadata))
        lower = bounds.get("Ge", bounds.get("Gt"))
        upper = bounds.get("Le", bounds.get("Lt"))
        if lower is not None:
            assert spec.get("min") == lower, f"{step_type}.{name} min"
        if upper is not None:
            assert spec.get("max") == upper, f"{step_type}.{name} max"


def test_nodes_without_fields_are_untouched():
    # tap_ratio declares no 'fields' — only required/optional applies, exactly
    # as before this migration.
    assert "fields" not in STEP_SCHEMA["tap_ratio"]
    assert validate_step({"type": "tap_ratio", "x": "not-a-number", "y": 0.5}, 0) == []
