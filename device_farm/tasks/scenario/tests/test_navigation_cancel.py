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
    del sc.device.u2_flow
    sc.cancel_event = _CancelAfterWait()
    step = {"type": "scroll_to", "by": "text", "value": "Missing", "max_swipes": 5}
    result = {"index": 0, "type": "scroll_to", "ok": True}

    handle_scroll_to(sc, step, 0, result)

    assert sc.device.swipe.call_count == 1
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["message"] == "scroll_to: cancelled by user"


def test_scroll_to_uses_u2_flow_fast_path(monkeypatch):
    from tasks.scenario.steps import navigation
    from tasks.scenario.steps.navigation import handle_scroll_to

    sc = _make_sc()
    sc.device.u2_flow.return_value = {"found": True, "swipes": 4}
    slept: list[float] = []
    monkeypatch.setattr(navigation.time, "sleep", lambda seconds: slept.append(seconds))
    step = {"type": "scroll_to", "by": "description", "value": "Bình luận", "max_swipes": 50}
    result = {"index": 0, "type": "scroll_to", "ok": True}

    handle_scroll_to(sc, step, 0, result)

    sc.device.u2_flow.assert_called_once()
    flow_name, params = sc.device.u2_flow.call_args.args[:2]
    assert flow_name == "swipe_until_found"
    assert params["selector"]["spec"]["by"] == "description"
    assert params["selector"]["spec"]["value"] == "Bình luận"
    assert params["direction"] == "up"
    assert params["max_swipes"] == 8
    assert result["message"] == "scroll_to found description='Bình luận' after 4 swipe(s)"
    assert result["scroll_to_driver"] == "u2_flow"
    assert sc.device.swipe.call_count == 0
    assert slept == []


def test_scroll_to_caps_facebook_comment_target_fast_path(monkeypatch):
    from tasks.scenario.steps import navigation
    from tasks.scenario.steps.navigation import handle_scroll_to

    sc = _make_sc()
    sc.device.u2_flow.return_value = {"found": False, "swipes": 8}
    monkeypatch.setattr(navigation.time, "sleep", lambda _seconds: None)
    step = {"type": "scroll_to", "by": "description", "value": "Bình luận", "max_swipes": 50}
    result = {"index": 0, "type": "scroll_to", "ok": True}

    handle_scroll_to(sc, step, 0, result)

    _, params = sc.device.u2_flow.call_args.args[:2]
    assert params["max_swipes"] == 8
    assert result["ok"] is False
    assert result["scroll_to_swipes"] == 8
    assert result["scroll_to_max_swipes_requested"] == 50
    assert result["scroll_to_max_swipes_effective"] == 8
    assert sc.ctx["_fb_comment_target_missing"]["max_swipes_effective"] == 8


def test_scroll_to_skips_facebook_comment_target_while_post_extract_is_pending():
    from tasks.scenario.steps.navigation import handle_scroll_to

    sc = _make_sc()
    marker = {
        "reason_code": "post_extract_pending",
        "source_index": 2,
    }
    sc.ctx["_fb_comment_target_missing"] = marker
    step = {
        "type": "scroll_to",
        "by": "description",
        "value": "Bình luận",
        "max_swipes": 50,
    }
    result = {"index": 0, "type": "scroll_to", "ok": True}

    handle_scroll_to(sc, step, 0, result)

    assert result["skipped"] is True
    assert result["comment_target_missing"] is True
    assert result["comment_target_missing_detail"] == marker
    assert result["message"] == "scroll_to: skipped — current post extract not ready"
    assert sc.ctx["_fb_comment_target_missing"] == marker
    sc.device.u2_flow.assert_not_called()
    assert sc.device.swipe.call_count == 0


def test_scroll_to_falls_back_to_loop_when_u2_flow_unavailable(monkeypatch):
    from tasks.scenario.steps import navigation
    from tasks.scenario.steps.navigation import handle_scroll_to

    sc = _make_sc()
    del sc.device.u2_flow
    sc.device.u2 = None
    monkeypatch.setattr(navigation.time, "sleep", lambda _seconds: None)
    step = {"type": "scroll_to", "by": "text", "value": "Continue", "max_swipes": 5}
    result = {"index": 0, "type": "scroll_to", "ok": True}

    handle_scroll_to(sc, step, 0, result)

    assert "scroll_to_driver" not in result
    assert sc.device.swipe.call_count == 5
