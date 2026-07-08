from __future__ import annotations

from web.server import _RelayBootstrapGate


def test_relay_bootstrap_gate_dedupes_inflight_and_cooldown():
    now = 1000.0

    def clock() -> float:
        return now

    gate = _RelayBootstrapGate(cooldown_s=60.0, clock=clock)

    assert gate.acquire("dev-1") == (True, "queued")
    assert gate.acquire("dev-1") == (False, "in-flight")

    gate.release("dev-1")
    assert gate.acquire("dev-1") == (False, "cooldown")

    now = 1061.0
    assert gate.acquire("dev-1") == (True, "queued")


def test_relay_bootstrap_gate_skips_when_u2_ready():
    gate = _RelayBootstrapGate(cooldown_s=60.0, clock=lambda: 1000.0)

    assert gate.acquire("dev-1", has_runtime_u2=True) == (False, "u2-ready")
    assert gate.acquire("dev-1", caps={"has_u2": True}) == (False, "u2-ready")
