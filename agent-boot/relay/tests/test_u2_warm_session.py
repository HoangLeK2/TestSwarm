from __future__ import annotations

import asyncio

import pytest

from relay.agent import RelayAgent


class _WarmPool:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.event = asyncio.Event()
        self.evicts: list[str] = []
        self.sessions: set[str] = set()
        self.keep_warm: set[str] = set()

    def has_session(self, serial: str) -> bool:
        return serial in self.sessions

    def mark_keep_warm(self, serial: str, enabled: bool = True) -> bool:
        if serial not in self.sessions:
            return False
        if enabled:
            self.keep_warm.add(serial)
        else:
            self.keep_warm.discard(serial)
        return True

    async def warm_session(self, serial: str, *, keep_warm: bool = True) -> bool:
        self.calls.append(serial)
        self.sessions.add(serial)
        if keep_warm:
            self.keep_warm.add(serial)
        self.event.set()
        return True

    async def evict(self, serial: str) -> None:
        self.evicts.append(serial)
        self.sessions.discard(serial)
        self.keep_warm.discard(serial)


@pytest.mark.asyncio
async def test_online_device_does_not_schedule_u2_warm_session(monkeypatch) -> None:
    monkeypatch.setenv("U2_BATCH_ENABLED", "true")
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)

    await agent._on_device_event("dev-001", "device", asyncio.Queue())
    await asyncio.sleep(0)

    assert warm_pool.calls == []
    assert warm_pool.keep_warm == set()


@pytest.mark.asyncio
async def test_explicit_bootstrap_schedules_u2_warm_session(monkeypatch) -> None:
    monkeypatch.setenv("U2_BATCH_ENABLED", "true")
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    agent._u2_pool = warm_pool

    agent._schedule_u2_warm("dev-001", reason="explicit-bootstrap")

    await asyncio.wait_for(warm_pool.event.wait(), timeout=1.0)
    assert warm_pool.calls == ["dev-001"]
    assert warm_pool.keep_warm == {"dev-001"}


@pytest.mark.asyncio
async def test_heartbeat_does_not_warm_by_default(monkeypatch) -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)
    agent._registry.on_adb_event("dev-001", "device")
    agent._registry.set_capabilities("dev-001", {"u2": True})

    await agent._send_heartbeat(asyncio.Queue())
    await asyncio.sleep(0)

    assert warm_pool.calls == []


@pytest.mark.asyncio
async def test_heartbeat_warm_env_is_ignored_before_explicit_bootstrap(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BOOT_U2_WARM_ON_HEARTBEAT", "true")
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)
    agent._registry.on_adb_event("dev-001", "device")
    agent._registry.set_capabilities("dev-001", {"u2": True})

    await agent._send_heartbeat(asyncio.Queue())
    await asyncio.sleep(0)

    assert warm_pool.calls == []


@pytest.mark.asyncio
async def test_heartbeat_does_not_warm_without_u2_capability(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BOOT_U2_WARM_ON_HEARTBEAT", "true")
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)
    agent._registry.on_adb_event("dev-001", "device")

    await agent._send_heartbeat(asyncio.Queue())
    await asyncio.sleep(0)

    assert warm_pool.calls == []


@pytest.mark.asyncio
async def test_heartbeat_does_not_rewarm_existing_session(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BOOT_U2_WARM_ON_HEARTBEAT", "true")
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    warm_pool.sessions.add("dev-001")
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)
    agent._registry.on_adb_event("dev-001", "device")
    agent._registry.set_capabilities("dev-001", {"u2": True})

    await agent._send_heartbeat(asyncio.Queue())
    await asyncio.sleep(0)

    assert warm_pool.calls == []
    assert warm_pool.keep_warm == set()


@pytest.mark.asyncio
async def test_heartbeat_warm_failure_path_is_not_entered_before_bootstrap(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_BOOT_U2_WARM_ON_HEARTBEAT", "true")

    class _FailingWarmPool(_WarmPool):
        async def warm_session(self, serial: str, *, keep_warm: bool = True) -> bool:
            self.calls.append(serial)
            self.event.set()
            return False

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _FailingWarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("relay.agent.random.random", lambda: 0.0)
    agent._registry.on_adb_event("dev-001", "device")
    agent._registry.set_capabilities("dev-001", {"u2": True})

    await agent._send_heartbeat(asyncio.Queue())
    await asyncio.sleep(0)
    assert warm_pool.calls == []
    assert agent._u2_warm_fail_count.get("dev-001", 0) == 0


@pytest.mark.asyncio
async def test_offline_device_evicts_completed_warm_session(monkeypatch) -> None:
    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _WarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)

    agent._schedule_u2_warm("dev-001", reason="explicit-bootstrap")
    await asyncio.wait_for(warm_pool.event.wait(), timeout=1.0)
    assert warm_pool.sessions == {"dev-001"}

    await agent._on_device_event("dev-001", "offline", asyncio.Queue())
    await asyncio.sleep(0)

    assert warm_pool.evicts == ["dev-001"]


@pytest.mark.asyncio
async def test_offline_cancels_inflight_warm_and_evicts_after_race(monkeypatch) -> None:
    class _SlowWarmPool(_WarmPool):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def warm_session(self, serial: str, *, keep_warm: bool = True) -> bool:
            self.calls.append(serial)
            self.started.set()
            await self.release.wait()
            self.event.set()
            return True

    agent = RelayAgent(
        server_url="localhost:50051",
        api_key="x",
        relay_id="relay-1",
        enrollment_token="",
    )
    warm_pool = _SlowWarmPool()
    agent._u2_pool = warm_pool
    monkeypatch.setattr(agent, "_schedule_capability_probe", lambda *_args, **_kwargs: None)

    agent._schedule_u2_warm("dev-001", reason="explicit-bootstrap")
    await asyncio.wait_for(warm_pool.started.wait(), timeout=1.0)

    await agent._on_device_event("dev-001", "offline", asyncio.Queue())
    warm_pool.release.set()
    await asyncio.sleep(0)

    assert warm_pool.evicts
    assert "dev-001" not in agent._u2_warm_inflight
