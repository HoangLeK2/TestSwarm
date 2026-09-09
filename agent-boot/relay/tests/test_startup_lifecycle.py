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


@pytest.mark.parametrize(
    "args",
    [
        ("--ws-url", "ws://farm.example/ws"),
        ("--tcpip-port", "5555"),
    ],
)
def test_explicit_value_flags_keep_bootstrap_semantics(
    monkeypatch,
    args: tuple[str, str],
) -> None:
    assert _run_main(monkeypatch, *args) == ["bootstrap", "relay"]


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


@pytest.mark.asyncio
async def test_adb_connect_backoff_suppresses_retry_until_deadline(monkeypatch) -> None:
    monkeypatch.setattr(relay_agent_module.random, "random", lambda: 0.0)
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._adb_connect_retry_base_s = 2.0
    agent._adb_connect_retry_max_s = 10.0

    agent._record_adb_connect_failed("10.0.0.2:5555", "failed")

    assert agent._adb_connect_backoff_active("10.0.0.2:5555") is True
    agent._adb_connect_retry_after["10.0.0.2:5555"] = (
        asyncio.get_running_loop().time() - 0.01
    )
    assert agent._adb_connect_backoff_active("10.0.0.2:5555") is False


@pytest.mark.asyncio
async def test_grpc_relay_failure_reconnects_without_stopping_control_plane(
    monkeypatch,
) -> None:
    """A transient relay-stream failure must not take campaign control offline."""

    class _ChannelContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    relay_attempts = 0
    second_relay_attempt = asyncio.Event()
    control_started = asyncio.Event()
    control_stopped = 0

    class _GrpcClient:
        def __init__(self, *args, **kwargs) -> None:
            self.ctrl_q: asyncio.Queue = asyncio.Queue()

        async def _stream_once(self, channel, *, initial_meta=None) -> None:
            nonlocal relay_attempts
            relay_attempts += 1
            if relay_attempts == 1:
                await asyncio.sleep(0)
                raise RuntimeError("simulated execute_batch relay failure")
            second_relay_attempt.set()
            await asyncio.Event().wait()

        def stop(self) -> None:
            return None

    class _ControlClient:
        def __init__(self, grpc_channel, api_key, relay_agent) -> None:
            self._agent = relay_agent

        async def run(self) -> None:
            control_started.set()
            # The real client sets this when the server acks the control
            # channel (control_client.py). The relay stream gates registration
            # on it, so a fake that never sets it stalls for the full 30s.
            self._agent._identity_ready.set()
            await asyncio.Event().wait()

        def stop(self) -> None:
            nonlocal control_stopped
            control_stopped += 1

    class _Watcher:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def run(self) -> None:
            await asyncio.Event().wait()

    import relay.control_client as control_client_module
    import relay.grpc_client as grpc_client_module

    monkeypatch.setattr(grpc_client_module, "create_grpc_channel", lambda *args, **kwargs: _ChannelContext())
    monkeypatch.setattr(grpc_client_module, "GrpcRelayClient", _GrpcClient)
    monkeypatch.setattr(control_client_module, "AgentControlClient", _ControlClient)
    monkeypatch.setattr(relay_agent_module, "AdbDeviceWatcher", _Watcher)

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="grpc",
    )
    agent._registry = SimpleNamespace(online_serials=["phone-1"])
    agent._scrcpy_auto_resume_enabled = False
    agent._send_heartbeat = AsyncMock()

    async def _wait_forever(*_args) -> None:
        await asyncio.Event().wait()

    agent._periodic_heartbeat = _wait_forever
    agent._shutdown_stream_helpers = AsyncMock()

    stream_task = asyncio.create_task(agent._connect_and_stream_grpc())
    try:
        await asyncio.wait_for(control_started.wait(), timeout=0.5)
        await asyncio.wait_for(second_relay_attempt.wait(), timeout=1.0)
        assert control_stopped == 0
    finally:
        stream_task.cancel()
        await asyncio.gather(stream_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_grpc_relay_retry_does_not_replay_stale_registration(
    monkeypatch,
) -> None:
    """A failed RPC attempt must not leave registration in the shared queue."""

    class _ChannelContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    relay_attempts = 0
    second_relay_attempt = asyncio.Event()
    received_message_types: list[str] = []

    class _GrpcClient:
        def __init__(self, *args, **kwargs) -> None:
            self.ctrl_q: asyncio.Queue = asyncio.Queue()
            self._send_queue = kwargs["send_queue"]

        async def _stream_once(self, channel, *, initial_meta=None) -> None:
            nonlocal relay_attempts
            relay_attempts += 1
            if relay_attempts == 1:
                raise RuntimeError("failed before request generator consumption")

            if initial_meta is not None:
                received_message_types.append(
                    relay_agent_module.json.loads(initial_meta)["type"]
                )
            while self._send_queue.qsize():
                item = await self._send_queue.get()
                if isinstance(item, str):
                    received_message_types.append(
                        relay_agent_module.json.loads(item)["type"]
                    )
            second_relay_attempt.set()
            await asyncio.Event().wait()

        def stop(self) -> None:
            return None

    class _ControlClient:
        def __init__(self, grpc_channel, api_key, relay_agent) -> None:
            self._agent = relay_agent

        async def run(self) -> None:
            # See the sibling test: registration is gated on this.
            self._agent._identity_ready.set()
            await asyncio.Event().wait()

        def stop(self) -> None:
            return None

    class _Watcher:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def run(self) -> None:
            await asyncio.Event().wait()

    import relay.control_client as control_client_module
    import relay.grpc_client as grpc_client_module

    monkeypatch.setattr(
        grpc_client_module,
        "create_grpc_channel",
        lambda *args, **kwargs: _ChannelContext(),
    )
    monkeypatch.setattr(grpc_client_module, "GrpcRelayClient", _GrpcClient)
    monkeypatch.setattr(control_client_module, "AgentControlClient", _ControlClient)
    monkeypatch.setattr(relay_agent_module, "AdbDeviceWatcher", _Watcher)
    monkeypatch.setattr(relay_agent_module.random, "random", lambda: 0.0)

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="grpc",
    )
    agent._registry = SimpleNamespace(online_serials=["phone-1"])
    agent._scrcpy_auto_resume_enabled = False

    async def _send_heartbeat(queue) -> None:
        await queue.put(relay_agent_module.dumps({"type": "heartbeat"}))

    agent._send_heartbeat = _send_heartbeat

    async def _wait_forever(*_args) -> None:
        await asyncio.Event().wait()

    agent._periodic_heartbeat = _wait_forever
    agent._shutdown_stream_helpers = AsyncMock()

    stream_task = asyncio.create_task(agent._connect_and_stream_grpc())
    try:
        await asyncio.wait_for(second_relay_attempt.wait(), timeout=1.0)
        assert received_message_types.count("register") == 1
    finally:
        stream_task.cancel()
        await asyncio.gather(stream_task, return_exceptions=True)


