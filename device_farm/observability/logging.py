"""Structured logging helpers — redaction only (no /metrics or OTel in Phase 3)."""
from __future__ import annotations

import re
from typing import Any

_REDACT_KEYS = {
    "password",
    "authorization",
    "x-device-key",
    "refresh_token",
    "secret",
    "token",
    "access_token",
    "api_key",
    "hashed_password",
}

_REDACT_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9\-._~+/]+=*)"),
    re.compile(r"(?i)(\"refresh_token\"\s*:\s*\")([^\"]+)(\")"),
)


def _should_redact_key(key: str) -> bool:
    lowered = (key or "").lower().replace("-", "_")
    return any(part in lowered for part in _REDACT_KEYS)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "<REDACTED>" if _should_redact_key(str(k)) else redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        redacted = value
        for pattern in _REDACT_PATTERNS:
            redacted = pattern.sub(r"\1<REDACTED>", redacted)
        return redacted
    return value


def redact_event(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key, value in list(event_dict.items()):
        if _should_redact_key(str(key)):
            event_dict[key] = "<REDACTED>"
        elif isinstance(value, (dict, list, str)):
            event_dict[key] = redact_value(value)
    return event_dict
