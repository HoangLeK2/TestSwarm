"""Screenshot capture pipeline — pre/post step screenshots (DF-T-04-014)."""
from __future__ import annotations

import logging
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)


class StaleFrameError(RuntimeError):
    """Frame timestamp did not advance after settle-wait."""


def capture_pre_step(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    step_idx: int,
    step_result: Dict[str, Any],
    *,
    attempt_index: int = 1,
) -> None:
    from services.execution.capture_service import capture_before_step

    capture_before_step(sc, step, step_idx, step_result, attempt_index=attempt_index)


def capture_post_step(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    step_idx: int,
    step_result: Dict[str, Any],
    step_start_t: float,
    *,
    attempt_index: int = 1,
    sync: bool = False,
) -> None:
    from services.execution.capture_service import capture_after_step

    capture_after_step(
        sc,
        step,
        step_idx,
        step_result,
        step_start_t,
        attempt_index=attempt_index,
        sync=sync,
    )


def capture_fail_step(
    sc: "ScenarioContext",
    step: Dict[str, Any],
    step_idx: int,
    step_result: Dict[str, Any],
    *,
    attempt_index: int = 1,
) -> None:
    from services.execution.capture_service import capture_on_fail

    capture_on_fail(sc, step, step_idx, step_result, attempt_index=attempt_index)
