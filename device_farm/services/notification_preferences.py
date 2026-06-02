from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EffectivePreference:
    enabled: bool
    source: str
    reason: str


def resolve_effective_preference(
    *,
    event_type: str,
    channel: str,
    user_override: bool | None,
    admin_override: bool | None,
    default_enabled: bool,
    mandatory: bool = False,
) -> EffectivePreference:
    if mandatory:
        return EffectivePreference(
            enabled=True,
            source="mandatory",
            reason=f"{event_type} on {channel} cannot opt out",
        )
    if user_override is not None:
        return EffectivePreference(enabled=bool(user_override), source="user", reason="user override")
    if admin_override is not None:
        return EffectivePreference(enabled=bool(admin_override), source="admin", reason="admin override")
    return EffectivePreference(enabled=bool(default_enabled), source="default", reason="default preference")
