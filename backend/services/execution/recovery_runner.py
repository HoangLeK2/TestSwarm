"""Run configured recovery scenarios at scenario step boundaries."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from services.execution.incident_detection import (
    Incident,
    capture_snapshot,
    detect_incident,
)
from services.execution.recovery_policy import (
    RecoveryPolicy,
    RecoveryRule,
    parse_recovery_policy,
)

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RecoveryDecision:
    handled: bool = False
    retry_step: bool = False
    continue_step: bool = False
    fail_message: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


def _state(ctx: dict[str, Any]) -> dict[str, Any]:
    raw = ctx.setdefault("_recovery_state", {})
    if not isinstance(raw, dict):
        raw = {}
        ctx["_recovery_state"] = raw
    raw.setdefault("total_attempts", 0)
    raw.setdefault("by_step", {})
    raw.setdefault("by_rule", {})
    raw.setdefault("by_incident", {})
    raw.setdefault("by_incident_step", {})
    raw.setdefault("by_incident_rule", {})
    return raw


def _cancel_requested(sc: Any) -> bool:
    ev = getattr(sc, "cancel_event", None)
    if ev is None or not callable(getattr(ev, "is_set", None)):
        return False
    try:
        state = ev.is_set()
    except Exception:
        return False
    return state if isinstance(state, bool) else False


def _next_incident_key(sc: Any, idx: int) -> str:
    seq = int(sc.ctx.get("_recovery_incident_seq") or 0) + 1
    sc.ctx["_recovery_incident_seq"] = seq
    depth = len(getattr(sc, "call_stack", None) or ())
    trace = str(getattr(sc, "trace_id", None) or "root")
    return f"{trace}:{depth}:{idx}:{seq}"


def _incident_key(sc: Any, idx: int, step_result: dict[str, Any]) -> str:
    existing = step_result.get("_recovery_incident_key")
    if existing:
        return str(existing)
    key = _next_incident_key(sc, idx)
    step_result["_recovery_incident_key"] = key
    return key


def _budget_available(
    sc: Any,
    rule: RecoveryRule,
    idx: int,
    *,
    incident_key: str | None = None,
) -> bool:
    policy = parse_recovery_policy(sc.scenario.get("recovery_policy"))
    state = _state(sc.ctx)
    if int(state.get("total_attempts") or 0) >= policy.max_total_attempts:
        return False
    if incident_key:
        by_incident_step = (
            state.get("by_incident_step")
            if isinstance(state.get("by_incident_step"), dict)
            else {}
        )
        if int(by_incident_step.get(f"{incident_key}:{idx}", 0) or 0) >= policy.max_attempts_per_step:
            return False
        by_incident_rule = (
            state.get("by_incident_rule")
            if isinstance(state.get("by_incident_rule"), dict)
            else {}
        )
        if int(by_incident_rule.get(f"{incident_key}:{rule.id}", 0) or 0) >= rule.max_attempts:
            return False
    return True


def _record_attempt(
    sc: Any,
    rule: RecoveryRule,
    idx: int,
    incident: Incident,
    *,
    incident_key: str,
) -> int:
    state = _state(sc.ctx)
    state["total_attempts"] = int(state.get("total_attempts") or 0) + 1
    by_step = state.setdefault("by_step", {})
    by_step[str(idx)] = int(by_step.get(str(idx), 0) or 0) + 1
    by_rule = state.setdefault("by_rule", {})
    by_rule[rule.id] = int(by_rule.get(rule.id, 0) or 0) + 1
    by_incident = state.setdefault("by_incident", {})
    incident_attempt = int(by_incident.get(incident_key, 0) or 0) + 1
    by_incident[incident_key] = incident_attempt
    by_incident_step = state.setdefault("by_incident_step", {})
    incident_step_key = f"{incident_key}:{idx}"
    by_incident_step[incident_step_key] = int(by_incident_step.get(incident_step_key, 0) or 0) + 1
    by_incident_rule = state.setdefault("by_incident_rule", {})
    incident_rule_key = f"{incident_key}:{rule.id}"
    by_incident_rule[incident_rule_key] = int(by_incident_rule.get(incident_rule_key, 0) or 0) + 1
    state["last_incident"] = {
        "key": incident_key,
        "attempt": incident_attempt,
        "type": incident.type,
        "rule_id": rule.id,
        "step_index": idx,
    }
    return incident_attempt


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _contains_any(haystack: str, needles: list[str]) -> str | None:
    for needle in needles:
        clean = _norm(needle)
        if clean and clean in haystack:
            return needle
    return None


def _contains_all(haystack: str, needles: list[str]) -> bool:
    return all(_norm(needle) in haystack for needle in needles if _norm(needle))


def _equals_any(value: Any, candidates: list[Any]) -> bool:
    normalized = _norm(value)
    return any(normalized == _norm(candidate) for candidate in candidates)


def _rule_scope_matches(rule: RecoveryRule, step: dict[str, Any], idx: int) -> bool:
    scope = rule.scope or {}
    if not scope:
        return True
    step_type_any = scope.get("step_type_any") or []
    if step_type_any and not _equals_any(step.get("type"), step_type_any):
        return False
    step_id = step.get("id") or step.get("_id") or step.get("step_id")
    step_id_any = scope.get("step_id_any") or []
    if step_id_any and not _equals_any(step_id, step_id_any):
        return False
    strategy_any = scope.get("strategy_any") or []
    if strategy_any and not _equals_any(step.get("strategy"), strategy_any):
        return False
    step_index_any = scope.get("step_index_any") or []
    if step_index_any and idx not in {int(value) for value in step_index_any}:
        return False
    return True


def _rule_match_incident(
    sc: Any,
    policy: RecoveryPolicy,
    step: dict[str, Any],
    idx: int,
    step_result: dict[str, Any],
    *,
    incident_key: str,
) -> tuple[Incident, RecoveryRule] | None:
    rules = [
        rule
        for rule in policy.rules
        if rule.match
        and _rule_scope_matches(rule, step, idx)
        and _budget_available(sc, rule, idx, incident_key=incident_key)
    ]
    if not rules:
        return None

    snapshot = None
    result_text = _norm(
        f"{step_result.get('reason_code') or ''} {step_result.get('message') or ''}"
    )
    step_type = _norm(step.get("type"))
    strategy = _norm(step.get("strategy"))

    for rule in rules:
        match = rule.match
        evidence: dict[str, Any] = {"source": "recovery_rule", "rule_id": rule.id}

        step_type_any = match.get("step_type_any") or []
        if step_type_any and not _contains_any(step_type, step_type_any):
            continue

        strategy_any = match.get("strategy_any") or []
        if strategy_any and not _contains_any(strategy, strategy_any):
            continue

        result_any = match.get("result_any") or []
        if result_any:
            matched = _contains_any(result_text, result_any)
            if not matched:
                continue
            evidence["matched_result"] = matched

        needs_snapshot = any(
            match.get(key)
            for key in ("text_any", "text_all", "package_any", "activity_any")
        )
        if needs_snapshot and snapshot is None:
            snapshot = capture_snapshot(sc.device)

        if snapshot is not None:
            xml_text = _norm(snapshot.xml)
            package_name = _norm(snapshot.package_name)
            activity_name = _norm(snapshot.activity_name)

            text_any = match.get("text_any") or []
            if text_any:
                matched = _contains_any(xml_text, text_any)
                if not matched:
                    continue
                evidence["matched_text"] = matched

            text_all = match.get("text_all") or []
            if text_all and not _contains_all(xml_text, text_all):
                continue

            package_any = match.get("package_any") or []
            if package_any and not _contains_any(package_name, package_any):
                continue

            activity_any = match.get("activity_any") or []
            if activity_any and not _contains_any(activity_name, activity_any):
                continue

            if snapshot.hierarchy_hash:
                evidence["hierarchy_hash"] = snapshot.hierarchy_hash

        incident_type = rule.incident_types[0] if rule.incident_types else "unknown"
        confidence = float(match.get("min_confidence") or 0.9)
        return (
            Incident(
                incident_type,
                confidence,
                "recovery_rule_match",
                evidence,
            ),
            rule,
        )
    return None


def _match_rule(
    sc: Any,
    incident: Incident,
    step: dict[str, Any],
    idx: int,
    *,
    incident_key: str,
) -> RecoveryRule | None:
    policy = parse_recovery_policy(sc.scenario.get("recovery_policy"))
    if not policy.enabled or not policy.rules:
        return None
    if incident.confidence < 0.7:
        return None
    for rule in policy.rules:
        if (
            incident.type in rule.incident_types
            and _rule_scope_matches(rule, step, idx)
            and _budget_available(sc, rule, idx, incident_key=incident_key)
        ):
            return rule
    return None


def recovery_timeout_ms_for_step(sc: Any, step: dict[str, Any], idx: int) -> int:
    if sc.scenario.get("_recovery_disabled"):
        return 0
    policy = parse_recovery_policy(sc.scenario.get("recovery_policy"))
    if not policy.enabled or not policy.rules:
        return 0
    timeouts = [
        int(rule.timeout_ms)
        for rule in policy.rules
        if int(rule.timeout_ms or 0) > 0
        and _rule_scope_matches(rule, step, idx)
        and _budget_available(sc, rule, idx)
        and (rule.scenario_id or rule.scenario_name)
    ]
    return min(timeouts) if timeouts else 0


def _resolve_recovery_scenario(sc: Any, rule: RecoveryRule) -> dict[str, Any] | None:
    registry = sc.scenario.get("_scenario_registry") or {}
    if rule.scenario_id:
        found = (registry.get("by_id") or {}).get(rule.scenario_id)
        if isinstance(found, dict):
            return found
    if rule.scenario_name:
        for bucket in ("by_campaign_name", "by_template_name"):
            found = (registry.get(bucket) or {}).get(rule.scenario_name)
            if isinstance(found, dict):
                return found
    return None


def _synthetic_incident(
    rule: RecoveryRule, reason_code: str, evidence: dict[str, Any]
) -> Incident:
    incident_type = rule.incident_types[0] if rule.incident_types else "unknown"
    return Incident(incident_type, 0.9, reason_code, evidence)


def _decision_from_outcome(
    outcome: str,
    *,
    events: list[dict[str, Any]],
    failure_prefix: str = "incident recovery failed",
) -> RecoveryDecision:
    if outcome == "retry_step":
        return RecoveryDecision(handled=True, retry_step=True, events=events)
    if outcome == "continue":
        return RecoveryDecision(handled=True, continue_step=True, events=events)
    message = failure_prefix
    if outcome == "pause_for_takeover":
        message = f"{failure_prefix}; takeover required"
    elif outcome == "open_dlq":
        message = f"{failure_prefix}; open DLQ"
    return RecoveryDecision(handled=True, fail_message=message, events=events)


def _step_deadline(policy: RecoveryPolicy) -> float | None:
    """Wall-clock point past which no further playbook starts for this step."""
    if policy.max_step_recovery_ms <= 0:
        return None
    return time.monotonic() + policy.max_step_recovery_ms / 1000.0


def _out_of_time(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _try_recovery_playbooks(
    sc: Any,
    policy: RecoveryPolicy,
    step: dict[str, Any],
    idx: int,
    *,
    incident_key: str,
    deadline: float | None = None,
) -> RecoveryDecision | None:
    attempted = False
    events: list[dict[str, Any]] = []
    for rule in policy.rules:
        if not rule.scenario_id and not rule.scenario_name:
            continue
        if _out_of_time(deadline):
            log.warning(
                "[%s] recovery budget spent at step#%s — skipping remaining playbooks",
                sc.serial, idx,
            )
            break
        if not _rule_scope_matches(rule, step, idx):
            continue
        if not _budget_available(sc, rule, idx, incident_key=incident_key):
            continue
        recovery_scenario = _resolve_recovery_scenario(sc, rule)
        if recovery_scenario is None:
            continue

        attempted = True
        incident = _synthetic_incident(
            rule,
            "recovery_playbook",
            {
                "source": "recovery_playbook",
                "rule_id": rule.id,
                "scenario_id": rule.scenario_id,
                "scope": rule.scope,
                "incident_key": incident_key,
            },
        )
        attempt = _record_attempt(sc, rule, idx, incident, incident_key=incident_key)
        started = time.monotonic()
        events.append(
            _event(
                "incident.detected",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                attempt=attempt,
                matched=True,
            )
        )
        events.append(
            _event(
                "incident.recovery.started",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                attempt=attempt,
            )
        )
        try:
            from tasks.scenario.executor import run_nested_scenario

            sub = run_nested_scenario(
                sc,
                recovery_scenario.get("steps") or [],
                variables=dict(recovery_scenario.get("variables") or {}),
                call_stack_add=rule.scenario_id or rule.scenario_name or rule.id,
                extra_scenario_keys={
                    "_scenario_registry": sc.scenario.get("_scenario_registry") or {},
                    "_recovery_disabled": True,
                    "recovery_policy": {"enabled": False},
                },
            )
        except Exception as exc:
            log.exception("[%s] recovery playbook raised rule=%s", sc.serial, rule.id)
            events.append(
                _event(
                    "incident.failed",
                    step=step,
                    idx=idx,
                    rule=rule,
                    incident=incident,
                    incident_key=incident_key,
                    attempt=attempt,
                    reason=str(exc),
                )
            )
            if _cancel_requested(sc):
                return RecoveryDecision(
                    handled=True,
                    fail_message="cancelled by user",
                    events=events,
                )
            continue

        if _cancel_requested(sc):
            return RecoveryDecision(
                handled=True,
                fail_message="cancelled by user",
                events=events,
            )
        ok = bool(sub.get("success"))
        duration_ms = round((time.monotonic() - started) * 1000.0, 1)
        events.append(
            _event(
                "incident.recovery.completed",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                attempt=attempt,
                ok=ok,
                duration_ms=duration_ms,
                recovery_steps_executed=sub.get("steps_executed", 0),
                recovery_failed_message=sub.get("failed_message"),
            )
        )
        if ok:
            events.append(
                _event(
                    "incident.resolved",
                    step=step,
                    idx=idx,
                    rule=rule,
                    incident=incident,
                    incident_key=incident_key,
                    attempt=attempt,
                    outcome=rule.on_success,
                )
            )
            return _decision_from_outcome(rule.on_success, events=events)

        events.append(
            _event(
                "incident.failed",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                attempt=attempt,
                outcome=rule.on_failure,
                reason=sub.get("failed_message") or "playbook_not_matched_or_failed",
            )
        )

    if attempted:
        return _decision_from_outcome(
            "fail",
            events=events,
            failure_prefix="incident recovery playbooks did not resolve the step",
        )
    return None


def _event(
    event_type: str,
    *,
    step: dict[str, Any],
    idx: int,
    rule: RecoveryRule | None,
    incident: Incident | None,
    incident_key: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "step_index": idx,
        "step_type": step.get("type"),
        **extra,
    }
    if rule is not None:
        payload["rule_id"] = rule.id
        payload["scenario_id"] = rule.scenario_id
        payload["recovery_scenario_id"] = rule.scenario_id
        payload["recovery_scenario_name"] = rule.scenario_name
    if incident_key:
        payload["incident_key"] = incident_key
    if incident is not None:
        payload.update(incident.to_payload())
    return {"event_type": event_type, "payload": payload}


def _success(sc: Any, rule: RecoveryRule, step: dict[str, Any]) -> bool:
    if not rule.success_checks:
        return True
    current = detect_incident(device=sc.device, step=step, step_result={})
    for check in rule.success_checks:
        if check.type == "not_incident":
            if current is None:
                continue
            if check.incident_type and current.type != check.incident_type:
                continue
            return False
        if check.type == "post_detail_visible":
            if current is not None and current.type in {
                "profile_page",
                "lost_post_detail",
                "login_or_checkpoint",
            }:
                return False
        if check.type == "comment_panel_visible":
            if current is not None and current.type in {
                "comment_panel_closed",
                "login_or_checkpoint",
            }:
                return False
    return True


def maybe_recover_step(
    sc: Any,
    step: dict[str, Any],
    idx: int,
    step_result: dict[str, Any],
) -> RecoveryDecision:
    if sc.scenario.get("_recovery_disabled"):
        return RecoveryDecision()
    policy = parse_recovery_policy(sc.scenario.get("recovery_policy"))
    if not policy.enabled:
        return RecoveryDecision()
    if _cancel_requested(sc):
        return RecoveryDecision()
    incident_key = _incident_key(sc, idx, step_result)
    deadline = _step_deadline(policy)

    playbook_decision = _try_recovery_playbooks(
        sc,
        policy,
        step,
        idx,
        incident_key=incident_key,
        deadline=deadline,
    )
    if playbook_decision is not None:
        return playbook_decision

    configured = _rule_match_incident(
        sc,
        policy,
        step,
        idx,
        step_result,
        incident_key=incident_key,
    )
    if configured is not None:
        incident, rule = configured
    else:
        incident = detect_incident(device=sc.device, step=step, step_result=step_result)
        if incident is None:
            return RecoveryDecision()
        rule = _match_rule(sc, incident, step, idx, incident_key=incident_key)
    if rule is None:
        return RecoveryDecision(
            events=[
                _event(
                    "incident.detected",
                    step=step,
                    idx=idx,
                    rule=None,
                    incident=incident,
                    incident_key=incident_key,
                    matched=False,
                )
            ]
        )
    recovery_scenario = _resolve_recovery_scenario(sc, rule)
    events = [
        _event(
            "incident.detected",
            step=step,
            idx=idx,
            rule=rule,
            incident=incident,
            incident_key=incident_key,
            matched=True,
        )
    ]
    if recovery_scenario is None:
        events.append(
            _event(
                "incident.failed",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                reason="recovery_scenario_not_found",
            )
        )
        return RecoveryDecision(
            handled=True,
            fail_message="recovery scenario not found",
            events=events,
        )

    attempt = _record_attempt(sc, rule, idx, incident, incident_key=incident_key)
    events[0]["payload"]["attempt"] = attempt
    started = time.monotonic()
    events.append(
        _event(
            "incident.recovery.started",
            step=step,
            idx=idx,
            rule=rule,
            incident=incident,
            incident_key=incident_key,
            attempt=attempt,
        )
    )
    try:
        from tasks.scenario.executor import run_nested_scenario

        sub = run_nested_scenario(
            sc,
            recovery_scenario.get("steps") or [],
            variables=dict(recovery_scenario.get("variables") or {}),
            call_stack_add=rule.scenario_id or rule.scenario_name or rule.id,
            extra_scenario_keys={
                "_scenario_registry": sc.scenario.get("_scenario_registry") or {},
                "_recovery_disabled": True,
                "recovery_policy": {"enabled": False},
            },
        )
    except Exception as exc:
        log.exception("[%s] recovery scenario failed rule=%s", sc.serial, rule.id)
        events.append(
            _event(
                "incident.failed",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                attempt=attempt,
                reason=str(exc),
            )
        )
        if _cancel_requested(sc):
            return RecoveryDecision(
                handled=True,
                fail_message="cancelled by user",
                events=events,
            )
        return RecoveryDecision(
            handled=True, fail_message=f"recovery failed: {exc}", events=events
        )

    if _cancel_requested(sc):
        return RecoveryDecision(
            handled=True,
            fail_message="cancelled by user",
            events=events,
        )
    ok = bool(sub.get("success")) and _success(sc, rule, step)
    duration_ms = round((time.monotonic() - started) * 1000.0, 1)
    events.append(
        _event(
            "incident.recovery.completed",
            step=step,
            idx=idx,
            rule=rule,
            incident=incident,
            incident_key=incident_key,
            attempt=attempt,
            ok=ok,
            duration_ms=duration_ms,
            recovery_steps_executed=sub.get("steps_executed", 0),
            recovery_failed_message=sub.get("failed_message"),
        )
    )
    if ok:
        events.append(
            _event(
                "incident.resolved",
                step=step,
                idx=idx,
                rule=rule,
                incident=incident,
                incident_key=incident_key,
                attempt=attempt,
                outcome=rule.on_success,
            )
        )
        return RecoveryDecision(
            handled=True,
            retry_step=rule.on_success == "retry_step",
            continue_step=rule.on_success == "continue",
            events=events,
        )

    events.append(
        _event(
            "incident.failed",
            step=step,
            idx=idx,
            rule=rule,
            incident=incident,
            incident_key=incident_key,
            attempt=attempt,
            outcome=rule.on_failure,
        )
    )
    if rule.on_failure == "continue":
        return RecoveryDecision(handled=True, continue_step=True, events=events)
    message = "incident recovery failed"
    if rule.on_failure == "pause_for_takeover":
        message = "incident recovery failed; takeover required"
    elif rule.on_failure == "open_dlq":
        message = "incident recovery failed; open DLQ"
    return RecoveryDecision(handled=True, fail_message=message, events=events)
