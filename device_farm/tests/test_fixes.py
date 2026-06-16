"""
tests/test_fixes.py — Unit tests for the 4 bug fixes.

Fix #5: Temporal fallback → TaskQueue when temporal.enabled=False or Temporal unreachable
Fix #3: Popup dismiss only after tap fails, never before
Fix #1: SSIM screen check skipped when reliable selector exists
Fix #2: SSIM mismatch logs at INFO not WARNING
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest



class _MockU2:
    def __init__(self, present: set | None = None) -> None:
        self._present: set = present or set()
        self.clicks: list = []
        self.texts_typed: list = []

    def find_element(self, by: str, value: str, timeout: float = 0) -> Optional[str]:
        if (by, value) in self._present:
            return f"eid:{by}:{value}"
        return None

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict]:
        if (by, value) in self._present:
            return {"eid": f"eid:{by}:{value}", "bounds": {"left": 100, "top": 200, "right": 300, "bottom": 250}}
        return None

    def element_click(self, eid: str) -> None:
        self.clicks.append(eid)


class _MockDevice:
    def __init__(
        self,
        serial: str = "mock_serial",
        u2: Optional[_MockU2] = None,
        xml: str = "<hierarchy/>",
    ) -> None:
        self.serial = serial
        self.u2 = u2 or _MockU2()
        self.screen_width = 1080
        self.screen_height = 1920
        self.model = "MockPhone"
        self._xml = xml
        self.taps: list = []
        self._screenshot_jpeg = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG bytes

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        return self._xml

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

    def launch_app(self, package: str, **kwargs) -> None:
        pass

    def take_screenshot(self) -> Optional[bytes]:
        return self._screenshot_jpeg

    def ensure_u2_healthy(self) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Fix #5: Temporal fallback
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalFallback:
    """campaign_fleet router behavior when Temporal availability changes."""

    @pytest.mark.anyio
    async def test_temporal_disabled_calls_taskqueue(self):
        """When temporal.enabled=False, route rejects campaign run (503)."""
        from core.config import Config, TemporalConfig, DatabaseConfig
        from fastapi.responses import JSONResponse

        config = Config()
        config.temporal = TemporalConfig(enabled=False)
        config.database = DatabaseConfig(enabled=True)

        queue = MagicMock()
        manager = MagicMock()

        with patch(
            "api.routes.device_control.campaign_fleet.enqueue_campaign_run_temporal",
            new_callable=AsyncMock,
        ) as mock_temporal, patch(
            "api.routes.device_control.campaign_fleet.repo.get_campaign",
            new_callable=AsyncMock,
            return_value=MagicMock(user_id="u1"),
        ):
            from api.routes.device_control.campaign_fleet import build_campaign_fleet_router
            router = build_campaign_fleet_router(manager, queue, config)

            # Find the route handler directly
            handler = None
            for route in router.routes:
                if hasattr(route, "path") and route.path == "/campaigns/{campaign_id}/run":
                    handler = route.endpoint
                    break
            assert handler is not None

            result = await handler("c1", db=AsyncMock(), user=MagicMock(id="u1"))

            assert isinstance(result, JSONResponse)
            assert result.status_code == 503
            mock_temporal.assert_not_called()

    @pytest.mark.anyio
    async def test_temporal_enabled_but_fails_fallback_to_taskqueue(self):
        """When temporal.enabled=True but Temporal raises, route returns 500."""
        from core.config import Config, TemporalConfig, DatabaseConfig
        from fastapi.responses import JSONResponse

        config = Config()
        config.temporal = TemporalConfig(enabled=True, server_url="localhost:9999")
        config.database = DatabaseConfig(enabled=True)

        queue = MagicMock()
        manager = MagicMock()

        with patch(
            "api.routes.device_control.campaign_fleet.get_temporal_client",
            new_callable=AsyncMock,
            side_effect=ConnectionRefusedError("temporal not running"),
        ), patch(
            "api.routes.device_control.campaign_fleet.repo.get_campaign",
            new_callable=AsyncMock,
            return_value=MagicMock(user_id="u1"),
        ):
            from api.routes.device_control.campaign_fleet import build_campaign_fleet_router
            router = build_campaign_fleet_router(manager, queue, config)

            handler = None
            for route in router.routes:
                if hasattr(route, "path") and route.path == "/campaigns/{campaign_id}/run":
                    handler = route.endpoint
                    break

            result = await handler("c1", db=AsyncMock(), user=MagicMock(id="u1"))
            assert isinstance(result, JSONResponse)
            assert result.status_code == 500

    @pytest.mark.anyio
    async def test_database_disabled_returns_503(self):
        """When database is disabled, returns 503 regardless of Temporal setting."""
        from core.config import Config, TemporalConfig, DatabaseConfig
        from fastapi.responses import JSONResponse

        config = Config()
        config.temporal = TemporalConfig(enabled=False)
        config.database = DatabaseConfig(enabled=False)

        queue = MagicMock()
        manager = MagicMock()

        from api.routes.device_control.campaign_fleet import build_campaign_fleet_router
        router = build_campaign_fleet_router(manager, queue, config)

        handler = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/campaigns/{campaign_id}/run":
                handler = route.endpoint
                break

        with patch(
            "api.routes.device_control.campaign_fleet.repo.get_campaign",
            new_callable=AsyncMock,
            return_value=MagicMock(user_id="u1"),
        ):
            result = await handler("c1", db=AsyncMock(), user=MagicMock(id="u1"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 503

    @pytest.mark.anyio
    async def test_interrupt_uses_db_execution_workflow_ids_without_temporal_scan(self):
        """Manual takeover should not scan all running workflows in Temporal."""
        from core.config import Config, TemporalConfig, DatabaseConfig

        config = Config()
        config.temporal = TemporalConfig(enabled=True, server_url="localhost:7233")
        config.database = DatabaseConfig(enabled=True)

        device = MagicMock(id="dev-1", serial="SN001")
        execution = MagicMock(
            id="exec-1",
            meta={"workflow_id": "exec_exec-1"},
        )
        runtime_device = MagicMock()
        manager = MagicMock()
        manager.get_device.return_value = runtime_device
        queue = MagicMock()

        class _TemporalClient:
            def __init__(self) -> None:
                self.cancelled: list[str] = []

            def list_workflows(self, _query):
                raise AssertionError("interrupt must not scan Temporal when DB IDs exist")

            def get_workflow_handle(self, workflow_id):
                client = self

                class _Handle:
                    async def cancel(self) -> None:
                        client.cancelled.append(workflow_id)

                return _Handle()

        temporal_client = _TemporalClient()

        with patch(
            "api.routes.device_control.campaign_fleet.repo.get_device_by_serial",
            AsyncMock(return_value=device),
        ), patch(
            "api.routes.device_control.campaign_fleet.device_visible_to_user",
            AsyncMock(return_value=True),
        ), patch(
            "api.routes.device_control.campaign_fleet.repo.list_running_executions_for_device",
            AsyncMock(return_value=[execution]),
        ), patch(
            "api.routes.device_control.campaign_fleet.get_temporal_client",
            AsyncMock(return_value=temporal_client),
        ), patch(
            "api.routes.device_control.scenarios.cancel_all_previews_for_serial",
            return_value=0,
        ), patch(
            "tasks.scenario_task.force_clear_scenario_busy",
        ):
            from api.routes.device_control.campaign_fleet import build_campaign_fleet_router

            router = build_campaign_fleet_router(manager, queue, config)
            handler = next(
                route.endpoint
                for route in router.routes
                if getattr(route, "path", "") == "/devices/{serial}/interrupt"
            )

            result = await handler("SN001", db=AsyncMock(), user=MagicMock(id="u1"))

        assert result["ok"] is True
        assert result["cancelled_workflows"] == ["exec_exec-1", "exec_exec-1:steps"]
        assert temporal_client.cancelled == ["exec_exec-1", "exec_exec-1:steps"]

    @pytest.mark.anyio
    async def test_interrupt_sets_execution_cancel_flags_before_return(self):
        """Manual takeover must trip cooperative cancel flags even if Temporal is slow."""
        from core.config import Config, TemporalConfig, DatabaseConfig

        config = Config()
        config.temporal = TemporalConfig(enabled=True, server_url="localhost:7233")
        config.database = DatabaseConfig(enabled=True)

        device = MagicMock(id="dev-1", serial="SN001")
        execution = MagicMock(id="exec-1", meta={"workflow_id": "exec_exec-1"})
        manager = MagicMock()
        manager.get_device.return_value = MagicMock()

        class _TemporalClient:
            def get_workflow_handle(self, workflow_id):
                class _Handle:
                    async def cancel(self) -> None:
                        await asyncio.sleep(0)

                return _Handle()

        with patch(
            "api.routes.device_control.campaign_fleet.repo.get_device_by_serial",
            AsyncMock(return_value=device),
        ), patch(
            "api.routes.device_control.campaign_fleet.device_visible_to_user",
            AsyncMock(return_value=True),
        ), patch(
            "api.routes.device_control.campaign_fleet.repo.list_running_executions_for_device",
            AsyncMock(return_value=[execution]),
        ), patch(
            "api.routes.device_control.campaign_fleet.get_temporal_client",
            AsyncMock(return_value=_TemporalClient()),
        ), patch(
            "services.execution_pause_flags.clear_execution_paused",
            AsyncMock(),
        ) as clear_paused, patch(
            "services.execution_pause_flags.set_execution_cancelled",
            AsyncMock(),
        ) as set_cancelled, patch(
            "api.routes.device_control.scenarios.cancel_all_previews_for_serial",
            return_value=0,
        ), patch("tasks.scenario_task.force_clear_scenario_busy"):
            from api.routes.device_control.campaign_fleet import build_campaign_fleet_router

            router = build_campaign_fleet_router(manager, MagicMock(), config)
            handler = next(
                route.endpoint
                for route in router.routes
                if getattr(route, "path", "") == "/devices/{serial}/interrupt"
            )

            result = await handler("SN001", db=AsyncMock(), user=MagicMock(id="u1"))

        assert result["ok"] is True
        clear_paused.assert_awaited_once_with("exec-1")
        set_cancelled.assert_awaited_once_with("exec-1")

    @pytest.mark.anyio
    async def test_interrupt_cancel_workflows_runs_concurrently(self):
        """A slow workflow cancel must not block later workflow cancels in sequence."""
        from api.routes.device_control import campaign_fleet

        active = 0
        max_active = 0

        class _TemporalClient:
            def get_workflow_handle(self, _workflow_id):
                class _Handle:
                    async def cancel(self) -> None:
                        nonlocal active, max_active
                        active += 1
                        max_active = max(max_active, active)
                        await asyncio.sleep(0.01)
                        active -= 1

                return _Handle()

        cancelled = await campaign_fleet._cancel_interrupt_workflows(
            _TemporalClient(),
            ["wf-1", "wf-2", "wf-3"],
        )

        assert cancelled == ["wf-1", "wf-2", "wf-3"]
        assert max_active > 1


# ─────────────────────────────────────────────────────────────────────────────
# Fix #3: Popup dismiss only after tap fails
# ─────────────────────────────────────────────────────────────────────────────

class TestPopupDismissOrder:
    """_auto_dismiss_popup is called only when tap fails, never before a successful tap."""

    def _run_tap_step(self, device, step, dismiss_returns=False):
        """Helper: run a single 'tap' step via run_scenario_task and return step results."""
        from tasks.scenario_task import run_scenario_task
        scenario = {"steps": [step]}
        results = run_scenario_task(device, scenario)
        return results.get("step_results", [])

    def test_popup_not_called_when_tap_succeeds(self):
        """No popup check when tap succeeds on first try."""
        u2 = _MockU2(present={("resource-id", "com.app:id/btn")})
        device = _MockDevice(u2=u2)

        step = {
            "type": "tap",
            "selector": {"by": "resource-id", "value": "com.app:id/btn"},
            "fallback": {"rx": 0.5, "ry": 0.5},
        }

        with patch("tasks.scenario_task._auto_dismiss_popup") as mock_dismiss:
            results = self._run_tap_step(device, step)

        assert results[0]["ok"] is True
        mock_dismiss.assert_not_called()

    def test_popup_called_when_tap_fails(self):
        """Popup check is triggered when tap fails (element not found)."""
        u2 = _MockU2(present=set())  # element not found
        device = _MockDevice(u2=u2)

        step = {
            "type": "tap",
            "selector": {"by": "resource-id", "value": "com.app:id/missing_btn"},
            "fallback": {},  # no fallback coords either
        }

        with patch("tasks.scenario_task._auto_dismiss_popup", return_value=False) as mock_dismiss:
            results = self._run_tap_step(device, step)

        mock_dismiss.assert_called_once()

    def test_popup_dismissed_then_tap_retried(self):
        """After popup is dismissed, tap is retried once."""
        call_count = {"n": 0}

        # First call: element not found. After dismiss: element found.
        def fake_execute_tap(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (False, "selector not found", None)
            return (True, "selector found", {"left": 100, "top": 200, "right": 300, "bottom": 250})

        device = _MockDevice()
        step = {
            "type": "tap",
            "selector": {"by": "text", "value": "Submit"},
            "fallback": {"rx": 0.5, "ry": 0.5},
        }

        with patch("tasks.scenario_task._execute_tap", side_effect=fake_execute_tap), \
             patch("tasks.scenario_task._auto_dismiss_popup", return_value=True):
            results = self._run_tap_step(device, step)

        assert call_count["n"] == 2  # tried twice: initial + retry after dismiss
        assert results[0].get("popup_dismissed") is True

    def test_tap_ratio_no_popup_check(self):
        """tap_ratio step never calls _auto_dismiss_popup."""
        device = _MockDevice()
        step = {"type": "tap_ratio", "x": 0.5, "y": 0.5}

        with patch("tasks.scenario_task._auto_dismiss_popup") as mock_dismiss:
            self._run_tap_step(device, step)

        mock_dismiss.assert_not_called()

    def test_no_dismiss_of_intended_target(self):
        """Element with text matching popup pattern is NOT dismissed when tap succeeds."""
        # "OK" is in _POPUP_DISMISS_PATTERNS — should NOT be auto-dismissed when it's the target
        u2 = _MockU2(present={("text", "OK")})
        device = _MockDevice(u2=u2)
        step = {
            "type": "tap",
            "selector": {"by": "text", "value": "OK"},
            "fallback": {"rx": 0.5, "ry": 0.5},
        }

        with patch("tasks.scenario_task._auto_dismiss_popup") as mock_dismiss:
            results = self._run_tap_step(device, step)

        assert results[0]["ok"] is True
        mock_dismiss.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Fix #1: SSIM check skipped when reliable selector exists
# ─────────────────────────────────────────────────────────────────────────────

class TestSSIMSkipWithSelector:
    """wait_for_screen_match is not called when step has a reliable selector."""

    def _run_tap_step(self, device, step):
        from tasks.scenario_task import run_scenario_task
        scenario = {"steps": [step]}
        return run_scenario_task(device, scenario).get("step_results", [])

    def test_ssim_skipped_when_selector_present(self):
        """SSIM screen match not called when step has resource-id selector."""
        u2 = _MockU2(present={("resource-id", "com.app:id/btn")})
        device = _MockDevice(u2=u2)
        step = {
            "type": "tap",
            "selector": {"by": "resource-id", "value": "com.app:id/btn"},
            "fallback": {"rx": 0.5, "ry": 0.5},
            "screen": {
                "screenshot": "aW1hZ2U=",  # base64 dummy
                "hash": "abc123",
            },
        }

        with patch("tasks.scenario_task.run_scenario_task.__wrapped__", None, create=True), \
             patch("runtime.visual_anchor.wait_for_screen_match") as mock_ssim:
            self._run_tap_step(device, step)

        mock_ssim.assert_not_called()

    def test_ssim_runs_when_no_selector(self):
        """SSIM screen match IS called when step has no selector (fallback only)."""
        device = _MockDevice()
        # minimal valid base64 JPEG header
        import base64
        dummy_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 50).decode()
        step = {
            "type": "tap",
            "selector": {},   # no selector
            "fallback": {"rx": 0.5, "ry": 0.5},
            "screen": {
                "screenshot": dummy_b64,
                "hash": "abc123",
            },
        }

        with patch("runtime.visual_anchor.wait_for_screen_match", return_value=(True, 0.9)) as mock_ssim, \
             patch("runtime.visual_anchor._b64_to_bytes", return_value=b"\xff\xd8\xff"):
            self._run_tap_step(device, step)

        mock_ssim.assert_called_once()

    def test_ssim_skipped_for_text_selector(self):
        """SSIM also skipped for text-based selector."""
        u2 = _MockU2(present={("text", "Login")})
        device = _MockDevice(u2=u2)
        import base64
        dummy_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 50).decode()
        step = {
            "type": "tap",
            "selector": {"by": "text", "value": "Login"},
            "fallback": {"rx": 0.5, "ry": 0.5},
            "screen": {"screenshot": dummy_b64},
        }

        with patch("runtime.visual_anchor.wait_for_screen_match") as mock_ssim:
            self._run_tap_step(device, step)

        mock_ssim.assert_not_called()

    def test_container_class_selector_does_not_skip_ssim(self):
        """Container class selectors are treated as 'no real selector' — SSIM still runs."""
        import base64
        device = _MockDevice()
        dummy_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 50).decode()
        step = {
            "type": "tap",
            "selector": {"by": "class name", "value": "android.widget.FrameLayout"},
            "fallback": {"rx": 0.5, "ry": 0.5},
            "screen": {"screenshot": dummy_b64},
        }

        with patch("runtime.visual_anchor.wait_for_screen_match", return_value=(True, 0.9)) as mock_ssim, \
             patch("runtime.visual_anchor._b64_to_bytes", return_value=b"\xff\xd8\xff"):
            self._run_tap_step(device, step)

        mock_ssim.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Fix #2: SSIM mismatch logs at INFO not WARNING
# ─────────────────────────────────────────────────────────────────────────────

class TestSSIMLogLevel:
    """Screen SSIM mismatch is logged at INFO (non-blocking), not WARNING."""

    def test_ssim_mismatch_logs_info_not_warning(self, caplog):
        """When SSIM is below threshold, message is at INFO level."""
        import base64
        from tasks.scenario_task import run_scenario_task

        device = _MockDevice()
        dummy_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 50).decode()

        # Step with no selector → SSIM check will run
        step = {
            "type": "tap",
            "selector": {},
            "fallback": {"rx": 0.5, "ry": 0.5},
            "screen": {"screenshot": dummy_b64},
        }

        with patch(
            "runtime.visual_anchor.wait_for_screen_match",
            return_value=(False, 0.45),  # mismatch
        ), patch(
            "runtime.visual_anchor._b64_to_bytes",
            return_value=b"\xff\xd8\xff",
        ):
            with caplog.at_level(logging.DEBUG, logger="tasks.scenario_task"):
                run_scenario_task(device, {"steps": [step]})

        # Must have logged the mismatch
        mismatch_records = [r for r in caplog.records if "SSIM" in r.message and "0.45" in r.message]
        assert mismatch_records, "Expected SSIM mismatch log message"

        # Must NOT be WARNING — should be INFO or lower
        for record in mismatch_records:
            assert record.levelno <= logging.INFO, (
                f"SSIM mismatch logged at {record.levelname}, expected INFO or lower"
            )

    def test_ssim_mismatch_does_not_block_execution(self):
        """Execution continues (tap attempted) even when SSIM does not match."""
        import base64
        from tasks.scenario_task import run_scenario_task

        device = _MockDevice()
        dummy_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 50).decode()

        step = {
            "type": "tap",
            "selector": {},
            "fallback": {"rx": 0.5, "ry": 0.5},
            "screen": {"screenshot": dummy_b64},
        }

        with patch("runtime.visual_anchor.wait_for_screen_match", return_value=(False, 0.3)), \
             patch("runtime.visual_anchor._b64_to_bytes", return_value=b"\xff\xd8\xff"):
            results = run_scenario_task(device, {"steps": [step]})

        step_result = results["step_results"][0]
        assert step_result.get("screen_mismatch") is True
        # Tap still ran (device.taps populated or method=fallback_position)
        assert len(device.taps) > 0 or step_result.get("method") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Fix #5 config: TemporalConfig.enabled field
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalConfig:
    """TemporalConfig.enabled field defaults to False and is loaded from YAML."""

    def test_default_enabled_is_false(self):
        from core.config import TemporalConfig
        cfg = TemporalConfig()
        assert cfg.enabled is False

    def test_enabled_true_from_dict(self):
        from core.config import _build_temporal_config
        cfg = _build_temporal_config({"enabled": True, "server_url": "localhost:7233"})
        assert cfg.enabled is True

    def test_enabled_false_from_dict(self):
        from core.config import _build_temporal_config
        cfg = _build_temporal_config({"enabled": False})
        assert cfg.enabled is False

    def test_missing_enabled_defaults_false(self):
        from core.config import _build_temporal_config
        cfg = _build_temporal_config({})
        assert cfg.enabled is False
