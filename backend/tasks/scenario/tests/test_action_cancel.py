"""Regression tests for cancelling active single-step actions."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))

from unittest.mock import MagicMock


class _CancelOnWait:
    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def wait(self, _timeout):
        self._set = True
        return True


def _make_sc(device=None):
    from tasks.scenario.context import ScenarioContext

    d = device or MagicMock()
    d.serial = "test"
    d.screen_width = 1080
    d.screen_height = 1920
    return ScenarioContext.from_args(d, {"steps": []})


def test_tap_ratio_marks_cancelled_during_post_tap_wait():
    from tasks.scenario.steps.interaction import handle_tap_ratio

    device = MagicMock()
    sc = _make_sc(device)
    sc.cancel_event = _CancelOnWait()
    result = {"index": 0, "type": "tap_ratio", "ok": True}

    handle_tap_ratio(sc, {"type": "tap_ratio", "x": 0.5, "y": 0.5}, 0, result)

    device.tap.assert_called_once()
    assert result["ok"] is False
    assert result["cancelled"] is True


def test_input_text_stops_before_fallback_strategy_when_cancelled():
    from tasks.scenario.steps.input import handle_input_text

    device = MagicMock()
    u2 = MagicMock()
    cancel_event = _CancelOnWait()

    def _cancel_and_fail(_text):
        cancel_event._set = True
        raise RuntimeError("u2 failed")

    u2.send_keys.side_effect = _cancel_and_fail
    device.u2 = u2
    sc = _make_sc(device)
    sc.cancel_event = cancel_event
    result = {"index": 0, "type": "input_text", "ok": True}

    handle_input_text(sc, {"type": "input_text", "text": "hello"}, 0, result)

    u2.send_keys.assert_called_once_with("hello")
    device._a11y_mutate.assert_not_called()
    assert result["ok"] is False
    assert result["cancelled"] is True


def test_input_text_clear_first_replaces_focused_field_when_supported():
    from tasks.scenario.steps.input import handle_input_text

    device = MagicMock()
    u2 = MagicMock()
    device.u2 = u2
    sc = _make_sc(device)
    result = {"index": 0, "type": "input_text", "ok": True}

    handle_input_text(
        sc,
        {"type": "input_text", "text": "Booking.com", "clear_first": True},
        0,
        result,
    )

    u2.adb_keyboard_replace_text.assert_called_once_with("Booking.com")
    u2.clear_text.assert_not_called()
    u2.send_keys.assert_not_called()
    assert result["ok"] is True


def test_input_text_clear_first_clears_focused_field_before_typing_without_replace():
    from tasks.scenario.steps.input import handle_input_text

    device = MagicMock()
    u2 = MagicMock(spec=["clear_text", "send_keys"])
    device.u2 = u2
    sc = _make_sc(device)
    result = {"index": 0, "type": "input_text", "ok": True}

    handle_input_text(
        sc,
        {"type": "input_text", "text": "Booking.com", "clear_first": True},
        0,
        result,
    )

    u2.clear_text.assert_called_once()
    u2.send_keys.assert_called_once_with("Booking.com")
    assert result["ok"] is True


def test_launch_app_marks_cancelled_during_wait_after():
    from tasks.scenario.steps.navigation import handle_launch_app

    device = MagicMock()
    device._u2 = None
    sc = _make_sc(device)
    sc.cancel_event = _CancelOnWait()
    result = {"index": 0, "type": "launch_app", "ok": True}

    handle_launch_app(
        sc,
        {"type": "launch_app", "package": "com.example", "wait_after": 2},
        0,
        result,
    )

    device.launch_app.assert_called_once()
    assert result["ok"] is False
    assert result["cancelled"] is True


def test_retry_find_element_uses_cancelable_wait():
    from tasks.scenario.utils import _retry_find_element

    u2 = MagicMock(spec_set=["find_element"])
    u2.find_element.return_value = None
    cancel_event = _CancelOnWait()

    found = _retry_find_element(
        u2,
        "text",
        "Missing",
        timeout=5.0,
        poll=1.0,
        cancel_event=cancel_event,
    )

    assert found is None
    assert cancel_event.is_set() is True
    assert u2.find_element.call_count == 1


def test_retry_find_element_prefers_single_bounds_probe():
    from tasks.scenario.utils import _retry_find_element

    u2 = MagicMock()
    u2.find_element_with_bounds_spec.return_value = {
        "eid": "text::OK",
        "bounds": {"left": 1, "top": 2, "right": 3, "bottom": 4},
    }

    found = _retry_find_element(u2, "text", "OK", timeout=3.0, poll=0.25)

    assert found == u2.find_element_with_bounds_spec.return_value
    u2.find_element_with_bounds_spec.assert_called_once()
    assert u2.find_element_with_bounds_spec.call_args.kwargs["timeout"] == 0.25
    u2.find_element_spec.assert_not_called()
