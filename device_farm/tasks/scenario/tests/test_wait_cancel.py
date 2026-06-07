"""Regression tests for cancellable wait steps."""
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


def _make_sc():
    from tasks.scenario.context import ScenarioContext

    device = MagicMock()
    device.serial = "test"
    device.screen_width = 1080
    device.screen_height = 1920
    return ScenarioContext.from_args(device, {"steps": []})


def test_wait_marks_result_cancelled_when_cancelled_during_sleep():
    from tasks.scenario.steps.wait import handle_wait

    sc = _make_sc()
    sc.cancel_event = _CancelOnWait()
    step = {"type": "wait", "seconds": 5}
    result = {"index": 0, "type": "wait", "ok": True}

    handle_wait(sc, step, 0, result)

    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["message"] == "wait: cancelled by user"
