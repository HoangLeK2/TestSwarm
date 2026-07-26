from __future__ import annotations

import asyncio
import json

import pytest

from relay.control_client import AgentControlClient
from relay.grpc_gen import relay_pb2


class _Registry:
    online_serials = ["dev-001"]


class _Agent:
    _enrollment_token = ""
    _relay_id = "relay-1"
    _registry = _Registry()


@pytest.mark.asyncio
async def test_grpc_bootstrap_uses_async_bootstrap_admission(monkeypatch):
    calls = []

    class _BootstrapAgent(_Agent):
        async def _execute_bootstrap_command(self, msg_id, serial, timeout):
            calls.append((msg_id, serial, timeout))
            return json.dumps(
                {
                    "ok": True,
                    "exit_code": 0,
                    "output": "ready",
                    "error": "",
                }
            )

        def _execute_command(self, *_args):
            raise AssertionError("gRPC bootstrap must not use generic command execution")

    monkeypatch.setattr(
        "relay.runtime.adb_executor",
        lambda: (_ for _ in ()).throw(
            AssertionError("gRPC bootstrap must not use the shared ADB executor")
        ),
    )
    client = AgentControlClient(object(), "relay-key", _BootstrapAgent())
    q = asyncio.Queue()
    msg = relay_pb2.ServerControlMsg(
        bootstrap=relay_pb2.BootstrapCmd(
            msg_id="bootstrap-1",
            serial="dev-001",
            timeout=180,
        )
    )

    await client._handle(msg, q)
    result = await asyncio.wait_for(q.get(), timeout=1.0)

    assert calls == [("bootstrap-1", "dev-001", 180)]
    assert result.result.ok is True
    assert result.result.output == "ready"


@pytest.mark.asyncio
async def test_control_stream_reader_does_not_wait_for_slow_command(monkeypatch):
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    first = relay_pb2.ServerControlMsg(
        bootstrap=relay_pb2.BootstrapCmd(
            msg_id="cmd-1",
            serial="dev-001",
            timeout=180,
        )
    )
    second = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-2",
            serial="dev-001",
            cmd="input tap 1 1",
            timeout=2,
        )
    )

    class _Stub:
        def __init__(self, _channel):
            pass

        async def ControlStream(self, _producer, metadata=None):
            yield first
            yield second
            await release_first.wait()
            await second_started.wait()

    async def _slow_handle(self, msg, q):
        if msg.WhichOneof("payload") == "bootstrap":
            first_started.set()
            await release_first.wait()
            return
        if msg.WhichOneof("payload") == "shell":
            second_started.set()

    monkeypatch.setattr(
        "relay.grpc_gen.relay_pb2_grpc.AgentControlServiceStub",
        _Stub,
    )
    monkeypatch.setattr(AgentControlClient, "_handle", _slow_handle)
    monkeypatch.setattr(AgentControlClient, "_heartbeat_loop", lambda self, q: asyncio.sleep(3600))

    client = AgentControlClient(object(), "relay-key", _Agent())
    task = asyncio.create_task(client._stream_once())
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        await asyncio.wait_for(second_started.wait(), timeout=0.2)
    finally:
        release_first.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interactive_commands_keep_stream_order(monkeypatch):
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    first = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-1",
            serial="dev-001",
            cmd="input tap 1 1",
            timeout=2,
        )
    )
    second = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-2",
            serial="dev-001",
            cmd="input text hello",
            timeout=2,
        )
    )

    class _Stub:
        def __init__(self, _channel):
            pass

        async def ControlStream(self, _producer, metadata=None):
            yield first
            yield second
            await release_first.wait()
            await second_started.wait()
            await second_started.wait()

    async def _ordered_handle(self, msg, q):
        if msg.shell.msg_id == "cmd-1":
            first_started.set()
            await release_first.wait()
            return
        second_started.set()

    monkeypatch.setattr(
        "relay.grpc_gen.relay_pb2_grpc.AgentControlServiceStub",
        _Stub,
    )
    monkeypatch.setattr(AgentControlClient, "_handle", _ordered_handle)
    monkeypatch.setattr(AgentControlClient, "_heartbeat_loop", lambda self, q: asyncio.sleep(3600))

    client = AgentControlClient(object(), "relay-key", _Agent())
    task = asyncio.create_task(client._stream_once())
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(second_started.wait(), timeout=0.1)
        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=1.0)
    finally:
        release_first.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interactive_commands_for_different_serials_do_not_block_each_other(monkeypatch):
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    first = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-1",
            serial="dev-001",
            cmd="input tap 1 1",
            timeout=2,
        )
    )
    second = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-2",
            serial="dev-002",
            cmd="input tap 2 2",
            timeout=2,
        )
    )

    class _Stub:
        def __init__(self, _channel):
            pass

        async def ControlStream(self, _producer, metadata=None):
            yield first
            yield second
            await release_first.wait()
            await second_started.wait()

    async def _per_serial_handle(self, msg, q):
        if msg.shell.msg_id == "cmd-1":
            first_started.set()
            await release_first.wait()
            return
        second_started.set()

    monkeypatch.setattr(
        "relay.grpc_gen.relay_pb2_grpc.AgentControlServiceStub",
        _Stub,
    )
    monkeypatch.setattr(AgentControlClient, "_handle", _per_serial_handle)
    monkeypatch.setattr(AgentControlClient, "_heartbeat_loop", lambda self, q: asyncio.sleep(3600))

    client = AgentControlClient(object(), "relay-key", _Agent())
    task = asyncio.create_task(client._stream_once())
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        await asyncio.wait_for(second_started.wait(), timeout=0.2)
    finally:
        release_first.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_same_serial_shell_commands_keep_stream_order_across_classification(monkeypatch):
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()

    first = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-1",
            serial="dev-001",
            cmd="pm clear com.example.app",
            timeout=60,
        )
    )
    second = relay_pb2.ServerControlMsg(
        shell=relay_pb2.ShellCmd(
            msg_id="cmd-2",
            serial="dev-001",
            cmd="input tap 2 2",
            timeout=2,
        )
    )

    class _Stub:
        def __init__(self, _channel):
            pass

        async def ControlStream(self, _producer, metadata=None):
            yield first
            yield second
            await release_first.wait()
            await second_started.wait()

    async def _classified_handle(self, msg, q):
        if msg.shell.msg_id == "cmd-1":
            first_started.set()
            await release_first.wait()
            return
        second_started.set()

    monkeypatch.setattr(
        "relay.grpc_gen.relay_pb2_grpc.AgentControlServiceStub",
        _Stub,
    )
    monkeypatch.setattr(AgentControlClient, "_handle", _classified_handle)
    monkeypatch.setattr(AgentControlClient, "_heartbeat_loop", lambda self, q: asyncio.sleep(3600))

    client = AgentControlClient(object(), "relay-key", _Agent())
    task = asyncio.create_task(client._stream_once())
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(second_started.wait(), timeout=0.1)
        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=1.0)
    finally:
        release_first.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_queue_overflow_waits_for_result_queue_capacity():
    client = AgentControlClient(object(), "relay-key", _Agent())
    q = asyncio.Queue(maxsize=1)
    await q.put(relay_pb2.AgentControlMsg(heartbeat=relay_pb2.HeartbeatMsg(relay_id="relay-1")))
    msg = relay_pb2.ServerControlMsg(
        bootstrap=relay_pb2.BootstrapCmd(
            msg_id="overflow-1",
            serial="dev-001",
            timeout=180,
        )
    )

    enqueue_task = asyncio.create_task(
        client._enqueue_queue_full_result(msg, q, serial="dev-001", lane="maintenance")
    )
    await asyncio.sleep(0)
    assert not enqueue_task.done()

    await q.get()
    await asyncio.wait_for(enqueue_task, timeout=1.0)
    result = await asyncio.wait_for(q.get(), timeout=1.0)

    assert result.WhichOneof("payload") == "result"
    assert result.result.msg_id == "overflow-1"
    assert result.result.ok is False
    assert "control queue full" in result.result.error


