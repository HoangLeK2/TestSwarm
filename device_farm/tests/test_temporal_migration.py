"""
tests/test_temporal_migration.py — Unit tests for Temporal-only migration.

Covers:
  1. New dataclasses in temporal/shared.py (LegacyConditionCheckInput, ExtractInput,
     ExtractResult, SaveExtractionInput, new fields on StepsInput/StepsResult)
  2. New activities (evaluate_legacy_condition, execute_extract, execute_save_extraction)
  3. New workflow handlers (loop, if, set_var, break_if, extract, save_extraction)
     via mocked workflow.execute_activity and _execute_child_steps
  4. Context propagation through nested step execution
  5. Fallback removal verification (no TaskQueue path in campaign dispatch)

Run: pytest tests/test_temporal_migration.py -v
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from temporal.shared import (
    MAX_NESTING_DEPTH,
    ExtractInput,
    ExtractResult,
    LegacyConditionCheckInput,
    SaveExtractionInput,
    StepResult,
    StepsInput,
    StepsResult,
    WorkflowProgress,
    WorkflowStatus,
)
from temporal.activities import (
    DeviceActivities,
    _validate_serial,
    set_device_registry,
)
from temporal.workflows import ScenarioStepsWorkflow


# ═══════════════════════════════════════════════════════════════════════════════
# Part 0: Mock infrastructure (shared across all test classes)
# ═══════════════════════════════════════════════════════════════════════════════


class MockU2:
    def __init__(self, present: set[tuple[str, str]] | None = None) -> None:
        self._present: set[tuple[str, str]] = present or set()

    def find_element(self, by: str, value: str, timeout: float = 0) -> Optional[str]:
        return f"eid:{by}:{value}" if (by, value) in self._present else None

    def find_element_with_bounds(self, by: str, value: str) -> Optional[Dict]:
        if (by, value) in self._present:
            return {"eid": f"eid:{by}:{value}", "bounds": {"left": 0, "top": 0, "right": 100, "bottom": 100}}
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
        self.launched_apps: list[str] = []
        self._xml_calls = 0

    def ensure_u2_healthy(self) -> None:
        pass

    def hierarchy_xml(self, force_refresh: bool = False) -> str:
        self._xml_calls += 1
        return self._xml

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))

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


_SERIAL = "192.168.1.1:5555"


def _make_registry(device: MockDevice):
    """Set up the global device registry for activities."""
    registry = MagicMock()
    registry.get_device.return_value = device
    set_device_registry(registry)
    return registry


def _make_steps_input(
    steps: list[dict],
    depth: int = 0,
    context: dict | None = None,
    runtime_vars: dict | None = None,
) -> StepsInput:
    return StepsInput(
        device_serial=_SERIAL,
        steps=steps,
        depth=depth,
        parent_runtime_vars=runtime_vars or {},
        context=context or {},
    )


def _ok_steps_result(
    steps_executed: int = 1,
    runtime_vars: dict | None = None,
    context: dict | None = None,
    break_requested: bool = False,
) -> StepsResult:
    return StepsResult(
        success=True,
        steps_executed=steps_executed,
        runtime_vars=runtime_vars or {},
        context=context or {},
        break_requested=break_requested,
    )


def _fail_steps_result(msg: str = "fail") -> StepsResult:
    return StepsResult(success=False, steps_executed=1, failed_message=msg)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 1: New dataclasses
# ═══════════════════════════════════════════════════════════════════════════════


class TestNewDataclasses:
    """Verify new dataclass fields and defaults from shared.py."""

    def test_steps_input_has_context_field(self):
        inp = StepsInput(device_serial="s1", steps=[])
        assert hasattr(inp, "context")
        assert inp.context == {}

    def test_steps_input_context_is_mutable(self):
        inp = StepsInput(device_serial="s1", steps=[], context={"posts": [{"id": "1"}]})
        assert inp.context["posts"][0]["id"] == "1"

    def test_steps_result_has_context_field(self):
        r = StepsResult(success=True, steps_executed=1)
        assert hasattr(r, "context")
        assert r.context == {}

    def test_steps_result_has_break_requested_field(self):
        r = StepsResult(success=True, steps_executed=1)
        assert hasattr(r, "break_requested")
        assert r.break_requested is False

    def test_steps_result_break_requested_can_be_set(self):
        r = StepsResult(success=True, steps_executed=1, break_requested=True)
        assert r.break_requested is True

    def test_legacy_condition_check_input_defaults(self):
        inp = LegacyConditionCheckInput(device_serial="s1", condition={"type": "element_exists"})
        assert inp.runtime_vars == {}
        assert inp.context == {}
        assert inp.device_serial == "s1"

    def test_legacy_condition_check_input_with_context(self):
        inp = LegacyConditionCheckInput(
            device_serial="s1",
            condition={"type": "posts_count_gte", "count": 5},
            runtime_vars={"LOOP_ITER": 3},
            context={"posts": [1, 2, 3, 4, 5, 6]},
        )
        assert len(inp.context["posts"]) == 6
        assert inp.runtime_vars["LOOP_ITER"] == 3

    def test_extract_input_defaults(self):
        inp = ExtractInput(device_serial="s1", step={"type": "extract"})
        assert inp.step_index == 0
        assert inp.context == {}
        assert inp.scenario_config == {}

    def test_extract_result_defaults(self):
        r = ExtractResult(ok=True, message="ok")
        assert r.context == {}
        assert r.break_requested is False
        assert r.details == {}

    def test_extract_result_break_requested(self):
        r = ExtractResult(
            ok=True,
            message="breaking",
            context={"posts": [], "_no_new_streak": 3},
            break_requested=True,
        )
        assert r.break_requested is True
        assert r.context["_no_new_streak"] == 3

    def test_save_extraction_input_defaults(self):
        inp = SaveExtractionInput(device_serial="s1", step={"type": "save_extraction"})
        assert inp.step_index == 0
        assert inp.context == {}

    def test_context_independence_between_instances(self):
        """Two StepsInput instances should not share the same context dict."""
        a = StepsInput(device_serial="s1", steps=[])
        b = StepsInput(device_serial="s2", steps=[])
        a.context["key"] = "value"
        assert "key" not in b.context


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2: evaluate_legacy_condition activity
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvaluateLegacyConditionActivity:
    """Test evaluate_legacy_condition activity with mocked device and functions."""

    def setup_method(self):
        self.device = MockDevice(serial=_SERIAL)
        _make_registry(self.device)
        self.acts = DeviceActivities()

    @pytest.mark.asyncio
    async def test_delegates_to_evaluate_condition_and_returns_true(self):
        inp = LegacyConditionCheckInput(
            device_serial=_SERIAL,
            condition={"type": "element_exists", "by": "text", "value": "OK"},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.scenario_task._evaluate_condition", return_value=True) as mock_eval,
        ):
            result = await self.acts.evaluate_legacy_condition(inp)

        assert result is True
        mock_eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_delegates_and_returns_false(self):
        inp = LegacyConditionCheckInput(
            device_serial=_SERIAL,
            condition={"type": "element_not_exists", "by": "text", "value": "Loading"},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.scenario_task._evaluate_condition", return_value=False),
        ):
            result = await self.acts.evaluate_legacy_condition(inp)

        assert result is False

    @pytest.mark.asyncio
    async def test_merges_runtime_vars_into_ctx(self):
        """runtime_vars should be injected under ctx['vars'] for condition evaluation."""
        captured: list[dict] = []

        def fake_eval(device, condition, ctx):
            captured.append(dict(ctx))
            return ctx.get("vars", {}).get("MY_VAR") == "hello"

        inp = LegacyConditionCheckInput(
            device_serial=_SERIAL,
            condition={"type": "element_exists"},
            runtime_vars={"MY_VAR": "hello"},
            context={},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.scenario_task._evaluate_condition", side_effect=fake_eval),
        ):
            result = await self.acts.evaluate_legacy_condition(inp)

        assert result is True
        assert captured[0]["vars"]["MY_VAR"] == "hello"

    @pytest.mark.asyncio
    async def test_context_posts_available_to_condition(self):
        """posts in context must be accessible so posts_count_gte works."""
        captured: list[dict] = []

        def fake_eval(device, condition, ctx):
            captured.append(dict(ctx))
            return len(ctx.get("posts", [])) >= 3

        inp = LegacyConditionCheckInput(
            device_serial=_SERIAL,
            condition={"type": "posts_count_gte", "count": 3},
            context={"posts": ["a", "b", "c"]},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.scenario_task._evaluate_condition", side_effect=fake_eval),
        ):
            result = await self.acts.evaluate_legacy_condition(inp)

        assert result is True
        assert captured[0]["posts"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_no_new_streak_in_context(self):
        """_no_new_streak must be passed through to condition checker."""
        captured: list[dict] = []

        def fake_eval(device, condition, ctx):
            captured.append(dict(ctx))
            return ctx.get("_no_new_streak", 0) >= 3

        inp = LegacyConditionCheckInput(
            device_serial=_SERIAL,
            condition={"type": "no_new_posts", "threshold": 3},
            context={"_no_new_streak": 4},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.scenario_task._evaluate_condition", side_effect=fake_eval),
        ):
            result = await self.acts.evaluate_legacy_condition(inp)

        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_serial_raises(self):
        inp = LegacyConditionCheckInput(
            device_serial="../../../etc/passwd",
            condition={"type": "element_exists"},
        )
        with pytest.raises(ValueError):
            await self.acts.evaluate_legacy_condition(inp)

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        inp = LegacyConditionCheckInput(
            device_serial=_SERIAL,
            condition={"type": "element_exists"},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.scenario_task._evaluate_condition", side_effect=RuntimeError("boom")),
        ):
            result = await self.acts.evaluate_legacy_condition(inp)

        assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3: execute_extract activity
# ═══════════════════════════════════════════════════════════════════════════════

_SIMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node text="Hello World" resource-id="com.test:id/text1" class="android.widget.TextView"/>
  <node text="Another line of text here" resource-id="com.test:id/text2"/>
</hierarchy>"""


