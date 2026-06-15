"""ScenarioContext — shared state for scenario execution."""
from __future__ import annotations

import os
import threading
from uuid import uuid4
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.core.device_client import DeviceClient
    from common.variable_resolver import VariableContext


@dataclass
class ScenarioContext:
    """All shared state needed by step handlers during scenario execution."""
    device: DeviceClient
    serial: str
    steps: list
    ctx: Dict[str, Any]
    var_ctx: VariableContext
    scenario: Dict[str, Any]
    w: int
    h: int
    cancel_event: Optional[threading.Event]
    # Capture config
    capture_dir: Optional[str]
    capture_enabled: bool
    capture_pre_step: bool
    capture_settle_ms: int
    capture_stale_wait_s: float
    capture_skip_settle: frozenset
    # Visual anchoring
    visual_anchor_enabled: bool
    va_ssim_threshold: float
    va_image_threshold: float
    va_screen_timeout: float
    va_screen_poll: float
    # Implicit wait
    scenario_iw_config: Dict[str, Any]
    # Recursion
    depth: int
    call_stack: frozenset
    # Callbacks
    on_step_done: Optional[Callable]
    # Trace metadata
    trace_id: str
    trace_source: str
    execution_id: Optional[str] = None
    start_step: int = 0  # executor skips steps < start_step on resume
    # Phase 2 — anti-detection step jitter (ms). 0 disables.
    jitter_min_ms: int = 0
    jitter_max_ms: int = 0
    # Accumulated state
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    last_popup_t: float = 0.0

    @classmethod
    def from_args(
        cls,
        device: DeviceClient,
        scenario: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        on_step_done: Optional[Callable] = None,
        _var_ctx: Optional[VariableContext] = None,
        _depth: int = 0,
        _call_stack: frozenset = frozenset(),
        cancel_event: Optional[threading.Event] = None,
    ) -> ScenarioContext:
        from common.variable_resolver import VariableContext as VC

        serial = device.serial
        steps = scenario.get("steps", []) or []
        ctx = context if context is not None else {}
        ctx.setdefault("posts", [])
        ctx.setdefault("vars", {})
        trace_id = str(
            scenario.get("_trace_id")
            or ctx.get("_trace_id")
            or f"scn-{uuid4().hex[:10]}"
        )
        trace_source = str(
            scenario.get("_trace_source")
            or ctx.get("_trace_source")
            or "scenario_task"
        )
        ctx["_trace_id"] = trace_id
        ctx["_trace_source"] = trace_source

        if _var_ctx is None:
            _var_ctx = VC(
                scenario_vars=scenario.get("variables", {}),
                campaign_vars=scenario.get("_campaign_vars", {}),
                device_serial=device.serial,
                device_model=getattr(device, "model", ""),
            )

        w = device.screen_width or 1080
        h = device.screen_height or 1920

        # Implicit wait config
        scenario_iw_config: Dict[str, Any] = {}
        raw_iw = scenario.get("implicit_wait")
        if raw_iw is not None:
            if isinstance(raw_iw, (int, float)):
                scenario_iw_config["implicit_wait"] = raw_iw
            elif isinstance(raw_iw, dict):
                scenario_iw_config["implicit_wait"] = raw_iw

        # Visual anchoring config
        va_raw = scenario.get("visual_anchor")
        va_ssim_threshold = 0.65
        va_image_threshold = 0.7
        va_screen_timeout = 3.0
        va_screen_poll = 0.5

        if isinstance(va_raw, bool):
            visual_anchor_enabled = va_raw
        elif isinstance(va_raw, dict):
            visual_anchor_enabled = bool(va_raw.get("enabled", True))
            va_ssim_threshold = max(0.0, min(1.0, float(va_raw.get("ssim_threshold", 0.75))))
            va_image_threshold = max(0.0, min(1.0, float(va_raw.get("image_threshold", 0.7))))
            va_screen_timeout = min(float(va_raw.get("screen_timeout", 8.0)), 30.0)
            va_screen_poll = max(0.1, float(va_raw.get("screen_poll", 0.5)))
        else:
            visual_anchor_enabled = any(
                (s.get("screen") or {}).get("screenshot") or (s.get("screen") or {}).get("element_image")
                for s in steps if isinstance(s, dict)
            )

        # Step capture config (DF-T-04-014: default ON for Epic 04 executions)
        from core.env import capture_pre_step_enabled
        from services.execution.capture_service import epic04_capture_default_enabled

        capture_enabled = epic04_capture_default_enabled(scenario)
        capture_dir: Optional[str] = None
        _exec_id = scenario.get("execution_id") or scenario.get("run_id")
        capture_pre = capture_enabled and (bool(_exec_id) or capture_pre_step_enabled())
        # Use `is not None` so an explicit settle_timeout_ms=0 (crawl fast-path)
        # is honored instead of falling back to the 800ms env default.
        _raw_settle = scenario.get("settle_timeout_ms")
        if _raw_settle is None:
            _raw_settle = os.environ.get("SETTLE_TIMEOUT_MS", "800")
        capture_settle_ms = int(_raw_settle)
        capture_stale_wait_s = float(os.environ.get("CAPTURE_STALE_WAIT_MS", "1000")) / 1000.0
        capture_skip_settle = frozenset({
            "wait", "wait_stable", "wait_screen_stable",
            "set_variable", "assert_variable",
            "run_scenario",
        })

        if capture_enabled:
            ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "captures")
            capture_dir = os.path.join(base, f"{serial}_{ts}")
            os.makedirs(capture_dir, exist_ok=True)

        _start_step = int(scenario.get("_checkpoint_step") or scenario.get("start_step") or 0)

        # Phase 2 — anti-detection jitter. Scenario-level overrides env.
        # jitter: {"min_ms": N, "max_ms": M} or "enabled": false to disable.
        _jmin = 0
        _jmax = 0
        _j = scenario.get("jitter")
        if isinstance(_j, dict) and _j.get("enabled", True):
            _jmin = int(_j.get("min_ms", 0))
            _jmax = int(_j.get("max_ms", 0))
        elif _j is None:
            # Env-level default; 0/0 = disabled.
            _jmin = int(os.environ.get("SCENARIO_JITTER_MIN_MS", "0"))
            _jmax = int(os.environ.get("SCENARIO_JITTER_MAX_MS", "0"))
        if _jmax < _jmin:
            _jmax = _jmin

        return cls(
            device=device,
            serial=serial,
            steps=steps,
            ctx=ctx,
            var_ctx=_var_ctx,
            scenario=scenario,
            w=w,
            h=h,
            cancel_event=cancel_event,
            capture_dir=capture_dir,
            capture_enabled=capture_enabled,
            capture_pre_step=capture_pre,
            capture_settle_ms=capture_settle_ms,
            capture_stale_wait_s=capture_stale_wait_s,
            capture_skip_settle=capture_skip_settle,
            visual_anchor_enabled=visual_anchor_enabled,
            va_ssim_threshold=va_ssim_threshold,
            va_image_threshold=va_image_threshold,
            va_screen_timeout=va_screen_timeout,
            va_screen_poll=va_screen_poll,
            scenario_iw_config=scenario_iw_config,
            depth=_depth,
            call_stack=_call_stack,
            on_step_done=on_step_done,
            trace_id=trace_id,
            trace_source=trace_source,
            execution_id=_exec_id,
            start_step=_start_step,
            jitter_min_ms=_jmin,
            jitter_max_ms=_jmax,
        )
