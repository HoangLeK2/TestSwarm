"""Temporal activity path + DSL materialization for DF-T-04-011 retry."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.execution.dsl_runtime import materialize_legacy_step
from services.execution.retry_policy import parse_step_retry_policy
from services.execution.step_runner import execute_step_with_retry
from temporal.activities import DeviceActivities, _prepare_activity_step, set_device_registry


def test_materialize_dsl_wait_step():
    step = {
        "id": "w",
        "type": "input_wait.wait",
        "config": {"seconds": 2},
        "retry": {
            "max_attempts": 3,
            "backoff_ms": 100,
            "retryable_reasons": ["timeout"],
        },
    }
    legacy = materialize_legacy_step(step)
    assert legacy["type"] == "wait"
    assert legacy["seconds"] == 2
    policy = parse_step_retry_policy(legacy)
    assert policy is not None
    assert policy.max_attempts == 3


def test_prepare_activity_step_strips_retry_for_single_attempt():
    raw = {
        "id": "tap1",
        "type": "interaction.tap",
        "config": {"selector": "id:btn"},
        "retry": {"max_attempts": 2, "on": ["stale_frame"]},
    }
    prepared = _prepare_activity_step(raw)
    assert prepared["type"] == "tap_selector"
    assert prepared["selector"] == "id:btn"
    assert "retry" not in prepared
    assert parse_step_retry_policy(raw) is not None


def test_step_runner_retries_until_success():
    sc = MagicMock()
    sc.serial = "SN1"
    sc.trace_id = "t1"
    calls = {"n": 0}

    def fake_dispatch(_sc, _step, _idx):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"ok": False, "reason_code": "timeout", "message": "timeout"}
        return {"ok": True, "message": "ok"}

    step = {
        "type": "wait",
        "seconds": 0,
        "retry": {"max_attempts": 3, "backoff_ms": 0, "retryable_reasons": ["timeout"]},
    }

    with patch("services.execution.step_runner.dispatch_step", side_effect=fake_dispatch), patch(
        "services.execution.step_runner.capture_pre_step"
    ), patch("services.execution.step_runner.capture_post_step"), patch(
        "services.execution.step_runner.time.sleep"
    ):
        result, attempts = execute_step_with_retry(sc, step, 0)

    assert result["ok"] is True
    assert attempts == 3
    assert len(result.get("retry_attempts") or []) == 3


class _CancelOnWait:
    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def wait(self, _timeout):
        self._set = True
        return True


def test_step_runner_stops_retry_backoff_when_cancelled():
    sc = MagicMock()
    sc.serial = "SN1"
    sc.trace_id = "t1"
    sc.cancel_event = _CancelOnWait()

    step = {
        "type": "wait",
        "seconds": 0,
        "retry": {"max_attempts": 3, "backoff_ms": 1000, "retryable_reasons": ["timeout"]},
    }

    with patch(
        "services.execution.step_runner.dispatch_step",
        return_value={"ok": False, "reason_code": "timeout", "message": "timeout"},
    ) as dispatch, patch("services.execution.step_runner.capture_pre_step"), patch(
        "services.execution.step_runner.capture_post_step"
    ), patch("services.execution.step_runner.time.sleep") as sleep:
        result, attempts = execute_step_with_retry(sc, step, 0)

    assert dispatch.call_count == 1
    assert sleep.call_count == 0
    assert attempts == 1
    assert result["ok"] is False
    assert result["cancelled"] is True


@pytest.mark.asyncio
async def test_execute_device_action_materializes_dsl_before_executor():
    from temporalio.testing import ActivityEnvironment

    device = MagicMock()
    device.serial = "emulator-5554"
    device.model = "test"
    registry = MagicMock()
    registry.get_device.return_value = device
    set_device_registry(registry)

    captured: dict = {}

    def fake_run(_device, scenario, **_kwargs):
        captured["steps"] = scenario.get("steps")
        return {
            "success": True,
            "step_results": [{"index": 0, "type": "wait", "ok": True, "message": "ok"}],
        }

    inp = MagicMock()
    inp.device_serial = "emulator-5554"
    inp.step = {
        "id": "w",
        "type": "input_wait.wait",
        "config": {"seconds": 1},
        "retry": {"max_attempts": 2, "backoff_ms": 0, "retryable_reasons": ["timeout"]},
    }
    inp.step_index = 0
    inp.scenario_config = {}
    inp.scenario_registry = {}
    inp.campaign_vars = {}
    inp.variables = {}

    activities = DeviceActivities()
    env = ActivityEnvironment()

    with patch("tasks.scenario_task.run_scenario_task", side_effect=fake_run), patch(
        "temporal.activities._emit_step_events_for_activity", new_callable=AsyncMock
    ):
        result = await env.run(activities.execute_device_action, inp)

    assert result.ok is True
    assert captured["steps"][0]["type"] == "wait"
    assert captured["steps"][0]["seconds"] == 1
    assert "retry" not in captured["steps"][0]
    assert parse_step_retry_policy(inp.step) is not None
