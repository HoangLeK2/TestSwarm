"""Bounded reason codes for metrics (avoid Prometheus label cardinality)."""
from __future__ import annotations


def reason_code(reason: str) -> str:
    r = (reason or "").strip().lower()
    if not r:
        return "unspecified"
    if "ttl" in r or "expired" in r:
        return "ttl_expired"
    if "rate limit" in r or "rate_limit" in r:
        return "rate_limit"
    if "usage limit" in r or "daily usage" in r:
        return "usage_limit"
    if "legacy" in r or "patch /status" in r:
        return "legacy"
    if "ban" in r:
        return "ban"
    if "retire" in r or "archiv" in r:
        return "retired"
    if "suspend" in r or "checkpoint" in r:
        return "suspended"
    if "manual" in r or "operator" in r:
        return "manual"
    return "other"
