"""Shared campaign scenario-ref limits."""
from __future__ import annotations

DEFAULT_SCENARIO_REPEAT_COUNT = 1
MAX_SCENARIO_REPEAT_COUNT = 20


def normalize_scenario_repeat_count(value: object) -> int:
    if value is None:
        return DEFAULT_SCENARIO_REPEAT_COUNT
    try:
        repeat_count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("repeat_count must be an integer") from exc
    if repeat_count < DEFAULT_SCENARIO_REPEAT_COUNT:
        raise ValueError("repeat_count must be at least 1")
    if repeat_count > MAX_SCENARIO_REPEAT_COUNT:
        raise ValueError(
            f"repeat_count must be at most {MAX_SCENARIO_REPEAT_COUNT}"
        )
    return repeat_count
