"""Unit tests for ScenarioExecutor."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

import threading
from unittest.mock import MagicMock, patch, call
import pytest


def _make_sc(steps=None, depth=0, cancel_event=None):
    """Build a minimal ScenarioContext with mocked device."""
    from tasks.scenario.context import ScenarioContext

    device = MagicMock()
    device.serial = "test"
    device.screen_width = 1080
    device.screen_height = 1920

    sc = ScenarioContext.from_args(
        device, {"steps": steps or []},
        _depth=depth,
        cancel_event=cancel_event,
    )
    return sc


class TestScenarioExecutor:
    def test_empty_steps_returns_success(self):
        from tasks.scenario.executor import ScenarioExecutor
        sc = _make_sc(steps=[])
        result = ScenarioExecutor(sc).run()
        assert result["success"] is True
        assert result["steps_executed"] == 0

    def test_max_depth_exceeded(self):
        from tasks.scenario.executor import ScenarioExecutor
        sc = _make_sc(steps=[{"type": "wait", "seconds": 0}], depth=11)
        result = ScenarioExecutor(sc).run()
        assert result["success"] is False
        assert "depth" in result["failed_message"].lower()

    def test_cancelled_at_start(self):
        from tasks.scenario.executor import ScenarioExecutor
        ev = threading.Event()
        ev.set()
        sc = _make_sc(steps=[{"type": "wait", "seconds": 1}], cancel_event=ev)
        result = ScenarioExecutor(sc).run()
        assert result["success"] is False

    def test_serial_in_result(self):
        from tasks.scenario.executor import ScenarioExecutor
        sc = _make_sc(steps=[])
        result = ScenarioExecutor(sc).run()
        assert result["serial"] == "test"

    def test_step_executed_count(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        sc = _make_sc(steps=[
            {"type": "wait", "seconds": 0},
            {"type": "wait", "seconds": 0},
        ])

        with patch.dict(_STEP_HANDLERS, {"wait": lambda sc, step, idx, result: None}):
            result = ScenarioExecutor(sc).run()
        assert result["steps_executed"] == 2

    def test_root_executor_flushes_pending_captures(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        sc = _make_sc(steps=[{"type": "wait", "seconds": 0}], depth=0)

        with patch.dict(_STEP_HANDLERS, {"wait": lambda sc, step, idx, result: None}), patch(
            "services.execution.capture_service.flush_pending_captures"
        ) as flush:
            result = ScenarioExecutor(sc).run()

        assert result["success"] is True
        flush.assert_called_once()

    def test_nested_executor_does_not_flush_pending_captures(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        sc = _make_sc(steps=[{"type": "wait", "seconds": 0}], depth=1)

        with patch.dict(_STEP_HANDLERS, {"wait": lambda sc, step, idx, result: None}), patch(
            "services.execution.capture_service.flush_pending_captures"
        ) as flush:
            result = ScenarioExecutor(sc).run()

        assert result["success"] is True
        flush.assert_not_called()

    def test_unknown_step_fails_gracefully(self):
        from tasks.scenario.executor import ScenarioExecutor
        sc = _make_sc(steps=[{"type": "unknown_step_xyz"}])
        result = ScenarioExecutor(sc).run()
        # Unknown step should produce a failed step result but executor continues
        assert "step_results" in result
        failed = [r for r in result["step_results"] if not r.get("ok")]
        assert len(failed) >= 1

    def test_u2_http_502_step_retries_without_declared_retry_policy(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"swipe": 0}

        def flaky_swipe(_sc, _step, _idx, result):
            calls["swipe"] += 1
            if calls["swipe"] == 1:
                result["ok"] = False
                result["message"] = "swipe_ratio failed: JSON-RPC HTTP 502"
            else:
                result["message"] = "ok"

        sc = _make_sc(steps=[{"type": "swipe_ratio"}])
        sc.device._recover_u2_ws_mode = MagicMock()

        with patch.dict(_STEP_HANDLERS, {"swipe_ratio": flaky_swipe}), patch(
            "services.execution.step_runner.time.sleep"
        ) as sleep:
            result = ScenarioExecutor(sc).run()

        assert result["success"] is True
        assert calls["swipe"] == 2
        sc.device._recover_u2_ws_mode.assert_called_once()
        sleep.assert_called_once_with(2.5)
        attempts = result["step_results"][0]["retry_attempts"]
        assert attempts[0]["error_reason"] == "u2_transient_error"
        assert attempts[0]["wait_ms_before_next"] == 2500

    def test_u2_http_502_repeated_failure_triggers_recovery_once(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"swipe": 0}

        def failing_swipe(_sc, _step, _idx, result):
            calls["swipe"] += 1
            result["ok"] = False
            result["message"] = "swipe_ratio failed: JSON-RPC HTTP 502"

        sc = _make_sc(steps=[{"type": "swipe_ratio"}])
        sc.device._recover_u2_ws_mode = MagicMock()

        with patch.dict(_STEP_HANDLERS, {"swipe_ratio": failing_swipe}), patch(
            "services.execution.step_runner.time.sleep"
        ) as sleep:
            result = ScenarioExecutor(sc).run()

        assert result["success"] is False
        assert calls["swipe"] == 3
        sc.device._recover_u2_ws_mode.assert_called_once()
        assert sleep.call_args_list == [call(2.5), call(5.0)]
        failed_step = result["step_results"][0]
        assert failed_step["reason_code"] == "u2_transient_error"
        attempts = failed_step["retry_attempts"]
        assert [attempt["wait_ms_before_next"] for attempt in attempts] == [2500, 5000, None]

    def test_recovery_failure_preserves_original_step_message(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        def failing_scroll(_sc, _step, _idx, result):
            result["ok"] = False
            result["reason_code"] = "element_not_found"
            result["message"] = "scroll_to text='codex' not found after 5 swipes"

        def failing_recovery(_sc, _step, _idx, result):
            result["ok"] = False
            result["message"] = "recovery tap failed"

        sc = _make_sc(
            steps=[{"type": "scroll_to"}],
        )
        sc.scenario["recovery_policy"] = {
            "enabled": True,
            "rules": [
                {
                    "id": "rule-1",
                    "incident_type": "unknown",
                    "scenario_name": "recover_scroll",
                    "on_failure": "fail",
                }
            ],
        }
        sc.scenario["_scenario_registry"] = {
            "by_campaign_name": {
                "recover_scroll": {
                    "steps": [{"type": "recovery_fail"}],
                    "variables": {},
                }
            }
        }

        with patch.dict(
            _STEP_HANDLERS,
            {
                "scroll_to": failing_scroll,
                "recovery_fail": failing_recovery,
            },
        ):
            result = ScenarioExecutor(sc).run()

        assert result["success"] is False
        failed_step = result["step_results"][0]
        assert failed_step["message"] == "scroll_to text='codex' not found after 5 swipes"
        assert (
            failed_step["recovery_failed_message"]
            == "incident recovery playbooks did not resolve the step"
        )
        assert failed_step["reason_code"] == "element_not_found"

    def test_loop_wrapped_u2_transient_retries_without_declared_retry_policy(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"swipe": 0}

        def flaky_swipe(_sc, _step, _idx, result):
            calls["swipe"] += 1
            if calls["swipe"] <= 3:
                result["ok"] = False
                result["message"] = "u2_transient_error"
                result["reason_code"] = "u2_transient_error"
            else:
                result["message"] = "ok"

        sc = _make_sc(steps=[{"type": "loop", "count": 1, "steps": [{"type": "swipe_ratio"}]}])
        sc.device._recover_u2_ws_mode = MagicMock()

        with patch.dict(_STEP_HANDLERS, {"swipe_ratio": flaky_swipe}), patch(
            "services.execution.step_runner.time.sleep"
        ) as sleep:
            result = ScenarioExecutor(sc).run()

        assert result["success"] is True
        assert calls["swipe"] == 4
        loop_step = result["step_results"][0]
        assert loop_step["ok"] is True
        assert loop_step["retry_attempts"][0]["error_reason"] == "u2_transient_error"
        assert sleep.call_count == 3

    def test_loop_caps_retained_sub_results_without_losing_iteration_count(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"noop": 0}

        def noop(_sc, _step, _idx, result):
            calls["noop"] += 1
            result["message"] = "ok"

        sc = _make_sc(
            steps=[
                {
                    "type": "loop",
                    "count": 75,
                    "steps": [{"type": "noop"}],
                }
            ]
        )

        with patch.dict(_STEP_HANDLERS, {"noop": noop}):
            result = ScenarioExecutor(sc).run()

        loop_result = result["step_results"][0]
        assert result["success"] is True
        assert calls["noop"] == 75
        assert loop_result["iterations"] == 75
        assert len(loop_result["sub_results"]) == 51
        assert loop_result["sub_results"][-1]["truncated"] is True
        assert loop_result["sub_results"][-1]["omitted"] == 25
        assert loop_result["sub_results"][-1]["last"]["iteration"] == 74

    def test_repeat_caps_retained_sub_results_without_losing_iteration_count(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"noop": 0}

        def noop(_sc, _step, _idx, result):
            calls["noop"] += 1
            result["message"] = "ok"

        sc = _make_sc(
            steps=[
                {
                    "type": "repeat",
                    "count": 75,
                    "steps": [{"type": "noop"}],
                }
            ]
        )

        with patch.dict(_STEP_HANDLERS, {"noop": noop}):
            result = ScenarioExecutor(sc).run()

        repeat_result = result["step_results"][0]
        assert result["success"] is True
        assert calls["noop"] == 75
        assert repeat_result["iterations"] == 75
        assert len(repeat_result["sub_results"]) == 51
        assert repeat_result["sub_results"][-1]["truncated"] is True
        assert repeat_result["sub_results"][-1]["omitted"] == 25
        assert repeat_result["sub_results"][-1]["last"]["iteration"] == 74

    def test_loop_repeated_failed_nested_step_runs_recovery_per_iteration(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"failed": 0, "recovered": 0}

        def always_fail(_sc, _step, _idx, result):
            calls["failed"] += 1
            result["ok"] = False
            result["reason_code"] = "blocked"
            result["message"] = "blocked"

        def recover(_sc, _step, _idx, result):
            calls["recovered"] += 1
            result["message"] = "recovered"

        scenario = {
            "steps": [
                {
                    "type": "loop",
                    "count": 3,
                    "steps": [{"type": "always_fail"}],
                }
            ],
            "recovery_policy": {
                "enabled": True,
                "max_total_attempts": 10,
                "rules": [
                    {
                        "scenario_id": "recovery-1",
                        "outcome": "continue",
                        "max_attempts": 1,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-1": {
                        "steps": [{"type": "recover"}],
                        "variables": {},
                    }
                }
            },
        }
        sc = _make_sc(steps=scenario["steps"])
        sc.scenario.update({k: v for k, v in scenario.items() if k != "steps"})

        with patch.dict(
            _STEP_HANDLERS,
            {"always_fail": always_fail, "recover": recover},
        ):
            result = ScenarioExecutor(sc).run()

        assert result["success"] is True
        assert calls == {"failed": 3, "recovered": 3}
        assert sc.ctx["_recovery_state"]["total_attempts"] == 3
        assert len(sc.ctx["_recovery_state"]["by_incident"]) == 3
        assert result["step_results"][0]["iterations"] == 3

    def test_loop_recovery_stops_at_global_total_cap(self):
        from tasks.scenario.executor import ScenarioExecutor
        from tasks.scenario.steps import _STEP_HANDLERS

        calls = {"failed": 0, "recovered": 0}

        def always_fail(_sc, _step, _idx, result):
            calls["failed"] += 1
            result["ok"] = False
            result["reason_code"] = "blocked"
            result["message"] = "blocked"

        def recover(_sc, _step, _idx, result):
            calls["recovered"] += 1
            result["message"] = "recovered"

        scenario = {
            "steps": [
                {
                    "type": "loop",
                    "count": 5,
                    "steps": [{"type": "always_fail"}],
                }
            ],
            "recovery_policy": {
                "enabled": True,
                "max_total_attempts": 2,
                "rules": [
                    {
                        "scenario_id": "recovery-1",
                        "outcome": "continue",
                        "max_attempts": 1,
                    }
                ],
            },
            "_scenario_registry": {
                "by_id": {
                    "recovery-1": {
                        "steps": [{"type": "recover"}],
                        "variables": {},
                    }
                }
            },
        }
        sc = _make_sc(steps=scenario["steps"])
        sc.scenario.update({k: v for k, v in scenario.items() if k != "steps"})

        with patch.dict(
            _STEP_HANDLERS,
            {"always_fail": always_fail, "recover": recover},
        ):
            result = ScenarioExecutor(sc).run()

        assert result["success"] is False
        assert calls == {"failed": 3, "recovered": 2}
        assert sc.ctx["_recovery_state"]["total_attempts"] == 2
        assert len(sc.ctx["_recovery_state"]["by_incident"]) == 2
        assert result["step_results"][0]["iterations"] == 3
