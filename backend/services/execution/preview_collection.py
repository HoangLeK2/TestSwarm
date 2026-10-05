"""Preview content collection resolution (DF-T-04-018)."""
from __future__ import annotations

from typing import Any

PREVIEW_COLLECTION_VAR = "__PREVIEW_COLLECTION__"


def preview_collection_name(org_id: str) -> str:
    return f"preview:{org_id}"


def resolve_content_collection(
    step: dict[str, Any],
    *,
    campaign_vars: dict[str, Any] | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> str:
    """Resolve target collection for save_extraction during preview runs."""
    explicit = step.get("collection")
    if explicit and str(explicit) != "default":
        return str(explicit)
    cfg = scenario_config or {}
    preview = cfg.get("preview_collection")
    if preview:
        return str(preview)
    cv = campaign_vars or {}
    from_preview = cv.get(PREVIEW_COLLECTION_VAR)
    if from_preview:
        return str(from_preview)
    return str(explicit or "default")
