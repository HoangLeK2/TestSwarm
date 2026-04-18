"""Tests for scenario_task step capture: settle wait, stale-frame guard, pre/post modes.

Covers the three fixes:
  1. Settle wait before POST screenshot (skip for wait-type steps).
  2. Stale-frame guard: poll until _last_frame_time > step_start_t.
  3. `fresh` flag logged correctly, warning emitted when frame stays stale.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call
import pytest
from tasks.scenario_task import run_scenario_task


# ──────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_device(
    jpeg: bytes = b"\xff\xd8\xff\xe0fake",
    frame_time: Optional[float] = None,
) -> MagicMock:
    """Minimal DeviceClient mock that supports take_screenshot + _last_frame_time."""
    device = MagicMock()
    device.take_screenshot.return_value = jpeg
    device.serial = "test-serial"
    device.screen_width = 1080
    device.screen_height = 1920
    device.model = "TestDevice"
    device.u2 = None
    device.hierarchy_xml.return_value = None
    device._last_frame_time = frame_time if frame_time is not None else time.monotonic()
    return device


def _run_scenario(
    steps: List[Dict[str, Any]],
    device: MagicMock,
    scenario_extra: Optional[Dict] = None,
    env: Optional[Dict[str, str]] = None,
    tmp_path: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run execute_scenario with capture_steps=True and a temp capture dir."""
    from tasks.scenario_task import run_scenario_task as execute_scenario

    scenario: Dict[str, Any] = {"steps": steps, "capture_steps": True}
    if scenario_extra:
        scenario.update(scenario_extra)

    env_patch = {
        "CAPTURE_STEPS": "1",
        "SETTLE_TIMEOUT_MS": "0",   # tests control settle explicitly via scenario key
        "CAPTURE_STALE_WAIT_MS": "0",
    }
    if env:
        env_patch.update(env)

    with patch.dict(os.environ, env_patch, clear=False):
        with patch("tasks.scenario_task.os.makedirs"):
            with patch("tasks.scenario_task.os.path.join", side_effect=lambda *a: "/tmp/captures/test") if tmp_path is None else _noop():
                result = run_scenario_task(
                    device=device,
                    scenario=scenario,
                )
    return result


class _noop:
    """Context manager that does nothing (used as else branch)."""
    def __enter__(self): return self
    def __exit__(self, *a): pass


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests for _capture_step_screenshot
# ──────────────────────────────────────────────────────────────────────────────

