from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import grpc
import pytest

from runtime.transports.grpc_gen import relay_pb2
from runtime.transports.grpc_relay_server import RelayServicer
from tests.perf_assertions import (
    MemoryTracker,
    assert_p95,
    assert_peak_memory,
    perf_budget,
)


class _AbortError(RuntimeError):
    pass


class _FakeContext:
    def __init__(self, metadata: list[tuple[str, str]], *, fail_writes_after: int | None = None):
        self._metadata = metadata
        self.writes: list[relay_pb2.ControlMsg] = []
        self.abort_calls: list[tuple[grpc.StatusCode, str]] = []
        self._fail_writes_after = fail_writes_after

    def invocation_metadata(self):
        return self._metadata

    async def write(self, msg: relay_pb2.ControlMsg):
        if self._fail_writes_after is not None and len(self.writes) >= self._fail_writes_after:
            raise RuntimeError("simulated grpc write failure")
        self.writes.append(msg)

    async def abort(self, code: grpc.StatusCode, detail: str):
        self.abort_calls.append((code, detail))
        raise _AbortError(detail)


@dataclass
class _FakeRelayManager:
    grpc_agents: dict[str, asyncio.Queue] = field(default_factory=dict)
    relay_register_calls: list[str] = field(default_factory=list)
    relay_unregister_calls: list[str] = field(default_factory=list)
    serial_updates: list[tuple[str, set[str]]] = field(default_factory=list)
    caps_updates: list[dict] = field(default_factory=list)
    video_frames: list[tuple[str, int]] = field(default_factory=list)
    register_errors: int = 0

    def register_grpc_agent(self, agent_id: str, ctrl_q: asyncio.Queue) -> None:
        self.grpc_agents[agent_id] = ctrl_q
        # Push one control frame so we verify device_farm -> agent stream path.
        try:
            ctrl_q.put_nowait(relay_pb2.ControlMsg(serial="", data=b'{"type":"ping"}', is_json=True))
        except asyncio.QueueFull:
            self.register_errors += 1

    def unregister_grpc_agent(self, agent_id: str) -> None:
        q = self.grpc_agents.pop(agent_id, None)
        if q is not None:
            try:
                q.put_nowait(None)
            except Exception:
                pass

    async def register(self, conn) -> None:
        self.relay_register_calls.append(conn.relay_id)

    async def unregister(self, relay_id: str, _error: str = "") -> None:
        self.relay_unregister_calls.append(relay_id)

    async def update_serials(self, relay_id: str, serials: set[str]) -> None:
        self.serial_updates.append((relay_id, serials))

    def update_capabilities(self, caps: dict) -> None:
        self.caps_updates.append(caps)

    def dispatch_grpc_video_frame(self, frame) -> None:
        self.video_frames.append((frame.serial, int(frame.pts_us)))


async def _iter_msgs(msgs: list[relay_pb2.AgentMsg]):
    for m in msgs:
        yield m


def _meta_msg(payload: dict) -> relay_pb2.AgentMsg:
    import json

    return relay_pb2.AgentMsg(meta=json.dumps(payload).encode("utf-8"))


def _video_msg(serial: str, pts: int) -> relay_pb2.AgentMsg:
    return relay_pb2.AgentMsg(
        video=relay_pb2.VideoFrame(
            serial=serial,
            data=b"\x00\x00\x00\x01",
            pts_us=pts,
            is_config=False,
            is_key=True,
            width=720,
            height=1280,
        )
    )


@pytest.mark.asyncio
async def test_grpc_stream_rejects_invalid_api_key():
    rm = _FakeRelayManager()
    svc = RelayServicer(rm, api_key="k-secret")
    ctx = _FakeContext([("x-relay-api-key", "wrong"), ("x-agent-id", "agent-1")])

    with pytest.raises(_AbortError):
        await svc.Stream(_iter_msgs([]), ctx)

    assert ctx.abort_calls
    assert ctx.abort_calls[0][0] == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_grpc_stream_n_to_n_load_local_mock():
    """
    N-to-N load contract (local + mock):
    - N agents connect concurrently
    - each agent registers 1 relay, sends M video frames, heartbeat update
    - server must fan-in all frames and fan-out at least one control message per agent
    """
    rm = _FakeRelayManager()
    svc = RelayServicer(rm, api_key="k-secret")

    agent_count = 16
    frames_per_agent = 40
    contexts: list[_FakeContext] = []

    async def _run_agent(i: int):
        agent_id = f"agent-{i}"
        serial = f"SERIAL-{i}"
        ctx = _FakeContext([("x-relay-api-key", "k-secret"), ("x-agent-id", agent_id)])
        contexts.append(ctx)

        msgs = [
            _meta_msg({"type": "register", "relay_id": f"relay-{i}", "serials": [serial]}),
            _meta_msg(
                {
                    "type": "heartbeat",
                    "serials": [serial],
                    "capabilities": {"serial": serial, "model": "mock"},
                }
            ),
        ]
        msgs.extend(_video_msg(serial, pts=j) for j in range(frames_per_agent))
        await asyncio.wait_for(svc.Stream(_iter_msgs(msgs), ctx), timeout=15.0)

    await asyncio.gather(*(_run_agent(i) for i in range(agent_count)))

    assert len(rm.relay_register_calls) == agent_count
    assert len(rm.relay_unregister_calls) == agent_count
    assert len(rm.video_frames) == agent_count * frames_per_agent
    assert len(rm.serial_updates) == agent_count
    # each stream should have written at least the synthetic ping control frame
    assert all(len(c.writes) >= 1 for c in contexts)


