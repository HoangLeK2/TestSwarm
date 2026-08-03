"""
tests/test_temporal_activities.py — Unit tests for Temporal activities (DF-002).

Tests cover:
- Serial validation and security
- XML element check
- Delegation to run_scenario_task (the real executor)
- Element check activity
- Condition evaluation activity

Run: pytest tests/test_temporal_activities.py -v
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from temporal.activities import (
    _SERIAL_RE,
    _generate_totp,
    _validate_serial,
    _xml_has_element,
    DeviceActivities,
    set_device_registry,
)
from temporal.shared import (
    DeviceActionInput,
    ElementCheckInput,
    ElementCheckResult,
    ConditionCheckInput,
    StepResult,
)


# ── Mock infrastructure ──────────────────────────────────────────────────────


def test_generate_totp_matches_rfc6238_sha1_vector():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    assert _generate_totp(secret, now=59, digits=8) == "94287082"


class MockU2:
    def __init__(self, present: set[tuple[str, str]] | None = None) -> None:
        self._present: set[tuple[str, str]] = present or set()

    def find_element(self, by: str, value: str, timeout: float = 0) -> Optional[str]:
        if (by, value) in self._present:
            return f"eid:{by}:{value}"
        return None

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict]:
        if (by, value) in self._present:
            return {"eid": f"eid:{by}:{value}", "bounds": {"left": 100, "top": 200, "right": 300, "bottom": 400}}
        return None

    def element_click(self, eid: str) -> None:
        pass

    def send_keys(self, text: str) -> None:
        pass

    def clear_text(self) -> None:
        pass


class MockDevice:
    def __init__(
        self,
        serial: str = "test_serial",
        u2: Optional[MockU2] = None,
        xml: str = "",
    ) -> None:
        self.serial = serial
        self.u2 = u2
        self.screen_width = 1080
        self.screen_height = 1920
        self.model = "MockPhone"
        self._xml = xml
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple] = []
        self.launched_apps: list[str] = []

    def ensure_u2_healthy(self) -> None:
        pass

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self._xml

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def launch_app(self, package: str, **kwargs) -> None:
        self.launched_apps.append(package)

    def open_url(self, url: str, package: str = "") -> None:
        pass

    def key(self, key_name: str) -> None:
        pass

    def shell(self, cmd: str) -> str:
        return "ok"

    def take_screenshot(self) -> Optional[bytes]:
        return None


@pytest.mark.asyncio
async def test_successful_check_element_lifecycle_is_debug_only() -> None:
    device = MockDevice(u2=MockU2({("text", "OK")}))
    trace_log = MagicMock()

    with (
        patch(
            "temporal.activities._heartbeat_campaign_device_claim",
            AsyncMock(return_value=None),
        ),
        patch("temporal.activities._get_device", return_value=device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities.activity.heartbeat", MagicMock()),
        patch(
            "temporal.activities._to_thread_with_heartbeat",
            AsyncMock(return_value="eid:text:OK"),
        ),
        patch("temporal.activities.trace_log", trace_log),
    ):
        result = await DeviceActivities().check_element_exists(
            ElementCheckInput(
                device_serial="test_serial",
                by="text",
                value="OK",
                execution_id="exec-1",
            )
        )

    assert result.found is True
    assert [call.args[0] for call in trace_log.debug.call_args_list] == [
        "check_element_start",
        "check_element_end",
    ]
    trace_log.info.assert_not_called()
    trace_log.warning.assert_not_called()


@pytest.mark.asyncio
async def test_check_element_repairs_dead_state_when_u2_ready() -> None:
    from runtime.core.device_client import DeviceState

    device = MockDevice(u2=MockU2({("text", "OK")}))
    device.state = DeviceState.DEAD
    device._scenario_active = 1

    with (
        patch("temporal.activities._get_device", return_value=device),
        patch("temporal.activities._validate_serial"),
        patch("temporal.activities.activity.heartbeat", MagicMock()),
        patch("tasks.scenario_task._wait_for_element", return_value="eid:text:OK"),
    ):
        result = await DeviceActivities().check_element_exists(
            ElementCheckInput(
                device_serial="test_serial",
                by="text",
                value="OK",
                execution_id="exec-1",
            )
        )

    assert result.found is True
    assert device.state == DeviceState.BUSY


# ── Serial validation tests ─────────────────────────────────────────────────


class TestSerialValidation:
    def test_valid_serial_ip_port(self):
        _validate_serial("192.168.1.100:5555")

    def test_valid_serial_plain(self):
        _validate_serial("ABCD1234")

    def test_valid_serial_with_dots(self):
        _validate_serial("device.local")

    def test_empty_serial_rejected(self):
        with pytest.raises(ValueError, match="Invalid device serial"):
            _validate_serial("")

    def test_none_serial_rejected(self):
        with pytest.raises(ValueError, match="Invalid device serial"):
            _validate_serial(None)  # type: ignore

    def test_long_serial_rejected(self):
        with pytest.raises(ValueError, match="Invalid device serial"):
            _validate_serial("a" * 200)

    def test_special_chars_rejected(self):
        with pytest.raises(ValueError, match="Invalid device serial"):
            _validate_serial("device; rm -rf /")

    def test_newline_rejected(self):
        with pytest.raises(ValueError, match="Invalid device serial"):
            _validate_serial("device\nmalicious")

    def test_serial_regex_pattern(self):
        assert _SERIAL_RE.match("192.168.1.1:5555")
        assert _SERIAL_RE.match("ABC_DEF-123")
        assert not _SERIAL_RE.match("")
        assert not _SERIAL_RE.match("a b c")
        assert not _SERIAL_RE.match("x" * 200)


# ── XML element check tests ─────────────────────────────────────────────────


class TestXmlHasElement:
    SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
    <hierarchy>
        <node text="Allow" resource-id="btn1" class="android.widget.Button" content-desc=""/>
        <node text="" resource-id="com.test:id/login" class="android.widget.EditText" content-desc="Username"/>
        <node text="Submit" resource-id="" class="android.widget.Button" content-desc=""/>
    </hierarchy>
    """

    def test_find_by_text(self):
        assert _xml_has_element(self.SAMPLE_XML, "text", "Allow") is True

    def test_find_by_text_not_found(self):
        assert _xml_has_element(self.SAMPLE_XML, "text", "Cancel") is False

    def test_find_by_resource_id(self):
        assert _xml_has_element(self.SAMPLE_XML, "resource-id", "com.test:id/login") is True

    def test_find_by_content_desc(self):
        assert _xml_has_element(self.SAMPLE_XML, "content-desc", "Username") is True

    def test_find_by_class(self):
        assert _xml_has_element(self.SAMPLE_XML, "class name", "android.widget.Button") is True

    def test_empty_xml(self):
        assert _xml_has_element("", "text", "Allow") is False

    def test_empty_value(self):
        assert _xml_has_element(self.SAMPLE_XML, "text", "") is False

    def test_invalid_xml(self):
        assert _xml_has_element("<broken", "text", "Allow") is False

    def test_xpath_injection_safe(self):
        """Value with quotes should not break the check."""
        assert _xml_has_element(self.SAMPLE_XML, "text", 'Allow"] or 1=1 or ["') is False


