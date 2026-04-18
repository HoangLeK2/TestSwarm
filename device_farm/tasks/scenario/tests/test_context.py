"""Unit tests for ScenarioContext."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

import threading
from unittest.mock import MagicMock, patch
import pytest


class TestScenarioContext:
    def _make_device(self):
        d = MagicMock()
        d.serial = "emulator-5554"
        d.screen_width = 1080
        d.screen_height = 1920
        return d

    def test_from_args_minimal(self):
        from tasks.scenario.context import ScenarioContext
        device = self._make_device()
        sc = ScenarioContext.from_args(device, {"steps": []})
        assert sc.serial == "emulator-5554"
        assert sc.w == 1080
        assert sc.h == 1920
        assert sc.steps == []
        assert sc.depth == 0

    def test_from_args_defaults_ctx(self):
        from tasks.scenario.context import ScenarioContext
        device = self._make_device()
        sc = ScenarioContext.from_args(device, {"steps": []})
        assert "posts" in sc.ctx
        assert "vars" in sc.ctx

    def test_from_args_preserves_context(self):
        from tasks.scenario.context import ScenarioContext
        device = self._make_device()
        ctx = {"posts": [1, 2, 3], "custom": "value"}
        sc = ScenarioContext.from_args(device, {"steps": []}, context=ctx)
        assert sc.ctx["posts"] == [1, 2, 3]
        assert sc.ctx["custom"] == "value"

    def test_from_args_cancel_event(self):
        from tasks.scenario.context import ScenarioContext
        device = self._make_device()
        ev = threading.Event()
        sc = ScenarioContext.from_args(device, {"steps": []}, cancel_event=ev)
        assert sc.cancel_event is ev

    def test_from_args_depth(self):
        from tasks.scenario.context import ScenarioContext
        device = self._make_device()
        sc = ScenarioContext.from_args(device, {"steps": []}, _depth=3)
        assert sc.depth == 3

    def test_from_args_fallback_screen_size(self):
        from tasks.scenario.context import ScenarioContext
        device = self._make_device()
        device.screen_width = None
        device.screen_height = None
        sc = ScenarioContext.from_args(device, {"steps": []})
        assert sc.w == 1080   # default
        assert sc.h == 1920   # default
