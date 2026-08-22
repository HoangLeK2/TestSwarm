"""Step handler registry and dispatch."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

# Step type → handler function
_STEP_HANDLERS: Dict[str, Callable[["ScenarioContext", Dict[str, Any], int], Dict[str, Any]]] = {}

# Step types removed by migration 111 (platform-neutral node names). These are NOT
# aliases — nothing dispatches. They exist only so an execution that was already
# in flight when the migration ran fails with an actionable message instead of a
# bare "unknown step type". Delete this table one release after 111 ships.
_RETIRED_STEP_TYPES: Dict[str, str] = {
    "facebook_session_gate": "platform_session_gate",
    "fb_select_people_profile": "social_select_target (target_type=person)",
    "fb_select_post_target": "social_select_target (target_type=post)",
    "fb_connect_visible_people": "social_connect_visible_people",
    "fb_find_comment_button": "social_find_comment_button",
    "fb_tap_comment_target": "social_tap_comment_target",
    "fb_apply_comment_filter": "social_apply_comment_filter",
    "fb_tap_comment_button": "social_open_comments",
    "tap_fb_comment_button": "social_open_comments",
    "fb_scan_posts_interact": "social_scan_posts_interact",
    "fb_open_author_from_post_match": "social_open_author_from_post_match",
    "fb_open_commenter_from_post_match": "social_open_commenter_from_post_match",
}


def register_step(*step_types: str):
    """Decorator: register a handler for one or more step types."""
    def decorator(fn):
        for t in step_types:
            _STEP_HANDLERS[t] = fn
        return fn
    return decorator


def dispatch_step(sc: "ScenarioContext", step: Dict[str, Any], step_idx: int) -> Dict[str, Any]:
    """Dispatch a step to its registered handler."""
    t = step.get("type", "")
    handler = _STEP_HANDLERS.get(t)
    if handler is None:
        replacement = _RETIRED_STEP_TYPES.get(t)
        if replacement is not None:
            msg = (
                f"step type {t!r} was removed; use {replacement}. "
                "This scenario predates migration 111 — re-run the migration or "
                "re-save the scenario to convert it."
            )
        else:
            msg = f"unknown step type: {t!r}"
        log.warning(f"[{sc.serial}] {msg}")
        return {"index": step_idx, "type": t, "ok": False, "message": msg}
    result = {"index": step_idx, "type": t, "ok": True}
    handler(sc, step, step_idx, result)
    return result


# Import all step handler modules to trigger registration
from tasks.scenario.steps import (  # noqa: E402, F401
    navigation,
    interaction,
    input,
    app_automation,
    platform_session,
    wait,
    extraction,
    persistence,
    control_flow,
    composition,
    social_actions,
    source_pool,
    candidate_lease,
    account_target_lease,
    account_graph,
)