def test_concurrent_bootstrap_requests_for_one_phone_share_one_run() -> None:
    coordinator = BootstrapCoordinator(max_concurrency=4)
    operation_started = threading.Event()
    release_operation = threading.Event()
    calls: list[str] = []
    results: list[tuple[str, int]] = []
    follower_submitted = threading.Event()

    def operation() -> tuple[str, int]:
        calls.append("run")
        operation_started.set()
        release_operation.wait(timeout=2)
        return "ready", 0

    def invoke(*, follower: bool = False) -> None:
        future = coordinator.submit("phone-1", operation)
        if follower:
            follower_submitted.set()
        results.append(future.result(timeout=2))

    try:
        owner = threading.Thread(target=invoke)
        follower = threading.Thread(
            target=invoke,
            kwargs={"follower": True},
        )
        owner.start()
        assert operation_started.wait(timeout=1)
        follower.start()
        assert follower_submitted.wait(timeout=1)
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
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DELAY_SECONDS", "0")
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DEFER_WHILE_SCRCPY", "0")
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
async def test_auto_bootstrap_waits_until_viewer_scrcpy_stops(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DELAY_SECONDS", "0")
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DEFER_WHILE_SCRCPY", "1")
    monkeypatch.setattr(
        relay_agent_module,
        "_AUTO_BOOTSTRAP_VIEWER_POLL_SECONDS",
        0.01,
        raising=False,
    )
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._scrcpy_desired["phone-1"] = {
        "desired": True,
        "manual_stop": False,
    }
    bootstrap_started = threading.Event()

    def bootstrap(serial: str, timeout: int) -> tuple[str, int]:
        assert serial == "phone-1"
        bootstrap_started.set()
        return "ready", 0

    monkeypatch.setattr(relay_agent_module, "_auto_bootstrap_enabled", lambda: True)
    monkeypatch.setattr(relay_agent_module, "_bootstrap_device", bootstrap)

    task = asyncio.create_task(
        agent._auto_bootstrap_online_device("phone-1"),
    )
    try:
        await asyncio.sleep(0.03)
        assert not bootstrap_started.is_set()
        agent._scrcpy_desired["phone-1"]["desired"] = False
        await asyncio.wait_for(task, timeout=0.5)
        assert bootstrap_started.is_set()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        agent._bootstrap_coordinator.shutdown(wait=True)


@pytest.mark.asyncio
async def test_explicit_bootstrap_bypasses_active_viewer_deferral(
    monkeypatch,
) -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._scrcpy_desired["phone-1"] = {
        "desired": True,
        "manual_stop": False,
    }
    monkeypatch.setattr(
        relay_agent_module,
        "_bootstrap_device",
        lambda serial, timeout: (f"ready:{serial}", 0),
    )

    try:
        assert await asyncio.wait_for(
            agent._await_bootstrap("phone-1", 180),
            timeout=0.5,
        ) == ("ready:phone-1", 0)
    finally:
        agent._bootstrap_coordinator.shutdown(wait=True)


@pytest.mark.asyncio
async def test_device_online_does_not_schedule_auto_bootstrap_before_registration(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DELAY_SECONDS", "60")
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DEFER_WHILE_SCRCPY", "1")
    monkeypatch.setattr(relay_agent_module, "_auto_bootstrap_enabled", lambda: True)
    bootstrap_calls: list[str] = []
    monkeypatch.setattr(
        relay_agent_module,
        "_bootstrap_device",
        lambda serial, timeout: bootstrap_calls.append(serial) or ("ready", 0),
    )

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._send_heartbeat = AsyncMock()
    agent._schedule_capability_probe = lambda *_args: None
    u2_warm_calls: list[tuple[str, str]] = []
    agent._schedule_u2_warm = lambda serial, *, reason: u2_warm_calls.append(
        (serial, reason)
    )
    send_queue: asyncio.Queue = asyncio.Queue()

    try:
        await agent._on_device_event("phone-1", "device", send_queue)
        await asyncio.sleep(0)

        assert "phone-1" not in agent._auto_bootstrap_tasks
        assert bootstrap_calls == []
        assert u2_warm_calls == []

        result = await agent._execute_bootstrap_command("cmd-1", "phone-1", 180)
        await asyncio.sleep(0)

        assert '"ok":true' in result
        assert bootstrap_calls == ["phone-1"]
        assert u2_warm_calls == [("phone-1", "explicit-bootstrap")]
        assert "phone-1" not in agent._auto_bootstrap_tasks
    finally:
        pending = list(getattr(agent, "_auto_bootstrap_tasks", {}).values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        agent._bootstrap_coordinator.shutdown(wait=True)


@pytest.mark.asyncio
async def test_offline_device_cancels_deferred_auto_bootstrap(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DELAY_SECONDS", "60")
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DEFER_WHILE_SCRCPY", "1")
    monkeypatch.setattr(relay_agent_module, "_auto_bootstrap_enabled", lambda: True)
    bootstrap_started = threading.Event()
    monkeypatch.setattr(
        relay_agent_module,
        "_bootstrap_device",
        lambda _serial, _timeout: bootstrap_started.set() or ("ready", 0),
    )

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._send_heartbeat = AsyncMock()
    agent._schedule_capability_probe = lambda *_args: None
    agent._scrcpy_mgr.stop_all_for_serial = AsyncMock()
    send_queue: asyncio.Queue = asyncio.Queue()

    try:
        agent._schedule_auto_bootstrap("phone-1")
        await asyncio.sleep(0)
        task = agent._auto_bootstrap_tasks["phone-1"]
        assert not task.done()

        await agent._on_device_event("phone-1", "offline", send_queue)
        await asyncio.sleep(0)

        assert task.cancelled()
        assert "phone-1" not in agent._auto_bootstrap_tasks
        assert not bootstrap_started.is_set()
    finally:
        pending = list(getattr(agent, "_auto_bootstrap_tasks", {}).values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        agent._bootstrap_coordinator.shutdown(wait=True)


@pytest.mark.asyncio
async def test_cancelled_auto_bootstrap_can_be_rescheduled_immediately(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DELAY_SECONDS", "0")
    monkeypatch.setenv("RELAY_AUTO_BOOTSTRAP_DEFER_WHILE_SCRCPY", "1")
    monkeypatch.setattr(relay_agent_module, "_auto_bootstrap_enabled", lambda: True)
    monkeypatch.setattr(
        relay_agent_module,
        "_AUTO_BOOTSTRAP_VIEWER_POLL_SECONDS",
        0.01,
        raising=False,
    )
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        relay_mode="ws",
    )
    agent._scrcpy_desired["phone-1"] = {
        "desired": True,
        "manual_stop": False,
    }

    try:
        agent._schedule_auto_bootstrap("phone-1")
        await asyncio.sleep(0)
        previous = agent._auto_bootstrap_tasks["phone-1"]
        assert not previous.done()

        agent._cancel_auto_bootstrap("phone-1")
        agent._schedule_auto_bootstrap("phone-1")
        replacement = agent._auto_bootstrap_tasks["phone-1"]
        await asyncio.sleep(0)

        assert replacement is not previous
        assert not replacement.done()
    finally:
        pending = list(getattr(agent, "_auto_bootstrap_tasks", {}).values())
        for task in pending:
            task.cancel()
        await asyncio.gather(previous, *pending, return_exceptions=True)
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
