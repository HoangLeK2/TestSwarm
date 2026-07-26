from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
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


def test_bootstrap_cli_options_keep_their_bootstrap_before_relay_semantics(
    monkeypatch,
) -> None:
    assert _run_main(monkeypatch, "--serial", "phone-1") == [
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
            coordinator.submit("phone-1", operation).result(timeout=2)
        )

    try:
        owner = threading.Thread(target=invoke)
        follower = threading.Thread(target=invoke)
        owner.start()
        assert operation_started.wait(timeout=1)
        follower.start()
        release_operation.set()
        owner.join(timeout=2)
        follower.join(timeout=2)
    finally:
        release_operation.set()
        coordinator.shutdown(wait=True)

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

    def invoke(serial: str) -> None:
        coordinator.submit(serial, operation).result(timeout=2)

    workers = [
        threading.Thread(
            target=invoke,
            args=(f"phone-{index}",),
        )
        for index in range(8)
    ]
    try:
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
    finally:
        release.set()
        coordinator.shutdown(wait=True)

    assert peak_active == 2


def test_relay_retry_policy_is_fast_while_farm_is_starting() -> None:
    policy = RelayRetryPolicy()

    delays = [
        policy.delay(attempt=attempt, startup_elapsed=5, jitter_ratio=0)
        for attempt in range(1, 6)
    ]

    assert delays == [0.25, 0.5, 1.0, 2.0, 2.0]


def test_relay_retry_policy_caps_before_large_attempt_exponentiation() -> None:
    policy = RelayRetryPolicy()

    assert policy.delay(
        attempt=10_000,
        startup_elapsed=31,
        jitter_ratio=0,
    ) == 8.0


@pytest.mark.asyncio
async def test_auto_bootstrap_does_not_occupy_shared_adb_executor(
    monkeypatch,
) -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    monkeypatch.setattr(relay_agent_module, "_auto_bootstrap_enabled", lambda: True)
    monkeypatch.setattr(
        relay_agent_module,
        "adb_executor",
        lambda: (_ for _ in ()).throw(
            AssertionError("bootstrap must not use the shared ADB executor")
        ),
    )
    monkeypatch.setattr(
        relay_agent_module,
        "_bootstrap_device",
        lambda serial, timeout: (f"ready:{serial}", 0),
    )

    try:
        await agent._auto_bootstrap_online_device("phone-1")
    finally:
        agent._bootstrap_coordinator.shutdown(wait=True)


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_shared_bootstrap(
    monkeypatch,
) -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._bootstrap_coordinator.shutdown(wait=True)
    agent._bootstrap_coordinator = BootstrapCoordinator(max_concurrency=1)
    blocker_started = threading.Event()
    release_blocker = threading.Event()

    def bootstrap(serial: str, timeout: int) -> tuple[str, int]:
        if serial == "blocker":
            blocker_started.set()
            release_blocker.wait(timeout=2)
        return f"ready:{serial}", 0

    monkeypatch.setattr(relay_agent_module, "_bootstrap_device", bootstrap)
    blocker = agent._submit_bootstrap("blocker", 180)
    assert blocker_started.wait(timeout=1)

    cancelled_waiter = asyncio.create_task(
        agent._await_bootstrap("phone-1", 180)
    )
    surviving_waiter = asyncio.create_task(
        agent._await_bootstrap("phone-1", 180)
    )
    await asyncio.sleep(0)
    cancelled_waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_waiter

    try:
        release_blocker.set()
        assert await asyncio.wait_for(surviving_waiter, timeout=1.0) == (
            "ready:phone-1",
            0,
        )
    finally:
        release_blocker.set()
        agent._bootstrap_coordinator.shutdown(wait=True)


def test_relay_first_docker_entrypoint_does_not_wait_for_adb() -> None:
    entrypoint = Path(__file__).parents[2] / "docker" / "entrypoint.sh"
    env = os.environ.copy()
    env.update(
        {
            "ADB_SERVER_SOCKET": "tcp:unreachable.invalid:5037",
            "ADB_WAIT_SECONDS": "0",
            "AGENT_BOOT_STARTUP_MODE": "relay-first",
        }
    )

    completed = subprocess.run(
        ["bash", str(entrypoint), "bash", "-c", "printf command-ran"],
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.endswith("command-ran")


def test_docker_entrypoint_waits_for_adb_when_bootstrap_flags_are_explicit() -> None:
    entrypoint = Path(__file__).parents[2] / "docker" / "entrypoint.sh"
    env = os.environ.copy()
    env.update(
        {
            "ADB_SERVER_SOCKET": "tcp:unreachable.invalid:5037",
            "ADB_WAIT_SECONDS": "0",
            "AGENT_BOOT_STARTUP_MODE": "relay-first",
        }
    )

    completed = subprocess.run(
        [
            "bash",
            str(entrypoint),
            "bash",
            "-c",
            "printf command-ran",
            "--",
            "--serial",
            "phone-1",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )

    assert completed.returncode != 0
    assert "command-ran" not in completed.stdout
    assert "ADB not reachable" in completed.stderr


def test_docker_default_command_allows_startup_mode_to_take_effect() -> None:
    dockerfile = Path(__file__).parents[2] / "Dockerfile"
    source = dockerfile.read_text(encoding="utf-8")

    assert 'CMD ["/app/.venv/bin/python", "main.py"]' in source
    assert 'CMD ["/app/.venv/bin/python", "main.py", "--relay-only"]' not in source


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
