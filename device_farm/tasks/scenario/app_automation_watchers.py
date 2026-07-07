"""Runtime glue for app automation popup watchers."""
from __future__ import annotations

import time
from typing import Any, Dict

from services.app_automation_profile import AppAutomationProfile, validate_app_automation_profile
from services.app_automation_watcher import (
    WatcherRuntimeState,
    WatcherTrigger,
    evaluate_popup_watchers,
)
from services.scenario_selector import ScenarioSelectorSpec
from tasks.scenario.context import ScenarioContext
from tasks.scenario.utils import _get_implicit_wait_config, _retry_find_element


_STATE_KEY = "_app_popup_watcher_state"
_WATCHER_WAIT_CAP_S = 2.0


def _raw_profile(sc: ScenarioContext, step: Dict[str, Any]) -> dict[str, Any] | None:
    for raw in (
        step.get("profile"),
        step.get("app_automation_profile"),
        sc.scenario.get("app_automation_profile"),
        sc.scenario.get("automation_profile"),
    ):
        if isinstance(raw, dict) and raw.get("popup_watchers"):
            return raw
    return None


def _watchers_enabled(sc: ScenarioContext, step: Dict[str, Any]) -> bool:
    if step.get("app_popup_watchers_enabled") is False:
        return False
    if sc.scenario.get("app_popup_watchers_enabled") is False:
        return False
    return True


def _runtime_state(sc: ScenarioContext) -> WatcherRuntimeState:
    raw = sc.ctx.setdefault(_STATE_KEY, {"trigger_counts": {}, "last_trigger_ms": {}})
    if isinstance(raw, WatcherRuntimeState):
        return raw
    if not isinstance(raw, dict):
        raw = {"trigger_counts": {}, "last_trigger_ms": {}}
        sc.ctx[_STATE_KEY] = raw
    trigger_counts = raw.setdefault("trigger_counts", {})
    last_trigger_ms = raw.setdefault("last_trigger_ms", {})
    return WatcherRuntimeState(trigger_counts=trigger_counts, last_trigger_ms=last_trigger_ms)


def _current_app(sc: ScenarioContext, profile: AppAutomationProfile) -> tuple[str, str | None]:
    u2 = getattr(sc.device, "u2", None)
    if u2 is not None and callable(getattr(u2, "app_current", None)):
        try:
            current = u2.app_current() or {}
            package = str(current.get("package") or "").strip()
            activity = str(current.get("activity") or "").strip() or None
            if package:
                return package, activity
        except Exception:
            pass
    return profile.package, None


def _ensure_u2(sc: ScenarioContext) -> Any:
    u2 = getattr(sc.device, "u2", None)
    if u2 is None:
        sc.device.ensure_u2_healthy()
        u2 = getattr(sc.device, "u2", None)
    if u2 is None:
        raise RuntimeError("u2 not available")
    return u2


def _click_text(sc: ScenarioContext, step: Dict[str, Any], label: str) -> None:
    u2 = _ensure_u2(sc)
    spec = ScenarioSelectorSpec(by="text", value=str(label))
    by, value = spec.primary_by_value()
    iw_timeout, iw_poll = _get_implicit_wait_config(step, sc.scenario_iw_config)
    eid = _retry_find_element(
        u2,
        by,
        value,
        timeout=min(iw_timeout, _WATCHER_WAIT_CAP_S),
        poll=min(iw_poll, 0.2),
        cancel_event=sc.cancel_event,
        spec=spec,
        device=sc.device,
    )
    if isinstance(eid, dict):
        eid = eid.get("eid")
    if not eid:
        raise RuntimeError(f"watcher tap target not found: {label!r}")
    u2.element_click(eid)


def _execute_trigger(sc: ScenarioContext, step: Dict[str, Any], trigger: WatcherTrigger) -> dict[str, Any]:
    action = trigger.action
    event: dict[str, Any] = {
        "name": trigger.name,
        "package": trigger.package,
        "reason": trigger.reason,
        "trigger_count": trigger.trigger_count,
        "action": action,
        "executed": False,
    }
    try:
        if action.get("noop"):
            event["executed"] = True
            event["message"] = "noop"
            return event
        if action.get("press_key"):
            key = str(action["press_key"])
            sc.device.key(key)
            event["executed"] = True
            event["message"] = f"pressed {key}"
            return event

        labels: list[str] = []
        if action.get("tap_text"):
            labels.append(str(action["tap_text"]))
        labels.extend(str(item) for item in action.get("tap_text_any") or [])
        errors = []
        for label in labels:
            try:
                _click_text(sc, step, label)
                event["executed"] = True
                event["message"] = f"tapped text {label!r}"
                event["selector"] = {"by": "text", "value": label}
                return event
            except Exception as exc:
                errors.append(f"{label!r}: {exc}")
        raise RuntimeError("; ".join(errors) or "watcher action has no executable target")
    except Exception as exc:
        event["message"] = str(exc)
        return event


def run_app_popup_watchers(sc: ScenarioContext, step: Dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate and execute profile popup watchers before a scenario step."""
    if not _watchers_enabled(sc, step):
        return []
    raw = _raw_profile(sc, step)
    if raw is None:
        return []
    try:
        profile = validate_app_automation_profile(raw)
    except Exception as exc:
        return [{"executed": False, "message": f"profile invalid: {exc}"}]
    package, activity = _current_app(sc, profile)
    xml = sc.device.hierarchy_xml(force_refresh=True)
    if not xml:
        return []
    triggers = evaluate_popup_watchers(
        profile,
        xml,
        current_package=package,
        current_activity=activity,
        now_ms=int(time.monotonic() * 1000),
        state=_runtime_state(sc),
        max_triggers_per_evaluation=1,
    )
    return [_execute_trigger(sc, step, trigger) for trigger in triggers]
