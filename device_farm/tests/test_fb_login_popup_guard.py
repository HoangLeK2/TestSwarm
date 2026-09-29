"""Guard: the Facebook login scenario must clear popups before it confirms.

``login_if_needed`` returns the instant it taps submit, and the confirm gate
that follows only *reads* the screen — ``_observe_readiness`` polls, it never
taps. Facebook answers a fresh login with a queue of popups (save login info,
turn on notifications, find friends) that cover the tab bar and the composer,
which are exactly the markers ``resolve_platform_readiness`` looks for.

So the account is signed in, the phone is fine, and the gate reports failure.
No session row is written and the operator sees a red step for a login that
worked. Nothing in a unit test of either step catches it: each one is correct
on its own, and the defect lives in the gap between them.

This asserts the gap is filled, and that the fill sits in the right place —
after the login step, before the confirm gate. Moving it earlier restores the
bug in a diff that looks like a harmless reorder.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from db.seeds.scenario_templates import BUILTIN_TEMPLATES
from tasks.scenario.utils import _POPUP_DISMISS_PATTERNS

_LOGIN_TEMPLATE = "Đăng nhập Facebook"

# Step keys whose values hold nested step lists (branches, loops).
_NESTED_KEYS = ("steps", "then", "else")


def _walk(steps: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Yield every step in document order, descending into branches and loops."""
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        yield step
        for key in _NESTED_KEYS:
            nested = step.get(key)
            if isinstance(nested, list):
                yield from _walk(nested)


def _dismisses_popups(step: dict[str, Any]) -> bool:
    if step.get("type") == "dismiss_popup":
        return True
    # A repeat/branch counts only when a dismiss_popup actually lives inside it.
    return any(
        child.get("type") == "dismiss_popup"
        for key in _NESTED_KEYS
        for child in _walk(step.get(key) or [])
        if isinstance(child, dict)
    )


@pytest.fixture
def login_steps() -> list[dict[str, Any]]:
    template = next(
        (t for t in BUILTIN_TEMPLATES if t.get("name") == _LOGIN_TEMPLATE), None
    )
    assert template is not None, f"builtin template {_LOGIN_TEMPLATE!r} is gone"
    return list(_walk(template.get("steps") or []))


def test_login_step_is_followed_by_a_popup_dismissal_before_the_confirm_gate(
    login_steps: list[dict[str, Any]],
) -> None:
    types = [step.get("type") for step in login_steps]
    assert "login_if_needed" in types, "login template no longer logs in"

    login_at = types.index("login_if_needed")
    confirm_at = next(
        (
            i
            for i, step in enumerate(login_steps)
            if step.get("type") == "platform_session_gate"
            and str(step.get("phase") or "").lower() == "confirm"
            and i > login_at
        ),
        None,
    )
    assert confirm_at is not None, "no confirm gate after login_if_needed"

    between = login_steps[login_at + 1 : confirm_at]
    assert any(_dismisses_popups(step) for step in between), (
        "no popup dismissal between login_if_needed and the confirm gate — "
        "Facebook's post-login popups will hide the readiness markers and the "
        "gate will fail a login that actually succeeded"
    )


