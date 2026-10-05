"""Safe popup watcher evaluation for app automation profiles."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.xml_utils import XML_PARSE_ERRORS
from services.app_automation_profile import AppAutomationProfile, PopupWatcher, watcher_effective_package
from services.app_automation_locator import HierarchySnapshot, build_hierarchy_snapshot


@dataclass
class WatcherRuntimeState:
    trigger_counts: dict[str, int] = field(default_factory=dict)
    last_trigger_ms: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WatcherTrigger:
    name: str
    action: dict[str, Any]
    reason: str
    package: str
    trigger_count: int


def evaluate_popup_watchers(
    profile: AppAutomationProfile,
    hierarchy_xml: str,
    *,
    current_package: str,
    current_activity: str | None = None,
    current_screen: str | None = None,
    now_ms: int,
    state: WatcherRuntimeState | None = None,
    snapshot: HierarchySnapshot | None = None,
    max_triggers_per_evaluation: int = 1,
) -> list[WatcherTrigger]:
    """Evaluate popup watchers without executing their actions."""
    state = state or WatcherRuntimeState()
    runnable = [
        watcher for watcher in profile.popup_watchers
        if watcher.enabled
        and _scope_matches(profile, watcher, current_package, current_activity, current_screen)
        and _can_trigger(profile, watcher, now_ms, state)
    ]
    if not runnable or max_triggers_per_evaluation <= 0:
        return []
    if snapshot is None:
        try:
            snapshot = build_hierarchy_snapshot(hierarchy_xml)
        except XML_PARSE_ERRORS:
            return []
    nodes = snapshot.nodes
    triggers: list[WatcherTrigger] = []
    for watcher in runnable:
        package = watcher_effective_package(profile, watcher)
        reason = _match_watcher(watcher, nodes)
        if not reason:
            continue
        key = _state_key(profile, watcher)
        count = state.trigger_counts.get(key, 0) + 1
        state.trigger_counts[key] = count
        state.last_trigger_ms[key] = now_ms
        triggers.append(
            WatcherTrigger(
                name=watcher.name,
                action=watcher.action.model_dump(mode="json", exclude={"allow_unsafe"}),
                reason=reason,
                package=package,
                trigger_count=count,
            )
        )
        if len(triggers) >= max_triggers_per_evaluation:
            break
    return triggers


def _state_key(profile: AppAutomationProfile, watcher: PopupWatcher) -> str:
    return f"{watcher_effective_package(profile, watcher)}:{watcher.name}"


def _scope_matches(
    profile: AppAutomationProfile,
    watcher: PopupWatcher,
    current_package: str,
    current_activity: str | None,
    current_screen: str | None,
) -> bool:
    scope = watcher.scope
    if watcher_effective_package(profile, watcher) != current_package:
        return False
    if scope and scope.activity and scope.activity != current_activity:
        return False
    if scope and scope.screen and scope.screen != current_screen:
        return False
    return True


def _can_trigger(profile: AppAutomationProfile, watcher: PopupWatcher, now_ms: int, state: WatcherRuntimeState) -> bool:
    key = _state_key(profile, watcher)
    count = state.trigger_counts.get(key, 0)
    if count >= watcher.max_triggers_per_run:
        return False
    last = state.last_trigger_ms.get(key)
    if last is not None and now_ms - last < watcher.cooldown_ms:
        return False
    return True


def _match_watcher(watcher: PopupWatcher, nodes: list[Any]) -> str | None:
    condition = watcher.when
    for node in nodes:
        text = str(node.get("text") or "")
        desc = str(node.get("content-desc") or "")
        rid = str(node.get("resource-id") or "")
        class_name = str(node.get("class") or "")
        if condition.text and text == condition.text:
            return f"text={condition.text!r}"
        if condition.class_name and class_name == condition.class_name:
            return f"class_name={condition.class_name!r}"
        for needle in condition.text_contains:
            if needle and needle.lower() in text.lower():
                return f"text_contains={needle!r}"
        for needle in condition.description_contains:
            if needle and needle.lower() in desc.lower():
                return f"description_contains={needle!r}"
        for needle in condition.resource_id_contains:
            if needle and needle.lower() in rid.lower():
                return f"resource_id_contains={needle!r}"
    return None
