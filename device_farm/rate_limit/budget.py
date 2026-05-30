"""Parse rate-limit budget strings like ``30/min``."""
from __future__ import annotations

import re
from dataclasses import dataclass

_BUDGET_RE = re.compile(
    r"^\s*(?P<limit>\d+)\s*/\s*(?P<window>\d+)?\s*(?P<unit>sec|min|hour|day|s|m|h|d)?\s*$",
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    "sec": 1,
    "s": 1,
    "min": 60,
    "m": 60,
    "hour": 3600,
    "h": 3600,
    "day": 86400,
    "d": 86400,
}


@dataclass(frozen=True)
class RateBudget:
    limit: int
    window_seconds: int


def parse_budget(raw: str) -> RateBudget:
    match = _BUDGET_RE.match(raw or "")
    if not match:
        raise ValueError(f"invalid rate limit budget: {raw!r}")
    limit = int(match.group("limit"))
    unit = (match.group("unit") or "min").lower()
    window_raw = match.group("window")
    multiplier = int(window_raw) if window_raw else 1
    seconds = _UNIT_SECONDS.get(unit)
    if seconds is None:
        raise ValueError(f"unknown rate limit unit: {unit}")
    return RateBudget(limit=max(1, limit), window_seconds=max(1, multiplier * seconds))