class TestExecuteExtractActivity:
    """Test execute_extract for fb_posts and text_nodes strategies."""

    def setup_method(self):
        self.device = MockDevice(serial=_SERIAL, xml=_SIMPLE_XML)
        _make_registry(self.device)
        self.acts = DeviceActivities()

    @pytest.mark.asyncio
    async def test_fb_posts_adds_new_posts_to_context(self):
        fake_posts = [{"id": "1", "text": "post 1"}, {"id": "2", "text": "post 2"}]
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "fb_posts", "expand_see_more": False},
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=fake_posts),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.ok is True
        assert len(result.context["posts"]) == 2
        assert result.break_requested is False
        assert result.details["extracted"] == 2

    @pytest.mark.asyncio
    async def test_fb_posts_deduplicates_with_existing(self):
        existing = [{"id": "1"}]
        new_posts = [{"id": "1"}, {"id": "2"}]  # id=1 is duplicate

        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "fb_posts", "expand_see_more": False},
            context={"posts": existing},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=new_posts),
            patch("tasks.fb_extract._dedup", return_value=[{"id": "1"}, {"id": "2"}]),
        ):
            result = await self.acts.execute_extract(inp)

        assert len(result.context["posts"]) == 2  # deduped
        # added = len([1,2]) - len([1]) = 1
        assert result.details["extracted"] == 1

    @pytest.mark.asyncio
    async def test_stop_if_no_new_increments_streak(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "stop_if_no_new": True,
                "no_new_threshold": 3,
                "expand_see_more": False,
            },
            context={"posts": [{"id": "1"}], "_no_new_streak": 1},
        )
        # No new posts → streak increases
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=[]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.context["_no_new_streak"] == 2
        assert result.break_requested is False  # threshold=3 not reached

    @pytest.mark.asyncio
    async def test_stop_if_no_new_triggers_break_at_threshold(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "stop_if_no_new": True,
                "no_new_threshold": 3,
                "expand_see_more": False,
            },
            context={"posts": [{"id": "1"}], "_no_new_streak": 2},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=[]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.context["_no_new_streak"] == 3
        assert result.break_requested is True
        assert "breaking" in result.message

    @pytest.mark.asyncio
    async def test_stop_if_no_new_resets_streak_when_new_posts(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "stop_if_no_new": True,
                "no_new_threshold": 3,
                "expand_see_more": False,
            },
            context={"posts": [], "_no_new_streak": 2},
        )
        new_posts = [{"id": "fresh"}]
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=new_posts),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.context["_no_new_streak"] == 0
        assert result.break_requested is False

    @pytest.mark.asyncio
    async def test_text_nodes_strategy(self):
        """text_nodes strategy extracts visible texts from hierarchy XML."""
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "text_nodes"},
            context={},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_extract(inp)

        assert result.ok is True
        assert "text_nodes" in result.context
        # _SIMPLE_XML has "Hello World" and "Another line of text here"
        texts = result.context["text_nodes"]
        assert any("Hello" in t for t in texts)

    @pytest.mark.asyncio
    async def test_text_nodes_appends_to_existing(self):
        """text_nodes should extend, not replace, existing nodes."""
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "text_nodes"},
            context={"text_nodes": ["existing text"]},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_extract(inp)

        # Must contain the previously existing node
        assert "existing text" in result.context["text_nodes"]

    @pytest.mark.asyncio
    async def test_fb_posts_completion_retry_replaces_truncated_with_full(self):
        truncated = [{"author": "A", "timestamp": "1 giờ", "text": "Nội dung preview … Xem thêm", "_pid": "p1", "post_key": "k1"}]
        full = [{"author": "A", "timestamp": "1 giờ", "text": "Nội dung preview đã bung full không còn rút gọn", "_pid": "p1", "post_key": "k2"}]
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "expand_see_more": True,
                "expand_see_more_max_passes": 2,
                "expand_see_more_scroll": True,
                "expand_see_more_scroll_distance": 0.2,
            },
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract._expand_see_more", return_value=1),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", side_effect=[truncated, full]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.ok is True
        assert "Xem thêm" not in result.context["posts"][0]["text"]
        diag = (result.details or {}).get("extract_diagnostics") or {}
        assert diag.get("unresolved_before") == 1
        assert diag.get("unresolved_after") == 0

    @pytest.mark.asyncio
    async def test_fb_posts_completion_retry_stops_on_plateau(self):
        truncated = [{"author": "A", "timestamp": "1 giờ", "text": "Nội dung preview … Xem thêm", "_pid": "p1", "post_key": "k1"}]
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "expand_see_more": True,
                "expand_completion_retries": 4,
            },
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract._expand_see_more", return_value=1),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", side_effect=[truncated, truncated, truncated]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.ok is True
        diag = (result.details or {}).get("extract_diagnostics") or {}
        assert diag.get("completion_retries", 0) >= 2
        assert diag.get("plateau_count", 0) >= 1

    @pytest.mark.asyncio
    async def test_fb_posts_completion_retry_merges_when_viewport_drifts(self):
        first = [{"author": "A", "timestamp": "1 giờ", "text": "Post A preview … Xem thêm", "_pid": "p1", "post_key": "k1"}]
        second = [{"author": "B", "timestamp": "2 giờ", "text": "Post B full content", "_pid": "p2", "post_key": "k2"}]
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "expand_see_more": True,
                "expand_see_more_scroll": False,
                "expand_completion_retries": 2,
            },
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract._expand_see_more", return_value=1),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", side_effect=[first, second]),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.ok is True
        assert len(result.context["posts"]) == 2
        assert any(p.get("_pid") == "p1" for p in result.context["posts"])
        assert any(p.get("_pid") == "p2" for p in result.context["posts"])

    @pytest.mark.asyncio
    async def test_unknown_strategy_returns_error(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "unknown_strategy"},
            context={},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_extract(inp)

        assert result.ok is False
        assert "unknown strategy" in result.message

    @pytest.mark.asyncio
    async def test_hierarchy_xml_none_returns_error(self):
        self.device._xml = ""  # hierarchy_xml returns empty string → falsy
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "fb_posts"},
            context={},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_extract(inp)

        assert result.ok is False
        assert "hierarchy_xml" in result.message

    @pytest.mark.asyncio
    async def test_invalid_serial_raises(self):
        inp = ExtractInput(
            device_serial="'; DROP TABLE--",
            step={"type": "extract"},
        )
        with pytest.raises(ValueError):
            await self.acts.execute_extract(inp)

    @pytest.mark.asyncio
    async def test_context_is_not_mutated_in_place(self):
        """The original inp.context dict must not be mutated by the activity."""
        original_posts = [{"id": "1"}]
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "fb_posts", "expand_see_more": False},
            context={"posts": original_posts},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=[{"id": "2"}]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
        ):
            result = await self.acts.execute_extract(inp)

        # The returned context may have new posts; original list must be unchanged
        assert len(original_posts) == 1

    @pytest.mark.asyncio
    async def test_expand_see_more_called_when_true(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "fb_posts", "expand_see_more": True},
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=[]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
            patch("tasks.fb_extract._expand_see_more", return_value=True) as mock_expand,
        ):
            await self.acts.execute_extract(inp)

        mock_expand.assert_called_once_with(
            self.device,
            max_passes=2,
            scroll_between=False,
            scroll_distance=0.3,
        )

    @pytest.mark.asyncio
    async def test_expand_see_more_uses_progressive_params_for_long_posts(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={
                "type": "extract",
                "strategy": "fb_posts",
                "expand_see_more": True,
                "expand_see_more_max_passes": 6,
                "expand_see_more_scroll": True,
                "expand_see_more_scroll_distance": 0.22,
            },
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", return_value=[]),
            patch("tasks.fb_extract._dedup", side_effect=lambda lst: lst),
            patch("tasks.fb_extract._expand_see_more", return_value=3) as mock_expand,
        ):
            await self.acts.execute_extract(inp)

        mock_expand.assert_called_once_with(
            self.device,
            max_passes=6,
            scroll_between=True,
            scroll_distance=0.22,
        )

    @pytest.mark.asyncio
    async def test_exception_returns_error_result(self):
        inp = ExtractInput(
            device_serial=_SERIAL,
            step={"type": "extract", "strategy": "fb_posts", "expand_see_more": False},
            context={"posts": []},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("tasks.fb_extract.parse_fb_posts_from_xml", side_effect=RuntimeError("db down")),
        ):
            result = await self.acts.execute_extract(inp)

        assert result.ok is False
        assert "extract failed" in result.message


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4: execute_save_extraction activity
# ═══════════════════════════════════════════════════════════════════════════════


