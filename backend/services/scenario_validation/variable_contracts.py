"""Runtime variable outputs produced by scenario steps."""

from __future__ import annotations

from typing import Any

_STEP_OUTPUT_VARIABLES: dict[str, frozenset[str]] = {
    "lease_source_target": frozenset(
        {
            "TARGET_AVAILABLE",
            "TARGET_ACTION_ID",
            "TARGET_ENTITY_ID",
            "TARGET_EXTERNAL_ID",
            "TARGET_NAME",
            "TARGET_SEARCH_TEXT",
            "TARGET_URL",
        }
    ),
    "lease_connection_candidate": frozenset(
        {
            "CANDIDATE_AVAILABLE",
            "CANDIDATE_ID",
            "CANDIDATE_ENTITY_ID",
            "CANDIDATE_EXTERNAL_ID",
            "CANDIDATE_NAME",
            "CANDIDATE_URL",
            "CANDIDATE_LEASE_TOKEN",
            "TARGET_ENTITY_ID",
            "TARGET_EXTERNAL_ID",
            "TARGET_NAME",
            "TARGET_URL",
        }
    ),
}


def step_output_variables(step_type: Any) -> frozenset[str]:
    """Return variables made available after a step completes."""
    return _STEP_OUTPUT_VARIABLES.get(str(step_type or ""), frozenset())
