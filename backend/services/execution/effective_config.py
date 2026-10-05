"""Effective config snapshots for step audit (FR-04-09)."""
from __future__ import annotations

from typing import Any

from services.user_action_audit import sanitize_audit_value

_CREDENTIAL_KEYS = frozenset({
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "authorization",
    "__account_password__",
})


def build_effective_config_snapshot(
    step: dict[str, Any],
    *,
    step_index: int,
    provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Redacted resolved step config for audit storage."""
    snapshot: dict[str, Any] = {
        "step_index": step_index,
        "step_id": step.get("id") or step.get("_id"),
        "step_type": step.get("type"),
    }
    for key, value in step.items():
        if key.startswith("_"):
            continue
        if str(key).lower() in _CREDENTIAL_KEYS:
            snapshot[key] = "[REDACTED]"
            continue
        snapshot[key] = sanitize_audit_value(str(key), value)
    if provenance:
        snapshot["variable_provenance"] = dict(provenance)
    return snapshot
