"""Step handler: use_source_pool."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from tasks.scenario.steps import register_step

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext


@register_step("use_source_pool")
def handle_use_source_pool(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    idx: int,
    result: Dict[str, Any],
) -> None:
    platform = str(step.get("platform") or "facebook").strip().lower()
    entity_type = str(step.get("entity_type") or "group").strip().lower()
    variables = sc.scenario.get("variables") or {}
    resolved_target_entity_id = sc.var_ctx.resolve(
        "${TARGET_ENTITY_ID}", step_index=idx
    )
    if resolved_target_entity_id == "${TARGET_ENTITY_ID}":
        resolved_target_entity_id = None
    result["message"] = f"use_source_pool: {platform}/{entity_type}"
    result["output_prefix"] = str(step.get("output_prefix") or "GROUP").strip()
    result["target_entity_id"] = (
        sc.ctx.get("TARGET_ENTITY_ID")
        or variables.get("TARGET_ENTITY_ID")
        or resolved_target_entity_id
    )
