"""Internal counters for rate-limit telemetry (no Prometheus export in Phase 3)."""
from __future__ import annotations

from threading import Lock

_lock = Lock()
_allowed = 0
_rejected = 0
_backend_down = 0
_bypassed = 0
_bypass_failed = 0


def inc_allowed() -> None:
    global _allowed
    with _lock:
        _allowed += 1


def inc_rejected() -> None:
    global _rejected
    with _lock:
        _rejected += 1


def inc_backend_down() -> None:
    global _backend_down
    with _lock:
        _backend_down += 1


def inc_bypassed() -> None:
    global _bypassed
    with _lock:
        _bypassed += 1


def inc_bypass_failed() -> None:
    global _bypass_failed
    with _lock:
        _bypass_failed += 1


def snapshot() -> dict[str, int]:
    with _lock:
        return {
            "rate_limit.allowed.count": _allowed,
            "rate_limit.rejected.count": _rejected,
            "rate_limit.backend_down": _backend_down,
            "rate_limit.bypassed.count": _bypassed,
            "rate_limit.bypass_failed.count": _bypass_failed,
        }


def reset() -> None:
    global _allowed, _rejected, _backend_down, _bypassed, _bypass_failed
    with _lock:
        _allowed = _rejected = _backend_down = _bypassed = _bypass_failed = 0
