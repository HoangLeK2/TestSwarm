"""Per-device override merge for campaign dispatch (DF-T-04-008)."""
from __future__ import annotations

import json
from typing import Any

from services.campaign.constants import MAX_PER_DEVICE_OVERRIDES_BYTES


class OverridePayloadTooLargeError(ValueError):
    code = "OVERRIDE_PAYLOAD_TOO_LARGE"


def estimate_json_bytes(payload: Any) -> int:
    return len(json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8"))


def validate_per_device_overrides_size(
    overrides: dict[str, Any] | None,
    *,
    max_bytes: int = MAX_PER_DEVICE_OVERRIDES_BYTES,
) -> None:
    if not overrides:
        return
    size = estimate_json_bytes(overrides)
    if size > max_bytes:
        raise OverridePayloadTooLargeError(
            f"per_device_overrides exceeds {max_bytes} bytes (got {size})"
        )


def validate_per_device_accounts_size(
    accounts: dict[str, Any] | None,
    *,
    max_bytes: int = MAX_PER_DEVICE_OVERRIDES_BYTES,
) -> None:
    """Same payload budget as per_device_overrides (DF-T-04-009)."""
    if not accounts:
        return
    size = estimate_json_bytes(accounts)
    if size > max_bytes:
        raise OverridePayloadTooLargeError(
            f"per_device_accounts exceeds {max_bytes} bytes (got {size})"
        )


def merge_effective_vars(
    *,
    campaign_vars: dict[str, Any] | None,
    per_device_overrides: dict[str, Any] | None,
    device_id: str,
) -> dict[str, Any]:
    """Merge campaign defaults with per-device overrides (device wins)."""
    base = dict(campaign_vars or {})
    overrides_map = per_device_overrides or {}
    device_overrides = overrides_map.get(device_id)
    if isinstance(device_overrides, dict):
        base.update(device_overrides)
    return base


def device_vars_for_resolver(
    *,
    campaign_vars: dict[str, Any] | None,
    per_device_overrides: dict[str, Any] | None,
    device_id: str,
) -> dict[str, Any]:
    """Return only the device-layer delta for EffectiveVariableResolver."""
    effective = merge_effective_vars(
        campaign_vars=campaign_vars,
        per_device_overrides=per_device_overrides,
        device_id=device_id,
    )
    campaign = dict(campaign_vars or {})
    return {k: v for k, v in effective.items() if campaign.get(k) != v}