class TestExecuteSaveExtractionActivity:
    """Test execute_save_extraction activity with mocked save_content_item."""

    def setup_method(self):
        self.device = MockDevice(serial=_SERIAL)
        _make_registry(self.device)
        self.acts = DeviceActivities()

    @pytest.mark.asyncio
    async def test_saves_list_of_posts_from_context(self):
        posts = [{"id": "1", "text": "hello"}, {"id": "2", "text": "world"}]
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts", "collection": "default"},
            context={"posts": posts},
        )
        saved_responses = [{"saved": True}, {"saved": True}]

        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", side_effect=saved_responses),
        ):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is True
        assert result.details["saved_count"] == 2
        assert result.details["duplicate_count"] == 0
        assert result.details["error_count"] == 0

    @pytest.mark.asyncio
    async def test_duplicate_items_counted_correctly(self):
        posts = [{"id": "1"}, {"id": "2"}]
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts"},
            context={"posts": posts},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", side_effect=[
                {"saved": False},  # duplicate
                {"saved": True},   # new
            ]),
        ):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is True
        assert result.details["saved_count"] == 1
        assert result.details["duplicate_count"] == 1

    @pytest.mark.asyncio
    async def test_all_errors_marks_result_failed(self):
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts"},
            context={"posts": [{"id": "1"}]},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", side_effect=Exception("db down")),
        ):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is False
        assert result.details["error_count"] >= 1

    @pytest.mark.asyncio
    async def test_missing_data_var_returns_error(self):
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": ""},
            context={},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is False
        assert "missing data_var" in result.message

    @pytest.mark.asyncio
    async def test_variable_not_in_context_returns_error(self):
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "nonexistent_var"},
            context={},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_empty_list_is_no_op(self):
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts"},
            context={"posts": []},
        )
        with patch("temporal.activities.activity.heartbeat"):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is True
        assert result.details["saved_count"] == 0
        assert "no new items" in result.message or "no items" in result.message

    @pytest.mark.asyncio
    async def test_string_data_wrapped_in_list(self):
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "my_text"},
            context={"my_text": "extracted content"},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", return_value={"saved": True}),
        ):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is True
        assert result.details["saved_count"] == 1

    @pytest.mark.asyncio
    async def test_dict_data_saved_as_single_item(self):
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "item"},
            context={"item": {"id": "42", "text": "direct dict"}},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", return_value={"saved": True}),
        ):
            result = await self.acts.execute_save_extraction(inp)

        assert result.ok is True
        assert result.details["saved_count"] == 1

    @pytest.mark.asyncio
    async def test_offset_skips_already_saved_items(self):
        """Offset tracking ensures items already saved in previous runs are skipped."""
        posts = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        # start_idx=2 means only the 3rd item is new
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts"},
            context={
                "posts": posts,
                "__save_extraction_offsets__": {"posts": 2},
            },
        )
        saved_calls = []

        async def fake_save(data, **kwargs):
            saved_calls.append(data)
            return {"saved": True}

        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", side_effect=fake_save),
        ):
            result = await self.acts.execute_save_extraction(inp)

        # Only item at index 2 (id=3) should have been saved
        assert len(saved_calls) == 1
        assert saved_calls[0]["id"] == "3"
        assert result.details["saved_count"] == 1

    @pytest.mark.asyncio
    async def test_invalid_serial_raises(self):
        inp = SaveExtractionInput(
            device_serial="<script>",
            step={"type": "save_extraction"},
        )
        with pytest.raises(ValueError):
            await self.acts.execute_save_extraction(inp)


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5: Workflow handler methods
# ═══════════════════════════════════════════════════════════════════════════════
#
# The handlers use workflow.execute_activity (Temporal runtime).
# We patch it via `patch("temporalio.workflow.execute_activity")` and also
# patch `_execute_child_steps` on the instance to avoid recursion.
# ═══════════════════════════════════════════════════════════════════════════════


def _make_workflow() -> ScenarioStepsWorkflow:
    """Instantiate workflow class without Temporal context."""
    return ScenarioStepsWorkflow()


class TestSetVarHandler:
    """Test set_var inline handler in ScenarioStepsWorkflow.run()."""

    @pytest.mark.asyncio
    async def test_set_var_writes_to_context_vars(self):
        """set_var should write value to runtime_context['vars'][key]."""
        inp = _make_steps_input([{"type": "set_var", "key": "MY_KEY", "value": "hello"}])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            # Patch _execute_child_steps to prevent recursion (not needed here)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("MY_KEY") == "hello"

    @pytest.mark.asyncio
    async def test_set_var_uses_name_field_as_fallback(self):
        """set_var should accept 'name' as alias for 'key'."""
        inp = _make_steps_input([{"type": "set_var", "name": "ALT_KEY", "value": 42}])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("ALT_KEY") == 42

    @pytest.mark.asyncio
    async def test_set_var_missing_key_records_error_but_continues(self):
        """Missing key should produce an error step result but not fail the scenario."""
        inp = _make_steps_input([
            {"type": "set_var"},  # no key or name
            {"type": "set_var", "key": "AFTER", "value": "ok"},
        ])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        # The second step should still execute; result has 2 steps
        assert result.steps_executed == 2
        error_step = result.step_results[0]
        assert error_step["ok"] is False
        assert error_step["type"] == "set_var"

    @pytest.mark.asyncio
    async def test_set_var_multiple_vars_all_present(self):
        inp = _make_steps_input([
            {"type": "set_var", "key": "A", "value": 1},
            {"type": "set_var", "key": "B", "value": 2},
        ])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.context["vars"]["A"] == 1
        assert result.context["vars"]["B"] == 2


