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
                "PLATFORM_SESSION_READY": True,
                "PAGE_COUNT": 2,
                "PAGE_TARGETS": ["Go2Joy Vietnam", "Booking.com"],
            },
            "steps": [
                {
                    "type": "if_variable",
                    "name": "PLATFORM_SESSION_READY",
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


def test_loop_executes_random_pick_branch_each_iteration():
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
            "variables": {"VALUES": ["first", "second", "third"]},
            "steps": [
                {
                    "id": "cycle",
                    "type": "loop",
                    "count": 3,
                    "loop_var": "VALUE_INDEX",
                    "steps": [
                        {
                            "id": "pick",
                            "type": "random_pick",
                            "branches": [
                                {
                                    "weight": 1,
                                    "steps": [
                                        {
                                            "id": "unexpected",
                                            "type": "set_variable",
                                            "name": "PICKED",
                                            "value": "wrong",
                                        }
                                    ],
                                },
                                {
                                    "weight": 5,
                                    "steps": [
                                        {
                                            "id": "mark",
                                            "type": "set_variable",
                                            "name": "PICKED",
                                            "from_list": "${VALUES}",
                                            "from_list_index": "${VALUE_INDEX}",
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        },
    )

    with patch("tasks.scenario.steps.control_flow.random.choices", return_value=[1]) as choices:
        result = ScenarioExecutor(sc).run()

    loop_result = result["step_results"][0]
    observed = []
    for iteration in loop_result["sub_results"]:
        random_result = iteration["result"]["step_results"][0]
        mark_result = random_result["sub_result"]["step_results"][0]
        observed.append(
            (
                random_result["chosen_branch"],
                random_result["branch"],
                mark_result["message"],
            )
        )

    assert result["success"] is True
    assert loop_result["iterations"] == 3
    assert choices.call_count == 3
    assert observed == [
        (1, "branch1", "set_variable: PICKED = 'first' (from_list_index=0)"),
        (1, "branch1", "set_variable: PICKED = 'second' (from_list_index=1)"),
        (1, "branch1", "set_variable: PICKED = 'third' (from_list_index=2)"),
    ]


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


# ── stall detection ─────────────────────────────────────────────────────────
#
# A real run spun 88 iterations rescanning a screen that was not a feed. Every
# nested step returned ok, so the loop kept going and the scenario reported
# success. These cover the guard that stops that, and — more importantly — the
# case where it must NOT fire.


def _idle_iteration():
    return {"success": True, "step_results": [{"type": "wait", "ok": True}]}


def _busy_iteration():
    return {
        "success": True,
        "step_results": [
            {"type": "social_scan_posts_interact", "ok": True, "action_performed": True}
        ],
    }


def test_loop_stops_when_no_iteration_performs_an_action():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 50, "stall_after": 5, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: _idle_iteration(),
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False, "an idle loop must fail loudly, not report success"
    assert result["reason_code"] == "loop_stalled"
    assert result["stopped_by"] == "stall"
    assert result["outcome"] == "stalled"
    assert result["stalled_after"] == 5
    assert run_nested.call_count == 5, "must stop at the threshold, not run on"


def test_loop_invalid_count_returns_reason_code():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": "bad", "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["reason_code"] == "loop_invalid_count"
    assert result["stopped_by"] == "config"


def test_preview_step_path_spans_branch_and_loop_iteration():
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
            "variables": {"READY": True},
            "steps": [
                {
                    "id": "gate",
                    "type": "if_variable",
                    "name": "READY",
                    "then": [
                        {
                            "id": "cycle",
                            "type": "loop",
                            "count": 1,
                            "steps": [
                                {
                                    "id": "mark",
                                    "type": "set_variable",
                                    "name": "DONE",
                                    "value": "1",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )

    result = ScenarioExecutor(sc).run()

    leaf = (
        result["step_results"][0]["sub_result"]["step_results"][0]
        ["sub_results"][0]["result"]["step_results"][0]
    )
    assert leaf["step_path"] == "gate.then/cycle#0/mark"
    assert leaf["trace"]["loop_id"] == "cycle"
    assert leaf["trace"]["loop_iter"] == 0
    assert leaf["trace"]["branch"] == "then"


def test_loop_without_stall_after_keeps_old_behaviour():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 4, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: _idle_iteration(),
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True
    assert run_nested.call_count == 4


def test_action_deep_inside_nested_branches_counts_as_progress():
    """The case that would silently break every working friend-flow loop.

    ``connection_request`` sits two ``if_variable`` levels down, and each level
    hangs its branch off ``sub_result``. A shallow read of ``step_results``
    finds only the ``if_variable`` wrappers, calls the iteration idle, and stops
    a loop that was sending requests perfectly well.
    """
    from tasks.scenario.steps.control_flow import handle_loop

    deep = {
        "success": True,
        "step_results": [
            {
                "type": "if_variable",
                "ok": True,
                "sub_result": {
                    "success": True,
                    "step_results": [
                        {
                            "type": "if_variable",
                            "ok": True,
                            "sub_result": {
                                "success": True,
                                "step_results": [
                                    {
                                        "type": "connection_request",
                                        "ok": True,
                                        "action_performed": True,
                                    }
                                ],
                            },
                        }
                    ],
                },
            }
        ],
    }

    sc = _make_sc()
    step = {"type": "loop", "count": 6, "stall_after": 2, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: deep,
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True
    assert run_nested.call_count == 6, "progress was buried, not absent"


def test_idle_streak_resets_when_an_iteration_acts():
    from tasks.scenario.steps.control_flow import handle_loop

    # idle, idle, busy, idle, idle, busy ... never three idle in a row.
    pattern = [_idle_iteration(), _idle_iteration(), _busy_iteration()] * 4
    sc = _make_sc()
    step = {"type": "loop", "count": 12, "stall_after": 3, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=pattern,
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True
    assert run_nested.call_count == 12


def test_stall_message_says_what_to_look_at():
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 20, "stall_after": 3, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: _idle_iteration(),
    ):
        handle_loop(sc, step, 0, result)

    assert "3" in result["message"] and "no action" in result["message"]


def test_rate_limited_iterations_are_not_a_stall():
    """A throttled account is working, not lost.

    Observed on a real run: the comment limiter declined 46 iterations. Counting
    those as idle would trip stall_after and fail the scenario every time an
    account hit its hourly budget — the rate limiter would become an outage
    instead of a safety net.
    """
    from tasks.scenario.steps.control_flow import handle_loop

    throttled = {
        "success": True,
        "step_results": [
            {
                "type": "social_scan_posts_interact",
                "ok": True,
                "outcome": "rate_limited",
                "action_performed": False,
            }
        ],
    }

    sc = _make_sc()
    step = {"type": "loop", "count": 9, "stall_after": 3, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: throttled,
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True
    assert run_nested.call_count == 9


def test_a_screen_with_nothing_on_it_is_still_a_stall():
    """The guard must keep firing for the case it was built for."""
    from tasks.scenario.steps.control_flow import handle_loop

    lost = {
        "success": True,
        "step_results": [
            {
                "type": "social_scan_posts_interact",
                "ok": True,
                "outcome": "screen_is_not_a_feed",
                "action_performed": False,
            }
        ],
    }

    sc = _make_sc()
    step = {"type": "loop", "count": 9, "stall_after": 3, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: lost,
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["outcome"] == "stalled"
    assert run_nested.call_count == 3


# ── long-run behaviour ──────────────────────────────────────────────────────
#
# These campaigns are meant to run for 8 hours. A 5-minute device run says
# nothing about that, so the timescale properties are pinned here instead.


def test_idle_iterations_back_off_instead_of_hammering_the_device():
    """A refused iteration must cost wall-clock, not another hierarchy dump.

    The 20/08 run was refused 46 times in 5 minutes and retried immediately —
    about 4,400 dumps over an 8-hour campaign, every one answered "no".
    """
    from tasks.scenario.steps.control_flow import handle_loop

    throttled = {
        "success": True,
        "step_results": [
            {"type": "social_scan_posts_interact", "ok": True,
             "outcome": "rate_limited", "action_performed": False}
        ],
    }
    slept: list[float] = []

    sc = _make_sc()
    step = {
        "type": "loop", "count": 6, "stall_after": 0,
        "idle_delay_seconds": 30, "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: throttled,
    ), patch(
        "tasks.scenario.steps.control_flow.time.sleep", side_effect=slept.append
    ):
        handle_loop(sc, step, 0, result)

    assert slept == [30] * 6


def test_productive_iterations_are_never_delayed():
    """The backoff must not slow a loop that is working."""
    from tasks.scenario.steps.control_flow import handle_loop

    slept: list[float] = []
    sc = _make_sc()
    step = {
        "type": "loop", "count": 5, "idle_delay_seconds": 30,
        "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: _busy_iteration(),
    ), patch(
        "tasks.scenario.steps.control_flow.time.sleep", side_effect=slept.append
    ):
        handle_loop(sc, step, 0, result)

    assert slept == []


def test_a_throttled_eight_hour_run_never_stalls():
    """The combination that only shows up on a long run.

    Once an account reaches its hourly comment budget the limiter refuses every
    call for the rest of the hour. Those iterations perform nothing, so they
    must back off — and must NOT count toward the stall streak, or the campaign
    dies exactly when the safety limit starts working.
    """
    from tasks.scenario.steps.control_flow import handle_loop

    throttled = {
        "success": True,
        "step_results": [
            {"type": "social_scan_posts_interact", "ok": True,
             "outcome": "rate_limited", "action_performed": False}
        ],
    }
    slept: list[float] = []

    sc = _make_sc()
    step = {
        "type": "loop", "count": 120, "stall_after": 40,
        "idle_delay_seconds": 30, "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: throttled,
    ), patch(
        "tasks.scenario.steps.control_flow.time.sleep", side_effect=slept.append
    ):
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True, "being throttled is not being lost"
    assert len(slept) == 120
    assert sum(slept) == 3600, "120 refused iterations should cost an hour, not seconds"


def test_a_lost_run_still_stops_within_the_configured_window():
    """And the guard must still fire on the case it exists for.

    40 idle iterations at 30s apart is ~20 minutes of doing nothing — the right
    order of magnitude for an 8-hour campaign, where 5 iterations would stop on
    the first quiet stretch of feed.
    """
    from tasks.scenario.steps.control_flow import handle_loop

    lost = {
        "success": True,
        "step_results": [
            {"type": "social_scan_posts_interact", "ok": True,
             "outcome": "screen_is_not_a_feed", "action_performed": False}
        ],
    }
    slept: list[float] = []

    sc = _make_sc()
    step = {
        "type": "loop", "count": 960, "stall_after": 40,
        "idle_delay_seconds": 30, "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        side_effect=lambda *a, **k: lost,
    ) as run_nested, patch(
        "tasks.scenario.steps.control_flow.time.sleep", side_effect=slept.append
    ):
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["outcome"] == "stalled"
    assert run_nested.call_count == 40
    assert sum(slept) == 1200, "~20 minutes, not 8 hours and not 2 minutes"


def test_loop_random_count_range_overrides_fixed_count():
    """The editor always writes a `count`, so the range has to win.

    If `count` won, a scenario configured with a range would silently run the
    editor's default 10 iterations and nothing would report a problem.
    """
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {
        "type": "loop", "count": 1, "count_min": 3, "count_max": 5,
        "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        return_value={"success": True},
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is True
    assert 3 <= result["iterations"] <= 5
    assert result["count_chosen"] == result["iterations"] == run_nested.call_count


def test_loop_half_configured_random_range_fails_as_config_error():
    """Only one bound is a typo. Guessing the other one runs the wrong scenario."""
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    step = {"type": "loop", "count": 2, "count_max": 50, "steps": [{"type": "wait"}]}
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        return_value={"success": True},
    ) as run_nested:
        handle_loop(sc, step, 0, result)

    assert result["ok"] is False
    assert result["stopped_by"] == "config"
    assert "min and max" in result["message"]
    assert run_nested.call_count == 0


def test_loop_random_delay_is_repicked_per_iteration_and_skips_the_last():
    """One value reused for every iteration is a fixed delay, not a random one."""
    from tasks.scenario.steps.control_flow import handle_loop

    sc = _make_sc()
    slept: list[float] = []
    step = {
        "type": "loop", "count": 4,
        "delay_between_min": 2, "delay_between_max": 9,
        "steps": [{"type": "wait"}],
    }
    result = {"index": 0, "type": "loop", "ok": True}

    with patch(
        "tasks.scenario.steps.control_flow._run_nested",
        return_value={"success": True},
    ), patch(
        "tasks.scenario.steps.control_flow.time.sleep", side_effect=slept.append
    ):
        handle_loop(sc, step, 0, result)

    assert len(slept) == 3, "no pause after the last iteration"
    assert all(2 <= value <= 9 for value in slept)
    assert len(set(slept)) > 1, "re-picked per iteration, not once"
