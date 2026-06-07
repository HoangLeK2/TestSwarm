"""Regression tests for control-flow step failure propagation."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

import threading
from unittest.mock import patch


def _make_sc():
    from tasks.scenario.context import ScenarioContext
    from unittest.mock import MagicMock

    device = MagicMock()
    device.serial = "test"
    device.screen_width = 1080
    device.screen_height = 1920
    return ScenarioContext.from_args(device, {"steps": []})


def test_if_step_propagates_nested_failure():
    from tasks.scenario.steps.control_flow import handle_if

    sc = _make_sc()
    step = {"type": "if", "condition": {"type": "posts_count_gte", "count": 0}, "then": [{"type": "wait"}]}
    result = {"index": 0, "type": "if", "ok": True}

    with patch("tasks.scenario.steps.control_flow._run_nested", return_value={"success": False, "failed_message": "boom"}):
        handle_if(sc, step, 0, result)

    assert result["ok"] is False
    assert "failed" in result["message"]


def test_loop_step_propagates_nested_failure():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 3, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=[{"success": True}, {"success": False, "failed_message": "step failed"}],
    ):
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["iterations"] == 2


def test_loop_step_stops_when_cancel_event_set():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    sc.cancel_event = threading.Event()
    sc.cancel_event.set()
    step = {"type": "loop", "count": 5, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch("tasks.scenario.steps.control_flow._run_nested") as run_nested:
        handle_loop(sc, step, 0, result)

    run_nested.assert_not_called()
    assert result["ok"] is False
    assert "cancelled" in result["message"]
    assert result["iterations"] == 0


def test_loop_step_stops_when_cancel_event_set_after_iteration_body():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    sc.cancel_event = threading.Event()
    step = {"type": "loop", "count": 5, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    def _run_and_cancel(_sc, _steps, extra_scenario_keys=None):
        sc.cancel_event.set()
        return {"success": True}

    with patch("tasks.scenario.steps.control_flow._run_nested", side_effect=_run_and_cancel) as run_nested:
        handle_loop(sc, step, 0, result)

    assert run_nested.call_count == 1
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["iterations"] == 1


def test_repeat_step_stops_when_cancel_event_set_after_iteration_body():
    from tasks.scenario.steps.control_flow import handle_repeat

    sc = _make_sc()
    sc.cancel_event = threading.Event()
    step = {"type": "repeat", "count": 5, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "repeat", "ok": True}

    def _run_and_cancel(_sc, _steps, extra_scenario_keys=None):
        sc.cancel_event.set()
        return {"success": True}

    with patch("tasks.scenario.steps.control_flow._run_nested", side_effect=_run_and_cancel) as run_nested:
        handle_repeat(sc, step, 0, result)

    assert run_nested.call_count == 1
    assert result["ok"] is False
    assert result["cancelled"] is True
    assert result["iterations"] == 1


def test_loop_count_not_capped_by_max_iterations():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {
        "type": "loop",
        "count": 7,
        "max_iterations": 3,
        "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        return_value={"success": True},
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True
    assert result["iterations"] == 7
    assert run_nested.call_count == 7