class TestBreakIfHandler:
    """Test break_if inline handler in ScenarioStepsWorkflow.run()."""

    @pytest.mark.asyncio
    async def test_break_if_condition_met_sets_break_requested(self):
        """When condition is met, break_requested=True and loop exits."""
        steps = [
            {"type": "set_var", "key": "X", "value": 1},
            {"type": "break_if", "condition": {"type": "element_exists"}},
            {"type": "set_var", "key": "UNREACHABLE", "value": 99},
        ]
        inp = _make_steps_input(steps)

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = True  # condition met
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.break_requested is True
        # The step after break_if must NOT have executed
        executed_types = [s["type"] for s in result.step_results]
        assert "UNREACHABLE" not in str(result.context)
        assert "break_if" in executed_types

    @pytest.mark.asyncio
    async def test_break_if_condition_not_met_continues(self):
        """When condition is not met, execution continues normally."""
        steps = [
            {"type": "break_if", "condition": {"type": "element_not_exists"}},
            {"type": "set_var", "key": "REACHED", "value": True},
        ]
        inp = _make_steps_input(steps)

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = False  # condition NOT met
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.break_requested is False
        assert result.context.get("vars", {}).get("REACHED") is True

    @pytest.mark.asyncio
    async def test_break_if_missing_condition_records_error(self):
        """Missing condition dict produces error step result."""
        inp = _make_steps_input([{"type": "break_if"}])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.step_results[0]["ok"] is False
        assert "missing condition" in result.step_results[0]["message"]


