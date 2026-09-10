from __future__ import annotations

import re
from pathlib import Path

from common.node_capabilities import build_node_capability_registry, find_node_contract_gaps
from common.scenario_schema import SCENARIO_STEP_TYPES, STEP_SCHEMA, get_scenario_schema
from tasks.scenario.steps import _STEP_HANDLERS

# Handler names kept as aliases of a declared node. They dispatch to the same
# behaviour under a shorter legacy name and are deliberately not offered in the
# editor, so they are not gaps.
_HANDLER_ALIASES = {
    "if": "if_element",
    "set_var": "set_variable",
}


def test_schema_exposes_node_capability_registry():
    schema = get_scenario_schema()
    registry = schema["node_capabilities"]
    by_type = {entry["type"]: entry for entry in registry}

    assert list(by_type) == SCENARIO_STEP_TYPES
    assert by_type["install_apk"]["requires"] == ["supports_install_apk"]
    assert by_type["install_apk"]["risk"] == "high"
    assert by_type["tap_image"]["requires"] == ["has_image_match", "has_opencv"]
    assert "show_template_match" in by_type["tap_image"]["inspector_hints"]
    assert "ocr_boxes" in by_type["extract_text_ocr"]["recorder_evidence"]


def test_node_capability_registry_has_no_schema_gaps():
    registry = build_node_capability_registry(SCENARIO_STEP_TYPES, STEP_SCHEMA)
    gaps = find_node_contract_gaps(
        SCENARIO_STEP_TYPES,
        STEP_SCHEMA,
        registered_handlers=set(_STEP_HANDLERS),
    )

    assert len(registry) == len(SCENARIO_STEP_TYPES)
    assert len({entry["type"] for entry in registry}) == len(registry)
    assert gaps["missing_schema"] == []
    # A handler with no declared node type is unreachable from the editor and
    # rejected by validate_step — declare it or delete it.
    assert [t for t in gaps["orphan_handler"] if t not in _HANDLER_ALIASES] == []
    assert "install_apk" in SCENARIO_STEP_TYPES
    assert "install_apk" in STEP_SCHEMA


def test_frontend_all_step_types_are_unique():
    repo_root = Path(__file__).resolve().parents[2]
    types_path = repo_root / "front-end/src/features/campaigns/components/scenario-steps/types.ts"
    source = types_path.read_text(encoding="utf-8")
    match = re.search(r"export const ALL_STEP_TYPES:.*?=\s*\[(.*?)\];", source, re.S)
    assert match is not None

    values = re.findall(r"value:\s*'([^']+)'", match.group(1))
    duplicates = sorted({value for value in values if values.count(value) > 1})

    assert duplicates == []
    assert "install_apk" in values
    assert "extract_text_ocr" in values