@pytest.mark.asyncio
async def test_grpc_stream_n_to_n_tier2_64x200_with_fault_injection():
    """
    Stress tier 2:
    - 64 agents x 200 frames/agent (12,800 total)
    - Inject queue-full, write-error, malformed meta/video interleaving
    - Stream must remain resilient (no crash), and still process healthy data
    """
    rm = _FakeRelayManager()
    svc = RelayServicer(rm, api_key="k-secret")

    agent_count = 64
    frames_per_agent = 200
    contexts: list[_FakeContext] = []
    per_agent_ms: list[float] = []

    async def _run_agent(i: int):
        t0 = time.perf_counter()
        agent_id = f"tier2-agent-{i}"
        serial = f"T2-SERIAL-{i}"
        # Every 8th agent simulates writer failure after first control frame.
        fail_writes_after = 1 if i % 8 == 0 else None
        ctx = _FakeContext(
            [("x-relay-api-key", "k-secret"), ("x-agent-id", agent_id)],
            fail_writes_after=fail_writes_after,
        )
        contexts.append(ctx)

        msgs: list[relay_pb2.AgentMsg] = []

        # Every 10th agent injects malformed meta before register.
        if i % 10 == 0:
            msgs.append(relay_pb2.AgentMsg(meta=b"{not-json"))

        msgs.append(_meta_msg({"type": "register", "relay_id": f"t2-relay-{i}", "serials": [serial]}))

        # Every 6th agent floods heartbeat serial list to pressure queue + parser path.
        hb_serials = [serial] + ([f"{serial}-extra-{k}" for k in range(10)] if i % 6 == 0 else [])
        msgs.append(_meta_msg({"type": "heartbeat", "serials": hb_serials, "capabilities": {"serial": serial, "tier": 2}}))

        for j in range(frames_per_agent):
            # Every 25th frame inject malformed meta between video frames.
            if j > 0 and j % 25 == 0:
                msgs.append(relay_pb2.AgentMsg(meta=b"\xff\xfe\x00bad-meta"))
            # Every 40th frame emit "malformed video" (empty serial) to ensure no crash in manager path.
            if j > 0 and j % 40 == 0:
                msgs.append(
                    relay_pb2.AgentMsg(
                        video=relay_pb2.VideoFrame(
                            serial="",
                            data=b"",
                            pts_us=j,
                            is_config=False,
                            is_key=False,
                            width=0,
                            height=0,
                        )
                    )
                )
            msgs.append(_video_msg(serial, pts=j))

        await svc.Stream(_iter_msgs(msgs), ctx)
        per_agent_ms.append((time.perf_counter() - t0) * 1000.0)

    with MemoryTracker(enabled=True) as mem:
        await asyncio.gather(*(_run_agent(i) for i in range(agent_count)))

    # Registration/disconnect lifecycle remains complete for all agents.
    assert len(rm.relay_register_calls) == agent_count
    assert len(rm.relay_unregister_calls) == agent_count
    # Queue growth / leak guard: all grpc agent queues must be released.
    assert len(rm.grpc_agents) == 0
    # Healthy video path should still ingest full base frame count.
    assert len(rm.video_frames) >= agent_count * frames_per_agent
    # Heartbeat updates should happen for all registered agents.
    assert len(rm.serial_updates) == agent_count
    # Even with write errors, some controls should be attempted.
    assert sum(len(c.writes) for c in contexts) >= agent_count // 2
    # Performance assertions (env-overridable budgets to stay stable across CI/local).
    p95_budget_ms = perf_budget("STRESS_GRPC_TIER2_P95_MS_BUDGET", 2500.0)
    peak_mem_budget_mb = perf_budget("STRESS_GRPC_TIER2_PEAK_MEM_MB_BUDGET", 256.0)
    assert_p95(per_agent_ms, p95_budget_ms, label="grpc_tier2_agent_stream")
    assert_peak_memory(mem.peak_mb, peak_mem_budget_mb, label="grpc_tier2_memory")


@pytest.mark.asyncio
async def test_grpc_stream_handles_register_ack_queue_full_without_crash():
    """
    Explicit queue-full injection:
    fill ctrl queue at register_grpc_agent so ack enqueue in _handle_json hits QueueFull.
    """
    rm = _FakeRelayManager()

    original_register = rm.register_grpc_agent

    def _register_with_flood(agent_id: str, ctrl_q: asyncio.Queue):
        # Keep one slot free so stream shutdown sentinel can always be queued.
        for _ in range(max(0, ctrl_q.maxsize - 1)):
            try:
                ctrl_q.put_nowait(relay_pb2.ControlMsg(serial="", data=b"x", is_json=True))
            except asyncio.QueueFull:
                break
        original_register(agent_id, ctrl_q)

    rm.register_grpc_agent = _register_with_flood  # type: ignore[assignment]
    svc = RelayServicer(rm, api_key="k-secret")
    # Force sender path to exit quickly after dequeueing first control frame.
    ctx = _FakeContext(
        [("x-relay-api-key", "k-secret"), ("x-agent-id", "agent-qfull")],
        fail_writes_after=0,
    )

    msgs = [
        _meta_msg({"type": "register", "relay_id": "relay-qfull", "serials": ["SN-QFULL"]}),
        _video_msg("SN-QFULL", 1),
    ]
    await asyncio.wait_for(svc.Stream(_iter_msgs(msgs), ctx), timeout=5.0)

    assert "relay-qfull" in rm.relay_register_calls
    assert "relay-qfull" in rm.relay_unregister_calls
    assert len(rm.video_frames) >= 1
