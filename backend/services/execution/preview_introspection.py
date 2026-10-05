"""Preview step introspection — side effects and account guards (DF-T-04-018)."""
from __future__ import annotations

from typing import Any

from services.campaign.account_resolver import _step_requires_account
from services.org_scenario_validation.step_index import OrgStepIndex

SIDE_EFFECT_WARNING = "Step social-effect detected; consider test account"


def preview_has_side_effects(steps: list[dict]) -> bool:
    return OrgStepIndex.build(steps).has_social


def preview_requires_account(steps: list[dict]) -> bool:
    """Login / explicit account steps only — not all social side-effects."""
    if not steps:
        return False
    idx = OrgStepIndex.build(steps)
    return any(_step_requires_account(step) for step, _, _ in idx.entries)


def collect_preview_warnings(steps: list[dict]) -> list[str]:
    warnings: list[str] = []
    if preview_has_side_effects(steps):
        warnings.append(SIDE_EFFECT_WARNING)
    return warnings
