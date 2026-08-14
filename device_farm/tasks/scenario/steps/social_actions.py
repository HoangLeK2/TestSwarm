"""Generic social action steps; platform-specific UI logic lives in adapters."""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any

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
_GLOBAL_VERIFY_CONTENT_ACTIONS = frozenset({"comment", "share"})
_DEBUG_HIERARCHY_XML_MAX_CHARS = 200_000
_DEFAULT_PEOPLE_TARGET_VAR = "_people_target"
_DEFAULT_POST_TARGET_VAR = "_post_target"
_EXACT_VAR_RE = re.compile(r"^\$\{(\w+)\}$")
_DEFAULT_PEOPLE_SELECTED_VAR = "PEOPLE_PROFILE_SELECTED"


def _cancelled(sc: ScenarioContext) -> bool:
    return sc.cancel_event is not None and sc.cancel_event.is_set()


def _wait(sc: ScenarioContext, seconds: float) -> bool:
    if seconds <= 0:
        return _cancelled(sc)
    if sc.cancel_event is not None:
        return bool(sc.cancel_event.wait(seconds))
    time.sleep(seconds)
    return False


def _resolve_keyword_list(sc: ScenarioContext, raw: Any, *, step_index: int) -> Any:
    if isinstance(raw, dict):
        var_name = str(raw.get("var") or raw.get("name") or "").strip()
        lookup_raw = getattr(sc.var_ctx, "lookup_raw", None)
        if var_name and callable(lookup_raw):
            value = lookup_raw(var_name, step_index=step_index)
            if isinstance(value, list):
                return value
    if isinstance(raw, str):
        match = _EXACT_VAR_RE.match(raw.strip())
        lookup_raw = getattr(sc.var_ctx, "lookup_raw", None)
        if match and callable(lookup_raw):
            value = lookup_raw(match.group(1), step_index=step_index)
            if isinstance(value, list):
                return value
    return sc.var_ctx.resolve(raw or [], step_index=step_index)


def _observe(
    sc: ScenarioContext,
    *,
    adapter: Any,
    action_type: str,
    action: str,
    near_bounds: tuple[int, int, int, int] | None = None,
    phase: str,
    debug_trace: dict[str, Any] | None = None,
) -> SocialActionObservation | None:
    xml = sc.device.hierarchy_xml(force_refresh=True)
    if not xml:
        return None
    if debug_trace is not None:
        debug_trace.update(
            {
                "phase": phase,
                "xml": xml,
                "xml_chars": len(xml),
            }
        )
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
    phase: str,
    debug_trace: dict[str, Any] | None = None,
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
            phase=phase,
            debug_trace=debug_trace,
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


def _public_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in (
            "type",
            "platform",
            "action",
            "outcome",
            "state",
            "action_performed",
            "action_bounds",
            "matched_label",
            "verified_target",
            "matched_common",
            "row_text",
            "batch",
            "target_count",
            "sent_count",
            "eligible_count",
            "screens_scanned",
            "scrolls",
            "dry_run",
            "verified_targets",
        )
        if key in result
    }


def _save_result(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
) -> None:
    save_as = str(step.get("save_as") or "").strip()
    if not save_as:
        return
    payload = _public_payload(result)
    sc.var_ctx.set(save_as, payload)
    sc.ctx.setdefault("vars", {})[save_as] = payload
    result["save_as"] = save_as


def _save_verified_target(
    sc: ScenarioContext,
    *,
    save_as: str,
    target: dict[str, Any],
) -> None:
    id_variable = (
        "CANDIDATE_ENTITY_ID"
        if target.get("target_type") == "person"
        else "TARGET_ENTITY_ID"
    )
    placeholder = f"${{{id_variable}}}"
    resolved_target_id = sc.var_ctx.resolve(placeholder)
    target_id = (
        ""
        if resolved_target_id == placeholder
        else str(resolved_target_id or "").strip()
    )
    if target_id and not target.get("target_id"):
        target["target_id"] = target_id
    sc.var_ctx.set(save_as, target)
    sc.ctx.setdefault("vars", {})[save_as] = target


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if raw in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return bool(value)


def _resolve_step_value(
    sc: ScenarioContext,
    step: dict[str, Any],
    key: str,
    default: Any,
    *,
    step_index: int,
) -> Any:
    var_key = f"{key}_var"
    if step.get(var_key):
        return sc.var_ctx.resolve(f"${{{step[var_key]}}}", step_index=step_index)
    return sc.var_ctx.resolve(step.get(key, default), step_index=step_index)


def _set_runtime_variable(sc: ScenarioContext, name: str, value: Any) -> None:
    clean = str(name or "").strip()
    if not clean:
        return
    sc.var_ctx.set(clean, value)
    sc.ctx.setdefault("vars", {})[clean] = value


def _save_unverified_target(
    sc: ScenarioContext,
    *,
    save_as: str,
    target_type: str,
    outcome: str,
    message: str,
) -> None:
    if not save_as:
        return
    sc.var_ctx.set(
        save_as,
        {
            "verified": False,
            "target_type": target_type,
            "outcome": outcome,
            "message": message,
        },
    )
    sc.ctx.setdefault("vars", {})[save_as] = sc.var_ctx.resolve(f"${{{save_as}}}")


def _lookup_verified_target(sc: ScenarioContext, name: str) -> dict[str, Any] | None:
    clean = name.strip()
    if clean.startswith("${") and clean.endswith("}"):
        clean = clean[2:-1].strip()
    value = sc.ctx.get("vars", {}).get(clean)
    return value if isinstance(value, dict) else None


def _lookup_runtime_dict(sc: ScenarioContext, name: str) -> dict[str, Any] | None:
    clean = str(name or "").strip()
    if clean.startswith("${") and clean.endswith("}"):
        clean = clean[2:-1].strip()
    value = sc.ctx.get("vars", {}).get(clean)
    if isinstance(value, dict):
        return value
    lookup_raw = getattr(sc.var_ctx, "lookup_raw", None)
    if callable(lookup_raw):
        raw_value = lookup_raw(clean)
        if isinstance(raw_value, dict):
            return raw_value
    return None


def _verified_target_summary(name: str, target: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "name": name,
        "target_type": target.get("target_type"),
        "confidence": target.get("confidence"),
        "source": target.get("source"),
    }
    target_id = target.get("target_id")
    if target_id:
        summary["target_id"] = target_id
    return summary


