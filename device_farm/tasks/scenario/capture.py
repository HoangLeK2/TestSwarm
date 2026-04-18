"""Screenshot capture pipeline — pre/post step screenshots."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)


class StaleFrameError(RuntimeError):
    """Frame timestamp did not advance after settle-wait.

    Raised from ``capture_post_step`` when the captured frame is older than
    the step start AND the caller requested strict freshness. Scenario engine
    handles this as retryable (F1.5) when the step is an extraction.
    """


def capture_pre_step(sc: "ScenarioContext", step: Dict[str, Any], step_idx: int, step_result: Dict[str, Any]) -> None:
    """Capture screenshot BEFORE step execution (debug mode)."""
    if not sc.capture_dir or not sc.capture_pre_step:
        return
    try:
        from tasks.scenario.utils import _capture_step_screenshot
        t = step.get("type", "unknown")
        pre_cap = _capture_step_screenshot(
            sc.device, sc.capture_dir, step_idx,
            f"{t}_pre", None, sc.w, sc.h, selector=None,
        )
        if pre_cap:
            step_result["screenshot_pre"] = pre_cap
        last_frame_t = float(getattr(sc.device, "_last_frame_time", 0.0) or 0.0)
        if last_frame_t > 0:
            age_ms = int((time.monotonic() - last_frame_t) * 1000)
            log.info(f"[{sc.serial}] capture PRE step#{step_idx + 1} ({t}) frame_age={age_ms}ms")
        else:
            log.info(f"[{sc.serial}] capture PRE step#{step_idx + 1} ({t}) frame_age=unknown")
    except Exception as exc:
        log.debug(f"[{sc.serial}] pre-step capture failed: {exc}")


def capture_post_step(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    step_idx: int,
    step_result: Dict[str, Any],
    step_start_t: float,
) -> None:
    """Capture screenshot AFTER step execution (debug mode)."""
    if not sc.capture_dir:
        return
    try:
        from tasks.scenario.utils import _capture_step_screenshot
        t = step.get("type", "unknown")

        need_settle = t not in sc.capture_skip_settle and sc.capture_settle_ms > 0
        if need_settle:
            time.sleep(sc.capture_settle_ms / 1000.0)

        # Poll for fresh frame
        stale_after_wait = False
        if need_settle and sc.capture_stale_wait_s > 0:
            poll_deadline = time.monotonic() + sc.capture_stale_wait_s
            while time.monotonic() < poll_deadline:
                ft = float(getattr(sc.device, "_last_frame_time", 0.0) or 0.0)
                if ft > step_start_t:
                    break
                time.sleep(0.05)
            else:
                ft = float(getattr(sc.device, "_last_frame_time", 0.0) or 0.0)
                if ft <= step_start_t:
                    stale_after_wait = True
                    log.warning(
                        f"[{sc.serial}] POST step#{step_idx + 1} ({t}): "
                        f"frame stale after {int(sc.capture_stale_wait_s * 1000)}ms wait"
                    )

        # F1.3 — strict-freshness raise for extraction / assert-stable steps.
        # Env opt-in so legacy flows keep log-and-continue behavior; extraction
        # step opts in via ``step["require_fresh_frame"]=True`` which is promoted
        # to ``_require_fresh_frame`` on the capture call below.
        if stale_after_wait and (
            os.environ.get("FB_STRICT_FRESH_FRAME", "0") == "1"
            or step.get("require_fresh_frame") is True
        ):
            raise StaleFrameError(
                f"frame stale after {int(sc.capture_stale_wait_s * 1000)}ms "
                f"on step#{step_idx + 1} ({t})"
            )

        # Build selector dict
        step_selector: Optional[Dict[str, str]] = None
        if t in ("tap", "tap_selector", "wait_element", "assert_element",
                 "input_selector", "long_tap_selector", "scroll_to"):
            sel = step.get("selector") or {}
            s_by = str(sel.get("by") or step.get("by") or "").strip()
            s_val = str(sel.get("value") or step.get("value") or "").strip()
            if s_by and s_val:
                step_selector = {"by": s_by, "value": s_val}

        cap = _capture_step_screenshot(
            sc.device, sc.capture_dir, step_idx, t,
            step_result.pop("_bounds", None), sc.w, sc.h,
            selector=step_selector,
        )
        if cap:
            step_result["screenshot"] = cap

        last_frame_t = float(getattr(sc.device, "_last_frame_time", 0.0) or 0.0)
        if last_frame_t > 0:
            age_ms = int((time.monotonic() - last_frame_t) * 1000)
            fresh = last_frame_t > step_start_t
            log.info(
                f"[{sc.serial}] capture POST step#{step_idx + 1} ({t}) "
                f"frame_age={age_ms}ms fresh={fresh}"
            )
        else:
            log.info(f"[{sc.serial}] capture POST step#{step_idx + 1} ({t}) frame_age=unknown")
    except Exception as exc:
        log.debug(f"[{sc.serial}] step capture failed: {exc}")