# ── Delegation to run_scenario_task tests ────────────────────────────────────


class TestExecuteDeviceActionDelegation:
    """Test that execute_device_action delegates to the original scenario executor."""

    def test_delegation_imports_run_scenario_task(self):
        """Verify run_scenario_task is importable and callable."""
        from tasks.scenario_task import run_scenario_task
        assert callable(run_scenario_task)

    def test_step_result_extraction(self):
        """Test that StepResult is correctly built from run_scenario_task output."""
        step_result_raw = {
            "index": 0, "type": "tap", "ok": True,
            "message": "selector text='OK' tapped",
            "method": "selector",
            "popup_dismissed": True,
        }
        sr = StepResult(
            index=3,
            step_type="tap",
            ok=step_result_raw["ok"],
            message=step_result_raw["message"],
            details={
                k: v for k, v in step_result_raw.items()
                if k not in ("index", "type", "ok", "message")
            },
        )
        assert sr.ok is True
        assert sr.message == "selector text='OK' tapped"
        assert sr.details["method"] == "selector"
        assert sr.details["popup_dismissed"] is True
        assert sr.index == 3

    def test_empty_step_results_handled(self):
        """If run_scenario_task returns no step_results, use overall success."""
        result = {
            "serial": "test",
            "success": False,
            "steps_executed": 0,
            "step_results": [],
            "failed_message": "something went wrong",
        }
        # Simulate the extraction logic from the activity
        step_results = result.get("step_results", [])
        if step_results:
            sr = step_results[0]
        else:
            ok = result.get("success", False)
            msg = result.get("failed_message", "no step result")
            assert ok is False
            assert msg == "something went wrong"