def test_login_restarts_facebook_after_totp_before_confirming_session(
    login_steps: list[dict[str, Any]],
) -> None:
    by_id = {
        str(step.get("id")): step
        for step in login_steps
        if str(step.get("id") or "").startswith("facebook_post_login_")
    }
    required = (
        "facebook_post_login_wait",
        "facebook_post_login_stop",
        "facebook_post_login_restart_delay",
        "facebook_post_login_relaunch",
        "facebook_post_login_relaunch_stable",
    )
    assert all(step_id in by_id for step_id in required)

    types = [step.get("type") for step in login_steps]
    login_at = types.index("login_if_needed")
    confirm_at = next(
        index
        for index, step in enumerate(login_steps)
        if step.get("type") == "platform_session_gate"
        and step.get("phase") == "confirm"
    )
    positions = [
        next(
            index
            for index, step in enumerate(login_steps)
            if step.get("id") == step_id
        )
        for step_id in required
    ]
    assert login_at < positions[0] < positions[1] < positions[2] < positions[3]
    assert positions[3] < positions[4] < confirm_at

    assert by_id["facebook_post_login_wait"] == {
        "id": "facebook_post_login_wait",
        "type": "wait",
        "seconds": 5,
    }
    assert by_id["facebook_post_login_stop"] == {
        "id": "facebook_post_login_stop",
        "type": "stop_app",
        "package": "com.facebook.katana",
    }
    assert by_id["facebook_post_login_restart_delay"] == {
        "id": "facebook_post_login_restart_delay",
        "type": "wait",
        "seconds": 1,
    }
    relaunch = by_id["facebook_post_login_relaunch"]
    assert relaunch["type"] == "launch_app"
    assert relaunch["package"] == "com.facebook.katana"
    assert relaunch["stop_before"] is True
    assert relaunch["use_monkey"] is True
    assert relaunch["wait_after"] == 3
    assert by_id["facebook_post_login_relaunch_stable"] == {
        "id": "facebook_post_login_relaunch_stable",
        "type": "wait_stable",
        "timeout": 8,
        "stable_duration": 0.5,
    }

    popup_at = next(
        index
        for index, step in enumerate(login_steps)
        if step.get("id") == "facebook_post_login_popups"
    )
    assert positions[4] < popup_at < confirm_at


def test_login_opens_own_profile_then_syncs_after_session_confirmation(
    login_steps: list[dict[str, Any]],
) -> None:
    confirm_at = next(
        index
        for index, step in enumerate(login_steps)
        if step.get("type") == "platform_session_gate"
        and step.get("phase") == "confirm"
    )
    open_profile_at = next(
        index
        for index, step in enumerate(login_steps)
        if step.get("id") == "facebook_open_own_profile"
    )
    sync_at = next(
        index
        for index, step in enumerate(login_steps)
        if step.get("id") == "facebook_read_own_profile"
    )

    assert confirm_at < open_profile_at < sync_at
    assert login_steps[sync_at]["type"] == "social_sync_connections"
    open_profile = login_steps[open_profile_at]
    assert open_profile["then"] == [
        {
            "type": "tap_selector",
            "by": "content-desc",
            "value": "Đi tới trang cá nhân",
            "timeout": 5,
        }
    ]
    assert open_profile["else"] == [
        {
            "type": "if_element",
            "by": "content-desc",
            "value": "Trang cá nhân",
            "timeout": 2,
            "then": [
                {
                    "type": "tap_selector",
                    "by": "content-desc",
                    "value": "Trang cá nhân",
                    "timeout": 5,
                }
            ],
            "else": [],
        }
    ]


def test_post_login_dismissal_repeats(login_steps: list[dict[str, Any]]) -> None:
    """One pass is not enough: the next popup renders after the previous closes."""
    repeats = [
        step
        for step in login_steps
        if step.get("type") == "repeat" and _dismisses_popups(step)
    ]
    assert repeats, "post-login popup dismissal must repeat, not run once"
    assert any(int(step.get("count") or 0) >= 3 for step in repeats)


def test_login_dismisses_popups_before_preflight_gate(
    login_steps: list[dict[str, Any]],
) -> None:
    """Popup stacks can hide readiness before the login branch is selected."""
    preflight_at = next(
        (
            i
            for i, step in enumerate(login_steps)
            if step.get("type") == "platform_session_gate"
            and str(step.get("phase") or "").lower() == "preflight"
        ),
        None,
    )
    assert preflight_at is not None, "no preflight gate in login template"

    before_preflight = login_steps[:preflight_at]
    repeats = [
        step
        for step in before_preflight
        if step.get("type") == "repeat" and _dismisses_popups(step)
    ]
    assert repeats, "preflight must drain Facebook popups before reading readiness"
    assert any(int(step.get("count") or 0) >= 5 for step in repeats)


def test_login_dismisses_popups_after_confirm_gate(
    login_steps: list[dict[str, Any]],
) -> None:
    """Some Facebook quick-promotion screens appear only after readiness confirms."""
    confirm_at = next(
        (
            i
            for i, step in enumerate(login_steps)
            if step.get("type") == "platform_session_gate"
            and str(step.get("phase") or "").lower() == "confirm"
        ),
        None,
    )
    assert confirm_at is not None, "no confirm gate in login template"

    after_confirm = login_steps[confirm_at + 1 :]
    repeats = [
        step
        for step in after_confirm
        if step.get("type") == "repeat" and _dismisses_popups(step)
    ]
    assert repeats, "post-confirm Facebook popups must be dismissed"
    assert any(int(step.get("count") or 0) >= 5 for step in repeats)


