from __future__ import annotations

import asyncio
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main as agent_main
import pytest
import relay.agent as relay_agent_module
from relay.agent import RelayAgent
from relay.bootstrap_lifecycle import BootstrapCoordinator, RelayRetryPolicy


def _run_main(monkeypatch, *args: str) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["agent-boot", *args])
    monkeypatch.setattr(agent_main, "_load_dotenv", lambda: None)
    monkeypatch.setattr(agent_main, "_resolve_relay_id", lambda parsed: None)
    monkeypatch.setattr(
        agent_main,
        "_run_bootstrap",
        lambda parsed: calls.append("bootstrap") or True,
    )
    monkeypatch.setattr(
        agent_main,
        "_run_relay",
        lambda parsed: calls.append("relay"),
    )

    agent_main.main()
    return calls


def test_default_startup_connects_relay_without_blocking_on_bootstrap(monkeypatch) -> None:
    assert _run_main(monkeypatch) == ["relay"]


def test_legacy_startup_mode_keeps_bootstrap_first_rollback(monkeypatch) -> None:
    assert _run_main(monkeypatch, "--startup-mode", "legacy") == [
        "bootstrap",
        "relay",
    ]


def test_bootstrap_only_still_bootstraps_without_starting_relay(monkeypatch) -> None:
    with pytest.raises(SystemExit) as exited:
        _run_main(monkeypatch, "--bootstrap-only")

    assert exited.value.code == 0


@pytest.mark.asyncio
async def test_relay_attempts_first_connection_without_fixed_startup_sleep(
    monkeypatch,
) -> None:
    events: list[str] = []

    class _Background:
        def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(relay_agent_module, "start_mdns_discovery", lambda: None)
    monkeypatch.setattr(relay_agent_module, "init_executors", lambda: None)
    monkeypatch.setattr(relay_agent_module, "init_semaphores", lambda: None)
    monkeypatch.setattr(relay_agent_module, "shutdown_executors", lambda **_: None)
    monkeypatch.setattr(relay_agent_module, "register_stats_source", lambda *_: None)
    monkeypatch.setattr(relay_agent_module, "LoopWatchdog", _Background)
    monkeypatch.setattr(
        relay_agent_module,
        "RuntimeStats",
        lambda **_: _Background(),
    )

    async def _sleep(delay: float) -> None:
        events.append(f"sleep:{delay}")

    monkeypatch.setattr(relay_agent_module.asyncio, "sleep", _sleep)

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._u2_batch_enabled = False
    agent._scrcpy_mgr = SimpleNamespace(
        count=0,
        start=AsyncMock(),
        stop=AsyncMock(),
    )
    agent._supervisor = SimpleNamespace(
        start=AsyncMock(),
        stop=AsyncMock(),
    )
    agent._stream_tasks.cancel_all = AsyncMock()

    async def _connect() -> None:
        events.append("connect")
        raise asyncio.CancelledError

    agent._connect_and_stream = _connect

    with pytest.raises(asyncio.CancelledError):
        await agent.run()

    assert events[0] == "connect"


def test_concurrent_bootstrap_requests_for_one_phone_share_one_run() -> None:
    coordinator = BootstrapCoordinator(max_concurrency=4)
    operation_started = threading.Event()
    release_operation = threading.Event()
    calls: list[str] = []
    results: list[tuple[str, int]] = []

    def operation() -> tuple[str, int]:
        calls.append("run")
        operation_started.set()
        release_operation.wait(timeout=2)
        return "ready", 0

    def invoke() -> None:
        results.append(
            coordinator.run("phone-1", operation, wait_timeout=2)
        )

    owner = threading.Thread(target=invoke)
    follower = threading.Thread(target=invoke)
    owner.start()
    assert operation_started.wait(timeout=1)
    follower.start()
    release_operation.set()
    owner.join(timeout=2)
    follower.join(timeout=2)

    assert calls == ["run"]
    assert results == [("ready", 0), ("ready", 0)]


def test_bootstrap_repairs_are_bounded_across_many_phones() -> None:
    coordinator = BootstrapCoordinator(max_concurrency=2)
    active = 0
    peak_active = 0
    counter_lock = threading.Lock()
    release = threading.Event()

    def operation() -> tuple[str, int]:
        nonlocal active, peak_active
        with counter_lock:
            active += 1
            peak_active = max(peak_active, active)
        release.wait(timeout=2)
        with counter_lock:
            active -= 1
        return "ready", 0

    workers = [
        threading.Thread(
            target=coordinator.run,
            args=(f"phone-{index}", operation),
            kwargs={"wait_timeout": 2},
        )
        for index in range(8)
    ]
    for worker in workers:
        worker.start()

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with counter_lock:
            if peak_active == 2:
                break
        time.sleep(0.01)
    release.set()
    for worker in workers:
        worker.join(timeout=2)

    assert peak_active == 2


def test_relay_retry_policy_is_fast_while_farm_is_starting() -> None:
    policy = RelayRetryPolicy()

    delays = [
        policy.delay(attempt=attempt, startup_elapsed=5, jitter_ratio=0)
        for attempt in range(1, 6)
    ]

    assert delays == [0.25, 0.5, 1.0, 2.0, 2.0]


@pytest.mark.asyncio
async def test_empty_heartbeat_never_waits_for_a_slow_adb_snapshot(
    monkeypatch,
) -> None:
    release_adb = threading.Event()

    def slow_list_serials() -> list[str]:
        release_adb.wait(timeout=2)
        return ["late-phone"]

    monkeypatch.setattr(relay_agent_module, "_list_serials", slow_list_serials)
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    send_q: asyncio.Queue = asyncio.Queue()

    try:
        await asyncio.wait_for(agent._send_heartbeat(send_q), timeout=0.1)
    finally:
        release_adb.set()

    heartbeat = await asyncio.wait_for(send_q.get(), timeout=0.1)
    assert '"serials":[]' in heartbeat