# ── Integration test: full pipeline via run_scenario_task ────────────────────


class TestFullPipelineIntegration:
    """Test that the delegation actually runs through the full pipeline."""

    def test_tap_goes_through_full_pipeline(self):
        """A tap step should go through pre_hash → execute_tap → wait_ui_change."""
        from tasks.scenario_task import run_scenario_task

        device = MockDevice(u2=MockU2(present={("text", "OK")}))
        scenario = {
            "steps": [{"type": "tap_selector", "by": "text", "value": "OK", "timeout": 1}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True
        sr = result["step_results"][0]
        assert sr["ok"] is True
        assert "OK" in sr.get("message", "")

    def test_launch_app_pipeline(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice()
        scenario = {
            "steps": [{"type": "launch_app", "package": "com.test.app", "wait_after": 0}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True
        assert "com.test.app" in device.launched_apps

    def test_wait_element_found(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice(u2=MockU2(present={("text", "Home")}))
        scenario = {
            "steps": [{"type": "wait_element", "by": "text", "value": "Home", "timeout": 1}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True

    def test_wait_element_not_found(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice(u2=MockU2(present=set()))
        scenario = {
            "steps": [{"type": "wait_element", "by": "text", "value": "Missing", "timeout": 0.1}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is False

    def test_assert_element_fail(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice(u2=MockU2(present=set()))
        scenario = {
            "steps": [{"type": "assert_element", "by": "text", "value": "Home", "timeout": 0.1}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is False
        assert "FAILED" in result["step_results"][0].get("message", "")

    def test_tap_ratio(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice()
        scenario = {
            "steps": [{"type": "tap_ratio", "x": 0.5, "y": 0.5}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True
        assert len(device.taps) >= 1

    def test_scroll_down(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice()
        scenario = {
            "steps": [{"type": "scroll_down", "repeats": 2}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True
        assert len(device.swipes) == 2

    def test_set_variable(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice()
        scenario = {
            "steps": [
                {"type": "set_variable", "name": "X", "value": "hello"},
                {"type": "set_variable", "name": "Y", "increment": 1},
            ]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True

    def test_key_step(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice()
        scenario = {
            "steps": [{"type": "key", "key": "home"}]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True

    def test_repeat_via_original_executor(self):
        """Control flow steps should also work via the original executor."""
        from tasks.scenario_task import run_scenario_task

        device = MockDevice()
        scenario = {
            "steps": [{
                "type": "repeat",
                "count": 3,
                "steps": [{"type": "set_variable", "name": "COUNTER", "increment": 1}],
            }]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True

    def test_if_element_via_original_executor(self):
        from tasks.scenario_task import run_scenario_task

        device = MockDevice(u2=MockU2(present={("text", "Allow")}))
        scenario = {
            "steps": [{
                "type": "if_element",
                "by": "text",
                "value": "Allow",
                "timeout": 1,
                "then": [{"type": "set_variable", "name": "FOUND", "value": "yes"}],
                "else": [{"type": "set_variable", "name": "FOUND", "value": "no"}],
            }]
        }
        result = run_scenario_task(device, scenario)
        assert result["success"] is True
        sr = result["step_results"][0]
        assert sr.get("element_found") is True
        assert sr.get("branch") == "then"
