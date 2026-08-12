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


def test_loop_exposes_loop_iter_to_runtime_variables():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    observed: list[tuple[int, int]] = []

    def nested(_sc, _steps):
        observed.append(
            (
                _sc.var_ctx.resolve("${_loop_iter}"),
                _sc.var_ctx.resolve("${PAGE_INDEX}"),
            )
        )
        return {"success": True}

    step = {
        "type": "loop",
        "count": 3,
        "loop_var": "PAGE_INDEX",
        "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch("tasks.scenario.steps.control_flow._run_nested", side_effect=nested):
        handle_loop(sc, step, 0, result)

    assert observed == [(0, 0), (1, 1), (2, 2)]
    assert result["iterations"] == 3


def test_set_variable_selects_list_item_by_resolved_index():
    from tasks.scenario.steps.control_flow import handle_set_variable

    sc = _make_sc()
    sc.var_ctx.set("PAGE_INDEX", 1)
    sc.var_ctx.set(
        "PAGE_TARGETS",
        ["Go2Joy Vietnam", "Booking.com"],
    )
    step = {
        "type": "set_variable",
        "name": "PAGE_CONTEXT",
        "from_list": "${PAGE_TARGETS}",
        "from_list_index": "${PAGE_INDEX}",
    }
    sc.steps = [step]
    result = {"index": 0, "type": "set_variable", "ok": True}

    handle_set_variable(sc, step, 0, result)

    assert sc.var_ctx.resolve("${PAGE_CONTEXT}") == "Booking.com"
    assert "from_list_index=1" in result["message"]


def test_loop_page_index_walks_attached_pages_in_order():
    from tasks.scenario.steps.control_flow import handle_loop, handle_set_variable

    sc = _make_sc()
    sc.var_ctx.set("PAGE_TARGETS", ["Go2Joy Vietnam", "Booking.com"])
    observed: list[str] = []
    nested_steps = [
        {
            "type": "set_variable",
            "name": "PAGE_SEARCH_CURRENT",
            "from_list": "${PAGE_TARGETS}",
            "from_list_index": "${PAGE_INDEX}",
        }
    ]

    def nested(_sc, steps):
        step = steps[0]
        result = {"index": 0, "type": "set_variable", "ok": True}
        handle_set_variable(_sc, step, 0, result)
        observed.append(_sc.var_ctx.resolve("${PAGE_SEARCH_CURRENT}"))
        return {"success": True}

    result = {"index": 0, "type": "loop", "ok": True}
    step = {
        "type": "loop",
        "count": 2,
        "loop_var": "PAGE_INDEX",
        "steps": nested_steps,
    }

    with patch("tasks.scenario.steps.control_flow._run_nested", side_effect=nested):
        handle_loop(sc, step, 0, result)

    assert observed == ["Go2Joy Vietnam", "Booking.com"]
    assert result["iterations"] == 2


def test_if_variable_preserves_loop_branch_variables_until_runtime():
    from tasks.scenario.context import ScenarioContext
    from tasks.scenario.executor import ScenarioExecutor
    from unittest.mock import MagicMock

    device = MagicMock()
    device.serial = "test"
    device.screen_width = 1080
    device.screen_height = 1920
    sc = ScenarioContext.from_args(
        device,
        {
            "variables": {
                "FACEBOOK_SESSION_READY": True,
                "PAGE_COUNT": 2,
                "PAGE_TARGETS": ["Go2Joy Vietnam", "Booking.com"],
            },
            "steps": [
                {
                    "type": "if_variable",
                    "name": "FACEBOOK_SESSION_READY",
                    "then": [
                        {
                            "type": "loop",
                            "count": "${PAGE_COUNT}",
                            "loop_var": "PAGE_INDEX",
                            "steps": [
                                {
                                    "type": "set_variable",
                                    "name": "PAGE_SEARCH_CURRENT",
                                    "from_list": "${PAGE_TARGETS}",
                                    "from_list_index": "${PAGE_INDEX}",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    result = ScenarioExecutor(sc).run()

    loop_result = result["step_results"][0]["sub_result"]["step_results"][0]
    observed = [
        iteration["result"]["step_results"][0]["message"]
        for iteration in loop_result["sub_results"]
    ]
    assert "PAGE_SEARCH_CURRENT = 'Go2Joy Vietnam' (from_list_index=0)" in observed[0]
    assert "PAGE_SEARCH_CURRENT = 'Booking.com' (from_list_index=1)" in observed[1]


def test_loop_step_bubbles_nested_edge_extra_summary():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 1, "steps": [{"type": "extract"}]}
    result = {"index": 0, "type": "loop", "ok": True}
    nested_failure = {
        "success": False,
        "failed_message": "edge extra_data failed: post_open_required:post_open_target_not_found",
        "step_results": [
            {
                "index": 0,
                "type": "extract",
                "ok": False,
                "message": "edge extra_data failed: post_open_required:post_open_target_not_found",
                "edge_extra_summary": {
                    "diagnostic": {
                        "reason_code": "post_open_target_not_found",
                        "timing": {"total_ms": 42.0},
                    }
                },
                "extra_data_total_ms": 42.0,
            }
        ],
    }

    with patch("tasks.scenario.steps.control_flow._run_nested", return_value=nested_failure):
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["edge_extra_summary"]["diagnostic"]["reason_code"] == "post_open_target_not_found"
    assert result["edge_extra_summary"]["diagnostic"]["timing"]["total_ms"] == 42.0
    assert result["extra_data_total_ms"] == 42.0
    assert result["nested_failure"]["step_type"] == "extract"


def test_loop_does_not_persist_failed_iteration_as_complete():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 3, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        return_value={"success": False, "failed_message": "u2_transient_error"},
    ), patch("tasks.scenario.steps.control_flow._persist_loop_iter") as persist:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["iterations"] == 1
    persist.assert_not_called()


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
