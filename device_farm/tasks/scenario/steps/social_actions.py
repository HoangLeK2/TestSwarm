"""Generic social action steps; platform-specific UI logic lives in adapters."""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict

from services.social_actions import get_social_action_adapter
from services.social_actions.contract import (
    SocialActionObservation,
    UnsupportedSocialAction,
)
from tasks.scenario.context import ScenarioContext
from tasks.scenario.steps import register_step

log = logging.getLogger(__name__)

_DEFAULT_ACTIONS = {
    "content_interaction": "like",
    "connection_request": "request",
    "community_membership": "join",
}


def _cancelled(sc: ScenarioContext) -> bool:
    return sc.cancel_event is not None and sc.cancel_event.is_set()


def _wait(sc: ScenarioContext, seconds: float) -> bool:
    if seconds <= 0:
        return _cancelled(sc)
    if sc.cancel_event is not None:
        return bool(sc.cancel_event.wait(seconds))
    time.sleep(seconds)
    return False


def _observe(
    sc: ScenarioContext,
    *,
    adapter: Any,
    action_type: str,
    action: str,
    near_bounds: tuple[int, int, int, int] | None = None,
) -> SocialActionObservation | None:
    xml = sc.device.hierarchy_xml(force_refresh=True)
    if not xml:
        return None
    return adapter.observe(
        action_type=action_type,
        action=action,
        hierarchy_xml=xml,
        near_bounds=near_bounds,
    )


def _poll_observation(
    sc: ScenarioContext,
    *,
    adapter: Any,
    action_type: str,
    action: str,
    timeout: float,
    poll: float,
    require_satisfied: bool,
    near_bounds: tuple[int, int, int, int] | None = None,
) -> SocialActionObservation | None:
    deadline = time.monotonic() + timeout
    last: SocialActionObservation | None = None
    while True:
        if _cancelled(sc):
            return None
        last = _observe(
            sc,
            adapter=adapter,
            action_type=action_type,
            action=action,
            near_bounds=near_bounds,
        )
        if last is not None:
            if require_satisfied and last.is_satisfied:
                return last
            if not require_satisfied and (
                last.is_satisfied or last.target_bounds is not None
            ):
                return last
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last
        if _wait(sc, min(poll, remaining)):
            return None


def _public_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: result[key]
        for key in (
            "type",
            "platform",
            "action",
            "outcome",
            "state",
            "action_performed",
        )
        if key in result
    }


def _save_result(
    sc: ScenarioContext,
    step: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    save_as = str(step.get("save_as") or "").strip()
    if not save_as:
        return
    payload = _public_payload(result)
    sc.var_ctx.set(save_as, payload)
    sc.ctx.setdefault("vars", {})[save_as] = payload
    result["save_as"] = save_as


def _fail(
    sc: ScenarioContext,
    step: Dict[str, Any],
    result: Dict[str, Any],
    *,
    outcome: str,
    message: str,
) -> None:
    result["ok"] = False
    result["outcome"] = outcome
    result["message"] = message
    _save_result(sc, step, result)


@register_step(
    "content_interaction",
    "connection_request",
    "community_membership",
)
def handle_social_action(
    sc: ScenarioContext,
    step: Dict[str, Any],
    idx: int,
    result: Dict[str, Any],
) -> None:
    """Act only on the current screen and verify the resulting UI state."""

    del idx
    action_type = str(step.get("type") or "")
    platform = str(step.get("platform") or "facebook").strip().casefold()
    action = str(step.get("action") or _DEFAULT_ACTIONS.get(action_type) or "").strip().casefold()
    timeout = max(0.1, float(step.get("timeout", 6.0) or 6.0))
    poll = max(0.05, float(step.get("poll", 0.4) or 0.4))
    verify_timeout = max(
        0.1,
        float(step.get("verify_timeout", 5.0) or 5.0),
    )
    settle_seconds = max(
        0.0,
        float(step.get("settle_seconds", 0.35) or 0.0),
    )
    result.update(
        {
            "platform": platform,
            "action": action,
            "action_performed": False,
        }
    )

    adapter = get_social_action_adapter(platform)
    if adapter is None:
        _fail(
            sc,
            step,
            result,
            outcome="unsupported_platform",
            message=f"{action_type}: platform {platform!r} is not supported",
        )
        return

    try:
        before = _poll_observation(
            sc,
            adapter=adapter,
            action_type=action_type,
            action=action,
            timeout=timeout,
            poll=poll,
            require_satisfied=False,
        )
    except UnsupportedSocialAction as exc:
        _fail(
            sc,
            step,
            result,
            outcome="unsupported_action",
            message=str(exc),
        )
        return
    except (ET.ParseError, OSError, RuntimeError, ValueError) as exc:
        _fail(
            sc,
            step,
            result,
            outcome="observation_failed",
            message=f"{action_type}: cannot inspect current screen: {exc}",
        )
        return

    if _cancelled(sc):
        _fail(
            sc,
            step,
            result,
            outcome="cancelled",
            message=f"{action_type}: cancelled",
        )
        result["cancelled"] = True
        return
    if before is None:
        _fail(
            sc,
            step,
            result,
            outcome="hierarchy_unavailable",
            message=f"{action_type}: hierarchy unavailable",
        )
        return
    if before.is_satisfied:
        result.update(
            {
                "outcome": "already_applied",
                "state": before.state,
                "message": f"{action_type}: already {before.state}",
            }
        )
        _save_result(sc, step, result)
        return
    if before.state == "ambiguous":
        _fail(
            sc,
            step,
            result,
            outcome="ambiguous_target",
            message=f"{action_type}: multiple matching targets are visible",
        )
        return
    if before.target_bounds is None:
        _fail(
            sc,
            step,
            result,
            outcome="target_not_found",
            message=f"{action_type}: action is not available on the current screen",
        )
        return

    left, top, right, bottom = before.target_bounds
    try:
        sc.device.tap((left + right) // 2, (top + bottom) // 2)
        result["action_performed"] = True
        result["_bounds"] = before.target_bounds
    except (OSError, RuntimeError, ValueError) as exc:
        _fail(
            sc,
            step,
            result,
            outcome="tap_failed",
            message=f"{action_type}: tap failed: {exc}",
        )
        return

    if _wait(sc, settle_seconds):
        _fail(
            sc,
            step,
            result,
            outcome="cancelled",
            message=f"{action_type}: cancelled",
        )
        result["cancelled"] = True
        return

    try:
        after = _poll_observation(
            sc,
            adapter=adapter,
            action_type=action_type,
            action=action,
            timeout=verify_timeout,
            poll=poll,
            require_satisfied=True,
            near_bounds=before.target_bounds,
        )
    except (ET.ParseError, OSError, RuntimeError, ValueError) as exc:
        _fail(
            sc,
            step,
            result,
            outcome="verification_failed",
            message=f"{action_type}: verification failed: {exc}",
        )
        return

    if after is None or not after.is_satisfied:
        _fail(
            sc,
            step,
            result,
            outcome="verification_failed",
            message=f"{action_type}: state did not change after tap",
        )
        return

    result.update(
        {
            "outcome": "applied",
            "state": after.state,
            "message": f"{action_type}: applied ({after.state})",
        }
    )
    _save_result(sc, step, result)
