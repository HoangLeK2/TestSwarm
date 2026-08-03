"""Derive campaign source-pool allocation from declarative scenario steps."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from services.campaign.entity_allocation import (
    DEFAULT_POOL_STATUSES,
    SourcePoolSpec,
)

SOURCE_POOL_STEP_TYPE = "use_source_pool"


def _walk_steps(steps: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(steps, list):
        return
    for step in steps:
        if not isinstance(step, dict):
            continue
        yield step
        for key in ("steps", "then", "else"):
            yield from _walk_steps(step.get(key))
        branches = step.get("branches")
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    yield from _walk_steps(branch.get("steps"))


def source_pool_from_step(step: dict[str, Any]) -> SourcePoolSpec | None:
    if step.get("type") != SOURCE_POOL_STEP_TYPE:
        return None
    platform = str(step.get("platform") or "facebook").strip().lower()
    entity_type = str(step.get("entity_type") or "group").strip().lower()
    if not platform or not entity_type:
        return None
    raw_statuses = step.get("statuses")
    statuses = (
        tuple(
            str(status).strip().lower()
            for status in raw_statuses
            if str(status).strip()
        )
        if isinstance(raw_statuses, list)
        else DEFAULT_POOL_STATUSES
    )
    return SourcePoolSpec(
        platform=platform,
        entity_type=entity_type,
        search=str(step.get("search") or "").strip() or None,
        statuses=statuses or DEFAULT_POOL_STATUSES,
        output_prefix=str(step.get("output_prefix") or "GROUP").strip() or None,
    )


def source_pool_from_scenario_registry(
    registry: dict[str, Any] | None,
) -> SourcePoolSpec | None:
    if not isinstance(registry, dict):
        return None
    for entry in (registry.get("by_id") or {}).values():
        if not isinstance(entry, dict):
            continue
        for step in _walk_steps(entry.get("steps")):
            spec = source_pool_from_step(step)
            if spec is not None:
                return spec
    return None
