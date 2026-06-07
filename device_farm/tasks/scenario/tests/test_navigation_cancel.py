"""Regression tests for cancellable navigation loops."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))

from unittest.mock import MagicMock


class _CancelAfterWait:
    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def wait(self, _timeout):
        self._set = True
        return True


def _make_sc():
    from tasks.scenario.context import ScenarioContext

    device = MagicMock()
    device.serial = "test"
    device.screen_width = 1080
    device.screen_height = 1920
    return ScenarioContext.from_args(device, {"steps": []})


def test_scroll_down_stops_repeats_when_cancelled_during_pause():
    from tasks.scenario.steps.navigation import handle_scroll_down

    sc = _make_sc()
    sc.cancel_event = _CancelAfterWait()
    step = {"type": "scroll_down", "repeats": 5, "pause_seconds": 0.1}
    result = {"index": 0, "type": "scroll_down", "ok": True}

    handle_scroll_down(sc, step, 0, result)

    assert sc.device.swipe.call_count == 1
    assert result["ok"] is False
    assert result["cancelled"] is True


def test_scroll_to_keeps_cancelled_status_when_cancelled_during_pause():
    from tasks.scenario.steps.navigation import handle_scroll_to

    sc = _make_sc()
    sc.device.u2 = None
    sc.cancel_event = _CancelAfterWait()
    step = {"type": "scroll_to", "by": "text", "value": "Missing", "max_swipes": 5}
    result = {"index": 0, "type": "scroll_to", "ok": True}

    handle_scroll_to(sc, step, 0, result)

    assert sc.device.swipe.call_count == 1
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["message"] == "scroll_to: cancelled by user"
