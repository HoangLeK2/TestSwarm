"""Resolve platform-aware scenario steps without implicit Facebook execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.social_ext import supports_step

if TYPE_CHECKING:
    from tasks.scenario.context import ScenarioContext

_AUTO_PLATFORM = "auto"
_CONTEXT_PLATFORM_KEYS = (
    "platform",
    "default_platform",
    "target_platform",
    "social_platform",
    "PLATFORM",
    "DEFAULT_PLATFORM",
    "TARGET_PLATFORM",
    "SOCIAL_PLATFORM",
)


@dataclass(frozen=True, slots=True)
class ResolvedStepPlatform:
    requested: str
    resolved: str
    reason_code: str
    source: str
    legacy_default_used: bool = False

    def event_fields(self) -> dict[str, Any]:
        return {
            "platform_requested": self.requested,
            "platform_resolved": self.resolved,
            "platform_resolution_reason": self.reason_code,
            "platform_source": self.source,
            "platform_legacy_default_used": self.legacy_default_used,
        }


def _clean_platform(value: Any) -> str:
    return str(value or "").strip().casefold()


def _first_context_platform(sc: "ScenarioContext") -> tuple[str, str] | None:
    for source, payload in (("scenario", sc.scenario), ("context", sc.ctx)):
        if not isinstance(payload, dict):
            continue
        for key in _CONTEXT_PLATFORM_KEYS:
            platform = _clean_platform(payload.get(key))
            if platform and platform != _AUTO_PLATFORM:
                return platform, f"{source}.{key}"
    vars_payload = sc.ctx.get("vars", {}) if isinstance(sc.ctx, dict) else {}
    if isinstance(vars_payload, dict):
        for key in _CONTEXT_PLATFORM_KEYS:
            platform = _clean_platform(vars_payload.get(key))
            if platform and platform != _AUTO_PLATFORM:
                return platform, f"context.vars.{key}"
    return None


def resolve_step_platform(
    sc: "ScenarioContext",
    step: dict[str, Any],
) -> ResolvedStepPlatform | None:
    requested = _clean_platform(step.get("platform"))
    if requested and requested != _AUTO_PLATFORM:
        return ResolvedStepPlatform(
            requested=requested,
            resolved=requested,
            reason_code="explicit_step_platform",
            source="step.platform",
        )

    context_platform = _first_context_platform(sc)
    if context_platform is not None:
        platform, source = context_platform
        return ResolvedStepPlatform(
            requested=requested or "missing",
            resolved=platform,
            reason_code="resolved_from_platform_context",
            source=source,
        )

    return None


def resolve_supported_step_platform(
    sc: "ScenarioContext",
    step: dict[str, Any],
    step_type: str,
    result: dict[str, Any],
) -> str | None:
    resolved = resolve_step_platform(sc, step)
    if resolved is None:
        requested = _clean_platform(step.get("platform")) or "missing"
        reason = (
            "auto_without_platform_context"
            if requested == _AUTO_PLATFORM
            else "missing_platform_context"
        )
        result.update(
            {
                "ok": False,
                "outcome": "platform_required",
                "reason_code": "PLATFORM_REQUIRED",
                "platform_requested": requested,
                "platform_resolution_reason": reason,
                "message": (
                    f"{step_type}: platform requires scenario, campaign, "
                    "context, variable platform, or explicit step.platform"
                ),
            }
        )
        return None

    result.update(resolved.event_fields())
    result["platform"] = resolved.resolved
    if supports_step(resolved.resolved, step_type):
        return resolved.resolved

    result.update(
        {
            "ok": False,
            "outcome": "unsupported_platform",
            "reason_code": "CAPABILITY_UNSUPPORTED",
            "message": (
                f"{step_type}: platform {resolved.resolved!r} does not "
                "implement this step"
            ),
        }
    )
    return None
