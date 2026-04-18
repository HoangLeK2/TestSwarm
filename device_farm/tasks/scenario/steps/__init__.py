"""Step handler registry and dispatch."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

log = logging.getLogger(__name__)

# Step type → handler function
_STEP_HANDLERS: Dict[str, Callable[["ScenarioContext", Dict[str, Any], int], Dict[str, Any]]] = {}


def register_step(*step_types: str):
    """Decorator: register a handler for one or more step types."""
    def decorator(fn):
        for t in step_types:
            _STEP_HANDLERS[t] = fn
        return fn
    return decorator


def dispatch_step(sc: "ScenarioContext", step: Dict[str, Any], step_idx: int) -> Dict[str, Any]:
    """Dispatch a step to its registered handler."""
    t = step.get("type", "")
    handler = _STEP_HANDLERS.get(t)
    if handler is None:
        msg = f"unknown step type: {t!r}"
        log.warning(f"[{sc.serial}] {msg}")
        return {"index": step_idx, "type": t, "ok": False, "message": msg}
    result = {"index": step_idx, "type": t, "ok": True}
    handler(sc, step, step_idx, result)
    return result


# Import all step handler modules to trigger registration
from tasks.scenario.steps import (  # noqa: E402, F401
    navigation,
    interaction,
    input,
    wait,
    extraction,
    persistence,
    control_flow,
    composition,
)