def _require_verified_target(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    required = str(step.get("require_verified_target") or "").strip()
    if not required:
        return True
    target = _lookup_verified_target(sc, required)
    if not target or target.get("verified") is not True:
        _fail(
            sc,
            step,
            result,
            outcome="target_not_verified",
            message=(
                f"{step.get('type')}: require_verified_target={required!r} "
                "was not verified by a target resolver"
            ),
        )
        return False
    result["verified_target"] = _verified_target_summary(required, target)
    return True


def _attach_debug_hierarchy(
    sc: ScenarioContext,
    result: dict[str, Any],
    *,
    action_type: str,
    outcome: str,
    debug_trace: dict[str, Any] | None,
) -> None:
    if not debug_trace:
        return
    xml = str(debug_trace.get("xml") or "")
    if not xml:
        return

    result["debug_hierarchy_phase"] = debug_trace.get("phase") or "unknown"
    result["debug_hierarchy_chars"] = len(xml)
    if len(xml) <= _DEBUG_HIERARCHY_XML_MAX_CHARS:
        result["debug_hierarchy_xml"] = xml
    else:
        result["debug_hierarchy_xml"] = xml[:_DEBUG_HIERARCHY_XML_MAX_CHARS]
        result["debug_hierarchy_truncated"] = True

    capture_dir = str(getattr(sc, "capture_dir", "") or "")
    if not capture_dir:
        return
    try:
        os.makedirs(capture_dir, exist_ok=True)
        phase = str(result["debug_hierarchy_phase"]).replace(os.sep, "_")
        safe_outcome = str(outcome or "fail").replace(os.sep, "_")
        filename = (
            f"social_action_{action_type}_{safe_outcome}_{phase}_{time.time_ns()}.xml"
        )
        path = os.path.join(capture_dir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(xml)
        result["debug_hierarchy_path"] = path
    except OSError as exc:
        log.debug("[%s] social action hierarchy dump failed: %s", sc.serial, exc)


def _verification_bounds(
    *,
    action_type: str,
    action: str,
    target_bounds: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    if (
        action_type == "content_interaction"
        and action in _GLOBAL_VERIFY_CONTENT_ACTIONS
    ):
        return None
    return target_bounds


def _account_action_failure_is_terminal(
    step: dict[str, Any], result: dict[str, Any]
) -> bool:
    from services.campaign.failure_classification import annotate_step_failure
    from services.execution.retry_policy import (
        is_step_failure_retryable,
        parse_step_retry_policy,
    )

    annotate_step_failure(result, step_type=str(step.get("type") or ""))
    attempt = max(1, int(step.get("_account_action_retry_attempt") or 1))
    policy = parse_step_retry_policy(step)
    if (
        policy is not None
        and attempt < policy.max_attempts
        and is_step_failure_retryable(result, policy)
    ):
        return False
    if policy is None and result.get("failure_class") == "u2_transient" and attempt < 3:
        return False

    outer = step.get("_account_action_outer_retry")
    if isinstance(outer, dict):
        outer_policy = parse_step_retry_policy({"retry": outer.get("retry")})
        outer_attempt = max(1, int(outer.get("attempt") or 1))
        if (
            outer_policy is not None
            and outer_attempt < outer_policy.max_attempts
            and is_step_failure_retryable(result, outer_policy)
        ):
            return False
    return True


def _record_unclaimed_social_action(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
    *,
    ledger_mode: str,
    ledger_identity: dict[str, str | None] | None,
    action_type: str,
    platform: str,
    action: str,
    ledger_target: dict[str, Any] | None = None,
) -> None:
    if ledger_mode not in {"observe", "enabled"} or ledger_identity is None:
        return
    try:
        from services.account_actions import (
            finalize_action,
            observe_action,
            prepare_action,
            stable_target,
        )

        target = ledger_target or stable_target(
            action=action, verified_target=result.get("verified_target")
        )
        outcome = str(result.get("outcome") or "precondition_failed")
        if ledger_mode == "observe":
            result["account_action_ledger"] = observe_action(
                identity=ledger_identity,
                action_type=action_type,
                platform=platform,
                target=target,
                outcome=outcome,
            )
            return

        claim = prepare_action(
            identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            target=target,
            action_id=str(step.get("account_action_id") or "").strip() or None,
        )
        if claim.get("claimed") is False:
            result["account_action_ledger"] = claim
            return
        result["account_action_ledger"] = finalize_action(
            claim=claim,
            succeeded=False,
            terminal=_account_action_failure_is_terminal(step, result),
            reason=outcome,
            result=result,
        )
    except Exception as exc:
        result["account_action_ledger_error"] = str(exc)
        log.warning("[%s] unclaimed account action recording failed: %s", sc.serial, exc)


def _fail(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
    *,
    outcome: str,
    message: str,
    observation: SocialActionObservation | None = None,
    debug_trace: dict[str, Any] | None = None,
) -> None:
    result["ok"] = False
    result["outcome"] = outcome
    result["message"] = message
    if observation is not None:
        result["observation_state"] = observation.state
        if observation.matched_label:
            result["matched_label"] = observation.matched_label
        if observation.target_bounds is not None:
            result["observed_bounds"] = observation.target_bounds
    _attach_debug_hierarchy(
        sc,
        result,
        action_type=str(step.get("type") or "social_action"),
        outcome=outcome,
        debug_trace=debug_trace,
    )
    _release_unperformed_candidate_lease(sc, step, result)
    _save_result(sc, step, result)


def _release_unperformed_candidate_lease(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if step.get("type") != "connection_request" or result.get("action_performed"):
        return
    lease_token = str(step.get("candidate_lease_token") or "").strip()
    external_entity_id = str(step.get("candidate_entity_id") or "").strip()
    if not lease_token or not external_entity_id:
        return
    if result.get("_candidate_lease_release_attempted"):
        return
    result["_candidate_lease_release_attempted"] = True
    try:
        from services.account_actions import resolve_action_identity
        from services.facebook_candidate_runtime import release_connection_candidate

        identity = resolve_action_identity(
            step=step,
            scenario=sc.scenario,
            variables=sc.ctx.get("vars", {}),
            execution_id=sc.execution_id,
        )
        result["candidate_lease_release"] = release_connection_candidate(
            identity=identity,
            external_entity_id=external_entity_id,
            lease_token=lease_token,
        )
    except Exception as exc:
        log.warning(
            "[%s] failed to release unperformed candidate lease: %s",
            sc.serial,
            exc,
        )


def _handle_agent_boot_target_resolver(
    sc: ScenarioContext,
    result: dict[str, Any],
    *,
    flow_name: str,
    params: dict[str, Any],
    timeout: float,
    save_as: str,
    target_type: str,
    success_message: str,
    unavailable_message: str,
    invalid_message: str,
    not_verified_message: str,
) -> None:
    result.update(
        {
            "target_type": target_type,
            "save_as": save_as,
            "action_performed": False,
        }
    )
    try:
        flow_result = sc.device.u2_flow(
            flow_name,
            params,
            timeout=timeout,
            priority="visible",
        )
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "outcome": "target_resolver_unavailable",
                "message": f"{unavailable_message}: {exc}",
            }
        )
        return

    target = (
        flow_result.get("value")
        if isinstance(flow_result.get("value"), dict)
        else flow_result
    )
    if not isinstance(target, dict):
        result.update(
            {
                "ok": False,
                "outcome": "target_resolver_failed",
                "message": invalid_message,
            }
        )
        return

    target.setdefault("target_type", target_type)
    target.setdefault("source", "agent_boot")
    if target.get("verified") is not True:
        result.update(
            {
                "ok": False,
                "outcome": str(target.get("reason") or "target_not_verified"),
                "message": str(target.get("message") or not_verified_message),
                "resolver": target,
            }
        )
        return

    target["verified"] = True
    _save_verified_target(sc, save_as=save_as, target=target)
    result.update(
        {
            "ok": True,
            "outcome": "target_verified",
            "message": success_message,
            "action_performed": True,
            "verified_target": _verified_target_summary(save_as, target),
            "resolver": {
                "confidence": target.get("confidence"),
                "matched_keywords": target.get("matched_keywords"),
                "selected_bounds": target.get("selected_bounds"),
                "action_bounds": target.get("action_bounds"),
                "candidate_count": target.get("candidate_count"),
            },
        }
    )


def _defer_unverified_connection_candidate(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    lease_token = str(
        sc.var_ctx.resolve(step.get("candidate_lease_token") or "")
        or step.get("candidate_lease_token")
        or ""
    ).strip()
    external_entity_id = str(
        sc.var_ctx.resolve(step.get("candidate_entity_id") or "")
        or step.get("candidate_entity_id")
        or ""
    ).strip()
    if not lease_token or not external_entity_id:
        result["candidate_skip"] = {
            "deferred": False,
            "reason": "missing_candidate_lease",
        }
        return False

    defer_hours = max(0.1, float(step.get("skip_candidate_defer_hours", 24) or 24))
    next_eligible_at = datetime.now(UTC) + timedelta(hours=defer_hours)
    try:
        from services.account_actions import resolve_action_identity
        from services.facebook_candidate_runtime import defer_connection_candidate

        identity = resolve_action_identity(
            step=step,
            scenario=sc.scenario,
            variables=sc.ctx.get("vars", {}),
            execution_id=sc.execution_id,
        )
        result["candidate_skip"] = defer_connection_candidate(
            identity=identity,
            external_entity_id=external_entity_id,
            lease_token=lease_token,
            next_eligible_at=next_eligible_at,
            note=(
                "runtime skipped: Facebook People profile was not uniquely "
                f"verified ({result.get('outcome')})"
            ),
        )
        result["candidate_skip"]["deferred"] = True
        return True
    except Exception as exc:
        log.warning("[%s] failed to defer unverified candidate lease: %s", sc.serial, exc)
        result["candidate_skip"] = {
            "deferred": False,
            "reason": "defer_failed",
            "message": str(exc),
        }
        return False


@register_step(
    "fb_select_people_profile",
)
def handle_fb_select_people_profile(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    """Delegate Facebook people target selection to agent-boot and save proof."""

    del idx
    save_as = str(step.get("save_as") or _DEFAULT_PEOPLE_TARGET_VAR).strip()
    success_var = str(
        step.get("save_success_as") or _DEFAULT_PEOPLE_SELECTED_VAR
    ).strip()
    _set_runtime_variable(sc, success_var, False)
    _save_unverified_target(
        sc,
        save_as=save_as,
        target_type="person",
        outcome="target_not_checked",
        message="fb_select_people_profile: target has not been verified",
    )
    _handle_agent_boot_target_resolver(
        sc,
        result,
        flow_name="fb_select_people_profile",
        params={
            "search": step.get("search"),
            "display_name": step.get("display_name") or step.get("row_text"),
            "required_keywords": step.get("required_keywords") or [],
            "optional_keywords": step.get("optional_keywords") or [],
            "forbidden_keywords": step.get("forbidden_keywords") or [],
            "min_score": step.get("min_score", 80),
            "require_unique": step.get("require_unique", True),
            "profile_wait_s": step.get("profile_wait_s", 1.0),
        },
        timeout=max(1.0, float(step.get("timeout", 12.0) or 12.0)),
        save_as=save_as,
        target_type="person",
        success_message="fb_select_people_profile: verified people profile is open",
        unavailable_message="fb_select_people_profile: agent-boot flow failed",
        invalid_message="fb_select_people_profile: agent-boot returned an invalid payload",
        not_verified_message="fb_select_people_profile: no unique verified people target",
    )
    if result.get("ok") is True and result.get("outcome") == "target_verified":
        _set_runtime_variable(sc, success_var, True)
        return

    _set_runtime_variable(sc, success_var, False)
    _save_unverified_target(
        sc,
        save_as=save_as,
        target_type="person",
        outcome=str(result.get("outcome") or "target_not_verified"),
        message=str(result.get("message") or "fb_select_people_profile failed"),
    )
    if not bool(step.get("skip_candidate_on_not_verified", False)):
        return
    if result.get("outcome") == "target_resolver_unavailable":
        return

    original_outcome = str(result.get("outcome") or "target_not_verified")
    original_message = str(result.get("message") or "")
    deferred = _defer_unverified_connection_candidate(sc, step, result)
    if not deferred:
        return
    result.update(
        {
            "ok": True,
            "outcome": "candidate_skipped",
            "message": (
                "fb_select_people_profile: skipped candidate because no unique "
                f"verified People profile was found ({original_outcome}: "
                f"{original_message})"
            ),
        }
    )


@register_step("fb_connect_visible_people")
def handle_fb_connect_visible_people(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    """Click one visible Add Friend row only when the UI exposes common context."""

    platform = str(step.get("platform") or "facebook").strip().casefold()
    if platform != "facebook":
        _fail(
            sc,
            step,
            result,
            outcome="unsupported_platform",
            message=f"fb_connect_visible_people: unsupported {platform!r}",
        )
        return

    min_score = sc.var_ctx.resolve(step.get("min_score", 40), step_index=idx)
    common_keywords = sc.var_ctx.resolve(
        step.get("common_keywords") or [], step_index=idx
    )
    forbidden_keywords = sc.var_ctx.resolve(
        step.get("forbidden_keywords") or [], step_index=idx
    )
    target_count = sc.var_ctx.resolve(
        step.get("target_count", step.get("batch_size", 1)), step_index=idx
    )
    max_scrolls = sc.var_ctx.resolve(step.get("max_scrolls", 0), step_index=idx)
    open_surface = sc.var_ctx.resolve(step.get("open_surface", False), step_index=idx)
    dry_run = sc.var_ctx.resolve(step.get("dry_run", False), step_index=idx)
    timeout = max(
        1.0,
        float(sc.var_ctx.resolve(step.get("timeout", 8.0), step_index=idx) or 8.0),
    )
    try:
        flow_result = sc.device.u2_flow(
            "fb_connect_visible_people",
            {
                "min_score": max(0, int(min_score or 40)),
                "require_common": _bool_value(
                    sc.var_ctx.resolve(
                        step.get("require_common", True), step_index=idx
                    ),
                    True,
                ),
                "common_keywords": common_keywords or [],
                "forbidden_keywords": forbidden_keywords or [],
                "verify_wait_s": step.get("verify_wait_s", 0.8),
                "open_surface": _bool_value(open_surface, False),
                "target_count": max(1, int(target_count or 1)),
                "max_scrolls": max(0, int(max_scrolls or 0)),
                "no_more_common_limit": max(
                    1,
                    int(
                        sc.var_ctx.resolve(
                            step.get("no_more_common_limit", 3), step_index=idx
                        )
                        or 3
                    ),
                ),
                "dry_run": _bool_value(dry_run, False),
                "scroll_wait_s": step.get("scroll_wait_s", 0.7),
                "surface_wait_s": step.get("surface_wait_s", 0.8),
                "stop_on_unverified": _bool_value(
                    sc.var_ctx.resolve(
                        step.get("stop_on_unverified", True), step_index=idx
                    ),
                    True,
                ),
            },
            timeout=timeout,
            priority="visible",
        )
    except Exception as exc:
        _fail(
            sc,
            step,
            result,
            outcome="target_resolver_unavailable",
            message=f"fb_connect_visible_people: agent-boot flow failed: {exc}",
        )
        return

    target = (
        flow_result.get("value")
        if isinstance(flow_result.get("value"), dict)
        else flow_result
    )
    if not isinstance(target, dict):
        _fail(
            sc,
            step,
            result,
            outcome="target_resolver_failed",
            message="fb_connect_visible_people: agent-boot returned an invalid payload",
        )
        return

    if target.get("batch") is True:
        sent_targets = [
            item for item in (target.get("sent") or []) if isinstance(item, dict)
        ]
        verified_targets = [
            {
                "verified": True,
                "target_type": "person",
                "target_id": item.get("target_id"),
                "source": item.get("source") or "visible_people_surface",
                "confidence": item.get("confidence"),
                "name": item.get("display_name")
                or item.get("row_text")
                or "visible_person",
                "mutual_count": item.get("mutual_count", 0),
                "matched_common": item.get("matched_common") or [],
                "action_bounds": item.get("action_bounds"),
            }
            for item in sent_targets
        ]
        sent_count = len(verified_targets)
        reason = str(target.get("reason") or "")
        dry_run_result = bool(target.get("dry_run") is True)
        benign_empty = reason in {"no_common_connectable_people", "dry_run"}
        if sent_count <= 0 and not benign_empty and target.get("verified") is not True:
            result.update(
                {
                    "ok": False,
                    "outcome": reason or "target_resolver_failed",
                    "message": str(
                        target.get("message")
                        or "fb_connect_visible_people: batch resolver failed"
                    ),
                    "action_performed": False,
                    "batch": True,
                    "target_count": target.get("target_count"),
                    "sent_count": 0,
                    "eligible_count": target.get("eligible_count", 0),
                    "screens_scanned": target.get("screens_scanned", 0),
                    "scrolls": target.get("scrolls", 0),
                    "dry_run": dry_run_result,
                    "resolver": target,
                }
            )
            _save_result(sc, step, result)
            return

        result.update(
            {
                "ok": True,
                "outcome": "applied" if sent_count > 0 else (reason or "no_action"),
                "message": str(
                    target.get("message")
                    or f"fb_connect_visible_people: sent {sent_count} visible requests"
                ),
                "action_performed": sent_count > 0,
                "state": "request_pending" if sent_count > 0 else None,
                "batch": True,
                "target_count": target.get("target_count"),
                "sent_count": sent_count,
                "eligible_count": target.get("eligible_count", 0),
                "screens_scanned": target.get("screens_scanned", 0),
                "scrolls": target.get("scrolls", 0),
                "dry_run": dry_run_result,
                "verified_targets": verified_targets,
                "resolver": target,
            }
        )
        if verified_targets:
            first_target = verified_targets[0]
            result["verified_target"] = first_target
            result["action_bounds"] = first_target.get("action_bounds")
            result["_bounds"] = first_target.get("action_bounds")

        ledger_mode = (
            os.environ.get("ACCOUNT_ACTION_LEDGER_MODE", "disabled").strip().lower()
        )
        reserved_action_id = str(step.get("account_action_id") or "").strip()
        if reserved_action_id:
            ledger_mode = "enabled"
        if sent_count > 0 and ledger_mode in {"observe", "enabled"}:
            try:
                from services.account_actions import (
                    finalize_action,
                    observe_action,
                    prepare_action,
                    resolve_action_identity,
                )

                identity = resolve_action_identity(
                    step=step,
                    scenario=sc.scenario,
                    variables=sc.ctx.get("vars", {}),
                    execution_id=sc.execution_id,
                )
                ledger_records: list[dict[str, Any]] = []
                for offset, verified_target in enumerate(verified_targets):
                    ledger_target = {
                        "action": "request",
                        "target_type": "person",
                        "target_id": verified_target.get("target_id"),
                        "source": verified_target.get("source"),
                        "name": verified_target.get("name"),
                    }
                    if ledger_mode == "observe":
                        ledger_records.append(
                            observe_action(
                                identity=identity,
                                action_type="connection_request",
                                platform="facebook",
                                target=ledger_target,
                                outcome="applied",
                            )
                        )
                        continue
                    claim = prepare_action(
                        identity=identity,
                        action_type="connection_request",
                        platform="facebook",
                        target=ledger_target,
                        action_id=reserved_action_id if offset == 0 else None,
                    )
                    if claim.get("claimed") is False:
                        ledger_records.append(claim)
                        continue
                    ledger_records.append(
                        finalize_action(
                            claim=claim,
                            succeeded=True,
                            terminal=True,
                            reason="verified_visible_common_context",
                            result={
                                **result,
                                "verified_target": verified_target,
                            },
                        )
                    )
                result["account_action_ledgers"] = ledger_records
                if ledger_records:
                    result["account_action_ledger"] = ledger_records[0]
            except Exception as exc:
                _fail(
                    sc,
                    step,
                    result,
                    outcome="ledger_prepare_failed",
                    message=(
                        "fb_connect_visible_people: durable batch action ledger "
                        f"failed: {exc}"
                    ),
                )
                return

        _save_result(sc, step, result)
        return

    if target.get("verified") is not True:
        result.update(
            {
                "ok": target.get("reason") == "no_common_connectable_people",
                "outcome": str(target.get("reason") or "target_not_verified"),
                "message": str(
                    target.get("message")
                    or "fb_connect_visible_people: no eligible visible row"
                ),
                "action_performed": False,
                "resolver": target,
            }
        )
        _save_result(sc, step, result)
        return

    verified_target = {
        "verified": True,
        "target_type": "person",
        "target_id": target.get("target_id"),
        "source": target.get("source") or "visible_people_surface",
        "confidence": target.get("confidence"),
        "name": target.get("display_name") or target.get("row_text") or "visible_person",
    }
    result.update(
        {
            "ok": True,
            "outcome": "applied",
            "message": "fb_connect_visible_people: sent request from common-context row",
            "action_performed": True,
            "state": "request_pending",
            "verified_target": verified_target,
            "action_bounds": target.get("action_bounds"),
            "_bounds": target.get("action_bounds"),
            "matched_common": target.get("matched_common") or [],
            "row_text": target.get("row_text") or "",
            "resolver": target,
        }
    )

    ledger_mode = (
        os.environ.get("ACCOUNT_ACTION_LEDGER_MODE", "disabled").strip().lower()
    )
    reserved_action_id = str(step.get("account_action_id") or "").strip()
    if reserved_action_id:
        ledger_mode = "enabled"
    if ledger_mode in {"observe", "enabled"}:
        try:
            from services.account_actions import (
                observe_action,
                prepare_action,
                resolve_action_identity,
            )

            identity = resolve_action_identity(
                step=step,
                scenario=sc.scenario,
                variables=sc.ctx.get("vars", {}),
                execution_id=sc.execution_id,
            )
            ledger_target = {
                "action": "request",
                "target_type": "person",
                "target_id": verified_target.get("target_id"),
                "source": verified_target.get("source"),
                "name": verified_target.get("name"),
            }
            if ledger_mode == "observe":
                result["account_action_ledger"] = observe_action(
                    identity=identity,
                    action_type="connection_request",
                    platform="facebook",
                    target=ledger_target,
                    outcome="applied",
                )
            else:
                claim = prepare_action(
                    identity=identity,
                    action_type="connection_request",
                    platform="facebook",
                    target=ledger_target,
                    action_id=reserved_action_id or None,
                )
                if claim.get("claimed") is False:
                    result["account_action_ledger"] = claim
                else:
                    _finalize_social_action_ledger(
                        sc,
                        step,
                        result,
                        claim,
                        succeeded=True,
                        reason="verified_visible_common_context",
                    )
        except Exception as exc:
            _fail(
                sc,
                step,
                result,
                outcome="ledger_prepare_failed",
                message=f"fb_connect_visible_people: durable action ledger failed: {exc}",
            )
            return

    _save_result(sc, step, result)


def _handle_social_scan_posts_interact(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
    *,
    flow_name: str,
    step_name: str,
) -> None:
    """Delegate visible social post scanning and interaction to agent-boot."""

    keywords_source = (
        {"var": step.get("keywords_var")}
        if step.get("keywords_var")
        else step.get("keywords")
    )
    keywords = _resolve_keyword_list(sc, keywords_source or [], step_index=idx)
    comment_text = sc.var_ctx.resolve(step.get("comment_text") or "", step_index=idx)
    target_count = _resolve_step_value(
        sc,
        step,
        "target_count",
        step.get("batch_size", 1),
        step_index=idx,
    )
    max_scrolls = _resolve_step_value(
        sc,
        step,
        "max_scrolls",
        0,
        step_index=idx,
    )
    timeout = max(
        1.0,
        float(
            _resolve_step_value(
                sc,
                step,
                "timeout",
                step.get("scan_timeout_seconds", 30.0),
                step_index=idx,
            )
            or 30.0
        ),
    )
    scan_timeout = _resolve_step_value(
        sc,
        step,
        "scan_timeout_seconds",
        timeout,
        step_index=idx,
    )
    timeout = max(timeout, float(scan_timeout or timeout))
    match_mode = _resolve_step_value(
        sc,
        step,
        "match_mode",
        "any",
        step_index=idx,
    )
    scroll_x_ratio = _resolve_step_value(
        sc,
        step,
        "scroll_x_ratio",
        0.5,
        step_index=idx,
    )
    try:
        selector_config = {
            key: step[key]
            for key in (
                "like_terms",
                "liked_terms",
                "comment_terms",
                "comment_input_terms",
                "comment_submit_terms",
                "overlay_close_terms",
                "forbidden_context_terms",
                "comment_input_classes",
                "input_classes",
            )
            if key in step
        }
        flow_result = sc.device.u2_flow(
            flow_name,
            {
                "keywords": keywords or [],
                "match_mode": match_mode or "any",
                "comment_text": comment_text or "",
                "target_count": max(1, int(target_count or 1)),
                "max_scrolls": max(0, int(max_scrolls or 0)),
                "scan_timeout_seconds": max(1.0, float(scan_timeout or timeout)),
                "scroll_x_ratio": scroll_x_ratio,
                "scroll_y1_ratio": step.get("scroll_y1_ratio", 0.78),
                "scroll_y2_ratio": step.get("scroll_y2_ratio", 0.34),
                "scroll_duration_s": step.get("scroll_duration_s", 0.45),
                "scroll_wait_s": step.get("scroll_wait_s", 0.7),
                "comment_wait_s": step.get("comment_wait_s", 0.8),
                "submit_wait_s": step.get("submit_wait_s", 0.6),
                "require_comment": _bool_value(step.get("require_comment"), True),
                "like_post": _bool_value(step.get("like_post"), True),
                **selector_config,
            },
            timeout=timeout,
            priority="visible",
        )
    except Exception as exc:
        _fail(
            sc,
            step,
            result,
            outcome="agent_boot_flow_failed",
            message=f"{step_name}: agent-boot flow failed: {exc}",
        )
        return

    target = (
        flow_result.get("value")
        if isinstance(flow_result.get("value"), dict)
        else flow_result
    )
    if not isinstance(target, dict):
        _fail(
            sc,
            step,
            result,
            outcome="agent_boot_flow_invalid",
            message=f"{step_name}: agent-boot returned an invalid payload",
        )
        return

    interacted_count = int(target.get("interacted_count") or 0)
    no_match = target.get("reason") == "no_matching_post"
    result.update(
        {
            "ok": True if no_match else target.get("verified") is True,
            "outcome": (
                "applied"
                if interacted_count > 0
                else str(target.get("reason") or "no_action")
            ),
            "message": str(
                target.get("message")
                or f"{step_name}: interacted with {interacted_count} posts"
            ),
            "action_performed": interacted_count > 0,
            "batch": True,
            "target_type": "post",
            "target_count": target.get("target_count"),
            "interacted_count": interacted_count,
            "liked_count": target.get("liked_count", 0),
            "commented_count": target.get("commented_count", 0),
            "candidate_count": target.get("candidate_count", 0),
            "screens_scanned": target.get("screens_scanned", 0),
            "scrolls": target.get("scrolls", 0),
            "resolver": target,
        }
    )
    if result["ok"] is not True:
        result["ok"] = False
    save_as = str(step.get("save_as") or "").strip()
    _save_result(sc, step, result)
    if save_as:
        _set_runtime_variable(sc, save_as, target)


@register_step("social_scan_posts_interact")
def handle_social_scan_posts_interact(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    _handle_social_scan_posts_interact(
        sc,
        step,
        idx,
        result,
        flow_name="social_scan_posts_interact",
        step_name="social_scan_posts_interact",
    )


@register_step("fb_scan_posts_interact")
def handle_fb_scan_posts_interact(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    _handle_social_scan_posts_interact(
        sc,
        step,
        idx,
        result,
        flow_name="fb_scan_posts_interact",
        step_name="fb_scan_posts_interact",
    )


@register_step(
    "social_open_author_from_post_match",
    "fb_open_author_from_post_match",
    "social_open_commenter_from_post_match",
    "fb_open_commenter_from_post_match",
)
def handle_social_open_author_from_post_match(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    """Open and verify a profile from a previously matched post action."""

    is_commenter = str(step.get("type") or "").startswith(
        ("social_open_commenter", "fb_open_commenter")
    )
    step_name = (
        "social_open_commenter_from_post_match"
        if is_commenter
        else "social_open_author_from_post_match"
    )
    flow_name = step_name
    source_var = str(step.get("source_var") or "_post_scan").strip()
    save_as = str(step.get("save_as") or _DEFAULT_PEOPLE_TARGET_VAR).strip()
    success_var = str(
        step.get("save_success_as") or _DEFAULT_PEOPLE_SELECTED_VAR
    ).strip()
    opened_var = str(
        step.get("save_opened_as")
        or ("COMMENTER_PROFILE_OPENED" if is_commenter else "AUTHOR_PROFILE_OPENED")
    ).strip()
    sheet_opened_var = str(step.get("save_sheet_opened_as") or "COMMENT_SHEET_OPENED").strip()
    platform = str(step.get("platform") or "facebook").strip().casefold()
    _set_runtime_variable(sc, success_var, False)
    _set_runtime_variable(sc, opened_var, False)
    if is_commenter:
        _set_runtime_variable(sc, sheet_opened_var, False)
    _save_unverified_target(
        sc,
        save_as=save_as,
        target_type="person",
        outcome="target_not_checked",
        message=f"{step_name}: target has not been verified",
    )

    source = _lookup_runtime_dict(sc, source_var)
    actions = source.get("actions") if isinstance(source, dict) else None
    if not isinstance(actions, list):
        result.update(
            {
                "ok": True,
                "outcome": "source_actions_missing",
                "message": (
                    f"{step_name}: source scan has no actions to inspect"
                ),
                "action_performed": False,
                "source_var": source_var,
            }
        )
        return

    try:
        action_index = int(
            sc.var_ctx.resolve(step.get("action_index", 0), step_index=idx) or 0
        )
    except (TypeError, ValueError):
        action_index = 0
    if action_index < 0 or action_index >= len(actions):
        result.update(
            {
                "ok": True,
                "outcome": "source_action_index_missing",
                "message": (
                    f"{step_name}: requested post action index is not available"
                ),
                "action_performed": False,
                "source_var": source_var,
                "source_action_index": action_index,
                "source_action_count": len(actions),
            }
        )
        return

    action = actions[action_index]
    if not isinstance(action, dict) or action.get("verified") is not True:
        result.update(
            {
                "ok": True,
                "outcome": "source_action_not_verified",
                "message": (
                    f"{step_name}: selected post action was not verified"
                ),
                "action_performed": False,
                "source_var": source_var,
                "source_action_index": action_index,
            }
        )
        return

    required_keywords = _resolve_keyword_list(
        sc,
        {"var": step.get("required_keywords_var")}
        if step.get("required_keywords_var")
        else step.get("required_keywords"),
        step_index=idx,
    )
    optional_keywords = _resolve_keyword_list(
        sc,
        {"var": step.get("optional_keywords_var")}
        if step.get("optional_keywords_var")
        else step.get("optional_keywords"),
        step_index=idx,
    )
    forbidden_keywords = _resolve_keyword_list(
        sc,
        {"var": step.get("forbidden_keywords_var")}
        if step.get("forbidden_keywords_var")
        else step.get("forbidden_keywords"),
        step_index=idx,
    )

    timeout = max(1.0, float(step.get("timeout", 12.0) or 12.0))
    try:
        flow_result = sc.device.u2_flow(
            flow_name,
            {
                "platform": platform,
                "action": action,
                "search": step.get("search") or action.get("author_label"),
                "display_name": step.get("display_name") or action.get("author_label"),
                "required_keywords": required_keywords or [],
                "optional_keywords": optional_keywords or [],
                "forbidden_keywords": forbidden_keywords or [],
                "min_score": step.get("min_score", 80),
                "profile_wait_s": step.get("profile_wait_s", 1.0),
                "comment_wait_s": step.get("comment_wait_s", 1.0),
                "max_commenters": step.get("max_commenters", 5),
            },
            timeout=timeout,
            priority="visible",
        )
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "outcome": "target_resolver_unavailable",
                "message": (
                    f"{step_name}: agent-boot flow failed: {exc}"
                ),
                "action_performed": False,
            }
        )
        return

    target = (
        flow_result.get("value")
        if isinstance(flow_result.get("value"), dict)
        else flow_result
    )
    if not isinstance(target, dict):
        result.update(
            {
                "ok": False,
                "outcome": "target_resolver_failed",
                "message": (
                    f"{step_name}: agent-boot returned an invalid payload"
                ),
                "action_performed": False,
            }
        )
        return

    target.setdefault("target_type", "person")
    target.setdefault("source", "matched_feed_post_author")
    result.update(
        {
            "ok": target.get("verified") is True,
            "outcome": (
                    "target_verified"
                    if target.get("verified") is True
                    else str(target.get("reason") or "target_not_verified")
            ),
            "message": str(
                target.get("message")
                or (
                    "social_open_author_from_post_match: verified author profile is open"
                    if target.get("verified") is True and not is_commenter
                    else (
                        "social_open_commenter_from_post_match: verified commenter profile is open"
                        if target.get("verified") is True
                        else f"{step_name}: profile not verified"
                    )
                )
            ),
            "action_performed": target.get("verified") is True,
            "target_type": "person",
            "platform": platform,
            "source_var": source_var,
            "source_action_index": action_index,
            "source_post_target_id": action.get("target_id"),
            "profile_opened": target.get("profile_opened") is True,
            "resolver": target,
        }
    )
    _set_runtime_variable(sc, opened_var, target.get("profile_opened") is True)
    if is_commenter:
        _set_runtime_variable(sc, sheet_opened_var, target.get("comment_sheet_opened") is True)
    if target.get("verified") is True:
        target["verified"] = True
        _save_verified_target(sc, save_as=save_as, target=target)
        _set_runtime_variable(sc, success_var, True)
        result["verified_target"] = _verified_target_summary(save_as, target)
        result["action_bounds"] = target.get("action_bounds")
        result["_bounds"] = target.get("action_bounds")
    else:
        result["ok"] = True
        _set_runtime_variable(sc, success_var, False)
        _save_unverified_target(
            sc,
            save_as=save_as,
            target_type="person",
            outcome=str(result.get("outcome") or "target_not_verified"),
            message=str(result.get("message") or "author profile not verified"),
        )


@register_step(
    "fb_select_post_target",
)
def handle_fb_select_post_target(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    """Delegate Facebook post target selection to agent-boot and save proof."""

    del idx
    _handle_agent_boot_target_resolver(
        sc,
        result,
        flow_name="fb_select_post_target",
        params={
            "search": step.get("search"),
            "display_text": step.get("display_text") or step.get("row_text"),
            "required_keywords": step.get("required_keywords") or [],
            "optional_keywords": step.get("optional_keywords") or [],
            "forbidden_keywords": step.get("forbidden_keywords") or [],
            "min_score": step.get("min_score", 80),
            "require_unique": step.get("require_unique", True),
            "current_detail": step.get("current_detail", False),
            "detail_wait_s": step.get("detail_wait_s", 1.0),
        },
        timeout=max(1.0, float(step.get("timeout", 12.0) or 12.0)),
        save_as=str(step.get("save_as") or _DEFAULT_POST_TARGET_VAR).strip(),
        target_type="post",
        success_message="fb_select_post_target: verified post target is open",
        unavailable_message="fb_select_post_target: agent-boot flow failed",
        invalid_message="fb_select_post_target: agent-boot returned an invalid payload",
        not_verified_message="fb_select_post_target: no unique verified post target",
    )


@register_step(
    "content_interaction",
    "connection_request",
    "community_membership",
)
def handle_social_action(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    """Act only on the current screen and verify the resulting UI state."""

    action_type = str(step.get("type") or "")
    platform = str(step.get("platform") or "facebook").strip().casefold()
    action = (
        str(step.get("action") or _DEFAULT_ACTIONS.get(action_type) or "")
        .strip()
        .casefold()
    )
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
    require_completion = bool(step.get("require_completion", False))
    completion_steps = step.get("completion_steps") or []
    completion_verify = step.get("completion_verify")
    if require_completion and (
        not completion_steps
        or (action in _GLOBAL_VERIFY_CONTENT_ACTIONS and not completion_verify)
    ):
        _fail(
            sc,
            step,
            result,
            outcome="completion_not_configured",
            message=(
                f"{action_type}: require_completion needs explicit "
                "completion_steps and completion_verify"
            ),
        )
        return
    ledger_mode = (
        os.environ.get("ACCOUNT_ACTION_LEDGER_MODE", "disabled").strip().lower()
    )
    reserved_action_id = str(step.get("account_action_id") or "").strip()
    if reserved_action_id:
        ledger_mode = "enabled"
    ledger_identity = None
    ledger_target = None
    ledger_claim = None
    ledger_identity_error = None
    if ledger_mode in {"observe", "enabled"}:
        from services.account_actions import resolve_action_identity

        try:
            ledger_identity = resolve_action_identity(
                step=step,
                scenario=sc.scenario,
                variables=sc.ctx.get("vars", {}),
                execution_id=sc.execution_id,
            )
        except Exception as exc:
            ledger_identity_error = exc
            if ledger_mode == "observe":
                log.warning(
                    "[%s] account action identity resolution failed: %s", sc.serial, exc
                )

    candidate_entity_id = str(step.get("candidate_entity_id") or "").strip()
    candidate_lease_token = str(step.get("candidate_lease_token") or "").strip()
    if (
        action_type == "connection_request"
        and candidate_lease_token
        and not candidate_entity_id
    ):
        _fail(
            sc,
            step,
            result,
            outcome="candidate_contract_invalid",
            message=(
                "connection_request: candidate_lease_token requires "
                "candidate_entity_id"
            ),
        )
        return
    if action_type == "connection_request" and candidate_entity_id:
        from services.account_actions import resolve_action_identity
        from services.facebook_candidate_runtime import (
            assert_connection_candidate_allowed,
        )

        try:
            if ledger_identity is None:
                ledger_identity = resolve_action_identity(
                    step=step,
                    scenario=sc.scenario,
                    variables=sc.ctx.get("vars", {}),
                    execution_id=sc.execution_id,
                )
            required_status = str(
                step.get("require_candidate_status") or "ready_to_connect"
            ).strip()
            result["candidate_guard"] = assert_connection_candidate_allowed(
                identity=ledger_identity,
                external_entity_id=candidate_entity_id,
                allowed_statuses=(required_status,),
                lease_token=candidate_lease_token or None,
            )
        except (LookupError, RuntimeError, ValueError) as exc:
            _fail(
                sc,
                step,
                result,
                outcome="candidate_not_approved",
                message=f"{action_type}: candidate guard rejected action: {exc}",
            )
            return

    adapter = get_social_action_adapter(platform)
    debug_trace: dict[str, Any] = {}
    if adapter is None:
        _fail(
            sc,
            step,
            result,
            outcome="unsupported_platform",
            message=f"{action_type}: platform {platform!r} is not supported",
        )
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
        )
        return
    if ledger_mode == "enabled" and ledger_identity_error is not None:
        _fail(
            sc,
            step,
            result,
            outcome="ledger_identity_failed",
            message=f"{action_type}: durable action identity failed: {ledger_identity_error}",
        )
        return
    if not _require_verified_target(sc, step, result):
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
        )
        return
    if ledger_mode in {"observe", "enabled"}:
        from services.account_actions import stable_target

        ledger_target = stable_target(
            action=action, verified_target=result.get("verified_target")
        )

    try:
        before = _poll_observation(
            sc,
            adapter=adapter,
            action_type=action_type,
            action=action,
            timeout=timeout,
            poll=poll,
            require_satisfied=False,
            phase="before",
            debug_trace=debug_trace,
        )
    except UnsupportedSocialAction as exc:
        _fail(
            sc,
            step,
            result,
            outcome="unsupported_action",
            message=str(exc),
            debug_trace=debug_trace,
        )
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
            ledger_target=ledger_target,
        )
        return
    except (ET.ParseError, OSError, RuntimeError, ValueError) as exc:
        _fail(
            sc,
            step,
            result,
            outcome="observation_failed",
            message=f"{action_type}: cannot inspect current screen: {exc}",
            debug_trace=debug_trace,
        )
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
            ledger_target=ledger_target,
        )
        return

    if _cancelled(sc):
        _fail(
            sc,
            step,
            result,
            outcome="cancelled",
            message=f"{action_type}: cancelled",
            debug_trace=debug_trace,
        )
        result["cancelled"] = True
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
            ledger_target=ledger_target,
        )
        return
    if before is None:
        _fail(
            sc,
            step,
            result,
            outcome="hierarchy_unavailable",
            message=f"{action_type}: hierarchy unavailable",
            debug_trace=debug_trace,
        )
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
            ledger_target=ledger_target,
        )
        return
    if before.is_satisfied:
        if action_type == "connection_request" and candidate_lease_token:
            from services.facebook_candidate_runtime import complete_connection_candidate

            candidate_guard = result.get("candidate_guard") or {}
            try:
                result["candidate_completion"] = complete_connection_candidate(
                    identity=ledger_identity,
                    candidate_id=str(candidate_guard.get("candidate_id") or ""),
                    lease_token=candidate_lease_token,
                )
            except (LookupError, RuntimeError, ValueError) as exc:
                _fail(
                    sc,
                    step,
                    result,
                    outcome="candidate_finalize_failed",
                    message=(
                        f"{action_type}: already applied but candidate finalize "
                        f"failed: {exc}"
                    ),
                    observation=before,
                    debug_trace=debug_trace,
                )
                return
        result.update(
            {
                "outcome": "already_applied",
                "state": before.state,
                "message": f"{action_type}: already {before.state}",
            }
        )
        if before.target_bounds is not None:
            result["action_bounds"] = before.target_bounds
            result["_bounds"] = before.target_bounds
        if before.matched_label:
            result["matched_label"] = before.matched_label
        _save_result(sc, step, result)
        if ledger_mode == "enabled" and ledger_identity is not None:
            try:
                from services.account_actions import prepare_action

                ledger_claim = prepare_action(
                    identity=ledger_identity,
                    action_type=action_type,
                    platform=platform,
                    target=ledger_target,
                    action_id=reserved_action_id or None,
                )
                if ledger_claim.get("claimed") is not False:
                    _finalize_social_action_ledger(
                        sc,
                        step,
                        result,
                        ledger_claim,
                        succeeded=True,
                        reason="already_applied",
                    )
                else:
                    result["account_action_ledger"] = ledger_claim
            except Exception as exc:
                _fail(
                    sc,
                    step,
                    result,
                    outcome="ledger_prepare_failed",
                    message=f"{action_type}: durable no-op claim failed: {exc}",
                    observation=before,
                    debug_trace=debug_trace,
                )
        elif ledger_mode == "observe" and ledger_identity is not None:
            try:
                from services.account_actions import observe_action

                result["account_action_ledger"] = observe_action(
                    identity=ledger_identity,
                    action_type=action_type,
                    platform=platform,
                    target=ledger_target,
                    outcome="already_applied",
                )
            except Exception as exc:
                log.warning(
                    "[%s] account action observation failed: %s", sc.serial, exc
                )
        return
    if before.state == "ambiguous":
        _fail(
            sc,
            step,
            result,
            outcome="ambiguous_target",
            message=f"{action_type}: multiple matching targets are visible",
            observation=before,
            debug_trace=debug_trace,
        )
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
            ledger_target=ledger_target,
        )
        return
    if before.target_bounds is None:
        _fail(
            sc,
            step,
            result,
            outcome="target_not_found",
            message=f"{action_type}: action is not available on the current screen",
            observation=before,
            debug_trace=debug_trace,
        )
        _record_unclaimed_social_action(
            sc,
            step,
            result,
            ledger_mode=ledger_mode,
            ledger_identity=ledger_identity,
            action_type=action_type,
            platform=platform,
            action=action,
            ledger_target=ledger_target,
        )
        return

    if ledger_mode == "enabled":
        try:
            from services.account_actions import prepare_action

            ledger_claim = prepare_action(
                identity=ledger_identity,
                action_type=action_type,
                platform=platform,
                target=ledger_target,
                action_id=reserved_action_id or None,
            )
            result["account_action_ledger"] = ledger_claim
            if ledger_claim.get("claimed") is False:
                _fail(
                    sc,
                    step,
                    result,
                    outcome="ledger_state_conflict",
                    message=(
                        f"{action_type}: ledger is already "
                        f"{ledger_claim.get('status') or 'completed'} but UI is not applied"
                    ),
                    observation=before,
                    debug_trace=debug_trace,
                )
                return
        except Exception as exc:
            _fail(
                sc,
                step,
                result,
                outcome="ledger_prepare_failed",
                message=f"{action_type}: durable action claim failed: {exc}",
                observation=before,
                debug_trace=debug_trace,
            )
            return
    elif ledger_mode == "observe" and ledger_identity is not None:
        try:
            from services.account_actions import observe_action

            result["account_action_ledger"] = observe_action(
                identity=ledger_identity,
                action_type=action_type,
                platform=platform,
                target=ledger_target,
                outcome="attempted",
            )
        except Exception as exc:
            log.warning("[%s] account action observation failed: %s", sc.serial, exc)

    left, top, right, bottom = before.target_bounds
    try:
        sc.device.tap((left + right) // 2, (top + bottom) // 2)
        result["action_performed"] = True
        result["action_bounds"] = before.target_bounds
        if before.matched_label:
            result["matched_label"] = before.matched_label
        result["_bounds"] = before.target_bounds
    except (OSError, RuntimeError, ValueError) as exc:
        _fail(
            sc,
            step,
            result,
            outcome="tap_failed",
            message=f"{action_type}: tap failed: {exc}",
            observation=before,
            debug_trace=debug_trace,
        )
        _finalize_social_action_ledger(
            sc,
            step,
            result,
            ledger_claim,
            succeeded=False,
            reason="uncertain_tap_error",
        )
        return

    if _wait(sc, settle_seconds):
        _fail(
            sc,
            step,
            result,
            outcome="cancelled",
            message=f"{action_type}: cancelled",
            observation=before,
            debug_trace=debug_trace,
        )
        result["cancelled"] = True
        _finalize_social_action_ledger(
            sc,
            step,
            result,
            ledger_claim,
            succeeded=False,
            reason="uncertain_cancelled_after_tap",
        )
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
            near_bounds=_verification_bounds(
                action_type=action_type,
                action=action,
                target_bounds=before.target_bounds,
            ),
            phase="after",
            debug_trace=debug_trace,
        )
    except (ET.ParseError, OSError, RuntimeError, ValueError) as exc:
        _fail(
            sc,
            step,
            result,
            outcome="verification_failed",
            message=f"{action_type}: verification failed: {exc}",
            observation=before,
            debug_trace=debug_trace,
        )
        _finalize_social_action_ledger(
            sc,
            step,
            result,
            ledger_claim,
            succeeded=False,
            reason="uncertain_verification_error_after_tap",
        )
        return

    if after is None or not after.is_satisfied:
        _fail(
            sc,
            step,
            result,
            outcome="verification_failed",
            message=f"{action_type}: state did not change after tap",
            observation=after,
            debug_trace=debug_trace,
        )
        _finalize_social_action_ledger(
            sc,
            step,
            result,
            ledger_claim,
            succeeded=False,
            reason="uncertain_unverified_after_tap",
        )
        return

    if require_completion:
        from tasks.scenario.steps import dispatch_step

        nested_steps = [*completion_steps]
        if completion_verify:
            nested_steps.append(completion_verify)
        completion_results: list[dict[str, Any]] = []
        for completion_idx, completion_step in enumerate(nested_steps):
            nested_type = str(completion_step.get("type") or "")
            if nested_type in {
                "content_interaction",
                "connection_request",
                "community_membership",
            }:
                nested_result = {
                    "index": completion_idx,
                    "type": nested_type,
                    "ok": False,
                    "message": "recursive social completion steps are not allowed",
                }
            else:
                nested_result = dispatch_step(sc, completion_step, completion_idx)
            completion_results.append(nested_result)
            if not nested_result.get("ok", False):
                result["completion_results"] = completion_results
                _fail(
                    sc,
                    step,
                    result,
                    outcome="completion_failed",
                    message=(
                        f"{action_type}: completion step {completion_idx} "
                        f"failed: {nested_result.get('message') or nested_type}"
                    ),
                    observation=after,
                    debug_trace=debug_trace,
                )
                _finalize_social_action_ledger(
                    sc,
                    step,
                    result,
                    ledger_claim,
                    succeeded=False,
                    reason="completion_failed_after_panel_open",
                )
                return
        result["completion_results"] = completion_results
        completed_states = {
            "comment": "comment_submitted",
            "share": "share_confirmed",
        }
        after_state = completed_states.get(action, f"{action}_completed")
    else:
        after_state = after.state

    if action_type == "connection_request" and candidate_lease_token:
        from services.facebook_candidate_runtime import complete_connection_candidate

        candidate_guard = result.get("candidate_guard") or {}
        try:
            result["candidate_completion"] = complete_connection_candidate(
                identity=ledger_identity,
                candidate_id=str(candidate_guard.get("candidate_id") or ""),
                lease_token=candidate_lease_token,
            )
        except (LookupError, RuntimeError, ValueError) as exc:
            _finalize_social_action_ledger(
                sc,
                step,
                result,
                ledger_claim,
                succeeded=True,
                reason="verified_applied_candidate_finalize_failed",
            )
            _fail(
                sc,
                step,
                result,
                outcome="candidate_finalize_failed",
                message=f"{action_type}: action applied but candidate finalize failed: {exc}",
                observation=after,
                debug_trace=debug_trace,
            )
            return

    result.update(
        {
            "outcome": "applied",
            "state": after_state,
            "message": f"{action_type}: applied ({after_state})",
        }
    )
    _finalize_social_action_ledger(
        sc, step, result, ledger_claim, succeeded=True, reason="verified_applied"
    )
    _save_result(sc, step, result)


def _finalize_social_action_ledger(
    sc: ScenarioContext,
    step: dict[str, Any],
    result: dict[str, Any],
    claim: dict[str, Any] | None,
    *,
    succeeded: bool,
    reason: str,
) -> None:
    if claim is None:
        return
    try:
        from services.account_actions import finalize_action

        result["account_action_ledger"] = finalize_action(
            claim=claim,
            succeeded=succeeded,
            terminal=(
                True if succeeded else _account_action_failure_is_terminal(step, result)
            ),
            reason=reason,
            result=result,
        )
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "outcome": "ledger_finalize_failed",
                "message": (
                    f"{step.get('type')}: durable action finalization failed: {exc}"
                ),
                "action_performed": bool(result.get("action_performed", False)),
            }
        )
        _save_result(sc, step, result)
