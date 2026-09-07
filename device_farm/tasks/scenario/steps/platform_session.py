"""Scenario step for account-scoped platform session establishment."""

from __future__ import annotations

import time
from typing import Any

from services.platform_readiness import (
    PlatformReadinessResult,
    PlatformReadinessStatus,
    resolve_platform_readiness,
)
from tasks.scenario.context import ScenarioContext
from tasks.scenario.steps import register_step
from tasks.scenario.steps.platform_resolution import resolve_supported_step_platform

_STEP_TYPE = "platform_session_gate"

_CONFIRM_TERMINAL_STATUSES = frozenset(
    {
        PlatformReadinessStatus.READY,
        PlatformReadinessStatus.CHECKPOINT,
        PlatformReadinessStatus.UNRESPONSIVE,
        PlatformReadinessStatus.UNSUPPORTED_BUILD,
    }
)


def _observe_readiness(
    sc: ScenarioContext,
    *,
    platform: str,
    phase: str,
    timeout: float,
    poll_interval: float,
) -> PlatformReadinessResult:
    deadline = time.monotonic() + timeout

    def observe() -> PlatformReadinessResult:
        return resolve_platform_readiness(
            sc.device.hierarchy_xml(force_refresh=True) or "",
            platform=platform,
        )

    last = observe()
    while phase == "confirm" and last.status not in _CONFIRM_TERMINAL_STATUSES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        delay = min(poll_interval, remaining)
        if sc.cancel_event is not None and sc.cancel_event.wait(delay):
            break
        if sc.cancel_event is None:
            time.sleep(delay)
        last = observe()
    return last


@register_step(_STEP_TYPE)
def handle_platform_session_gate(
    sc: ScenarioContext,
    step: dict[str, Any],
    idx: int,
    result: dict[str, Any],
) -> None:
    platform = resolve_supported_step_platform(sc, step, _STEP_TYPE, result)
    if platform is None:
        return
    try:
        phase = str(step.get("phase") or "preflight").strip().lower()
        if phase not in {"preflight", "confirm"}:
            raise ValueError("phase must be preflight or confirm")
        timeout = max(
            0.0, min(30.0, float(step.get("timeout", 15 if phase == "confirm" else 0)))
        )
        poll_interval = max(0.1, min(2.0, float(step.get("poll_interval", 0.5))))

        from services.account_actions import resolve_action_identity
        from services.platform_session_runtime import run_platform_session_gate

        variables = dict(sc.ctx.get("vars", {}))
        account_var = "__ACCOUNT_ID__"
        effective_account_id = sc.var_ctx.resolve(
            f"${{{account_var}}}",
            step_index=idx,
        )
        if effective_account_id != f"${{{account_var}}}":
            variables.setdefault(account_var, effective_account_id)
        identity = resolve_action_identity(
            step=step,
            scenario=sc.scenario,
            variables=variables,
            execution_id=sc.execution_id,
            device_serial=sc.serial,
        )
        readiness = _observe_readiness(
            sc,
            platform=platform,
            phase=phase,
            timeout=timeout,
            poll_interval=poll_interval,
        )
        provenance = sc.ctx.get("_platform_login_gate") if phase == "confirm" else None
        decision = run_platform_session_gate(
            identity=identity,
            device_serial=sc.serial,
            phase=phase,
            readiness=readiness,
            login_provenance=provenance if isinstance(provenance, dict) else None,
        )
        result.update(
            {
                "platform": platform,
                "phase": phase,
                "readiness_status": readiness.status.value,
                "readiness_reason": readiness.reason,
                "session_gate": decision,
            }
        )
        if not decision.get("allowed"):
            result["ok"] = False
            result["message"] = (
                f"{_STEP_TYPE} {phase} blocked: {decision.get('reason')}"
            )
            return

        ready = bool(decision.get("ready"))
        sc.var_ctx.set("PLATFORM_SESSION_READY", ready)
        sc.ctx.setdefault("vars", {})["PLATFORM_SESSION_READY"] = ready
        if phase == "preflight" and not ready:
            sc.ctx["_platform_login_gate"] = {
                "platform": platform,
                "org_id": decision.get("org_id"),
                "device_id": decision.get("device_id"),
                "account_id": decision.get("account_id"),
                "login_required": True,
            }
        elif phase == "confirm" and ready:
            sc.ctx.pop("_platform_login_gate", None)
        result["message"] = (
            f"{_STEP_TYPE} {phase}: "
            f"{'ready' if ready else 'login required'} ({decision.get('reason')})"
        )
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"{_STEP_TYPE} failed: {exc}"
