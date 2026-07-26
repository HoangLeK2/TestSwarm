from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeVarContext:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set(self, name: str, value: object) -> None:
        self.values[name] = value


class _FakeDevice:
    def __init__(self, *hierarchies: str) -> None:
        self._hierarchies = list(hierarchies)
        self.taps: list[tuple[int, int]] = []
        self.keys: list[str] = []

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        assert force_refresh is True
        if len(self._hierarchies) > 1:
            return self._hierarchies.pop(0)
        return self._hierarchies[0]

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def key(self, name: str) -> None:
        self.keys.append(name)


def _xml(*nodes: str) -> str:
    return f"<hierarchy>{''.join(nodes)}</hierarchy>"


def _node(
    label: str,
    *,
    selected: bool = False,
    bounds: str = "[10,20][110,70]",
) -> str:
    return (
        f'<node text="{label}" content-desc="{label}" '
        f'clickable="true" selected="{str(selected).lower()}" '
        f'bounds="{bounds}" />'
    )


def _context(device: _FakeDevice) -> SimpleNamespace:
    return SimpleNamespace(
        serial="PHONE-01",
        device=device,
        cancel_event=None,
        ctx={"vars": {}},
        var_ctx=_FakeVarContext(),
    )


@pytest.mark.parametrize(
    ("step_type", "before_label", "after_label", "expected_state"),
    [
        ("content_interaction", "Thích", "Bỏ Thích", "liked"),
        ("connection_request", "Thêm bạn bè", "Hủy lời mời", "request_pending"),
        ("community_membership", "Tham gia nhóm", "Đang chờ", "join_pending"),
    ],
)
def test_social_action_taps_current_screen_and_verifies_state(
    step_type: str,
    before_label: str,
    after_label: str,
    expected_state: str,
) -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node(before_label)), _xml(_node(after_label)))
    sc = _context(device)
    step = {
        "type": step_type,
        "platform": "facebook",
        "timeout": 0.1,
        "poll": 0.01,
        "verify_timeout": 0.1,
        "settle_seconds": 0,
        "save_as": "SOCIAL_RESULT",
    }

    result = dispatch_step(sc, step, 0)

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert result["state"] == expected_state
    assert result["action_performed"] is True
    assert device.taps == [(60, 45)]
    assert device.keys == []
    assert sc.var_ctx.values["SOCIAL_RESULT"]["state"] == expected_state
    assert sc.ctx["vars"]["SOCIAL_RESULT"]["outcome"] == "applied"


def test_social_action_is_idempotent_when_membership_is_already_satisfied() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Đã tham gia")))
    result = dispatch_step(
        _context(device),
        {
            "type": "community_membership",
            "platform": "facebook",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "already_applied"
    assert result["state"] == "member"
    assert result["action_performed"] is False
    assert device.taps == []
    assert device.keys == []


def test_social_action_rejects_unknown_platform_without_touching_device() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(_xml(_node("Like")))
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "unsupported-platform",
            "action": "like",
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "unsupported_platform"
    assert device.taps == []


def test_social_action_fails_closed_when_post_state_cannot_be_verified() -> None:
    from tasks.scenario.steps import dispatch_step

    unchanged = _xml(_node("Like"))
    device = _FakeDevice(unchanged, unchanged)
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.02,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "verification_failed"
    assert result["action_performed"] is True
    assert device.taps == [(60, 45)]


def test_social_action_adapter_registry_can_add_future_platforms() -> None:
    from services.social_actions import (
        get_social_action_adapter,
        register_social_action_adapter,
        unregister_social_action_adapter,
    )
    from services.social_actions.contract import SocialActionObservation

    class _FutureAdapter:
        platform = "future-network"

        def observe(self, **_: object) -> SocialActionObservation:
            return SocialActionObservation(state="connected")

    adapter = _FutureAdapter()
    register_social_action_adapter(adapter)
    try:
        assert get_social_action_adapter("FUTURE-NETWORK") is adapter
    finally:
        unregister_social_action_adapter(adapter.platform)


def test_social_action_fails_closed_when_multiple_targets_are_visible() -> None:
    from tasks.scenario.steps import dispatch_step

    device = _FakeDevice(
        _xml(
            _node("Like", bounds="[10,20][110,70]"),
            _node("Like", bounds="[10,220][110,270]"),
        )
    )
    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "timeout": 0.1,
            "poll": 0.01,
        },
        0,
    )

    assert result["ok"] is False
    assert result["outcome"] == "ambiguous_target"
    assert device.taps == []


def test_social_action_verifies_state_near_the_tapped_target() -> None:
    from tasks.scenario.steps import dispatch_step

    unrelated_liked = _node("Unlike", bounds="[10,20][110,70]")
    target_before = _node("Like", bounds="[10,220][110,270]")
    target_after = _node("Unlike", bounds="[10,220][110,270]")
    device = _FakeDevice(
        _xml(unrelated_liked, target_before),
        _xml(unrelated_liked, target_after),
    )

    result = dispatch_step(
        _context(device),
        {
            "type": "content_interaction",
            "platform": "facebook",
            "action": "like",
            "timeout": 0.1,
            "poll": 0.01,
            "verify_timeout": 0.1,
            "settle_seconds": 0,
        },
        0,
    )

    assert result["ok"] is True
    assert result["outcome"] == "applied"
    assert device.taps == [(60, 245)]