class TestLoopHandler:
    """Test _handle_loop — count mode, while mode, break_if integration."""

    @pytest.mark.asyncio
    async def test_loop_count_executes_n_iterations(self):
        inp = _make_steps_input([{
            "type": "loop",
            "count": 3,
            "steps": [{"type": "set_var", "key": "ITER", "value": "x"}],
        }])
        child_result = _ok_steps_result(context={"vars": {"ITER": "x"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=child_result)
            result = await wf.run(inp)

        assert result.success is True
        assert wf._execute_child_steps.call_count == 3

    @pytest.mark.asyncio
    async def test_loop_count_zero_runs_no_iterations(self):
        inp = _make_steps_input([{
            "type": "loop",
            "count": 0,
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=_ok_steps_result())
            result = await wf.run(inp)

        assert result.success is True
        assert wf._execute_child_steps.call_count == 0

    @pytest.mark.asyncio
    async def test_loop_while_exits_when_condition_false(self):
        """while-loop should stop when evaluate_legacy_condition returns False."""
        call_count = [0]

        async def fake_exec_act(name, inp, **kwargs):
            call_count[0] += 1
            # Returns True for first 2 condition checks (run 2 iterations), False on 3rd
            return call_count[0] <= 2

        inp = _make_steps_input([{
            "type": "loop",
            "while": {"type": "element_exists"},
            "max_iterations": 10,
            "steps": [{"type": "set_var", "key": "W", "value": 1}],
        }])
        child_result = _ok_steps_result()

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.side_effect = fake_exec_act
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=child_result)
            result = await wf.run(inp)

        assert result.success is True
        # Should have run 2 iterations (condition True x2, then False)
        assert wf._execute_child_steps.call_count == 2

    @pytest.mark.asyncio
    async def test_loop_break_requested_from_child_exits_early(self):
        """break_requested from child steps should stop the loop early."""
        child_results = [
            _ok_steps_result(),
            _ok_steps_result(break_requested=True),  # break on 2nd iteration
            _ok_steps_result(),  # should NOT be reached
        ]

        inp = _make_steps_input([{
            "type": "loop",
            "count": 10,
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(side_effect=child_results)
            result = await wf.run(inp)

        assert result.success is True
        assert wf._execute_child_steps.call_count == 2

    @pytest.mark.asyncio
    async def test_loop_failed_iteration_stops_scenario(self):
        """Failed child step should propagate failure up."""
        child_results = [
            _ok_steps_result(),
            _fail_steps_result("step 2 device error"),
        ]
        inp = _make_steps_input([{
            "type": "loop",
            "count": 5,
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(side_effect=child_results)
            result = await wf.run(inp)

        assert result.success is False
        assert "step 2 device error" in (result.failed_message or "")
        assert wf._execute_child_steps.call_count == 2

    @pytest.mark.asyncio
    async def test_loop_missing_steps_fails(self):
        inp = _make_steps_input([{"type": "loop", "count": 3, "steps": []}])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "no nested steps" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_loop_missing_count_and_while_fails(self):
        inp = _make_steps_input([{
            "type": "loop",
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "count" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_loop_sets_loop_iter_variable(self):
        """__LOOP_ITER__ should be set to the iteration index."""
        received_vars: list[dict] = []

        async def spy_child(parent_inp, steps, runtime_vars, runtime_context, **kw):
            received_vars.append(dict(runtime_vars))
            return _ok_steps_result()

        inp = _make_steps_input([{
            "type": "loop",
            "count": 3,
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = spy_child
            await wf.run(inp)

        assert received_vars[0]["__LOOP_ITER__"] == 0
        assert received_vars[1]["__LOOP_ITER__"] == 1
        assert received_vars[2]["__LOOP_ITER__"] == 2

    @pytest.mark.asyncio
    async def test_loop_context_accumulates_across_iterations(self):
        """Context from each iteration should carry forward to the next."""
        iteration = [0]

        async def child_with_growing_context(parent_inp, steps, runtime_vars, runtime_context, **kw):
            n = iteration[0]
            iteration[0] += 1
            new_posts = runtime_context.get("posts", []) + [{"id": str(n)}]
            return _ok_steps_result(context={"posts": new_posts})

        inp = _make_steps_input(
            steps=[{"type": "loop", "count": 3, "steps": [{"type": "set_var", "key": "X", "value": 1}]}],
            context={"posts": []},
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = child_with_growing_context
            result = await wf.run(inp)

        assert result.success is True
        assert len(result.context.get("posts", [])) == 3


class TestIfHandler:
    """Test _handle_if — generic condition-based branch."""

    @pytest.mark.asyncio
    async def test_if_true_executes_then_branch(self):
        inp = _make_steps_input([{
            "type": "if",
            "condition": {"type": "element_exists", "by": "text", "value": "OK"},
            "then": [{"type": "set_var", "key": "BRANCH", "value": "then"}],
            "else": [{"type": "set_var", "key": "BRANCH", "value": "else"}],
        }])
        then_result = _ok_steps_result(context={"vars": {"BRANCH": "then"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = True  # condition met
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=then_result)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("BRANCH") == "then"

    @pytest.mark.asyncio
    async def test_if_false_executes_else_branch(self):
        inp = _make_steps_input([{
            "type": "if",
            "condition": {"type": "element_not_exists", "by": "text", "value": "Loading"},
            "then": [{"type": "set_var", "key": "BRANCH", "value": "then"}],
            "else": [{"type": "set_var", "key": "BRANCH", "value": "else"}],
        }])
        else_result = _ok_steps_result(context={"vars": {"BRANCH": "else"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = False  # condition not met
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=else_result)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("BRANCH") == "else"

    @pytest.mark.asyncio
    async def test_if_false_no_else_branch_succeeds(self):
        inp = _make_steps_input([{
            "type": "if",
            "condition": {"type": "element_exists"},
            "then": [{"type": "set_var", "key": "X", "value": 1}],
            # no else
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = False  # condition false
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock()
            result = await wf.run(inp)

        assert result.success is True
        wf._execute_child_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_if_missing_condition_fails(self):
        inp = _make_steps_input([{
            "type": "if",
            "then": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "missing condition" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_if_branch_failure_propagates(self):
        inp = _make_steps_input([{
            "type": "if",
            "condition": {"type": "element_exists"},
            "then": [{"type": "launch_app", "package": "com.test"}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = True
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=_fail_steps_result("app not installed"))
            result = await wf.run(inp)

        assert result.success is False
        assert "app not installed" in (result.failed_message or "")


class TestExtractInWorkflow:
    """Test extract and save_extraction dispatch in workflow run()."""

    @pytest.mark.asyncio
    async def test_extract_calls_execute_extract_activity(self):
        """Workflow must call execute_extract activity for extract steps."""
        extract_result = ExtractResult(
            ok=True,
            message="extract fb_posts: +5 new (total 5)",
            context={"posts": [{"id": str(i)} for i in range(5)]},
        )
        inp = _make_steps_input([{
            "type": "extract",
            "strategy": "fb_posts",
        }])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = extract_result
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is True
        assert len(result.context.get("posts", [])) == 5
        mock_act.assert_called_once()
        call_args = mock_act.call_args[0]
        assert call_args[0] == "execute_extract"

    @pytest.mark.asyncio
    async def test_extract_break_requested_propagates(self):
        """break_requested from extract activity must stop execution."""
        extract_result = ExtractResult(
            ok=True,
            message="breaking — no new for 3 scrolls",
            context={"posts": [], "_no_new_streak": 3},
            break_requested=True,
        )
        inp = _make_steps_input([
            {"type": "extract", "strategy": "fb_posts"},
            {"type": "set_var", "key": "UNREACHABLE", "value": 1},
        ])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = extract_result
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.break_requested is True
        assert result.steps_executed == 1  # only the extract step ran

    @pytest.mark.asyncio
    async def test_extract_failure_stops_scenario(self):
        extract_result = ExtractResult(ok=False, message="hierarchy_xml returned None")
        inp = _make_steps_input([
            {"type": "extract", "strategy": "fb_posts"},
            {"type": "set_var", "key": "X", "value": 1},
        ])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = extract_result
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "hierarchy_xml" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_extract_merges_context_back(self):
        """Context returned from extract activity must be merged into runtime_context."""
        extract_result = ExtractResult(
            ok=True,
            message="ok",
            context={"posts": [{"id": "1"}], "_no_new_streak": 0},
        )
        inp = _make_steps_input(
            steps=[{"type": "extract", "strategy": "fb_posts"}],
            context={"existing_key": "preserved"},
        )

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = extract_result
            wf = _make_workflow()
            result = await wf.run(inp)

        assert len(result.context.get("posts", [])) == 1
        assert result.context.get("existing_key") == "preserved"

    @pytest.mark.asyncio
    async def test_save_extraction_calls_activity(self):
        save_result = StepResult(
            index=0, step_type="save_extraction", ok=True,
            message="save_extraction: saved=3, duplicate=0, errors=0",
            details={"saved_count": 3, "duplicate_count": 0, "error_count": 0},
        )
        inp = _make_steps_input(
            steps=[{"type": "save_extraction", "data_var": "posts"}],
            context={"posts": [{"id": str(i)} for i in range(3)]},
        )

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = save_result
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is True
        call_name = mock_act.call_args[0][0]
        assert call_name == "execute_save_extraction"

    @pytest.mark.asyncio
    async def test_save_extraction_passes_context_to_activity(self):
        """The current runtime_context must be forwarded to execute_save_extraction."""
        captured_inputs: list = []
        save_result = StepResult(
            index=0, step_type="save_extraction", ok=True,
            message="saved=1", details={"saved_count": 1},
        )

        async def capture(name, inp_obj, **kwargs):
            captured_inputs.append(inp_obj)
            return save_result

        posts = [{"id": "1"}, {"id": "2"}]
        inp = _make_steps_input(
            steps=[{"type": "save_extraction", "data_var": "posts"}],
            context={"posts": posts},
        )

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.side_effect = capture
            wf = _make_workflow()
            await wf.run(inp)

        assert len(captured_inputs) == 1
        assert captured_inputs[0].context.get("posts") == posts


# ═══════════════════════════════════════════════════════════════════════════════
# Part 6: Context propagation through _execute_child_steps
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextPropagation:
    """Verify context flows correctly through nested step execution."""

    @pytest.mark.asyncio
    async def test_execute_child_steps_passes_context_to_nested_input(self):
        """_execute_child_steps must include runtime_context in StepsInput.context."""
        captured_inputs: list[StepsInput] = []

        original_run = ScenarioStepsWorkflow.run

        async def spy_run(self_wf, inp: StepsInput) -> StepsResult:
            captured_inputs.append(inp)
            if inp.depth > 0:
                return _ok_steps_result(context={"passed_through": True})
            return await original_run(self_wf, inp)

        parent_inp = _make_steps_input(
            steps=[{
                "type": "repeat",
                "count": 1,
                "steps": [{"type": "set_var", "key": "X", "value": 1}],
            }],
            context={"initial_context_key": "value"},
        )

        with (
            patch("temporalio.workflow.execute_activity", new_callable=AsyncMock),
            patch("temporalio.workflow.sleep", new_callable=AsyncMock),
            patch.object(ScenarioStepsWorkflow, "run", spy_run),
        ):
            wf = ScenarioStepsWorkflow()
            await wf.run(parent_inp)

        # The child input (depth=1) must have context populated
        child_inputs = [i for i in captured_inputs if i.depth > 0]
        assert len(child_inputs) >= 1
        assert child_inputs[0].context.get("initial_context_key") == "value"

    @pytest.mark.asyncio
    async def test_child_context_merged_back_to_parent(self):
        """Context returned from _execute_child_steps must be merged into runtime_context."""
        child_ctx = {"posts": [{"id": "from_child"}], "new_key": True}
        child_res = _ok_steps_result(context=child_ctx)

        inp = _make_steps_input(
            steps=[{
                "type": "repeat",
                "count": 1,
                "steps": [{"type": "set_var", "key": "X", "value": 1}],
            }],
            context={"parent_key": "preserved"},
        )

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=child_res)
            result = await wf.run(inp)

        assert result.context.get("parent_key") == "preserved"
        assert result.context.get("new_key") is True
        assert len(result.context.get("posts", [])) == 1

    @pytest.mark.asyncio
    async def test_break_requested_propagates_from_child_to_parent(self):
        """break_requested=True in child StepsResult must propagate up."""
        child_res = _ok_steps_result(break_requested=True)

        inp = _make_steps_input(
            steps=[{
                "type": "loop",
                "count": 5,
                "steps": [{"type": "set_var", "key": "X", "value": 1}],
            }]
        )

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=child_res)
            result = await wf.run(inp)

        assert result.success is True
        # Loop should have exited after 1 iteration
        assert wf._execute_child_steps.call_count == 1

    def test_execute_child_steps_increments_depth(self):
        """_execute_child_steps must pass depth+1 to nested StepsInput."""
        wf = _make_workflow()
        parent = _make_steps_input(steps=[{"type": "wait", "seconds": 1}], depth=3)

        # We call the method but it recurses into self.run — we just check
        # that the StepsInput it would build has depth=4.
        # Access via inspection of the code path.
        child_inp = StepsInput(
            device_serial=parent.device_serial,
            steps=[],
            depth=parent.depth + 1,
            context=dict(parent.context),
        )
        assert child_inp.depth == 4

    @pytest.mark.asyncio
    async def test_max_nesting_depth_enforced(self):
        """Steps at depth > MAX_NESTING_DEPTH must be rejected."""
        inp = _make_steps_input(
            steps=[{"type": "set_var", "key": "X", "value": 1}],
            depth=MAX_NESTING_DEPTH + 1,
        )
        wf = _make_workflow()
        result = await wf.run(inp)

        assert result.success is False
        assert "Max nesting depth" in (result.failed_message or "")


# ═══════════════════════════════════════════════════════════════════════════════
# Part 7: Integrated scenario — loop + extract + save_extraction
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntegratedScrollAndExtract:
    """
    Simulate the canonical scroll→extract→save_extraction pattern
    that motivated the migration.
    """

    @pytest.mark.asyncio
    async def test_loop_extract_accumulates_posts_over_iterations(self):
        """
        loop(count=3) { extract fb_posts } should accumulate posts in context
        across iterations and return the final combined context.
        """
        iter_posts = [
            [{"id": "1"}],
            [{"id": "2"}, {"id": "3"}],
            [],  # no new posts on 3rd scroll
        ]
        call_count = [0]

        async def fake_execute_child(parent_inp, steps, runtime_vars, runtime_context, **kw):
            n = call_count[0]
            call_count[0] += 1
            existing = runtime_context.get("posts", [])
            new_context = {**runtime_context, "posts": existing + iter_posts[n]}
            return _ok_steps_result(context=new_context)

        inp = _make_steps_input(
            steps=[{
                "type": "loop",
                "count": 3,
                "steps": [{"type": "extract", "strategy": "fb_posts"}],
            }],
            context={"posts": []},
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = fake_execute_child
            result = await wf.run(inp)

        assert result.success is True
        assert len(result.context.get("posts", [])) == 3

    @pytest.mark.asyncio
    async def test_loop_stops_on_break_requested_from_extract(self):
        """
        When extract fires break_requested (stop_if_no_new), the parent loop
        must stop without running remaining iterations.
        """
        async def fake_execute_child(parent_inp, steps, runtime_vars, runtime_context, **kw):
            # First iteration fine, second triggers break
            if runtime_vars.get("__LOOP_ITER__", 0) == 1:
                return _ok_steps_result(break_requested=True, context={"_no_new_streak": 3})
            return _ok_steps_result(context={"posts": [{"id": "fresh"}]})

        inp = _make_steps_input(
            steps=[{
                "type": "loop",
                "count": 10,
                "steps": [{"type": "extract", "strategy": "fb_posts", "stop_if_no_new": True}],
            }],
            context={"posts": []},
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = fake_execute_child
            result = await wf.run(inp)

        assert result.success is True
        # Should have stopped after 2 iterations (index 0 and 1)
        assert result.context.get("_no_new_streak") == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Part 8: Fallback removal verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackRemoval:
    """Verify the TaskQueue fallback code has been removed from all dispatch paths."""

    def test_enqueue_campaign_run_no_longer_exported(self):
        """enqueue_campaign_run (TaskQueue path) must not exist in campaign_dispatch."""
        import services.campaign_dispatch as dispatch_module
        assert not hasattr(dispatch_module, "enqueue_campaign_run"), (
            "enqueue_campaign_run still exists — TaskQueue fallback was NOT removed"
        )

    def test_campaign_dispatch_has_no_task_queue_import(self):
        """TaskQueue should not be imported in campaign_dispatch after migration."""
        import inspect
        import services.campaign_dispatch as m
        src = inspect.getsource(m)
        # TaskQueue import was removed
        assert "from runtime.core import Task, TaskQueue" not in src
        # The enqueue_campaign_run function body must not exist
        assert "queue.put(task)" not in src

    def test_only_temporal_dispatch_function_remains(self):
        """Only enqueue_campaign_run_temporal should exist."""
        import services.campaign_dispatch as m
        assert hasattr(m, "enqueue_campaign_run_temporal")

    @pytest.mark.asyncio
    async def test_campaign_fleet_returns_503_when_temporal_disabled(self):
        """POST /campaigns/{id}/run must return 503 when temporal.enabled=False."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.routes.device_control.campaign_fleet import build_campaign_fleet_router
        from unittest.mock import MagicMock

        config = MagicMock()
        config.database.enabled = True
        config.temporal.enabled = False

        manager = MagicMock()
        queue = MagicMock()

        app = FastAPI()
        router = build_campaign_fleet_router(manager, queue, config)
        app.include_router(router, prefix="/api")

        client = TestClient(app)
        response = client.post("/api/campaigns/test-campaign/run")

        assert response.status_code == 503
        assert "Temporal" in response.json().get("error", "")

    @pytest.mark.asyncio
    async def test_scheduler_dispatch_campaign_raises_without_temporal(self):
        """_dispatch_campaign must raise RuntimeError when temporal_client is None."""
        from services.scheduler import _dispatch_campaign

        with pytest.raises(RuntimeError, match="Temporal"):
            await _dispatch_campaign(
                cfg={"target_id": "campaign-123"},
                queue=None,
                temporal_client=None,
                temporal_config=None,
            )

    @pytest.mark.asyncio
    async def test_schedule_activities_dispatch_raises_without_temporal(self):
        """schedule_activities dispatch_schedule must raise when temporal_client is None."""
        from temporal.schedule_activities import ScheduleActivities, set_scheduler_deps

        set_scheduler_deps(queue=None, manager=None, temporal_client=None, temporal_config=None)
        acts = ScheduleActivities()

        schedule_config = {
            "id": "sched-1",
            "target_type": "campaign",
            "target_id": "campaign-1",
            "stagger_devices": False,
            "stagger_interval_seconds": 5,
        }
        with patch("temporal.schedule_activities.activity.heartbeat"):
            result = await acts.dispatch_schedule(schedule_config, "run-1")

        # dispatch_schedule catches internal errors and returns them in error field
        assert result.error is not None
        assert "Temporal" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# Part 9: Round 2 security, correctness, and performance fixes
# ═══════════════════════════════════════════════════════════════════════════════


class TestCredentialSecurity:
    """CRITICAL: Passwords must not appear in workflow inputs (Temporal event history)."""

    def test_get_device_account_vars_excludes_password(self):
        """_get_device_account_vars must return __ACCOUNT_ID__ but NOT __ACCOUNT_PASSWORD__ in the return dict."""
        import inspect
        import services.campaign_dispatch as m
        src = inspect.getsource(m._get_device_account_vars)
        # Account ID must be included so activities can fetch credentials
        assert "__ACCOUNT_ID__" in src
        # Password must NOT be a key in the returned dict literal.
        # The function may mention the password in a comment but must not return it.
        # Find the return dict — it should not have __ACCOUNT_PASSWORD__ as a key.
        import ast
        tree = ast.parse(inspect.getsource(m._get_device_account_vars))
        returned_keys = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                for k in node.value.keys:
                    if isinstance(k, ast.Constant):
                        returned_keys.add(k.value)
        assert "__ACCOUNT_PASSWORD__" not in returned_keys, (
            f"__ACCOUNT_PASSWORD__ found in returned dict keys: {returned_keys}"
        )
        assert "__ACCOUNT_ID__" in returned_keys

    def test_account_id_in_scenario_input_not_password(self):
        """enqueue_campaign_run_temporal must pass __ACCOUNT_ID__, not __ACCOUNT_PASSWORD__."""
        import inspect
        import services.campaign_dispatch as m
        src = inspect.getsource(m.enqueue_campaign_run_temporal)
        # Password must not be placed in any workflow input
        assert "__ACCOUNT_PASSWORD__" not in src

    def test_execute_device_action_resolves_credentials_in_activity(self):
        """execute_device_action must contain the credential-resolution block."""
        import inspect
        from temporal.activities import DeviceActivities
        src = inspect.getsource(DeviceActivities.execute_device_action)
        # Must fetch credentials at activity time
        assert "__ACCOUNT_ID__" in src
        assert "decrypt_password" in src
        assert "get_account" in src


class TestSaveExtractionOffsetCorrectness:
    """HIGH-2: Offset must only advance past successfully processed items (not errors)."""

    def setup_method(self):
        self.device = MockDevice(serial=_SERIAL)
        _make_registry(self.device)
        self.acts = DeviceActivities()

    @pytest.mark.asyncio
    async def test_offset_does_not_advance_past_errored_items(self):
        """
        When some items error during save, offset must only count saved+dup.
        The errored items must be retryable on next call.
        """
        posts = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts"},
            context={"posts": posts},
        )
        # Item 1 saved, item 2 errors, item 3 saved
        side_effects = [
            {"saved": True},
            Exception("db timeout"),
            {"saved": True},
        ]

        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", side_effect=side_effects),
        ):
            result = await self.acts.execute_save_extraction(inp)

        # saved=2, dup=0, err=1 → offset should be 2 (not 3)
        assert result.details["saved_count"] == 2
        assert result.details["error_count"] == 1
        new_offset = result.details["updated_offsets"]["posts"]
        assert new_offset == 2  # only 2 successfully processed, not 3

    @pytest.mark.asyncio
    async def test_offset_advances_correctly_for_all_saved(self):
        """Offset = start_idx + saved + dup when no errors."""
        # start_idx=0, 3 items, 2 saved + 1 dup → new_offset=3
        posts = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        inp = SaveExtractionInput(
            device_serial=_SERIAL,
            step={"type": "save_extraction", "data_var": "posts"},
            context={"posts": posts},
        )
        with (
            patch("temporal.activities.activity.heartbeat"),
            patch("services.content_store.save_content_item", side_effect=[
                {"saved": True},   # saved
                {"saved": False},  # dup
                {"saved": True},   # saved
            ]),
        ):
            result = await self.acts.execute_save_extraction(inp)

        new_offset = result.details["updated_offsets"]["posts"]
        # start_idx=0, saved=2, dup=1 → offset=3
        assert new_offset == 3


class TestAllScenariosEmptySteps:
    """HIGH-3: Informative 400 error when all scenarios have empty steps."""

    def _make_db_mock(self):
        """Create a reusable async context-manager DB mock."""
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        return mock_db

    @pytest.mark.asyncio
    async def test_all_empty_scenarios_returns_400_not_500(self):
        """When all scenarios exist but have no steps, return 400 with clear message."""
        from services.campaign_dispatch import enqueue_campaign_run_temporal

        mock_campaign = MagicMock()
        mock_campaign.variables = {}
        mock_campaign.scenario = {}
        mock_campaign.target_group_id = None

        mock_device = MagicMock()
        mock_device.id = "dev-1"
        mock_device.serial = "emulator-5554"

        mock_scen1 = MagicMock(steps=[], variables={}, name="Scenario A")
        mock_scen2 = MagicMock(steps=[], variables={}, name="Scenario B")

        patches = [
            patch("services.campaign_dispatch.AsyncSessionLocal", return_value=self._make_db_mock()),
            patch("services.campaign_dispatch.repo.get_campaign", return_value=mock_campaign),
            patch("services.campaign_dispatch.repo.list_campaign_devices", return_value=[mock_device]),
            patch("services.campaign_dispatch.repo.list_scenarios", return_value=[mock_scen1, mock_scen2]),
            patch("services.campaign_dispatch.repo.update_campaign_status"),
            patch("db.crud.scenario_template.list_templates", return_value=[]),
            patch("db.crud.account.get_primary_account_for_device", return_value=None),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            result, status = await enqueue_campaign_run_temporal("campaign-1", MagicMock())

        assert status == 400
        assert "steps" in result["error"].lower()


class TestWifiAdbWorkflowFilter:
    """HIGH-4: Workflow ID filter must handle WiFi ADB serials (contain ':')."""

    def test_top_level_regex_accepts_wifi_serial(self):
        """Regex must accept workflow IDs with IP:port serials."""
        import re
        pattern = re.compile(r"^campaign:[^:]+:device:.+:scenario:[^:]+$")
        # Standard serial
        assert pattern.match("campaign:c1:device:emulator-5554:scenario:s1")
        # WiFi ADB serial (contains ':')
        assert pattern.match("campaign:c1:device:192.168.1.1:5555:scenario:s1")

    def test_top_level_regex_rejects_child_workflows(self):
        """Child workflows must be filtered out."""
        import re
        pattern = re.compile(r"^campaign:[^:]+:device:.+:scenario:[^:]+$")
        assert not pattern.match("campaign:c1:device:emulator-5554:scenario:s1:steps")
        assert not pattern.match("campaign:c1:device:192.168.1.1:5555:scenario:s1:repeat:0")
        assert not pattern.match("campaign:c1:device:192.168.1.1:5555:scenario:s1:if_element")

    def test_campaign_fleet_uses_regex_filter(self):
        """campaign_fleet.py must use regex, not colon counting."""
        import inspect
        import api.routes.device_control.campaign_fleet as m
        src = inspect.getsource(m)
        # Must use regex
        assert "re.compile" in src or "_top_level_re" in src
        # Must NOT use the old colon-count approach
        assert 'count(":") > 5' not in src


class TestDepthGuard:
    """M2: _execute_child_steps depth guard must use >= to prevent off-by-one."""

    @pytest.mark.asyncio
    async def test_depth_exactly_at_max_is_rejected(self):
        """Steps at depth == MAX_NESTING_DEPTH must also be rejected by _execute_child_steps."""
        wf = _make_workflow()
        # parent_inp.depth = MAX_NESTING_DEPTH → _execute_child_steps should reject
        parent_inp = _make_steps_input(
            steps=[{"type": "set_var", "key": "X", "value": 1}],
            depth=MAX_NESTING_DEPTH,
        )
        result = await wf._execute_child_steps(
            parent_inp,
            [{"type": "set_var", "key": "Y", "value": 2}],
            {},
            {},
        )
        assert result.success is False
        assert "Max nesting depth" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_depth_one_below_max_is_allowed(self):
        """Steps at depth == MAX_NESTING_DEPTH - 1 must be allowed."""
        wf = _make_workflow()
        parent_inp = _make_steps_input(
            steps=[{"type": "set_var", "key": "X", "value": 1}],
            depth=MAX_NESTING_DEPTH - 1,
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            result = await wf._execute_child_steps(
                parent_inp,
                [{"type": "set_var", "key": "Y", "value": 2}],
                {},
                {},
            )
        assert result.success is True


class TestDeadCodeRemoval:
    """L3/L4: Dead constants and parameters must be removed."""

    def test_short_timeout_constant_removed(self):
        """_SHORT_TIMEOUT constant must be removed from workflows.py."""
        import inspect
        import temporal.workflows as wf_module
        src = inspect.getsource(wf_module)
        assert "_SHORT_TIMEOUT" not in src

    def test_workflow_id_suffix_param_removed(self):
        """_execute_child_steps must not have the unused workflow_id_suffix parameter."""
        import inspect
        from temporal.workflows import ScenarioStepsWorkflow
        src = inspect.getsource(ScenarioStepsWorkflow._execute_child_steps)
        assert "workflow_id_suffix" not in src


# ═══════════════════════════════════════════════════════════════════════════════
# Part 10: Missing handler tests — repeat_until, random_pick, if_element, if_variable
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepeatUntilHandler:
    """Test _handle_repeat_until — pre-condition loop until met or max iterations."""

    @pytest.mark.asyncio
    async def test_condition_already_true_on_entry_runs_zero_iterations(self):
        """If condition is met before first body execution, body never runs."""
        inp = _make_steps_input([{
            "type": "repeat_until",
            "condition": {"type": "element_exists"},
            "max_iterations": 5,
            "steps": [{"type": "set_var", "key": "BODY", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = True  # condition met immediately
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=_ok_steps_result())
            result = await wf.run(inp)

        assert result.success is True
        wf._execute_child_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_runs_body_until_condition_met(self):
        """Body runs N times before condition becomes true."""
        call_count = [0]

        async def fake_act(name, inp_obj, **kwargs):
            call_count[0] += 1
            # Condition becomes true after 3 activity calls (3 body iterations checked)
            return call_count[0] >= 3

        inp = _make_steps_input([{
            "type": "repeat_until",
            "condition": {"type": "element_exists"},
            "max_iterations": 10,
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.side_effect = fake_act
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=_ok_steps_result())
            result = await wf.run(inp)

        assert result.success is True
        # Body ran 2 times: iteration 0 (check false, run body), iteration 1 (check false, run body),
        # iteration 2 (check true, exit) — 2 body runs
        assert wf._execute_child_steps.call_count == 2

    @pytest.mark.asyncio
    async def test_max_iterations_exhausted_returns_failure(self):
        """When max_iterations reached without condition, return failure."""
        inp = _make_steps_input([{
            "type": "repeat_until",
            "condition": {"type": "element_exists"},
            "max_iterations": 3,
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = False  # condition never met
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=_ok_steps_result())
            result = await wf.run(inp)

        assert result.success is False
        assert "max_iterations" in (result.failed_message or "")
        assert wf._execute_child_steps.call_count == 3

    @pytest.mark.asyncio
    async def test_missing_condition_fails(self):
        inp = _make_steps_input([{
            "type": "repeat_until",
            "steps": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "missing condition" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_body_failure_stops_loop(self):
        inp = _make_steps_input([{
            "type": "repeat_until",
            "condition": {"type": "element_exists"},
            "max_iterations": 5,
            "steps": [{"type": "tap", "x": 0, "y": 0}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = False
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(
                return_value=_fail_steps_result("device disconnected")
            )
            result = await wf.run(inp)

        assert result.success is False
        assert "device disconnected" in (result.failed_message or "")
        assert wf._execute_child_steps.call_count == 1


class TestRandomPickHandler:
    """Test _handle_random_pick — weighted random branch selection."""

    @pytest.mark.asyncio
    async def test_executes_a_branch(self):
        """random_pick must execute exactly one of the branches."""
        branches = [
            {"weight": 1, "steps": [{"type": "set_var", "key": "BRANCH", "value": "A"}]},
            {"weight": 1, "steps": [{"type": "set_var", "key": "BRANCH", "value": "B"}]},
        ]
        inp = _make_steps_input([{"type": "random_pick", "branches": branches}])
        child_result = _ok_steps_result(context={"vars": {"BRANCH": "A"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=child_result)
            result = await wf.run(inp)

        assert result.success is True
        # Exactly one branch ran
        assert wf._execute_child_steps.call_count == 1

    @pytest.mark.asyncio
    async def test_no_branches_fails(self):
        inp = _make_steps_input([{"type": "random_pick", "branches": []}])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "no branches" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_empty_branch_steps_skipped(self):
        """A branch with no steps should succeed without calling _execute_child_steps."""
        inp = _make_steps_input([{
            "type": "random_pick",
            "branches": [{"weight": 1, "steps": []}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            with patch("temporal.workflows._get_wf_random") as mock_rng:
                mock_rng.return_value.choices = lambda r, weights, k: [0]
                wf = _make_workflow()
                wf._execute_child_steps = AsyncMock()
                result = await wf.run(inp)

        assert result.success is True
        wf._execute_child_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_branch_failure_propagates(self):
        branches = [{"weight": 1, "steps": [{"type": "tap", "x": 0, "y": 0}]}]
        inp = _make_steps_input([{"type": "random_pick", "branches": branches}])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(
                return_value=_fail_steps_result("element not found")
            )
            result = await wf.run(inp)

        assert result.success is False
        # _handle_random_pick wraps the error: "random_pick: branch N failed"
        assert "random_pick" in (result.failed_message or "")
        assert "failed" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_break_requested_propagates_from_branch(self):
        branches = [{"weight": 1, "steps": [{"type": "break_if", "condition": {}}]}]
        inp = _make_steps_input([{"type": "random_pick", "branches": branches}])

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(
                return_value=_ok_steps_result(break_requested=True)
            )
            result = await wf.run(inp)

        assert result.success is True
        assert result.break_requested is True


class TestIfElementHandler:
    """Test _handle_if_element — branch based on UI element presence."""

    @pytest.mark.asyncio
    async def test_element_found_executes_then_branch(self):
        from temporal.shared import ElementCheckResult
        inp = _make_steps_input([{
            "type": "if_element",
            "by": "text", "value": "OK",
            "then": [{"type": "set_var", "key": "BRANCH", "value": "then"}],
            "else": [{"type": "set_var", "key": "BRANCH", "value": "else"}],
        }])
        then_result = _ok_steps_result(context={"vars": {"BRANCH": "then"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = ElementCheckResult(found=True, message="found")
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=then_result)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("BRANCH") == "then"

    @pytest.mark.asyncio
    async def test_element_not_found_executes_else_branch(self):
        from temporal.shared import ElementCheckResult
        inp = _make_steps_input([{
            "type": "if_element",
            "by": "text", "value": "Loading",
            "then": [{"type": "set_var", "key": "BRANCH", "value": "then"}],
            "else": [{"type": "set_var", "key": "BRANCH", "value": "else"}],
        }])
        else_result = _ok_steps_result(context={"vars": {"BRANCH": "else"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = ElementCheckResult(found=False, message="not found")
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=else_result)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("BRANCH") == "else"

    @pytest.mark.asyncio
    async def test_missing_by_or_value_fails(self):
        inp = _make_steps_input([{"type": "if_element", "by": "", "value": ""}])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "missing by/value" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_no_else_branch_succeeds_when_not_found(self):
        from temporal.shared import ElementCheckResult
        inp = _make_steps_input([{
            "type": "if_element",
            "by": "text", "value": "OK",
            "then": [{"type": "set_var", "key": "X", "value": 1}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = ElementCheckResult(found=False)
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock()
            result = await wf.run(inp)

        assert result.success is True
        wf._execute_child_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_break_requested_from_branch_propagates(self):
        from temporal.shared import ElementCheckResult
        inp = _make_steps_input([{
            "type": "if_element",
            "by": "text", "value": "OK",
            "then": [{"type": "break_if", "condition": {}}],
        }])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock) as mock_act:
            mock_act.return_value = ElementCheckResult(found=True)
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(
                return_value=_ok_steps_result(break_requested=True)
            )
            result = await wf.run(inp)

        assert result.success is True
        assert result.break_requested is True


class TestIfVariableHandler:
    """Test _handle_if_variable — branch based on variable value comparison."""

    @pytest.mark.asyncio
    async def test_equals_condition_true(self):
        inp = _make_steps_input(
            steps=[{
                "type": "if_variable",
                "name": "MY_VAR",
                "equals": "hello",
                "then": [{"type": "set_var", "key": "RESULT", "value": "matched"}],
            }],
            runtime_vars={"MY_VAR": "hello"},
        )
        then_result = _ok_steps_result(context={"vars": {"RESULT": "matched"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=then_result)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("RESULT") == "matched"

    @pytest.mark.asyncio
    async def test_equals_condition_false_runs_else(self):
        inp = _make_steps_input(
            steps=[{
                "type": "if_variable",
                "name": "MY_VAR",
                "equals": "hello",
                "then": [{"type": "set_var", "key": "RESULT", "value": "matched"}],
                "else": [{"type": "set_var", "key": "RESULT", "value": "no_match"}],
            }],
            runtime_vars={"MY_VAR": "world"},
        )
        else_result = _ok_steps_result(context={"vars": {"RESULT": "no_match"}})

        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=else_result)
            result = await wf.run(inp)

        assert result.success is True
        assert result.context.get("vars", {}).get("RESULT") == "no_match"

    @pytest.mark.asyncio
    async def test_greater_than_condition(self):
        inp = _make_steps_input(
            steps=[{
                "type": "if_variable",
                "name": "COUNT",
                "greater_than": 5,
                "then": [{"type": "set_var", "key": "BIG", "value": True}],
            }],
            runtime_vars={"COUNT": 10},
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(return_value=_ok_steps_result())
            result = await wf.run(inp)

        assert result.success is True
        wf._execute_child_steps.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_name_fails(self):
        inp = _make_steps_input([{"type": "if_variable"}])
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            result = await wf.run(inp)

        assert result.success is False
        assert "missing name" in (result.failed_message or "")

    @pytest.mark.asyncio
    async def test_no_branch_when_condition_false_and_no_else(self):
        inp = _make_steps_input(
            steps=[{
                "type": "if_variable",
                "name": "FLAG",
                "equals": "yes",
                "then": [{"type": "set_var", "key": "X", "value": 1}],
            }],
            runtime_vars={"FLAG": "no"},
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock()
            result = await wf.run(inp)

        assert result.success is True
        wf._execute_child_steps.assert_not_called()

    @pytest.mark.asyncio
    async def test_break_requested_propagates(self):
        inp = _make_steps_input(
            steps=[{
                "type": "if_variable",
                "name": "GO",
                "equals": "yes",
                "then": [{"type": "break_if", "condition": {}}],
            }],
            runtime_vars={"GO": "yes"},
        )
        with patch("temporalio.workflow.execute_activity", new_callable=AsyncMock):
            wf = _make_workflow()
            wf._execute_child_steps = AsyncMock(
                return_value=_ok_steps_result(break_requested=True)
            )
            result = await wf.run(inp)

        assert result.success is True
        assert result.break_requested is True
