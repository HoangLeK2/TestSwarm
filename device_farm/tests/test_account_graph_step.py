"""Reading an account's connection count, and routing on it.

The count decides which playbook an account runs, so the failure that matters
most is not "the read failed" — it is a read that quietly produces the wrong
stage.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.account_graph import (
    STAGE_SEED,
    STAGE_STEADY,
    STAGE_TRANSITION,
    stage_for_friend_count,
)


class _FakeVarContext:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def set(self, name: str, value: object) -> None:
        self.values[name] = value

    def resolve(self, value: object, step_index: int = 0) -> object:
        del step_index
        return value


class _FakeDevice:
    def __init__(self, flow_result: object) -> None:
        self.flow_result = flow_result
        self.calls: list[tuple] = []

    def u2_flow(self, name, params, timeout=None, priority=None):
        self.calls.append((name, params, timeout, priority))
        if isinstance(self.flow_result, Exception):
            raise self.flow_result
        return self.flow_result


def _context(device: _FakeDevice) -> SimpleNamespace:
    return SimpleNamespace(
        serial="PHONE-01",
        device=device,
        cancel_event=None,
        ctx={"vars": {}},
        var_ctx=_FakeVarContext(),
        capture_dir=None,
        scenario={},
        execution_id=None,
    )


def _step(**overrides) -> dict:
    step = {
        "id": "s1",
        "type": "social_sync_connections",
        "platform": "facebook",
        # Persistence needs a database; these tests cover the read and the
        # routing, which is what scenarios branch on.
        "persist": False,
    }
    step.update(overrides)
    return step


def _run(device: _FakeDevice, step: dict) -> tuple[dict, SimpleNamespace]:
    from tasks.scenario.steps import dispatch_step

    sc = _context(device)
    return dispatch_step(sc, step, 0), sc


# ── Stage routing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("count", "stage"),
    [
        (0, STAGE_SEED),
        (19, STAGE_SEED),
        (20, STAGE_TRANSITION),
        (49, STAGE_TRANSITION),
        (50, STAGE_STEADY),
        (500, STAGE_STEADY),
    ],
)
def test_stage_boundaries(count: int, stage: str) -> None:
    assert stage_for_friend_count(count) == stage


def test_unknown_count_is_treated_as_the_coldest_account() -> None:
    """Assuming an account is warmer than it is points it at suggestions that
    will not convert — the expensive direction to be wrong in."""
    assert stage_for_friend_count(None) == STAGE_SEED


def test_stage_thresholds_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("ACCOUNT_STAGE_SEED_CEILING", "5")
    monkeypatch.setenv("ACCOUNT_STAGE_STEADY_FLOOR", "10")
    assert stage_for_friend_count(4) == STAGE_SEED
    assert stage_for_friend_count(5) == STAGE_TRANSITION
    assert stage_for_friend_count(10) == STAGE_STEADY


# ── The step ─────────────────────────────────────────────────────────────────


def test_read_publishes_variables_for_branching() -> None:
    device = _FakeDevice({"found": True, "value": 34, "source": "count_label"})

    result, sc = _run(device, _step())

    assert result["ok"] is True
    assert result["count"] == 34
    assert sc.var_ctx.values["ACCOUNT_FRIEND_COUNT"] == 34
    assert sc.var_ctx.values["ACCOUNT_STAGE"] == STAGE_TRANSITION
    assert sc.var_ctx.values["ACCOUNT_COUNT_READ"] is True


def test_empty_friend_list_is_a_real_zero() -> None:
    """Facebook shows a sentence, not a number, when the list is empty.

    Reported as a successful read of 0 — the account that most needs routing
    must not be the one that comes back unclassified.
    """
    device = _FakeDevice(
        {
            "found": True,
            "value": 0,
            "source": "empty_state",
            "evidence": "Không có bạn bè nào để hiển thị",
        }
    )

    result, sc = _run(device, _step())

    assert result["count"] == 0
    assert result["source"] == "empty_state"
    assert sc.var_ctx.values["ACCOUNT_STAGE"] == STAGE_SEED


def test_unreadable_screen_does_not_invent_a_count() -> None:
    """Wrong screen is not an error, but it must not leave a stale number
    behind for the next branch to read."""
    device = _FakeDevice({"found": False, "reason": "count_not_visible"})

    result, sc = _run(device, _step())

    assert result["ok"] is True
    assert result["outcome"] == "count_not_visible"
    assert result["count_read"] is False
    assert sc.var_ctx.values["ACCOUNT_COUNT_READ"] is False
    assert "ACCOUNT_FRIEND_COUNT" not in sc.var_ctx.values
    assert "ACCOUNT_STAGE" not in sc.var_ctx.values


def test_flow_failure_is_reported_not_swallowed() -> None:
    device = _FakeDevice(RuntimeError("u2 flow not available for this device"))

    result, _sc = _run(device, _step())

    assert result["ok"] is False
    assert result["outcome"] == "count_read_failed"
    assert "u2 flow not available" in result["message"]


def test_unsupported_platform_is_rejected_before_touching_the_device() -> None:
    device = _FakeDevice({"found": True, "value": 10})

    result, _sc = _run(device, _step(platform="tiktok"))

    assert result["ok"] is False
    assert result["outcome"] == "unsupported_platform"
    assert device.calls == []


def test_followers_do_not_set_the_friend_stage() -> None:
    device = _FakeDevice({"found": True, "value": 1500, "source": "count_label"})

    result, sc = _run(device, _step(metric="followers"))

    assert result["count"] == 1500
    assert result["stage"] is None
    assert "ACCOUNT_FRIEND_COUNT" not in sc.var_ctx.values


# ── Surviving a uiautomator restart ──────────────────────────────────────────


class _FlakyDevice:
    """Fails with a transient u2 error N times, then succeeds."""

    def __init__(self, failures: int, error: str, result: object) -> None:
        self.remaining = failures
        self.error = error
        self.result = result
        self.attempts = 0

    def u2_flow(self, name, params, timeout=None, priority=None):
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise RuntimeError(self.error)
        return self.result


def _fast_backoff(monkeypatch) -> None:
    import tasks.scenario.steps.social_actions as sa

    monkeypatch.setattr(sa, "_U2_RECOVERY_BACKOFF_S", (0.0, 0.0, 0.0))


def test_step_waits_out_a_uiautomator_restart(monkeypatch) -> None:
    """uiautomator dies on its own; the farm restarts it asynchronously.

    Before this, the step that happened to be running when the session went
    away failed outright and took the whole execution to the dead-letter queue —
    two of five real-device runs died that way in one afternoon.
    """
    _fast_backoff(monkeypatch)
    device = _FlakyDevice(
        failures=2,
        error="u2 flow not available for this device",
        result={"found": True, "value": 7, "source": "count_label"},
    )

    result, sc = _run(device, _step())

    assert result["ok"] is True
    assert result["count"] == 7
    assert device.attempts == 3
    assert sc.var_ctx.values["ACCOUNT_FRIEND_COUNT"] == 7


def test_a_persistently_dead_session_still_fails(monkeypatch) -> None:
    _fast_backoff(monkeypatch)
    device = _FlakyDevice(
        failures=99,
        error="u2 flow not available for this device",
        result=None,
    )

    result, _sc = _run(device, _step())

    assert result["ok"] is False
    assert result["outcome"] == "count_read_failed"


def test_a_real_failure_is_not_retried(monkeypatch) -> None:
    """Retrying a flow that ran and disagreed would duplicate its side effects."""
    _fast_backoff(monkeypatch)
    device = _FlakyDevice(
        failures=99,
        error="element not found on screen",
        result=None,
    )

    result, _sc = _run(device, _step())

    assert result["ok"] is False
    assert device.attempts == 1


# ── the account's own display name ──────────────────────────────────────────


def test_display_name_is_exposed_and_reported_with_the_count() -> None:
    device = _FakeDevice(
        {
            "value": {
                "found": True,
                "metric": "friends",
                "value": 2,
                "display_name": "Ngân Thanh Thanh Võ",
            }
        }
    )

    result, sc = _run(device, _step())

    assert result["display_name"] == "Ngân Thanh Thanh Võ"
    assert sc.var_ctx.values["ACCOUNT_DISPLAY_NAME"] == "Ngân Thanh Thanh Võ"
    assert sc.ctx["vars"]["ACCOUNT_DISPLAY_NAME"] == "Ngân Thanh Thanh Võ"


def test_a_refused_name_leaves_the_variable_unset_and_says_why() -> None:
    """agent-boot refuses when the header is ambiguous. Falling back to the
    nearest label would record a stranger as the account's own name."""
    device = _FakeDevice(
        {
            "value": {
                "found": True,
                "metric": "friends",
                "value": 2,
                "display_name": None,
                "display_name_reason": "not_own_profile",
            }
        }
    )

    result, sc = _run(device, _step())

    assert result["count"] == 2
    assert "display_name" not in result
    assert result["display_name_reason"] == "not_own_profile"
    assert "ACCOUNT_DISPLAY_NAME" not in sc.var_ctx.values


def test_the_name_survives_a_count_that_scrolled_off_screen() -> None:
    """One dump answers both questions; losing one must not lose the other."""
    device = _FakeDevice(
        {
            "value": {
                "found": False,
                "reason": "count_not_visible",
                "display_name": "Ngân Thanh Thanh Võ",
            }
        }
    )

    result, sc = _run(device, _step())

    assert result["count_read"] is False
    assert sc.var_ctx.values["ACCOUNT_DISPLAY_NAME"] == "Ngân Thanh Thanh Võ"
