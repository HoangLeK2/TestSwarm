"""Single-pass index over scenario step trees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

StepEntry = tuple[dict, str, str | None]


@dataclass(frozen=True)
class StepIndex:
    """Precomputed walk of a scenario step tree (built once per validate)."""

    entries: tuple[StepEntry, ...]
    step_ids: frozenset[str]
    has_interaction: bool
    has_verification: bool
    has_social: bool
    run_scenario_refs: tuple[StepEntry, ...]

    @classmethod
    def build(cls, steps: list[dict]) -> StepIndex:
        entries: list[StepEntry] = []
        step_ids: set[str] = set()
        has_interaction = False
        has_verification = False
        has_social = False
        run_refs: list[StepEntry] = []

        for step, loc, sid in _walk_steps(steps):
            entries.append((step, loc, sid))
            if sid:
                step_ids.add(sid)
            stype = str(step.get("type") or "")
            if stype == "verify_screen":
                has_verification = True
            elif _is_interaction_type(stype):
                has_interaction = True
            if _is_social_step(step):
                has_social = True
            if stype == "run_scenario":
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
    def empty(cls) -> StepIndex:
        return cls(
            entries=(),
            step_ids=frozenset(),
            has_interaction=False,
            has_verification=False,
            has_social=False,
            run_scenario_refs=(),
        )


_INTERACTION_PREFIXES = (
    "tap",
    "swipe",
    "input",
    "scroll",
    "launch_app",
    "open_url",
    "long_tap",
    "double_tap",
    "pinch",
    "drag",
    "key",
    "clear_app",
    "stop_app",
)
_SOCIAL_MARKERS = ("tap_fb", "fb_", "ig_", "tiktok_", "linkedin_")
_GENERIC_SOCIAL_TYPES = frozenset(
    {"content_interaction", "connection_request", "community_membership"}
)


def _is_interaction_type(step_type: str) -> bool:
    return any(step_type == p or step_type.startswith(p) for p in _INTERACTION_PREFIXES)


def _is_social_step(step: dict) -> bool:
    t = str(step.get("type") or "")
    if t in _GENERIC_SOCIAL_TYPES:
        return True
    if any(marker in t for marker in _SOCIAL_MARKERS):
        return True
    strategy = str(step.get("strategy") or "")
    return any(marker in strategy for marker in ("fb_", "ig_", "tiktok_", "linkedin_"))


def _walk_steps(
    steps: list[dict],
    *,
    path_prefix: str = "steps",
) -> Iterator[StepEntry]:
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        loc = f"{path_prefix}[{idx}]"
        step_id = step.get("id")
        sid = str(step_id) if step_id else None
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
                yield from _walk_steps(child_steps, path_prefix=f"{loc}.{key}")
