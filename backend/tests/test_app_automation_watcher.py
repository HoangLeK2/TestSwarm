from __future__ import annotations

from services.app_automation_profile import validate_app_automation_profile
from services.app_automation_locator import build_hierarchy_snapshot
from services.app_automation_watcher import WatcherRuntimeState, evaluate_popup_watchers


_XML = """
<hierarchy>
  <node text="New version available" class="android.widget.TextView" bounds="[10,10][500,80]" />
  <node text="Later" class="android.widget.Button" clickable="true" bounds="[300,200][500,280]" />
</hierarchy>
"""


def _profile():
    return validate_app_automation_profile({
        "package": "com.example.app",
        "semantic_locators": {
            "later_button": {"candidates": [{"by": "text", "value": "Later"}]},
        },
        "popup_watchers": [
            {
                "name": "close_update",
                "when": {"text_contains": ["version available"]},
                "action": {"tap_text_any": ["Later", "Not now"]},
                "max_triggers_per_run": 2,
                "cooldown_ms": 1000,
            }
        ],
    })


def test_evaluate_popup_watcher_returns_action_metadata():
    state = WatcherRuntimeState()

    triggers = evaluate_popup_watchers(
        _profile(),
        _XML,
        current_package="com.example.app",
        now_ms=10_000,
        state=state,
    )

    assert len(triggers) == 1
    assert triggers[0].name == "close_update"
    assert triggers[0].action["tap_text_any"] == ["Later", "Not now"]
    assert triggers[0].package == "com.example.app"
    assert triggers[0].trigger_count == 1


def test_watcher_does_not_trigger_outside_package_scope():
    triggers = evaluate_popup_watchers(
        _profile(),
        _XML,
        current_package="com.other.app",
        now_ms=10_000,
        state=WatcherRuntimeState(),
    )

    assert triggers == []


def test_watcher_respects_activity_and_screen_scope():
    raw = _profile().model_dump(mode="json")
    raw["popup_watchers"][0]["scope"] = {
        "package": "com.example.app",
        "activity": ".LoginActivity",
        "screen": "login",
    }
    profile = validate_app_automation_profile(raw)

    wrong_screen = evaluate_popup_watchers(
        profile,
        _XML,
        current_package="com.example.app",
        current_activity=".LoginActivity",
        current_screen="home",
        now_ms=10_000,
        state=WatcherRuntimeState(),
    )
    matched = evaluate_popup_watchers(
        profile,
        _XML,
        current_package="com.example.app",
        current_activity=".LoginActivity",
        current_screen="login",
        now_ms=10_000,
        state=WatcherRuntimeState(),
    )

    assert wrong_screen == []
    assert len(matched) == 1


def test_watcher_respects_cooldown():
    state = WatcherRuntimeState()
    profile = _profile()

    first = evaluate_popup_watchers(profile, _XML, current_package="com.example.app", now_ms=10_000, state=state)
    second = evaluate_popup_watchers(profile, _XML, current_package="com.example.app", now_ms=10_500, state=state)

    assert len(first) == 1
    assert second == []


def test_watcher_respects_max_triggers_per_run():
    state = WatcherRuntimeState()
    profile = _profile()

    first = evaluate_popup_watchers(profile, _XML, current_package="com.example.app", now_ms=10_000, state=state)
    second = evaluate_popup_watchers(profile, _XML, current_package="com.example.app", now_ms=11_001, state=state)
    third = evaluate_popup_watchers(profile, _XML, current_package="com.example.app", now_ms=12_002, state=state)

    assert len(first) == 1
    assert len(second) == 1
    assert third == []


def test_disabled_watcher_does_not_trigger():
    raw = _profile().model_dump(mode="json")
    raw["popup_watchers"][0]["enabled"] = False
    profile = validate_app_automation_profile(raw)

    triggers = evaluate_popup_watchers(
        profile,
        _XML,
        current_package="com.example.app",
        now_ms=10_000,
        state=WatcherRuntimeState(),
    )

    assert triggers == []


def test_watcher_can_reuse_hierarchy_snapshot():
    profile = _profile()
    snapshot = build_hierarchy_snapshot(_XML)

    triggers = evaluate_popup_watchers(
        profile,
        "",
        current_package="com.example.app",
        now_ms=10_000,
        state=WatcherRuntimeState(),
        snapshot=snapshot,
    )

    assert len(triggers) == 1


def test_watcher_returns_single_trigger_by_default():
    raw = _profile().model_dump(mode="json")
    raw["popup_watchers"].append({
        "name": "close_update_second",
        "when": {"text_contains": ["New version"]},
        "action": {"tap_text": "Later"},
    })
    profile = validate_app_automation_profile(raw)

    triggers = evaluate_popup_watchers(
        profile,
        _XML,
        current_package="com.example.app",
        now_ms=10_000,
        state=WatcherRuntimeState(),
    )

    assert [trigger.name for trigger in triggers] == ["close_update"]
