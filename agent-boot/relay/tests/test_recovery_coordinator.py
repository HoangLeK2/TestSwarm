from __future__ import annotations

import threading
import time
from concurrent.futures import wait

from relay.recovery_coordinator import RecoveryCoordinator


def test_recovery_coordinator_coalesces_duplicate_serial_kind() -> None:
    coordinator = RecoveryCoordinator(max_concurrency=2)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def operation() -> tuple[str, int]:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=1.0)
        return "ok", 0

    first = coordinator.submit("SERIAL1", "restart_u2", operation)
    assert started.wait(timeout=1.0)
    duplicates = [
        coordinator.submit("SERIAL1", "restart_u2", operation)
        for _ in range(5)
    ]
    release.set()

    assert first.result(timeout=1.0) == ("ok", 0)
    assert [future.result(timeout=1.0) for future in duplicates] == [("ok", 0)] * 5
    assert calls == 1
    stats = coordinator.stats_snapshot(reset=True)
    assert stats["started"] == 1
    assert stats["coalesced"] == 5
    assert stats["succeeded"] == 1
    coordinator.shutdown(wait=True)


def test_recovery_coordinator_bounds_running_concurrency() -> None:
    coordinator = RecoveryCoordinator(max_concurrency=3)
    running = 0
    max_running = 0
    lock = threading.Lock()

    def operation() -> tuple[str, int]:
        nonlocal running, max_running
        with lock:
            running += 1
            max_running = max(max_running, running)
        time.sleep(0.01)
        with lock:
            running -= 1
        return "ok", 0

    futures = [
        coordinator.submit(f"SERIAL{index}", "restart_u2", operation)
        for index in range(20)
    ]
    done, pending = wait(futures, timeout=2.0)

    assert len(done) == 20
    assert not pending
    assert max_running <= 3
    stats = coordinator.stats_snapshot(reset=True)
    assert stats["started"] == 20
    assert stats["succeeded"] == 20
    assert stats["max_active"] <= 3
    coordinator.shutdown(wait=True)


def test_recovery_coordinator_opens_breaker_after_failures() -> None:
    now = 100.0

    def clock() -> float:
        return now

    coordinator = RecoveryCoordinator(
        max_concurrency=1,
        breaker_failures=2,
        breaker_base_s=10.0,
        breaker_max_s=10.0,
        clock=clock,
    )

    assert coordinator.submit("SERIAL1", "restart_atx", lambda: ("bad", 1)).result(
        timeout=1.0
    ) == ("bad", 1)
    assert coordinator.submit("SERIAL1", "restart_atx", lambda: ("bad", 1)).result(
        timeout=1.0
    ) == ("bad", 1)

    skipped_output, skipped_rc = coordinator.submit(
        "SERIAL1",
        "restart_atx",
        lambda: ("should-not-run", 0),
    ).result(timeout=1.0)

    assert skipped_rc == -1
    assert "breaker open" in skipped_output
    stats = coordinator.stats_snapshot(reset=True)
    assert stats["failed"] == 2
    assert stats["breaker_opened"] == 1
    assert stats["skipped_breaker"] == 1
    assert stats["breaker_open"] == 1
    coordinator.shutdown(wait=True)


def test_recovery_coordinator_force_bypasses_breaker_and_success_resets() -> None:
    now = 100.0

    def clock() -> float:
        return now

    coordinator = RecoveryCoordinator(
        max_concurrency=1,
        breaker_failures=1,
        breaker_base_s=10.0,
        breaker_max_s=10.0,
        clock=clock,
    )

    assert coordinator.submit("SERIAL1", "restart_u2", lambda: ("bad", 1)).result(
        timeout=1.0
    ) == ("bad", 1)
    assert coordinator.submit(
        "SERIAL1",
        "restart_u2",
        lambda: ("ok", 0),
        force=True,
    ).result(timeout=1.0) == ("ok", 0)

    assert coordinator.submit("SERIAL1", "restart_u2", lambda: ("ok2", 0)).result(
        timeout=1.0
    ) == ("ok2", 0)
    stats = coordinator.stats_snapshot(reset=True)
    assert stats["breaker_open"] == 0
    assert stats["succeeded"] == 2
    coordinator.shutdown(wait=True)