class TestCaptureStepScreenshot:
    def test_returns_empty_when_no_jpeg(self, tmp_path):
        from tasks.scenario_task import _capture_step_screenshot
        device = _make_device(jpeg=b"")
        device.take_screenshot.return_value = b""
        result = _capture_step_screenshot(device, str(tmp_path), 0, "tap", None, 1080, 1920)
        assert result == {}

    def test_saves_full_jpeg(self, tmp_path):
        from tasks.scenario_task import _capture_step_screenshot
        jpeg = b"\xff\xd8\xff\xe0" + b"A" * 100
        device = _make_device(jpeg=jpeg)
        result = _capture_step_screenshot(device, str(tmp_path), 0, "tap", None, 1080, 1920)
        assert "full" in result
        assert (tmp_path / "step_000_tap_full.jpg").exists()

    def test_saves_selector_json_when_provided(self, tmp_path):
        from tasks.scenario_task import _capture_step_screenshot
        jpeg = b"\xff\xd8\xff\xe0" + b"B" * 100
        device = _make_device(jpeg=jpeg)
        sel = {"by": "text", "value": "Login"}
        result = _capture_step_screenshot(device, str(tmp_path), 1, "tap_selector", None, 1080, 1920, selector=sel)
        assert "selector" in result
        sel_file = tmp_path / "step_001_tap_selector_selector.json"
        assert sel_file.exists()
        import json
        data = json.loads(sel_file.read_text())
        assert data["by"] == "text"
        assert data["value"] == "Login"

    def test_saves_xml_hierarchy_when_available(self, tmp_path):
        from tasks.scenario_task import _capture_step_screenshot
        jpeg = b"\xff\xd8\xff\xe0" + b"C" * 100
        device = _make_device(jpeg=jpeg)
        device.hierarchy_xml.return_value = "<hierarchy/>"
        result = _capture_step_screenshot(device, str(tmp_path), 2, "tap", None, 1080, 1920)
        assert "hierarchy" in result

    def test_crops_element_when_bounds_provided(self, tmp_path):
        """PIL crop path — requires a real JPEG."""
        pytest.importorskip("PIL")
        from tasks.scenario_task import _capture_step_screenshot
        from PIL import Image
        import io
        # Create a minimal valid JPEG
        img = Image.new("RGB", (1080, 1920), color=(255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        jpeg = buf.getvalue()

        device = _make_device(jpeg=jpeg)
        bounds = {"left": 100, "top": 200, "right": 400, "bottom": 600}
        result = _capture_step_screenshot(device, str(tmp_path), 3, "tap", bounds, 1080, 1920)
        assert "element" in result
        assert "bounds" in result
        assert (tmp_path / "step_003_tap_element.jpg").exists()

    def test_skips_crop_when_bounds_zero_size(self, tmp_path):
        """Degenerate bounds (left==right) should not produce element crop."""
        pytest.importorskip("PIL")
        from tasks.scenario_task import _capture_step_screenshot
        from PIL import Image
        import io
        img = Image.new("RGB", (100, 100))
        buf = io.BytesIO(); img.save(buf, format="JPEG"); jpeg = buf.getvalue()
        device = _make_device(jpeg=jpeg)
        bounds = {"left": 50, "top": 50, "right": 50, "bottom": 100}  # zero width
        result = _capture_step_screenshot(device, str(tmp_path), 4, "tap", bounds, 100, 100)
        assert "element" not in result


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests for settle wait logic
# ──────────────────────────────────────────────────────────────────────────────

class TestSettleWait:
    """Verify time.sleep is called (or not) depending on step type and config."""

    def _run_single_step(
        self,
        step: Dict[str, Any],
        settle_ms: int = 200,
        stale_wait_ms: int = 0,
        frame_time_offset: float = 1.0,
    ):
        """
        Minimal harness that patches just the capture path inside execute_scenario.
        Returns list of time.sleep calls within the capture block.
        """
        from tasks.scenario_task import run_scenario_task as execute_scenario

        device = _make_device()
        # Frame time is clearly AFTER step_start_t (frame_time_offset seconds in future)
        device._last_frame_time = time.monotonic() + frame_time_offset

        scenario = {
            "steps": [step],
            "capture_steps": True,
            "settle_timeout_ms": settle_ms,
        }
        sleep_calls: List[float] = []

        original_sleep = time.sleep

        def _mock_sleep(secs: float):
            sleep_calls.append(secs)
            # Don't actually sleep in tests

        env_patch = {
            "CAPTURE_STEPS": "1",
            "SETTLE_TIMEOUT_MS": str(settle_ms),
            "CAPTURE_STALE_WAIT_MS": str(stale_wait_ms),
        }
        with patch("tasks.scenario_task.time.sleep", side_effect=_mock_sleep):
            with patch("tasks.scenario_task._capture_step_screenshot", return_value={}):
                with patch("tasks.scenario_task.os.makedirs"):
                    with patch.dict(os.environ, env_patch, clear=False):
                        run_scenario_task(
                            device=device,
                            scenario=scenario,
                        )
        return sleep_calls

    def test_tap_step_triggers_settle_sleep(self):
        """tap is not in skip-settle set → sleep(settle_ms/1000) should be called."""
        step = {"type": "tap_ratio", "x": 0.5, "y": 0.5}
        calls = self._run_single_step(step, settle_ms=300)
        # At least one sleep matching our settle_ms
        settle_calls = [c for c in calls if abs(c - 0.3) < 0.01]
        assert settle_calls, f"Expected settle sleep of 0.3s, got calls: {calls}"

    def test_wait_step_skips_settle_sleep(self):
        """wait step → no settle sleep added by capture block."""
        step = {"type": "wait", "seconds": 0.01}  # tiny so test is fast
        calls = self._run_single_step(step, settle_ms=500)
        # The only sleep should be from the wait step itself (0.01s), not 0.5s settle
        settle_calls = [c for c in calls if abs(c - 0.5) < 0.01]
        assert not settle_calls, f"Unexpected settle sleep for wait step: {calls}"

    def test_wait_stable_step_skips_settle(self):
        step = {"type": "wait_stable", "timeout": 0.1}
        calls = self._run_single_step(step, settle_ms=400)
        settle_calls = [c for c in calls if abs(c - 0.4) < 0.01]
        assert not settle_calls

    def test_set_variable_skips_settle(self):
        step = {"type": "set_variable", "name": "x", "value": "1"}
        calls = self._run_single_step(step, settle_ms=400)
        settle_calls = [c for c in calls if abs(c - 0.4) < 0.01]
        assert not settle_calls

    def test_settle_ms_zero_disables_sleep(self):
        """settle_timeout_ms=0 → no settle sleep added by capture block.
        Note: tap actions may add their own 0.3s sleep; we only check that
        no 0.0s (zero-settle) sleep was injected."""
        step = {"type": "tap_ratio", "x": 0.5, "y": 0.5}
        calls = self._run_single_step(step, settle_ms=0)
        # Guard: _capture_settle_ms > 0 prevents any settle sleep when settle_ms=0.
        # The value 0.0 would only appear if the guard were absent.
        assert 0.0 not in calls, f"Unexpected 0.0s settle sleep with settle_ms=0: {calls}"
        # Also verify no 250ms-range sleep (use distinct value to separate from tap's 0.3s)
        calls_250 = self._run_single_step(step, settle_ms=250)
        assert any(abs(c - 0.25) < 0.01 for c in calls_250), (
            f"Expected 0.25s settle sleep with settle_ms=250, got: {calls_250}"
        )

    def test_swipe_step_triggers_settle(self):
        step = {"type": "swipe", "direction": "up"}
        calls = self._run_single_step(step, settle_ms=200)
        settle_calls = [c for c in calls if abs(c - 0.2) < 0.01]
        assert settle_calls


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests for stale-frame guard
# ──────────────────────────────────────────────────────────────────────────────

class TestStaleFrameGuard:
    """Verify polling logic and stale-frame warning."""

    def _run_with_frame_times(
        self,
        frame_times: List[Optional[float]],
        step_type: str = "tap_ratio",
        settle_ms: int = 10,      # must be > 0 so need_settle=True, enabling stale guard
        stale_wait_ms: int = 50,  # short so tests complete quickly
    ):
        """
        Run a single step and collect log warnings/infos from the capture block.

        frame_times[0] determines _last_frame_time relative to real time.monotonic():
          - Pass [time.monotonic() + 9999]  → frame clearly newer than step_start_t (fresh)
          - Pass [0.0]                       → frame at epoch, always stale
        settle_ms must be > 0 for the stale guard to activate (design constraint).
        """
        device = _make_device()
        ft0 = frame_times[0] if frame_times else 0.0
        device._last_frame_time = ft0 if ft0 is not None else 0.0

        warnings_list: List[str] = []
        infos_list: List[str] = []

        scenario = {
            "steps": [{"type": step_type, "x": 0.5, "y": 0.5}],
            "capture_steps": True,
            "settle_timeout_ms": settle_ms,
        }
        env_patch = {
            "CAPTURE_STEPS": "1",
            "SETTLE_TIMEOUT_MS": str(settle_ms),
            "CAPTURE_STALE_WAIT_MS": str(stale_wait_ms),
        }

        import logging as _logging
        _log = _logging.getLogger("tasks.scenario_task")
        _log_capture = _logging.getLogger("tasks.scenario.capture")
        _log_executor = _logging.getLogger("tasks.scenario.executor")

        # Patch time.sleep only (so settle sleep doesn't slow tests) but NOT
        # time.monotonic — the stale-guard deadline uses real monotonic,
        # which ensures the loop exits naturally after stale_wait_ms real ms.
        with patch("tasks.scenario_task.time.sleep"), \
             patch("tasks.scenario.capture.time.sleep"), \
             patch("tasks.scenario_task._capture_step_screenshot", return_value={}), \
             patch("tasks.scenario_task.os.makedirs"), \
             patch("tasks.scenario.context.os.makedirs"), \
             patch.dict(os.environ, env_patch, clear=False):
            _collect_warn = lambda m, *a, **kw: warnings_list.append(m % a if a else m)
            _collect_info = lambda m, *a, **kw: infos_list.append(m % a if a else m)
            with patch.object(_log, "warning", side_effect=_collect_warn), \
                 patch.object(_log, "info", side_effect=_collect_info), \
                 patch.object(_log_capture, "warning", side_effect=_collect_warn), \
                 patch.object(_log_capture, "info", side_effect=_collect_info), \
                 patch.object(_log_executor, "warning", side_effect=_collect_warn), \
                 patch.object(_log_executor, "info", side_effect=_collect_info):
                run_scenario_task(device=device, scenario=scenario)
        return warnings_list, infos_list

    def test_fresh_frame_no_warning(self):
        """If frame_time is clearly after step_start_t, no stale warning."""
        # Use a timestamp clearly in the future relative to when the step runs.
        future = time.monotonic() + 9999
        warnings, infos = self._run_with_frame_times(
            [future],
            stale_wait_ms=50,
        )
        stale_warns = [w for w in warnings if "stale" in w.lower()]
        assert not stale_warns, f"Got unexpected stale warning: {stale_warns}"

    def test_stale_frame_emits_warning(self):
        """Frame never updates → stale warning after timeout."""
        # Use 0.0: clearly older than any step_start_t from time.monotonic().
        warnings, _ = self._run_with_frame_times(
            [0.0],  # epoch — always stale
            stale_wait_ms=50,
        )
        stale_warns = [w for w in warnings if "stale" in w.lower()]
        assert stale_warns, f"Expected stale warning but got: {warnings}"

    def test_fresh_flag_true_in_log(self):
        """When frame is fresh, log message contains 'fresh=True'."""
        future = time.monotonic() + 9999
        _, infos = self._run_with_frame_times([future], stale_wait_ms=50)
        fresh_logs = [i for i in infos if "fresh=True" in i]
        assert fresh_logs, f"Expected 'fresh=True' in logs, got: {infos}"

    def test_stale_guard_skipped_for_wait_step(self):
        """wait step → guard never runs, no stale warning even with old frame."""
        warnings, _ = self._run_with_frame_times(
            [0.0],  # epoch — always stale, but guard should be skipped
            step_type="wait",
            stale_wait_ms=200,
        )
        stale_warns = [w for w in warnings if "stale" in w.lower()]
        assert not stale_warns


# ──────────────────────────────────────────────────────────────────────────────
# Integration: pre-capture + post-capture ordering
# ──────────────────────────────────────────────────────────────────────────────

class TestPrePostCaptureOrdering:
    """Ensure _capture_step_screenshot is called pre then post when CAPTURE_PRE_STEP=1."""

    def test_pre_and_post_both_called(self):
        from tasks.scenario_task import run_scenario_task as execute_scenario

        device = _make_device()
        device._last_frame_time = time.monotonic() + 9999

        capture_calls: List[str] = []

        def _mock_capture(dev, cdir, idx, step_type, bounds, w, h, selector=None):
            capture_calls.append(step_type)
            return {"full": f"/tmp/{step_type}_full.jpg"}

        scenario = {
            "steps": [{"type": "tap_ratio", "x": 0.5, "y": 0.5}],
            "capture_steps": True,
            "settle_timeout_ms": 0,
        }
        env_patch = {
            "CAPTURE_STEPS": "1",
            "CAPTURE_PRE_STEP": "1",
            "SETTLE_TIMEOUT_MS": "0",
            "CAPTURE_STALE_WAIT_MS": "0",
        }
        with patch("tasks.scenario_task.time.sleep"):
            with patch("tasks.scenario_task._capture_step_screenshot", side_effect=_mock_capture):
                with patch("tasks.scenario_task.os.makedirs"):
                    with patch.dict(os.environ, env_patch, clear=False):
                        run_scenario_task(
                            device=device,
                            scenario=scenario,
                        )

        assert len(capture_calls) == 2, f"Expected 2 captures (pre + post), got: {capture_calls}"
        assert "pre" in capture_calls[0], f"First capture should be PRE, got: {capture_calls[0]}"
        assert "pre" not in capture_calls[1], f"Second capture should be POST, got: {capture_calls[1]}"

    def test_only_post_when_pre_not_enabled(self):
        from tasks.scenario_task import run_scenario_task as execute_scenario

        device = _make_device()
        device._last_frame_time = time.monotonic() + 9999

        capture_calls: List[str] = []

        def _mock_capture(dev, cdir, idx, step_type, bounds, w, h, selector=None):
            capture_calls.append(step_type)
            return {}

        scenario = {
            "steps": [{"type": "tap_ratio", "x": 0.5, "y": 0.5}],
            "capture_steps": True,
            "settle_timeout_ms": 0,
        }
        env_patch = {
            "CAPTURE_STEPS": "1",
            "CAPTURE_PRE_STEP": "0",
            "SETTLE_TIMEOUT_MS": "0",
            "CAPTURE_STALE_WAIT_MS": "0",
        }
        with patch("tasks.scenario_task.time.sleep"):
            with patch("tasks.scenario_task._capture_step_screenshot", side_effect=_mock_capture):
                with patch("tasks.scenario_task.os.makedirs"):
                    with patch.dict(os.environ, env_patch, clear=False):
                        run_scenario_task(
                            device=device,
                            scenario=scenario,
                        )

        assert len(capture_calls) == 1
        assert "pre" not in capture_calls[0]


# ──────────────────────────────────────────────────────────────────────────────
# Scenario-level settle_timeout_ms override
# ──────────────────────────────────────────────────────────────────────────────

class TestScenarioLevelSettleOverride:
    """settle_timeout_ms in scenario JSON overrides SETTLE_TIMEOUT_MS env var."""

    def test_scenario_settle_overrides_env(self):
        from tasks.scenario_task import run_scenario_task as execute_scenario

        device = _make_device()
        device._last_frame_time = time.monotonic() + 9999

        sleep_calls: List[float] = []

        def _mock_sleep(secs: float):
            sleep_calls.append(secs)

        scenario = {
            "steps": [{"type": "tap_ratio", "x": 0.5, "y": 0.5}],
            "capture_steps": True,
            "settle_timeout_ms": 150,  # scenario says 150ms
        }
        env_patch = {
            "CAPTURE_STEPS": "1",
            "SETTLE_TIMEOUT_MS": "999",   # env says 999ms — should be ignored
            "CAPTURE_STALE_WAIT_MS": "0",
        }
        with patch("tasks.scenario_task.time.sleep", side_effect=_mock_sleep):
            with patch("tasks.scenario_task._capture_step_screenshot", return_value={}):
                with patch("tasks.scenario_task.os.makedirs"):
                    with patch.dict(os.environ, env_patch, clear=False):
                        run_scenario_task(
                            device=device,
                            scenario=scenario,
                        )

        settle_calls = [c for c in sleep_calls if abs(c - 0.15) < 0.01]
        assert settle_calls, f"Expected 150ms settle, got sleep calls: {sleep_calls}"
        bad_calls = [c for c in sleep_calls if abs(c - 0.999) < 0.01]
        assert not bad_calls, f"Env SETTLE_TIMEOUT_MS=999ms should be overridden by scenario"
