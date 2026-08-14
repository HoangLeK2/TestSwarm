"""Step index for org-scenario DSL bodies (DF-T-04-004)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from services.scenario_dsl.step_family import COMPOSITION_RUN_SCENARIO
from services.scenario_dsl.step_registry import StepRegistry

StepEntry = tuple[dict, str, str | None]

_INTERACTION_PREFIXES = (
    "interaction.",
    "tap",
    "swipe",
    "input",
    "scroll",
    "launch_app",
    "open_url",
)
_SOCIAL_MARKERS = ("tap_fb", "fb_", "ig_", "tiktok_", "linkedin_", "platform_specific.")
_GENERIC_SOCIAL_TYPES = frozenset(
    {
        "content_interaction",
        "connection_request",
        "lease_connection_candidate",
        "lease_source_target",
        "community_membership",
        "fb_select_people_profile",
        "fb_connect_visible_people",
        "fb_select_post_target",
        "fb_scan_posts_interact",
        "social_open_author_from_post_match",
    }
)


@dataclass(frozen=True)
class OrgStepIndex:
    entries: tuple[StepEntry, ...]
    step_ids: frozenset[str]
    has_interaction: bool
    has_verification: bool
    has_social: bool
    run_scenario_refs: tuple[StepEntry, ...]

    @classmethod
    def build(cls, steps: list[dict], *, path_prefix: str = "steps") -> OrgStepIndex:
        entries: list[StepEntry] = []
        step_ids: set[str] = set()
        has_interaction = False
        has_verification = False
        has_social = False
        run_refs: list[StepEntry] = []

        for step, loc, sid in _walk_steps(steps, path_prefix=path_prefix):
            entries.append((step, loc, sid))
            if sid:
                step_ids.add(sid)
            stype = str(step.get("type") or "")
            if stype.startswith("verification.") or stype == "verify_screen":
                has_verification = True
            elif _is_interaction_type(stype):
                has_interaction = True
            if _is_social_step(step):
                has_social = True
            if stype in (COMPOSITION_RUN_SCENARIO, "run_scenario"):
                run_refs.append((step, loc, sid))

        return cls(
            entries=tuple(entries),
            step_ids=frozenset(step_ids),
            has_interaction=has_interaction,
            has_verification=has_verification,
            has_social=has_social,
            run_scenario_refs=tuple(run_refs),
        )

    @classmethod
    def empty(cls) -> OrgStepIndex:
        return cls(
            entries=(),
            step_ids=frozenset(),
            has_interaction=False,
            has_verification=False,
            has_social=False,
            run_scenario_refs=(),
        )


def _is_interaction_type(step_type: str) -> bool:
    return any(step_type == p or step_type.startswith(p) for p in _INTERACTION_PREFIXES)


def _is_social_step(step: dict) -> bool:
    t = str(step.get("type") or "")
    if t in _GENERIC_SOCIAL_TYPES:
        return True
    if any(marker in t for marker in _SOCIAL_MARKERS):
        return True
    if StepRegistry.get(t) is not None and not t.startswith("interaction."):
        if any(marker in t for marker in ("fb_", "ig_", "tiktok_", "linkedin_")):
            return True
    config = step.get("config")
    if isinstance(config, dict):
        strategy = str(config.get("strategy") or "")
        if any(marker in strategy for marker in ("fb_", "ig_", "tiktok_", "linkedin_")):
            return True
    return False


def _walk_steps(
    steps: list[dict],
    *,
    path_prefix: str = "steps",
) -> Iterator[StepEntry]:
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        step_id = step.get("id")
        sid = str(step_id) if step_id else None
        loc = f"step.{sid}" if sid else f"{path_prefix}[{idx}]"
        yield step, loc, sid

        nested: list[tuple[str, list]] = [
            ("steps", step.get("steps") or []),
            ("then", step.get("then") or []),
            ("else", step.get("else") or step.get("else_steps") or []),
        ]
        for branch in step.get("branches") or []:
            if isinstance(branch, dict):
                nested.append(("branches", branch.get("steps") or []))
        for key, child_steps in nested:
            if child_steps:
                child_prefix = f"{loc}.{key}" if sid else f"{path_prefix}[{idx}].{key}"
                yield from _walk_steps(child_steps, path_prefix=child_prefix)
