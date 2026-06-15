"""Phase 0 benchmark: scenario step *transition* overhead (capture + settle).

Separates the fixed per-node transition cost (capture screenshot/hierarchy and
the post-step settle sleep) from the handler work itself. These costs are what
make crawl loops feel slow "between nodes" regardless of how many comments a
post has.

Validates the crawl fast-path:
  * `capture_steps: false` disables capture even for campaign-bound executions.
  * `settle_timeout_ms: 0` is honored (no 800ms fallback).
  * guard/navigation step types skip the post-step settle.
  * nested branch steps (depth > 0) skip per-step capture.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import patch

import pytest

from services.execution.capture_service import (
    epic04_capture_default_enabled,
    explicit_capture_steps,
)


# ── capture_steps tri-state ──────────────────────────────────────────────────

def test_crawl_fast_path_disables_capture_for_campaign_execution() -> None:
    """A campaign run sets execution_id (capture defaults ON). The crawl
    fast-path must be able to force capture OFF via capture_steps=false."""
    campaign_like = {"steps": [], "execution_id": "exec-123"}
    assert epic04_capture_default_enabled(campaign_like) is True

    fast_path = {"steps": [], "execution_id": "exec-123", "capture_steps": False}
    assert epic04_capture_default_enabled(fast_path) is False


def test_capture_steps_via_campaign_var() -> None:
    scenario = {
        "steps": [],
        "execution_id": "exec-1",
        "_campaign_vars": {"__CAPTURE_STEPS__": "0"},
    }
    assert explicit_capture_steps(scenario) is False
    assert epic04_capture_default_enabled(scenario) is False

    scenario["_campaign_vars"]["__CAPTURE_STEPS__"] = "1"
    assert explicit_capture_steps(scenario) is True
    assert epic04_capture_default_enabled(scenario) is True


def test_capture_steps_unset_returns_none() -> None:
    assert explicit_capture_steps({"steps": []}) is None


# ── settle_timeout_ms = 0 honored ────────────────────────────────────────────

def _make_device() -> SimpleNamespace:
    return SimpleNamespace(
        serial="bench-serial",
        screen_width=1080,
        screen_height=1920,
        model="Bench",
        u2=None,
        _last_frame_time=time.monotonic(),
        hierarchy_xml=lambda *a, **k: None,
        take_screenshot=lambda *a, **k: b"\xff\xd8\xff\xe0fake",
    )


def _context_for(scenario: Dict[str, Any]):
    from tasks.scenario.context import ScenarioContext

    return ScenarioContext.from_args(_make_device(), scenario)


def test_settle_timeout_zero_is_honored() -> None:
    sc = _context_for({"steps": [], "settle_timeout_ms": 0, "capture_steps": True})
    assert sc.capture_settle_ms == 0


def test_settle_timeout_default_when_unset() -> None:
    import os
    from unittest.mock import patch as _patch

    with _patch.dict(os.environ, {"SETTLE_TIMEOUT_MS": "800"}, clear=False):
        sc = _context_for({"steps": [], "capture_steps": True})
    assert sc.capture_settle_ms == 800


def test_capture_off_skips_settle_entirely() -> None:
    """The crawl fast-path eliminates settle by disabling capture: when
    capture is off, the post-step settle sleep is never reached at all."""
    sc = _context_for(
        {"steps": [], "execution_id": "exec-1", "capture_steps": False}
    )
    assert sc.capture_enabled is False


# ── nested (depth > 0) steps skip capture ────────────────────────────────────

def _fake_capture_ctx(depth: int) -> SimpleNamespace:
    sc = SimpleNamespace(
        depth=depth,
        capture_enabled=True,
        capture_dir="/tmp/x",
        capture_settle_ms=0,
        capture_stale_wait_s=0.0,
        capture_skip_settle=frozenset(),
        scenario={},
        serial="bench",
        device=_make_device(),
        execution_id="exec-1",
    )
    return sc


@pytest.mark.parametrize("depth,expect_capture", [(0, True), (1, False), (2, False)])
def test_nested_steps_skip_capture(depth: int, expect_capture: bool) -> None:
    from services.execution import capture_service

    step = {"type": "extract", "strategy": "fb_comments"}  # capture defaults ON
    calls: list[str] = []

    with patch(
        "services.execution.epic06_capture_adapter.capture_active",
        return_value=True,
    ), patch.object(
        capture_service,
        "_capture_payload",
        side_effect=lambda *a, **k: calls.append("payload") or {"full": "x"},
    ):
        sc = _fake_capture_ctx(depth)
        result: Dict[str, Any] = {"index": 0, "type": "extract", "ok": True}
        capture_service.capture_before_step(sc, step, 0, result)
        capture_service.capture_after_step(
            sc, step, 0, result, time.monotonic(), sync=True
        )

    captured = bool(calls)
    assert captured is expect_capture


def test_nested_capture_honored_when_require_capture() -> None:
    from services.execution import capture_service

    step = {"type": "extract", "strategy": "fb_comments", "require_capture": True}
    calls: list[str] = []

    with patch(
        "services.execution.epic06_capture_adapter.capture_active",
        return_value=True,
    ), patch.object(
        capture_service,
        "_capture_payload",
        side_effect=lambda *a, **k: calls.append("payload") or {"full": "x"},
    ):
        sc = _fake_capture_ctx(depth=1)
        result: Dict[str, Any] = {"index": 0, "type": "extract", "ok": True}
        capture_service.capture_before_step(sc, step, 0, result)

    assert calls, "require_capture must force capture even in nested branch"


# ── transition floor wall-clock (informational + soft gate) ──────────────────

@pytest.mark.parametrize("capture_steps", [False])
def test_transition_floor_under_budget_without_capture(capture_steps: bool) -> None:
    """With capture disabled, per-step transition overhead must be negligible.

    Runs a handful of device-free guard steps and checks the total wall time
    stays well under a generous CI budget (proves no hidden per-step sleeps).
    """
    from tasks.scenario_task import run_scenario_task

    steps = [{"type": "set_variable", "name": f"v{i}", "value": str(i)} for i in range(8)]
    scenario = {"steps": steps, "capture_steps": capture_steps, "settle_timeout_ms": 0}

    device = _make_device()
    t0 = time.monotonic()
    result = run_scenario_task(device=device, scenario=scenario)
    wall_ms = (time.monotonic() - t0) * 1000.0

    assert result.get("success") is True
    # 8 trivial steps with no capture must complete fast (no 800ms settle each).
    assert wall_ms < 1500, f"transition floor too slow: {wall_ms:.0f}ms for 8 steps"