def test_popup_dismissal_matches_facebook_uppercase_skip_label() -> None:
    labels = {value for by, value in _POPUP_DISMISS_PATTERNS if by == "text"}
    assert "BỎ QUA" in labels


def test_ready_session_branch_still_dismisses_popups() -> None:
    """An active session can still be blocked by quick-promotion popups."""
    template = next(
        (t for t in BUILTIN_TEMPLATES if t.get("name") == _LOGIN_TEMPLATE), None
    )
    assert template is not None, f"builtin template {_LOGIN_TEMPLATE!r} is gone"

    guard = next(
        (
            step
            for step in _walk(template.get("steps") or [])
            if step.get("type") == "if_variable"
            and step.get("name") == "PLATFORM_SESSION_READY"
        ),
        None,
    )
    assert guard is not None, "login template no longer checks session readiness"

    ready_branch = guard.get("then") or []
    repeats = [
        step
        for step in ready_branch
        if isinstance(step, dict)
        and step.get("type") == "repeat"
        and _dismisses_popups(step)
    ]
    assert repeats, (
        "ready-session branch must dismiss Facebook quick-promotion popups; "
        "otherwise active sessions skip cleanup and leave overlays on screen"
    )
    assert any(int(step.get("count") or 0) >= 5 for step in repeats)


def test_login_uses_existing_account_path_before_filling_fields(
    login_steps: list[dict[str, Any]],
) -> None:
    types = [step.get("type") for step in login_steps]
    login_at = types.index("login_if_needed")
    before_login = login_steps[:login_at]

    # Both labels are carried by the content-desc of a Bloks Button; the node
    # holding the same string as *text* is clickable=false. Matching by text
    # only ever worked because the two boxes overlap. Dumped from a V2352A.
    assert any(
        step.get("type") == "tap_selector"
        and step.get("by") == "content-desc"
        and step.get("value") == "Tôi có trang cá nhân rồi"
        for step in before_login
    ), "Vietnamese Facebook existing-account path must be opened before locating username"
    assert any(
        step.get("type") == "tap_selector"
        and step.get("by") == "content-desc"
        and step.get("value") == "I already have a profile"
        for step in before_login
    ), "English Facebook existing-account path must be opened before locating username"


def test_login_switches_app_language_to_vietnamese_before_logging_in(
    login_steps: list[dict[str, Any]],
) -> None:
    """Every step after the login is written in Vietnamese labels."""
    types = [step.get("type") for step in login_steps]
    login_at = types.index("login_if_needed")
    before_login = login_steps[:login_at]

    assert any(
        step.get("type") == "tap_selector"
        and step.get("by") == "content-desc"
        and step.get("value") == "Tiếng Việt"
        for step in before_login
    ), (
        "a fresh install comes up in English (US); without the language switch "
        "the post-login popup labels and 'Trang cá nhân' never match"
    )


def test_login_detect_logged_in_markers_are_facebook_specific() -> None:
    """A bare Home label can appear outside Facebook's authenticated feed."""
    template = next(
        (t for t in BUILTIN_TEMPLATES if t.get("name") == _LOGIN_TEMPLATE), None
    )
    assert template is not None, f"builtin template {_LOGIN_TEMPLATE!r} is gone"

    login_step = next(
        (
            step
            for step in _walk(template.get("steps") or [])
            if step.get("type") == "login_if_needed"
        ),
        None,
    )
    assert login_step is not None, "login template no longer logs in"

    any_text = (
        login_step.get("profile", {})
        .get("login_recipe", {})
        .get("detect_logged_in", {})
        .get("any_text", [])
    )
    assert "Home" not in any_text
    assert {"Trang chủ", "Tìm kiếm", "Bạn đang nghĩ gì?", "What's on your mind"}.issubset(
        set(any_text)
    )
