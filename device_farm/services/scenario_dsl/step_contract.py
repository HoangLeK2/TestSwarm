"""Step normalization and effective policy helpers (DF-T-04-002)."""

from __future__ import annotations

from typing import Any

from services.execution.capture_policy import default_capture_enabled_for_step

_VALID_ERROR_POLICIES = frozenset({"stop", "ignore", "continue", "on_error"})

# FR-04-20: normalization must never inject implicit recovery/retry.
IMPLICIT_RECOVERY_FORBIDDEN = True


def effective_error_policy(step: dict[str, Any]) -> str:
    """Return explicit error policy; run_scenario defaults to continue."""
    raw = step.get("error_policy")
    if raw is None or raw == "":
        step_type = str(step.get("type") or "")
        if step_type in {"run_scenario", "composition.run_scenario"}:
            return "ignore"
        return "stop"
    policy = str(raw)
    if policy == "continue":
        return "ignore"
    if policy not in _VALID_ERROR_POLICIES:
        return "ignore"
    return policy


def normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    """Apply contract defaults without inventing recovery branches."""
    out = dict(step)
    if "id" not in out or not str(out.get("id") or "").strip():
        raise ValueError("step id is required")
    if "type" not in out or not str(out.get("type") or "").strip():
        raise ValueError("step type is required")
    config = out.get("config")
    out["config"] = dict(config) if isinstance(config, dict) else {}
    out["error_policy"] = effective_error_policy(out)
    default_capture = default_capture_enabled_for_step(out)
    if "pre_capture" not in out:
        out["pre_capture"] = default_capture
    if "post_capture" not in out:
        out["post_capture"] = default_capture
    if "retry" not in out:
        out["retry"] = None
    return out


def normalize_body_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_step(s) for s in steps if isinstance(s, dict)]


def assert_no_implicit_recovery(steps: list[dict[str, Any]]) -> None:
    """Guard FR-04-20: normalization must not invent recovery branches/retries."""
    for step in steps:
        if not isinstance(step, dict):
            continue
        declared = step.get("error_policy")
        effective = effective_error_policy(step)
        if declared is None and effective == "on_error":
            raise AssertionError("implicit error_policy injected")
        if declared is None and step.get("retry") not in (None, {}):
            raise AssertionError("implicit retry on step without explicit retry block")
