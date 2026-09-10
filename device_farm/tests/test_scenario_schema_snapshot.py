"""Publish the scenario schema as a file the front-end can read without Python.

Two front-end checks need the *runtime* schema — after catalog metadata is
applied, not a regex over the source: the node-coverage test and
check-schema-field-i18n.mjs. Both used to shell out to device_farm/.venv/bin/python,
which works on a dev machine and breaks any front-end CI job that does not build
the backend venv (the `python3` fallback has none of the dependencies).

Same shape as openapi.json: the backend writes a file, the front-end reads it.
This test fails when the checked-in file drifts, so the schema and the editor
cannot disagree silently.

Regenerate after changing STEP_SCHEMA or NODE_FIELD_METADATA:

    UPDATE_SCENARIO_SCHEMA_SNAPSHOT=1 .venv/bin/python -m pytest \\
        tests/test_scenario_schema_snapshot.py
"""
from __future__ import annotations

import json
import os
import pathlib

from common.scenario_schema import get_scenario_schema

_SNAPSHOT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "front-end/generate/scenario-schema.json"
)


def _serialized() -> str:
    return json.dumps(get_scenario_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_front_end_scenario_schema_snapshot_is_current():
    current = _serialized()

    if os.environ.get("UPDATE_SCENARIO_SCHEMA_SNAPSHOT"):
        _SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT.write_text(current, encoding="utf-8")

    assert _SNAPSHOT.exists(), (
        f"{_SNAPSHOT} is missing — run with UPDATE_SCENARIO_SCHEMA_SNAPSHOT=1"
    )
    assert _SNAPSHOT.read_text(encoding="utf-8") == current, (
        "front-end/generate/scenario-schema.json is stale; regenerate with "
        "UPDATE_SCENARIO_SCHEMA_SNAPSHOT=1"
    )


def test_snapshot_carries_what_the_front_end_reads():
    """Guard the contract the two front-end consumers depend on."""
    schema = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    steps = schema["steps_schema"]

    assert steps["tap_position"]["fields"]["pos"]["values"]
    assert steps["loop"]["fields"]["stall_after"]["type"] == "number"
    assert steps["loop"]["fields"]["loop_var"]["advanced"] is True
