from __future__ import annotations

import asyncio

import pytest

from web.server import (
    _RelayBootstrapGate,
    _relay_discovery_bootstrap_decision,
    _run_relay_bootstrap_bounded,
)


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


def test_relay_discovery_never_bootstraps():
    assert _relay_discovery_bootstrap_decision() == (
        False,
        "discovery-gated",
    )


@pytest.mark.anyio
async def test_relay_bootstrap_is_bounded_and_skips_disconnected_jobs():
    class FakeRelay:
        def __init__(self) -> None:
            self.connected = {f"dev-{index}" for index in range(6)}
            self.active = 0
            self.max_active = 0
            self.calls: list[str] = []

        def relay_for_serial(self, serial: str):
            return object() if serial in self.connected else None

        async def bootstrap(self, serial: str) -> bool:
            self.calls.append(serial)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1
            return True

        def get_capabilities(self, _serial: str) -> dict:
            return {}

    relay = FakeRelay()
    slots = asyncio.Semaphore(2)
    bound: list[str] = []
    results = await asyncio.gather(
        *[
            _run_relay_bootstrap_bounded(
                relay,
                slots,
                f"dev-{index}",
                object(),
                lambda _device, serial, **_kwargs: bound.append(serial),
            )
            for index in range(6)
        ]
    )

    relay.connected.discard("dev-0")
    skipped = await _run_relay_bootstrap_bounded(
        relay,
        slots,
        "dev-0",
        object(),
        lambda *_args, **_kwargs: None,
    )

    assert results == [True] * 6
    assert relay.max_active == 2
    assert sorted(bound) == [f"dev-{index}" for index in range(6)]
    assert skipped is None
    assert relay.calls.count("dev-0") == 1
