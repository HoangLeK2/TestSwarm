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

    def test_unknown_step_fails_gracefully(self):
        from tasks.scenario.executor import ScenarioExecutor
        sc = _make_sc(steps=[{"type": "unknown_step_xyz"}])
        result = ScenarioExecutor(sc).run()
        # Unknown step should produce a failed step result but executor continues
        assert "step_results" in result
        failed = [r for r in result["step_results"] if not r.get("ok")]
        assert len(failed) >= 1
