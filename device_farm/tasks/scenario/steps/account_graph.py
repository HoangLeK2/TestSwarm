"""Scenario step that reads how many connections an account actually has.

Everything about growing an account depends on this number, and until now
nothing measured it. An account with no friends and one with five hundred need
opposite playbooks: the first has no mutual-friend signal, so the platform's own
suggestions are strangers; the second is exactly what those suggestions are for.

The step exposes the reading as scenario variables so `if_variable` can route
between playbooks, and records it so "is this account growing" becomes a
question with an answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tasks.scenario.steps import register_step
from tasks.scenario.steps.platform_resolution import resolve_supported_step_platform
from tasks.scenario.steps.social_actions import _u2_flow_with_recovery

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

_STEP_TYPE = "social_sync_connections"

FRIEND_COUNT_VAR = "ACCOUNT_FRIEND_COUNT"
STAGE_VAR = "ACCOUNT_STAGE"
COUNT_READ_VAR = "ACCOUNT_COUNT_READ"
DISPLAY_NAME_VAR = "ACCOUNT_DISPLAY_NAME"


def _set_var(sc: "ScenarioContext", name: str, value: Any) -> None:
    sc.var_ctx.set(name, value)
    sc.ctx.setdefault("vars", {})[name] = value


@register_step(_STEP_TYPE)
def handle_social_sync_connections(
    sc: "ScenarioContext",
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    platform = resolve_supported_step_platform(sc, step, _STEP_TYPE, result)
    if platform is None:
        return

    metric = str(step.get("metric") or "friends").strip().casefold()
    timeout = max(1.0, float(step.get("timeout", 8.0) or 8.0))

    try:
        flow_result = _u2_flow_with_recovery(
            sc,
            _STEP_TYPE,
            {"platform": platform, "metric": metric},
            timeout=timeout,
            priority="visible",
        )
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "outcome": "count_read_failed",
                "message": f"{_STEP_TYPE}: agent-boot flow failed: {exc}",
            }
        )
        return

    payload = (
        flow_result.get("value")
        if isinstance(flow_result.get("value"), dict)
        else flow_result
    )
    if not isinstance(payload, dict):
        result.update(
            {
                "ok": False,
                "outcome": "count_read_failed",
                "message": f"{_STEP_TYPE}: agent-boot returned an invalid payload",
            }
        )
        return

    result["platform"] = platform
    result["metric"] = metric
    result["resolver"] = payload

    # Both readings come out of the same hierarchy dump, so the name is recorded
    # even when the count is not on screen — a profile that scrolled past its
    # counter still says whose account this is.
    _apply_display_name(sc, step, platform, payload, result)

    if not payload.get("found"):
        # Not an error: the account profile simply is not on screen. Say so
        # loudly rather than leaving a stage decision to a missing number.
        _set_var(sc, COUNT_READ_VAR, False)
        result.update(
            {
                "ok": True,
                "outcome": str(payload.get("reason") or "count_not_visible"),
                "message": str(
                    payload.get("message")
                    or f"{_STEP_TYPE}: {metric} count is not visible on this screen"
                ),
                "count_read": False,
            }
        )
        return

    from services.account_graph import stage_for_friend_count

    count = max(0, int(payload.get("value") or 0))
    stage = stage_for_friend_count(count) if metric == "friends" else None

    _set_var(sc, COUNT_READ_VAR, True)
    if metric == "friends":
        _set_var(sc, FRIEND_COUNT_VAR, count)
        _set_var(sc, STAGE_VAR, stage)

    result.update(
        {
            "ok": True,
            "outcome": "read",
            "message": f"{_STEP_TYPE}: {metric}={count}",
            "count_read": True,
            "count": count,
            "stage": stage,
            "source": payload.get("source"),
            "evidence": payload.get("evidence"),
        }
    )

    if not _bool(step.get("persist", True)):
        return

    try:
        from services.account_graph_runtime import record_connection_count

        result["graph_metric"] = record_connection_count(
            sc=sc,
            step=step,
            platform=platform,
            metric=metric,
            value=count,
            source=str(payload.get("source") or "count_label"),
            evidence=payload.get("evidence"),
        )
    except Exception as exc:
        # A reading that cannot be stored is still a usable reading — the
        # scenario already has the variables it needs to branch.
        result["graph_metric_error"] = str(exc)


def _apply_display_name(
    sc: "ScenarioContext",
    step: dict[str, Any],
    platform: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Expose and store the profile owner's name, when the reader gave one.

    A missing name is never an error here: agent-boot refuses to guess when the
    header is ambiguous, and a refusal is the correct answer — recording the
    wrong person as the account's own name is the failure worth avoiding.
    """
    name = str(payload.get("display_name") or "").strip()
    if not name:
        result["display_name_reason"] = payload.get("display_name_reason")
        return

    _set_var(sc, DISPLAY_NAME_VAR, name)
    result["display_name"] = name
    if not _bool(step.get("persist", True)):
        return
    try:
        from services.account_graph_runtime import record_observed_display_name

        result["display_name_record"] = record_observed_display_name(
            sc=sc, step=step, platform=platform, display_name=name
        )
    except Exception as exc:
        # Same trade as the count: the scenario already has the variable, and
        # losing the write is not worth failing a step that read correctly.
        result["display_name_error"] = str(exc)


def _bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default