@pytest.mark.asyncio
async def test_queue_overflow_returns_actionable_result(monkeypatch):
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    overflow_result = asyncio.Event()
    result_holder = {}

    commands = [
        relay_pb2.ServerControlMsg(
            bootstrap=relay_pb2.BootstrapCmd(
                msg_id=f"cmd-{idx}",
                serial="dev-001",
                timeout=180,
            )
        )
        for idx in range(66)
    ]

    class _Stub:
        def __init__(self, _channel):
            pass

        async def ControlStream(self, producer, metadata=None):
            async def _consume_results():
                async for out in producer:
                    if out.WhichOneof("payload") == "result":
                        result_holder["result"] = out.result
                        overflow_result.set()
                        return

            consumer = asyncio.create_task(_consume_results())
            try:
                yield commands[0]
                await first_started.wait()
                for cmd in commands[1:]:
                    yield cmd
                await overflow_result.wait()
                await release_first.wait()
            finally:
                consumer.cancel()
                await asyncio.gather(consumer, return_exceptions=True)

    async def _blocking_handle(self, msg, q):
        first_started.set()
        await release_first.wait()

    monkeypatch.setattr(
        "relay.grpc_gen.relay_pb2_grpc.AgentControlServiceStub",
        _Stub,
    )
    monkeypatch.setattr(AgentControlClient, "_handle", _blocking_handle)
    monkeypatch.setattr(AgentControlClient, "_heartbeat_loop", lambda self, q: asyncio.sleep(3600))

    client = AgentControlClient(object(), "relay-key", _Agent())
    task = asyncio.create_task(client._stream_once())
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        await asyncio.wait_for(overflow_result.wait(), timeout=1.0)
        result = result_holder["result"]
        assert result.msg_id == "cmd-65"
        assert result.ok is False
        assert "control queue full" in result.error
        assert "lane=maintenance" in result.error
    finally:
        release_first.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
